"""Agregation des sources en un score, puis en un verdict.

Trois idees, dans cet ordre :

1. **Moyenne ponderee par la confiance de la source.** Un flux precis pese
   plus qu'un flux bruyant. Le poids est stocke en base (`Flux.poids`) et
   se corrige a l'usage, sans toucher au code.

2. **Bonus de corroboration.** Deux sources independantes qui signalent la
   meme valeur, c'est beaucoup plus solide qu'une seule qui la signale fort.
   C'est ce qui fait baisser le taux de faux positifs.

3. **Decroissance avec l'age.** Une IP signalee il y a huit mois n'est plus
   la meme menace : les adresses sont recyclees. Le score decroit, donc un
   flux qui s'arrete de la signaler la fait sortir d'elle-meme du verdict
   « malveillant » -- sans qu'on ait besoin de purger quoi que ce soit.

La liste blanche prime sur tout : elle est appliquee en dernier.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from modules.reputation.models import Flux, Indicateur, Plage

from .base import Brut
from .listeblanche import est_blanchi, raison

logger = logging.getLogger("sentinelle.audit")

# Seuils de verdict. Volontairement prudents : on prefere un « suspect »
# a un « malveillant » errone, parce que le client agit sur « malveillant ».
SEUIL_MALVEILLANT = 0.70
SEUIL_SUSPECT = 0.40

# Un score perd la moitie de sa valeur tous les 45 jours sans nouvelle mention.
DEMI_VIE_JOURS = 45

# Gain par source supplementaire qui corrobore (plafonne).
BONUS_CORROBORATION = 0.08
BONUS_MAX = 0.20

LOT = 2000


@dataclass
class Resultat:
    crees: int = 0
    mis_a_jour: int = 0
    blanchis: int = 0
    ignores: int = 0
    plages: int = 0

    def __str__(self):
        morceaux = [
            f"{self.crees} crees",
            f"{self.mis_a_jour} mis a jour",
            f"{self.blanchis} blanchis",
        ]
        if self.plages:
            morceaux.append(f"{self.plages} plages")
        return ", ".join(morceaux)


def _integrer_plages(source, enregistrements, poids, maintenant) -> int:
    """Stocke les CIDR avec leurs bornes entieres, interrogeables par encadrement."""
    connues = {p.cidr: p for p in Plage.objects.filter(
        cidr__in=[b.valeur for b in enregistrements])}
    a_creer, a_modifier = [], []

    for brut in enregistrements:
        bornes = Plage.bornes(brut.valeur)
        if bornes is None:
            continue
        version, debut, fin = bornes
        plage = connues.get(brut.valeur)
        if plage is None:
            sources = {source: brut.score}
            score = calculer_score(sources, poids)
            a_creer.append(Plage(
                cidr=brut.valeur, version=version, debut=debut, fin=fin,
                score=score, verdict=verdict_pour(score),
                categories=sorted(set(brut.categories)), sources=sources,
                derniere_vue=maintenant,
            ))
        else:
            plage.sources = {**(plage.sources or {}), source: brut.score}
            plage.score = calculer_score(plage.sources, poids)
            plage.verdict = verdict_pour(plage.score)
            plage.categories = sorted(set(plage.categories or []) | set(brut.categories))
            plage.derniere_vue = maintenant
            a_modifier.append(plage)

    if a_creer:
        Plage.objects.bulk_create(a_creer, batch_size=LOT, ignore_conflicts=True)
    if a_modifier:
        Plage.objects.bulk_update(
            a_modifier, ["score", "verdict", "categories", "sources", "derniere_vue"],
            batch_size=LOT)
    return len(a_creer) + len(a_modifier)


def facteur_age(jours: int) -> float:
    """Decroissance exponentielle par demi-vie."""
    return 0.5 ** (max(0, jours) / DEMI_VIE_JOURS)


def calculer_score(sources: dict[str, float], poids: dict[str, float]) -> float:
    """Score agrege a partir de {nom_source: score_brut}."""
    if not sources:
        return 0.0

    numerateur = sum(score * poids.get(nom, 1.0) for nom, score in sources.items())
    denominateur = sum(poids.get(nom, 1.0) for nom in sources)
    base = numerateur / denominateur if denominateur else 0.0

    bonus = min(BONUS_MAX, BONUS_CORROBORATION * (len(sources) - 1))
    return round(min(1.0, base + bonus), 4)


def verdict_pour(score: float) -> str:
    if score >= SEUIL_MALVEILLANT:
        return Indicateur.Verdict.MALVEILLANT
    if score >= SEUIL_SUSPECT:
        return Indicateur.Verdict.SUSPECT
    return Indicateur.Verdict.INCONNU


def _poids_des_flux() -> dict[str, float]:
    return dict(Flux.objects.values_list("nom", "poids"))


@transaction.atomic
def integrer(source: str, enregistrements: list[Brut]) -> Resultat:
    """Fusionne les enregistrements d'une source dans la base d'indicateurs.

    Idempotent : rejouer la meme collecte ne double rien, elle rafraichit
    seulement `derniere_vue` et le score de cette source.
    """
    res = Resultat()
    if not enregistrements:
        return res

    poids = _poids_des_flux()
    maintenant = timezone.now()

    # Les CIDR partent dans Plage, pas dans Indicateur : voir le modele.
    # Une seule passe : « not in liste » serait quadratique sur 1 700 plages.
    plages, simples = [], []
    for b in enregistrements:
        (plages if b.type == "ip" and "/" in b.valeur else simples).append(b)
    if plages:
        res.plages = _integrer_plages(source, plages, poids, maintenant)
    enregistrements = simples

    # Dedoublonnage interne au flux : certains publient deux fois la meme valeur.
    uniques: dict[tuple[str, str], Brut] = {}
    for b in enregistrements:
        cle = (b.type, b.valeur)
        existant = uniques.get(cle)
        if existant is None or b.score > existant.score:
            uniques[cle] = b

    cles = list(uniques)
    existants = {
        (i.type, i.valeur): i
        for i in Indicateur.objects.filter(
            type__in={t for t, _ in cles}, valeur__in=[v for _, v in cles]
        )
    }

    a_creer: list[Indicateur] = []
    a_modifier: list[Indicateur] = []

    for (type_ind, valeur), brut in uniques.items():
        if est_blanchi(type_ind, valeur):
            res.blanchis += 1
            # On enregistre quand meme, mais en « benin » explicite : le
            # tableau de bord doit pouvoir montrer pourquoi on n'a pas alerte.
            indicateur = existants.get((type_ind, valeur))
            if indicateur is None:
                a_creer.append(
                    Indicateur(
                        type=type_ind,
                        valeur=valeur,
                        score=0.0,
                        verdict=Indicateur.Verdict.BENIN,
                        categories=[f"liste_blanche:{raison(type_ind, valeur)}"],
                        sources={source: brut.score},
                        premiere_vue=maintenant,
                        derniere_vue=maintenant,
                    )
                )
            else:
                indicateur.verdict = Indicateur.Verdict.BENIN
                indicateur.score = 0.0
                indicateur.derniere_vue = maintenant
                a_modifier.append(indicateur)
            continue

        indicateur = existants.get((type_ind, valeur))

        if indicateur is None:
            sources = {source: brut.score}
            score = calculer_score(sources, poids)
            a_creer.append(
                Indicateur(
                    type=type_ind,
                    valeur=valeur,
                    score=score,
                    verdict=verdict_pour(score),
                    categories=sorted(set(brut.categories)),
                    sources=sources,
                    pays=brut.pays,
                    asn=brut.asn,
                    premiere_vue=maintenant,
                    derniere_vue=maintenant,
                )
            )
            res.crees += 1
        else:
            if indicateur.verdict == Indicateur.Verdict.BENIN:
                res.ignores += 1  # blanchi manuellement : on n'y touche pas
                continue
            indicateur.sources = {**(indicateur.sources or {}), source: brut.score}
            indicateur.categories = sorted(
                set(indicateur.categories or []) | set(brut.categories)
            )
            indicateur.score = calculer_score(indicateur.sources, poids)
            indicateur.verdict = verdict_pour(indicateur.score)
            indicateur.derniere_vue = maintenant
            indicateur.pays = indicateur.pays or brut.pays
            indicateur.asn = indicateur.asn or brut.asn
            a_modifier.append(indicateur)
            res.mis_a_jour += 1

    if a_creer:
        Indicateur.objects.bulk_create(a_creer, batch_size=LOT, ignore_conflicts=True)
    if a_modifier:
        Indicateur.objects.bulk_update(
            a_modifier,
            ["score", "verdict", "categories", "sources", "derniere_vue", "pays", "asn"],
            batch_size=LOT,
        )
    return res


def appliquer_decroissance(lot: int = LOT) -> int:
    """Recalcule les scores en tenant compte de l'age. A passer une fois par jour.

    Une valeur que plus aucun flux ne signale finit sous le seuil et sort
    du verdict « malveillant » toute seule.
    """
    poids = _poids_des_flux()
    maintenant = timezone.now()
    modifies: list[Indicateur] = []

    requete = Indicateur.objects.exclude(
        verdict=Indicateur.Verdict.BENIN
    ).iterator(chunk_size=lot)

    for indicateur in requete:
        jours = (maintenant - indicateur.derniere_vue).days
        if jours == 0:
            continue
        brut = calculer_score(indicateur.sources or {}, poids)
        nouveau = round(brut * facteur_age(jours), 4)
        nouveau_verdict = verdict_pour(nouveau)
        if (nouveau, nouveau_verdict) != (indicateur.score, indicateur.verdict):
            indicateur.score = nouveau
            indicateur.verdict = nouveau_verdict
            modifies.append(indicateur)
        if len(modifies) >= lot:
            Indicateur.objects.bulk_update(modifies, ["score", "verdict"], batch_size=lot)
            modifies.clear()

    if modifies:
        Indicateur.objects.bulk_update(modifies, ["score", "verdict"], batch_size=lot)

    total = Indicateur.objects.filter(verdict=Indicateur.Verdict.MALVEILLANT).count()
    logger.info("decroissance appliquee, %d indicateurs malveillants restants", total)
    return total


def sante_des_flux(seuil_heures: int = 36) -> list[dict]:
    """Etat de chaque flux. Un flux muet est un flux mort : il faut le voir."""
    maintenant = timezone.now()
    etat = []
    for flux in Flux.objects.all():
        if not flux.derniere_collecte:
            statut = "jamais collecte"
        elif flux.derniere_erreur:
            statut = "en erreur"
        elif (maintenant - flux.derniere_collecte).total_seconds() > seuil_heures * 3600:
            statut = "silencieux"
        else:
            statut = "ok"
        etat.append(
            {
                "flux": flux.nom,
                "statut": statut,
                "actif": flux.actif,
                "poids": flux.poids,
                "dernier_nombre": flux.dernier_nombre,
                "derniere_collecte": flux.derniere_collecte,
                "erreur": flux.derniere_erreur,
            }
        )
    return sorted(etat, key=lambda e: (e["statut"] == "ok", e["flux"]))
