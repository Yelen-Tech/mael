"""Registre des collecteurs.

Importer ce paquet suffit : la liste TOUS est la source unique pour la
tache Celery, la commande CLI et les tests.
"""
from .avec_cle import AbuseIPDB, AlienVaultOTX
from .sans_cle import FeodoC2, NoeudsTor, SpamhausDrop, ThreatFox, UrlhausRecent

# Ordre volontaire : les flux precis d'abord, pour que la corroboration
# joue en leur faveur lors de l'agregation.
TOUS = [
    FeodoC2,
    SpamhausDrop,
    UrlhausRecent,
    ThreatFox,
    AbuseIPDB,
    AlienVaultOTX,
    NoeudsTor,
]

SANS_CLE = [c for c in TOUS if not c.cle_requise]

PAR_NOM = {c.nom: c for c in TOUS}

__all__ = ["TOUS", "SANS_CLE", "PAR_NOM"]
