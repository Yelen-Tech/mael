"""Fenetres glissantes de comptage, en Redis.

Plan bloquant : aucune de ces operations ne touche la base. Une detection de
force brute qui interroge PostgreSQL a chaque tentative de connexion s'ecroule
exactement au moment ou on en a besoin -- pendant l'attaque.

Deux structures :

  - **compteur** : INCR + EXPIRE. Combien de fois X en N secondes.
  - **ensemble**  : SADD + EXPIRE. Combien de X *distincts* en N secondes.
    C'est ce qui distingue une force brute (1 compte, 500 essais) d'un
    bourrage d'identifiants (500 comptes, 1 essai chacun) -- deux attaques
    differentes qui appellent deux reponses differentes.

En developpement sans Redis, tout retourne 0 : les signaux de frequence sont
alors inactifs, les autres fonctionnent. C'est signale dans la reponse
(`degrade: true`) plutot que silencieusement faux.
"""
from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger("sentinelle.audit")

PREFIXE = "sentinelle:auth"
_client = None
_indisponible = False


def client():
    global _client, _indisponible
    if _indisponible:
        return None
    if _client is None:
        if not settings.REDIS_URL:
            _indisponible = True
            return None
        import redis

        _client = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=0.25)
    return _client


def disponible() -> bool:
    return client() is not None


def _cle(*morceaux) -> str:
    return ":".join((PREFIXE, *(str(m) for m in morceaux)))


# ------------------------------------------------------------------ compteurs
def incrementer(categorie: str, valeur: str, *, fenetre: int) -> int:
    """Incremente et renvoie le total sur la fenetre. 0 si Redis absent."""
    c = client()
    if c is None:
        return 0
    cle = _cle(categorie, fenetre, valeur)
    try:
        tube = c.pipeline()
        tube.incr(cle)
        tube.expire(cle, fenetre)
        return int(tube.execute()[0])
    except Exception:  # noqa: BLE001
        logger.warning("fenetres: Redis indisponible sur %s", categorie)
        return 0


def lire(categorie: str, valeur: str, *, fenetre: int) -> int:
    c = client()
    if c is None:
        return 0
    try:
        brut = c.get(_cle(categorie, fenetre, valeur))
        return int(brut) if brut else 0
    except Exception:  # noqa: BLE001
        return 0


# ------------------------------------------------------------------ ensembles
def ajouter_distinct(categorie: str, cle_groupe: str, membre: str, *, fenetre: int) -> int:
    """Ajoute `membre` au groupe et renvoie le nombre de membres distincts."""
    c = client()
    if c is None:
        return 0
    cle = _cle(categorie, fenetre, cle_groupe)
    try:
        tube = c.pipeline()
        tube.sadd(cle, membre)
        tube.expire(cle, fenetre)
        tube.scard(cle)
        return int(tube.execute()[2])
    except Exception:  # noqa: BLE001
        return 0


def compter_distinct(categorie: str, cle_groupe: str, *, fenetre: int) -> int:
    c = client()
    if c is None:
        return 0
    try:
        return int(c.scard(_cle(categorie, fenetre, cle_groupe)))
    except Exception:  # noqa: BLE001
        return 0


# ------------------------------------------------------------------ memoire courte
def memoriser(categorie: str, cle_valeur: str, valeur: str, *, duree: int) -> None:
    """Retient une derniere valeur connue (pays de derniere connexion, etc.)."""
    c = client()
    if c is None:
        return
    try:
        c.set(_cle(categorie, cle_valeur), valeur, ex=duree)
    except Exception:  # noqa: BLE001
        pass


def rappeler(categorie: str, cle_valeur: str) -> str | None:
    c = client()
    if c is None:
        return None
    try:
        brut = c.get(_cle(categorie, cle_valeur))
        return brut.decode() if isinstance(brut, bytes) else brut
    except Exception:  # noqa: BLE001
        return None


def reinitialiser(categorie: str, valeur: str, *, fenetre: int) -> None:
    """Remet un compteur a zero. Appele apres une connexion reussie legitime."""
    c = client()
    if c is None:
        return
    try:
        c.delete(_cle(categorie, fenetre, valeur))
    except Exception:  # noqa: BLE001
        pass
