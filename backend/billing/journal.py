"""Journal d'appels tamponne.

Pourquoi ce fichier existe : mesure faite sur 16 000 indicateurs, par appel
du plan bloquant --

    requete indicateur (indexee)      0.6 ms
    lecture cache                     0.01 ms
    ecriture ApiCall synchrone      169 ms      <-- 99 % du temps

L'ecriture du journal coutait plus cher que tout le reste reuni. En
production sur PostgreSQL c'est moins violent qu'en SQLite, mais le probleme
reste structurel : chaque appel client declenche une transaction d'ecriture
dans le chemin ou le client attend.

Solution : on empile dans Redis (operation en memoire, quelques dizaines de
microsecondes) et une tache groupe les lignes en base toutes les dix secondes.

Compromis assume : si Redis meurt entre l'empilage et le vidage, on perd
quelques secondes de lignes de facturation. C'est acceptable ici -- ApiCall
sert a facturer et a mesurer l'usage. La piste d'audit des decisions de
securite (`core.AuditLog`) est un autre objet, ecrite en direct, et elle
n'est pas dans le chemin bloquant.
"""
from __future__ import annotations

import json
import logging

from django.conf import settings

logger = logging.getLogger("sentinelle.audit")

CLE_FILE = "sentinelle:journal:appels"
LOT_VIDAGE = 1000
_client = None


def _redis():
    """Client Redis brut : l'API de cache de Django n'expose pas les listes."""
    global _client
    if _client is None:
        if not settings.REDIS_URL:
            return None
        import redis

        _client = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=1)
    return _client


def empiler(**ligne) -> None:
    """Enregistre un appel. Ne leve jamais : un journal casse ne casse pas l'API."""
    client = _redis()
    if client is None:
        _ecrire_direct([ligne])  # dev sans Redis
        return
    try:
        client.rpush(CLE_FILE, json.dumps(ligne, default=str))
    except Exception:  # noqa: BLE001
        logger.warning("journal: Redis indisponible, ecriture directe")
        _ecrire_direct([ligne])


def _ecrire_direct(lignes: list[dict]) -> int:
    import uuid

    from .models import ApiCall

    def en_uuid(valeur):
        if valeur is None or isinstance(valeur, uuid.UUID):
            return valeur
        try:
            return uuid.UUID(str(valeur))
        except (ValueError, AttributeError):
            return None

    objets = []
    for ligne in lignes:
        # copie : ne pas vider le dictionnaire de l'appelant
        ligne = dict(ligne)
        organisation_id = en_uuid(ligne.pop("organisation_id", None))
        if organisation_id is None:
            continue
        cle_id = en_uuid(ligne.pop("cle_id", None))
        objets.append(
            ApiCall(organisation_id=organisation_id, cle_id=cle_id, **ligne)
        )
    if not objets:
        return 0
    ApiCall.objects.bulk_create(objets, batch_size=LOT_VIDAGE)
    return len(objets)


def vider(limite: int = LOT_VIDAGE) -> int:
    """Transfere le tampon Redis vers la base. Appele par la tache periodique."""
    client = _redis()
    if client is None:
        return 0

    lignes: list[dict] = []
    try:
        # LPOP avec compte : atomique, donc deux vidages concurrents ne
        # traitent jamais la meme ligne deux fois.
        brut = client.lpop(CLE_FILE, limite)
    except Exception:  # noqa: BLE001
        logger.exception("journal: vidage impossible")
        return 0

    if not brut:
        return 0
    if isinstance(brut, (bytes, str)):
        brut = [brut]

    for element in brut:
        try:
            lignes.append(json.loads(element))
        except json.JSONDecodeError:
            continue

    ecrites = _ecrire_direct(lignes)
    logger.info("journal: %d lignes ecrites", ecrites)
    return ecrites


def en_attente() -> int:
    client = _redis()
    if client is None:
        return 0
    try:
        return int(client.llen(CLE_FILE))
    except Exception:  # noqa: BLE001
        return 0


# --------------------------------------------------------------- compteurs de quota
# Meme probleme que le journal : `ApiCall.objects.count()` a chaque appel est
# une requete d'agregation sur une table qui grossit sans fin. On compte dans
# Redis (INCR, quelques microsecondes) avec une cle par mois, et on reconcilie
# depuis la base au vidage. La base reste la verite pour la facturation ;
# le compteur n'est qu'un garde-fou rapide.
def _cle_compteur(organisation_id, module: str) -> str:
    from django.utils import timezone

    mois = timezone.now().strftime("%Y%m")
    return f"sentinelle:quota:{mois}:{organisation_id}:{module}"


def incrementer_quota(organisation_id, module: str) -> int:
    client = _redis()
    if client is None:
        return -1  # dev sans Redis : on retombe sur le comptage en base
    cle = _cle_compteur(organisation_id, module)
    try:
        valeur = client.incr(cle)
        if valeur == 1:
            client.expire(cle, 40 * 24 * 3600)  # le mois + une marge
        return int(valeur)
    except Exception:  # noqa: BLE001
        return -1


def consommation(organisation_id, module: str) -> int:
    """-1 si le compteur n'est pas disponible : l'appelant comptera en base."""
    client = _redis()
    if client is None:
        return -1
    try:
        valeur = client.get(_cle_compteur(organisation_id, module))
        return int(valeur) if valeur is not None else 0
    except Exception:  # noqa: BLE001
        return -1


def reconcilier_quota(organisation_id, module: str) -> int:
    """Recale le compteur sur la base. Appele au vidage du journal."""
    client = _redis()
    if client is None:
        return -1
    from django.utils import timezone

    from .models import ApiCall

    debut = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    reel = ApiCall.objects.filter(
        organisation_id=organisation_id, module=module, horodatage__gte=debut
    ).count()
    try:
        client.set(_cle_compteur(organisation_id, module), reel, ex=40 * 24 * 3600)
    except Exception:  # noqa: BLE001
        pass
    return reel
