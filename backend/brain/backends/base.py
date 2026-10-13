"""Abstraction du fournisseur de modele (mecanisme 1).

Le reste du code ignore quel modele tourne et ou. On change de moteur par
variable d'environnement, tache par tache -- jamais en modifiant du code metier.
"""
from __future__ import annotations

import abc
import json
from dataclasses import dataclass

from django.conf import settings


@dataclass
class Reponse:
    texte: str
    donnees: dict | None      # sortie structuree deja validee, si un schema etait fourni
    appels_outils: list[dict] # [{"nom": ..., "arguments": {...}}]
    modele: str
    jetons_entree: int = 0
    jetons_sortie: int = 0

    @property
    def veut_un_outil(self) -> bool:
        return bool(self.appels_outils)


class FluxReponse:
    """Une reponse qui arrive par morceaux, sans rien perdre du tout.

    On parcourt l'objet pour afficher les fragments au fur et a mesure ;
    quand le parcours est fini, `.reponse` porte la Reponse complete --
    exactement celle qu'aurait rendue `completer`. Le reste du programme
    (la garde, le fondement, les fiches) continue donc de juger le texte
    ENTIER : afficher plus tot ne veut pas dire decider plus tot.
    """

    def __init__(self, generateur):
        self._generateur = generateur
        self.reponse: "Reponse | None" = None

    def __iter__(self):
        self.reponse = yield from self._generateur
        return self.reponse

    def entier(self) -> "Reponse":
        """Consomme tout le flux sans rien afficher et rend la reponse."""
        for _ in self:
            pass
        return self.reponse


class LLMBackend(abc.ABC):
    """Interface unique. Implementations : ollama, llamacpp (petit modele local), vllm (grand modele sur la machine)."""

    nom: str = ""

    @abc.abstractmethod
    def completer(
        self,
        *,
        systeme: str,
        messages: list[dict],
        role_modele: str = "analyste",
        schema: dict | None = None,
        outils: list[dict] | None = None,
    ) -> Reponse:
        """`schema` non nul => sortie contrainte par grammaire (mecanisme 3).

        Ce n'est pas une consigne que le modele peut ignorer : le decodage
        lui interdit mecaniquement de produire autre chose.
        """

    # ------------------------------------------------------------------ commun
    def flux(self, **arguments) -> FluxReponse:
        """La reponse en morceaux, pour l'afficher pendant qu'elle se fait.

        Defaut : un seul morceau, a la fin. Un fournisseur qui ne sait pas
        diffuser garde ainsi le meme contrat, et l'appelant n'a pas a savoir
        lequel il a en face."""
        def _un_seul_bloc():
            reponse = self.completer(**arguments)
            if reponse.texte:
                yield reponse.texte
            return reponse

        return FluxReponse(_un_seul_bloc())

    def modele_pour(self, role: str) -> str:
        modeles = settings.BRAIN["MODELES"]
        if role not in modeles:
            raise ValueError(
                f"Role de modele « {role} » inconnu. Connus : {sorted(modeles)}"
            )
        return modeles[role]

    @staticmethod
    def _json_tolerant(texte: str) -> dict | None:
        """Les modeles echappent le JSON differemment. On parse, sans jamais
        faire de correspondance de chaines sur la sortie brute."""
        texte = texte.strip()
        debut, fin = texte.find("{"), texte.rfind("}")
        if debut == -1 or fin <= debut:
            return None
        try:
            return json.loads(texte[debut : fin + 1])
        except json.JSONDecodeError:
            return None


def obtenir_backend() -> LLMBackend:
    """Fabrique lue une seule fois par processus."""
    choix = settings.BRAIN["BACKEND"]
    if choix == "llamacpp":
        from .llamacpp import LlamaCppBackend
        return LlamaCppBackend()
    if choix == "ollama":
        from .ollama import OllamaBackend
        return OllamaBackend()
    if choix == "vllm":
        # le grand modele installe sur la machine de MAEL (13/10/2026)
        from .vllm import VllmBackend
        return VllmBackend()
    raise ValueError(f"BRAIN_BACKEND inconnu : {choix}")
