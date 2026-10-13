"""Flux demandant une cle d'API. Tous ont une offre gratuite suffisante
pour demarrer ; sans cle, ils sont ignores proprement (jamais d'echec).
"""
from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
from decouple import config

from ..base import Brut, Collecteur


class AbuseIPDB(Collecteur):
    """Liste noire d'adresses signalees par la communaute.

    Offre gratuite : 1 000 adresses par jour, largement assez pour la base
    de depart. Le champ `abuseConfidenceScore` est deja une confiance 0-100,
    on la reprend telle quelle.
    """

    nom = "abuseipdb"
    url = "https://api.abuseipdb.com/api/v2/blacklist"
    description = "Adresses signalees par la communaute (AbuseIPDB)"
    poids = 1.2
    cle_requise = True
    delai = 120

    def cle(self) -> str:
        return config("ABUSEIPDB_KEY", default="")

    def recuperer(self) -> str:
        with httpx.Client(timeout=self.delai) as c:
            rep = c.get(
                self.url,
                headers={**self.entetes(), "Key": self.cle(), "Accept": "application/json"},
                params={"confidenceMinimum": 75, "limit": 10000},
            )
            rep.raise_for_status()
            return rep.text

    def analyser(self, contenu: str) -> Iterator[Brut]:
        for entree in json.loads(contenu).get("data", []) or []:
            yield Brut(
                type="ip",
                valeur=entree["ipAddress"],
                score=float(entree.get("abuseConfidenceScore", 0)) / 100,
                categories=["signale_communaute"],
                pays=entree.get("countryCode") or "",
            )


class AlienVaultOTX(Collecteur):
    """Impulsions de la communaute OTX : indicateurs groupes par campagne."""

    nom = "otx"
    url = "https://otx.alienvault.com/api/v1/pulses/subscribed"
    description = "Campagnes et indicateurs (AlienVault OTX)"
    poids = 1.1
    cle_requise = True
    delai = 180

    CORRESPONDANCE = {
        "IPv4": "ip", "IPv6": "ip",
        "domain": "domaine", "hostname": "domaine",
        "URL": "url", "URI": "url",
        "FileHash-MD5": "empreinte", "FileHash-SHA1": "empreinte",
        "FileHash-SHA256": "empreinte",
    }

    def cle(self) -> str:
        return config("OTX_KEY", default="")

    def recuperer(self) -> str:
        with httpx.Client(timeout=self.delai) as c:
            rep = c.get(
                self.url,
                headers={**self.entetes(), "X-OTX-API-KEY": self.cle()},
                params={"limit": 50},
            )
            rep.raise_for_status()
            return rep.text

    def analyser(self, contenu: str) -> Iterator[Brut]:
        for impulsion in json.loads(contenu).get("results", []) or []:
            etiquettes = [t.lower() for t in (impulsion.get("tags") or [])[:3]]
            for ind in impulsion.get("indicators", []) or []:
                type_cible = self.CORRESPONDANCE.get(ind.get("type"))
                if not type_cible:
                    continue
                yield Brut(
                    type=type_cible,
                    valeur=ind.get("indicator", ""),
                    score=0.75,
                    categories=["campagne", *etiquettes],
                )
