"""Flux publics ne demandant aucune cle. Ce sont eux qui font tourner
le module Reputation le premier jour, sans inscription nulle part.

Les poids traduisent la precision observee de chaque source :
  - une liste de commande-et-controle est tres precise (peu de faux positifs)
  - une liste de noeuds Tor est factuelle mais pas une preuve de malveillance
"""
from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator

from ..base import Brut, Collecteur, lignes_utiles


class FeodoC2(Collecteur):
    """Serveurs de commande-et-controle de reseaux de machines zombies.

    Tres haute precision : une IP dans cette liste pilote activement des
    machines infectees. Poids maximal.
    """

    nom = "feodo"
    url = "https://feodotracker.abuse.ch/downloads/ipblocklist.json"
    description = "Serveurs de commande-et-controle (abuse.ch Feodo Tracker)"
    poids = 1.6

    def analyser(self, contenu: str) -> Iterator[Brut]:
        for entree in json.loads(contenu):
            famille = (entree.get("malware") or "inconnu").lower()
            yield Brut(
                type="ip",
                valeur=entree["ip_address"],
                score=0.95,
                categories=["c2", f"famille:{famille}"],
                asn=str(entree.get("as_number") or ""),
                pays=entree.get("country") or "",
            )


class UrlhausRecent(Collecteur):
    """URL distribuant des logiciels malveillants, signalees recemment."""

    nom = "urlhaus"
    url = "https://urlhaus.abuse.ch/downloads/csv_recent/"
    description = "URL de distribution de maliciels (abuse.ch URLhaus)"
    poids = 1.4
    delai = 120

    COLONNES = [
        "id", "dateadded", "url", "url_status", "last_online",
        "threat", "tags", "urlhaus_link", "reporter",
    ]

    def analyser(self, contenu: str) -> Iterator[Brut]:
        # Le fichier commence par des lignes de commentaire puis un en-tete.
        corps = "\n".join(lignes_utiles(contenu))
        for ligne in csv.DictReader(io.StringIO(corps), fieldnames=self.COLONNES):
            url = (ligne.get("url") or "").strip('"')
            if not url.startswith(("http://", "https://")):
                continue
            actif = (ligne.get("url_status") or "").strip('"') == "online"
            etiquettes = [
                t for t in (ligne.get("tags") or "").strip('"').split(",") if t
            ]
            yield Brut(
                type="url",
                valeur=url,
                # Une URL encore en ligne est une menace actuelle.
                score=0.92 if actif else 0.6,
                categories=["maliciel", *etiquettes[:5]],
            )


class SpamhausDrop(Collecteur):
    """Plages d'adresses entierement detournees ou vendues a des criminels.

    On ne developpe pas les plages en adresses individuelles : on enregistre
    la plage telle quelle, et la resolution se fera au moment de la requete.
    """

    nom = "spamhaus_drop"
    url = "https://www.spamhaus.org/drop/drop_v4.json"
    description = "Plages d'adresses detournees (Spamhaus DROP)"
    poids = 1.5

    def analyser(self, contenu: str) -> Iterator[Brut]:
        for ligne in lignes_utiles(contenu):
            try:
                entree = json.loads(ligne)
            except json.JSONDecodeError:
                continue
            plage = entree.get("cidr")
            if not plage:
                continue
            yield Brut(
                type="ip",
                valeur=plage,
                score=0.9,
                categories=["plage_detournee", f"sblid:{entree.get('sblid', '')}"],
            )


class NoeudsTor(Collecteur):
    """Noeuds de sortie du reseau Tor.

    Attention au poids : etre un noeud Tor n'est pas malveillant. C'est un
    fait contextuel utile (« cette connexion vient de Tor »), pas une preuve.
    Poids faible volontairement, pour que Tor seul ne suffise jamais a
    declencher un verdict « malveillant ».
    """

    nom = "tor_exit"
    url = "https://check.torproject.org/torbulkexitlist"
    description = "Noeuds de sortie Tor (contexte, pas malveillance)"
    poids = 0.4

    def analyser(self, contenu: str) -> Iterator[Brut]:
        for ligne in lignes_utiles(contenu):
            yield Brut(type="ip", valeur=ligne, score=0.35, categories=["tor"])


class ThreatFox(Collecteur):
    """Indicateurs de compromission recents, toutes familles confondues.

    abuse.ch demande desormais une cle d'authentification gratuite pour
    l'API. Sans cle, le flux est ignore proprement.
    """

    nom = "threatfox"
    url = "https://threatfox-api.abuse.ch/api/v1/"
    description = "Indicateurs recents multi-familles (abuse.ch ThreatFox)"
    poids = 1.3
    cle_requise = True

    def cle(self) -> str:
        from decouple import config
        return config("ABUSECH_KEY", default="")

    def recuperer(self) -> str:
        import httpx

        with httpx.Client(timeout=self.delai) as c:
            rep = c.post(
                self.url,
                json={"query": "get_iocs", "days": 3},
                headers={**self.entetes(), "Auth-Key": self.cle()},
            )
            rep.raise_for_status()
            return rep.text

    CORRESPONDANCE = {
        "ip:port": "ip",
        "domain": "domaine",
        "url": "url",
        "md5_hash": "empreinte",
        "sha256_hash": "empreinte",
    }

    def analyser(self, contenu: str) -> Iterator[Brut]:
        charge = json.loads(contenu)
        if charge.get("query_status") != "ok":
            raise ValueError(f"ThreatFox: {charge.get('query_status')}")
        for entree in charge.get("data", []) or []:
            type_cible = self.CORRESPONDANCE.get(entree.get("ioc_type"))
            if not type_cible:
                continue
            valeur = entree.get("ioc", "")
            if type_cible == "ip" and ":" in valeur:
                valeur = valeur.rsplit(":", 1)[0]
            confiance = float(entree.get("confidence_level") or 50) / 100
            yield Brut(
                type=type_cible,
                valeur=valeur,
                score=confiance,
                categories=[
                    entree.get("threat_type") or "inconnu",
                    f"famille:{(entree.get('malware_printable') or 'inconnu').lower()}",
                ],
            )
