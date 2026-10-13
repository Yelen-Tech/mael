"""Garde-fous deterministes du cerveau.

Rien ici n'est decide par le modele. Ce sont des regles ecrites, lisibles,
testables. Le modele PROPOSE une commande ; ce module la CLASSE et decide si
elle s'execute seule, exige une validation humaine, ou est refusee.
"""
from .commandes import NIVEAU, Verdict, classer

__all__ = ["classer", "Verdict", "NIVEAU"]
