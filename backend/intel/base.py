"""Socle des collecteurs de renseignement.

Un collecteur ne decide de rien. Il recupere un flux public, le normalise
en enregistrements bruts, et les rend. L'agregation et le verdict sont
faits ailleurs (`intel/agregation.py`), a partir de *toutes* les sources.

Regle : un collecteur qui echoue ne casse jamais la collecte des autres,
et son echec est enregistre. Un flux silencieux est un flux mort -- il
faut le voir, pas le decouvrir six mois plus tard.
"""
from __future__ import annotations

import abc
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field

import httpx
from django.utils import timezone

from modules.reputation.models import Flux, Indicateur

logger = logging.getLogger("sentinelle.audit")


@dataclass
class Brut:
    """Un enregistrement normalise, tel que sorti d'un flux.

    `score` est la confiance *de cette source seule*, entre 0 et 1.
    Le score final de l'indicateur est calcule par agregation.
    """

    type: str          # Indicateur.Type
    valeur: str
    score: float = 0.5
    categories: list[str] = field(default_factory=list)
    pays: str = ""
    asn: str = ""

    def __post_init__(self):
        self.valeur = self.valeur.strip().lower()
        self.score = max(0.0, min(1.0, float(self.score)))
        self.pays = (self.pays or "")[:2].upper()


class Collecteur(abc.ABC):
    """Un flux. Une sous-classe par source."""

    nom: str = ""
    url: str = ""
    description: str = ""
    # Confiance accordee a cette source dans le score agrege.
    poids: float = 1.0
    # Une cle est-elle indispensable ? Si oui et absente, le flux est ignore
    # proprement au lieu d'echouer.
    cle_requise: bool = False
    delai: int = 60

    # ------------------------------------------------------------ a redefinir
    @abc.abstractmethod
    def analyser(self, contenu: str) -> Iterator[Brut]:
        """Traduit le corps de la reponse en enregistrements normalises."""

    # ------------------------------------------------------------ surcharges
    def entetes(self) -> dict:
        return {"User-Agent": "Sentinelle/1.0 (collecteur de renseignement)"}

    def cle(self) -> str:
        return ""

    def recuperer(self) -> str:
        """Telecharge le flux. Surchargeable pour les flux en POST."""
        with httpx.Client(timeout=self.delai, follow_redirects=True) as c:
            rep = c.get(self.url, headers=self.entetes())
            rep.raise_for_status()
            return rep.text

    # ------------------------------------------------------------ execution
    def collecter(self) -> tuple[list[Brut], str]:
        """Renvoie (enregistrements, message d'erreur). Ne leve jamais."""
        flux, _ = Flux.objects.get_or_create(
            nom=self.nom, defaults={"url": self.url, "poids": self.poids}
        )
        if not flux.actif:
            return [], "flux desactive"

        if self.cle_requise and not self.cle():
            message = "cle d'API absente : flux ignore"
            flux.derniere_erreur = message
            flux.save(update_fields=["derniere_erreur"])
            return [], message

        try:
            contenu = self.recuperer()
            enregistrements = [b for b in self.analyser(contenu) if b.valeur]
        except Exception as exc:  # noqa: BLE001 -- un flux casse n'arrete rien
            message = f"{type(exc).__name__}: {exc}"[:400]
            flux.derniere_erreur = message
            flux.save(update_fields=["derniere_erreur"])
            logger.warning("flux=%s echec=%s", self.nom, message)
            return [], message

        flux.derniere_collecte = timezone.now()
        flux.dernier_nombre = len(enregistrements)
        flux.derniere_erreur = ""
        flux.save(
            update_fields=["derniere_collecte", "dernier_nombre", "derniere_erreur"]
        )
        logger.info("flux=%s enregistrements=%d", self.nom, len(enregistrements))
        return enregistrements, ""


# --------------------------------------------------------------------- utilitaires
def lignes_utiles(contenu: str) -> Iterator[str]:
    """Itere les lignes non vides et non commentees d'un flux texte."""
    for ligne in contenu.splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith(("#", ";", "//")):
            yield ligne


TYPES = Indicateur.Type
