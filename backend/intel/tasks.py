"""Taches Celery de collecte. Meme code que la commande CLI.

Planification : CELERY_BEAT_SCHEDULE dans config/settings.py
  - collecter_tout        toutes les 4 h
  - decroissance_scores   une fois par jour a 3 h 30
  - verifier_sante        toutes les 6 h
"""
from celery import shared_task

from .agregation import appliquer_decroissance, integrer, sante_des_flux
from .feeds import PAR_NOM, TOUS


@shared_task(name="intel.tasks.collecter_flux", bind=True, max_retries=2)
def collecter_flux(self, nom: str) -> dict:
    """Collecte un seul flux. Une tache par flux : un echec n'affecte rien d'autre."""
    classe = PAR_NOM.get(nom)
    if classe is None:
        return {"flux": nom, "erreur": "flux inconnu"}

    collecteur = classe()
    enregistrements, erreur = collecteur.collecter()
    if erreur:
        # Une cle absente n'est pas une panne : on ne reessaie pas.
        if "cle" in erreur:
            return {"flux": nom, "ignore": erreur}
        raise self.retry(exc=RuntimeError(erreur), countdown=300)

    resultat = integrer(nom, enregistrements)
    return {
        "flux": nom,
        "recus": len(enregistrements),
        "crees": resultat.crees,
        "mis_a_jour": resultat.mis_a_jour,
        "blanchis": resultat.blanchis,
    }


@shared_task(name="intel.tasks.collecter_tout")
def collecter_tout() -> dict:
    for classe in TOUS:
        collecter_flux.delay(classe.nom)
    return {"flux_lances": [c.nom for c in TOUS]}


@shared_task(name="intel.tasks.decroissance_scores")
def decroissance_scores() -> dict:
    return {"malveillants_restants": appliquer_decroissance()}


@shared_task(name="intel.tasks.verifier_sante")
def verifier_sante() -> dict:
    """Un flux silencieux ou en erreur doit remonter, pas dormir."""
    etat = sante_des_flux()
    problemes = [e for e in etat if e["statut"] != "ok" and e["actif"]]
    return {"total": len(etat), "problemes": [p["flux"] for p in problemes]}


@shared_task(name="intel.tasks.rafraichir_geo")
def rafraichir_geo() -> dict:
    """Recharge la table de geolocalisation. Une fois par mois suffit :
    les attributions d'adresses bougent lentement."""
    from django.core.management import call_command

    from .geo import couverture

    call_command("charger_geo", vider=True)
    return couverture()
