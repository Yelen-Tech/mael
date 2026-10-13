"""Backend VLLM : le GRAND modele, installe sur la machine meme ou tourne
MAEL, servi par vLLM.

Pourquoi (decision du responsable, 13/10/2026) : MAEL se teste sur un petit
modele (phi4-mini) ; au moment de conclure, il se mesure — et passe
l'examen — sur les machines a cartes graphiques de Hugging Face, avec un
grand modele libre (Apache-2.0 ou MIT) INSTALLE sur ces machines. Pas d'API
exterieure, pas de fournisseur : MAEL reste local, la machine est juste plus
grande. vLLM est le serveur de reference pour les grands modeles sur cartes
graphiques ; il parle la meme langue que llama-server (/v1/chat/completions).
Ce backend reprend donc LlamaCppBackend (corps, schema, outils, charabia,
flux), sans lancer de processus : vLLM est demarre a cote
(`vllm serve <modele>`).

Surete :
  - par defaut 127.0.0.1 : rien ne sort de la machine ;
  - un vLLM d'une AUTRE machine du reseau est permis (grappe de cartes),
    mais si une cle est donnee (vllm serve --api-key), elle ne part jamais
    en clair : http:// hors de la machine est alors refuse ;
  - la cle n'est jamais ecrite dans un journal.
"""
from __future__ import annotations

import logging
import os
import time
from urllib.parse import urlparse

from django.conf import settings

from .base import LLMBackend
from .llamacpp import LlamaCppBackend
from .sante import MoteurEnPanne

journal = logging.getLogger(__name__)

LOCAUX = {"localhost", "127.0.0.1", "::1"}


class VllmBackend(LlamaCppBackend):
    nom = "vllm"

    def __init__(self, reglages: dict | None = None):
        from brain.modeles import ProblemeDeModele
        r = reglages if reglages is not None else settings.BRAIN.get(
            "VLLM", {})
        url = (r.get("URL") or "http://127.0.0.1:8000").rstrip("/")
        url = url[:-3] if url.endswith("/v1") else url
        self.modele = r.get("MODELE") or ""
        cle = r.get("CLE") or os.environ.get("BRAIN_VLLM_CLE", "")
        if not self.modele:
            raise ProblemeDeModele(
                "Moteur vLLM : nom du modele manquant.",
                ["BRAIN_VLLM_MODELE=<le nom donne a `vllm serve`>",
                 "ou revenir au petit modele : BRAIN_BACKEND=ollama"])
        hote = urlparse(url).hostname or ""
        if cle and urlparse(url).scheme != "https" and hote not in LOCAUX:
            raise ProblemeDeModele(
                f"Moteur vLLM : {url} est sur une autre machine sans HTTPS — "
                "la cle partirait en clair. Refuse.",
                ["Mettre vLLM sur la meme machine (127.0.0.1) ou en HTTPS"])
        self.base = url
        self._entetes = {"Authorization": f"Bearer {cle}"} if cle else {}
        self.contexte = int(r.get("CONTEXTE") or 65536)
        self.milliards = float(r.get("MILLIARDS") or 0)
        self.timeout = settings.BRAIN["TIMEOUT"]
        self.relances = 0
        if hote not in LOCAUX:
            journal.warning("MAEL envoie les consignes et le code au vLLM de "
                            "la machine %s (modele %s)", hote, self.modele)

    def __repr__(self) -> str:                # jamais la cle
        return f"VllmBackend({self.base}, {self.modele})"

    # -------------------------------- vLLM est lance a cote : pas de processus
    def modele_pour(self, role: str) -> str:
        LLMBackend.modele_pour(self, role)  # valide le role
        return self.modele

    def demarrer(self) -> None:
        return None

    def arreter(self) -> None:
        return None

    def decharger(self) -> bool:
        return True

    def relancer(self, modele: str = "") -> None:
        """MAEL ne tient pas ce processus : on laisse passer la surcharge
        (erreur 5xx, delai) avant le second essai."""
        self.relances += 1
        time.sleep(min(30, 5 * self.relances))

    def verifier_sante(self, role_modele: str = "codeur") -> str:
        if self.sonde():
            return ""
        raise MoteurEnPanne(f"{self.modele} sur {self.base} ne repond pas "
                            "juste (sonde « 2 + 3 » ratee)")

    def envergure(self):
        """vLLM ne dit pas le nombre de parametres : il vient de la carte du
        modele, recopie dans BRAIN_VLLM_MILLIARDS (0 = traite comme un grand
        modele, ce pour quoi on lance vLLM)."""
        from brain.codage.envergure import Envergure
        return Envergure(modele=self.modele, milliards=self.milliards or 100,
                         contexte=self.contexte)

    def _corps(self, systeme, messages, schema, outils, flux, max_jetons):
        corps = super()._corps(systeme, messages, schema, outils, flux,
                               max_jetons)
        corps["model"] = self.modele
        if flux:
            corps["stream_options"] = {"include_usage": True}
        return corps
