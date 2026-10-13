"""Outils embarques.

Importer ce paquet suffit a peupler le registre : les adaptateurs
s'inscrivent au chargement. Sans cet import, le registre est vide et
le cerveau n'a aucun outil -- c'est un bug silencieux, donc on le rend
impossible ici.
"""
from . import (
    inspection,  # noqa: F401  -- effet de bord : inscription
    locaux,  # noqa: F401  -- CVE des paquets, secrets, antivirus
    surface,  # noqa: F401  -- ports, sous-domaines, services web
)
from .base import Observation, Outil, OutilEchoue, OutilRefuse, registre

__all__ = [
    "registre",
    "Outil",
    "Observation",
    "OutilRefuse",
    "OutilEchoue",
    "inspection",
]
