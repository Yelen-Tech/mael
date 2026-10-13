"""Outils de SURFACE D'EXPOSITION : ce qu'un attaquant voit de l'exterieur.

Tous exigent la preuve de propriete de la cible (actif declare et prouve du
client) : on ne sonde que ce qui appartient au client. Licences MIT (aucune
restriction de revente) — nmap est ecarte : sa licence NPSL interdit de
l'inclure dans un produit commercial sans licence OEM.

  PortsOuverts      naabu     ports TCP en ecoute (scan de connexion, sans
                              privilege, debit limite)
  SousDomaines      subfinder sous-domaines publics d'un domaine (sources
                              passives : certificats, DNS publics)
  ServicesWeb       httpx     services web exposes : statut, titre,
                              technologies, HTTP en clair
"""
from __future__ import annotations

import json

from .base import Observation, Outil, registre

# Ports dont l'exposition directe est un risque en soi (acces distant
# en clair, bases de donnees, administration, partage de fichiers).
PORTS_RISQUES = {
    21: ("elevee", "FTP : identifiants et fichiers en clair"),
    23: ("critique", "Telnet : administration en clair"),
    25: ("faible", "SMTP : a reserver au serveur de messagerie"),
    111: ("elevee", "rpcbind : service RPC expose"),
    135: ("elevee", "RPC Windows expose"),
    139: ("elevee", "NetBIOS/SMB expose"),
    445: ("critique", "SMB expose (rancongiciels, vers)"),
    1433: ("critique", "SQL Server expose"),
    2375: ("critique", "API Docker sans TLS : prise de controle de l'hote"),
    3306: ("critique", "MySQL/MariaDB expose"),
    3389: ("elevee", "Bureau a distance (RDP) expose"),
    5432: ("critique", "PostgreSQL expose"),
    5900: ("elevee", "VNC expose"),
    6379: ("critique", "Redis expose (souvent sans authentification)"),
    9200: ("critique", "Elasticsearch expose"),
    11211: ("elevee", "Memcached expose (amplification)"),
    27017: ("critique", "MongoDB expose"),
}


def _lignes_json(sortie: str):
    """Objets JSON d'une sortie ligne a ligne (le bruit est ignore)."""
    for ligne in sortie.splitlines():
        ligne = ligne.strip()
        if not ligne.startswith("{"):
            continue
        try:
            yield json.loads(ligne)
        except json.JSONDecodeError:
            continue


@registre.inscrire
class PortsOuverts(Outil):
    nom = "ports_ouverts"
    description = (
        "Liste les ports TCP ouverts d'une cible declaree (1000 ports les "
        "plus courants par defaut) et signale ceux dont l'exposition est un "
        "risque (bases de donnees, SMB, Telnet, API Docker...)."
    )
    schema = {
        "type": "object",
        "properties": {
            "cible": {"type": "string", "description": "Domaine ou IP du client"},
            "ports": {"type": "string", "pattern": r"^(top-100|top-1000|[0-9,-]{1,200})$",
                      "default": "top-1000",
                      "description": "top-100, top-1000 ou liste « 22,80,443 »"},
        },
        "required": ["cible"],
        "additionalProperties": False,
    }
    image = "projectdiscovery/naabu"      # figee par images.lock (@sha256)
    # Le conteneur est --read-only : naabu ecrit son dossier de travail dans
    # /tmp et ne demarre pas sans (premier lancement reel, 20/09/2026).
    tmpfs = {"/tmp": "256m"}
    delai = 900

    def commande(self, *, cible: str, ports: str = "top-1000") -> list[str]:
        choix = (["-top-ports", ports.split("-", 1)[1]] if ports.startswith("top-")
                 else ["-p", ports])
        # -scan-type c : scan de CONNEXION (aucun paquet forge, aucune
        # capacite reseau requise : le conteneur tourne en --cap-drop ALL).
        return ["-host", cible, *choix, "-scan-type", "c", "-json", "-silent",
                "-rate", "200", "-retries", "1"]

    def analyser(self, sortie: str, obs: Observation) -> None:
        vus = set()
        for r in _lignes_json(sortie):
            port = r.get("port")
            if isinstance(port, dict):               # anciennes versions
                port = port.get("Port")
            try:
                port = int(port)
            except (TypeError, ValueError):
                continue
            if port in vus:
                continue
            vus.add(port)
            gravite, resume = PORTS_RISQUES.get(
                port, ("info", f"Port {port}/tcp ouvert"))
            obs.ajouter(code=f"port.{port}", gravite=gravite,
                        resume=f"{resume} (port {port}/tcp)",
                        port=port, ip=r.get("ip", ""))


@registre.inscrire
class SousDomaines(Outil):
    nom = "sous_domaines"
    description = (
        "Recense les sous-domaines publics d'un domaine du client a partir de "
        "sources passives (journaux de certificats, DNS publics) : revele les "
        "services oublies exposes sur Internet. Aucun paquet vers la cible."
    )
    schema = {
        "type": "object",
        "properties": {"cible": {"type": "string",
                                 "description": "Domaine du client"}},
        "required": ["cible"],
        "additionalProperties": False,
    }
    image = "projectdiscovery/subfinder"  # figee par images.lock (@sha256)
    # Conteneur --read-only : cet outil ecrit son dossier de travail dans
    # /tmp et, au premier lancement, ecrit sa configuration par defaut dans
    # /root/.config/subfinder -- sans quoi il ne demarre pas (premiers
    # lancements reels, 20/09/2026). Les deux sont en memoire et
    # disparaissent avec le conteneur.
    tmpfs = {"/tmp": "256m", "/root": "64m"}
    delai = 600
    MAX_CONSTATS = 200

    def commande(self, *, cible: str) -> list[str]:
        return ["-d", cible, "-oJ", "-silent", "-timeout", "30"]

    def analyser(self, sortie: str, obs: Observation) -> None:
        hotes = sorted({str(r.get("host", "")).lower()
                        for r in _lignes_json(sortie) if r.get("host")})
        for h in hotes[: self.MAX_CONSTATS]:
            obs.ajouter(code="surface.sous-domaine", gravite="info",
                        resume=f"Sous-domaine public : {h}", hote=h)
        if len(hotes) > self.MAX_CONSTATS:
            obs.ajouter(code="surface.sous-domaines-tronques", gravite="info",
                        resume=f"{len(hotes) - self.MAX_CONSTATS} sous-domaines "
                               f"de plus (liste complete dans le brut)")


@registre.inscrire
class ServicesWeb(Outil):
    nom = "services_web"
    description = (
        "Identifie le service web d'une cible declaree : statut, titre, "
        "serveur, technologies detectees, et signale un site servi en HTTP "
        "clair."
    )
    schema = {
        "type": "object",
        "properties": {"cible": {"type": "string",
                                 "description": "Domaine ou URL du client"}},
        "required": ["cible"],
        "additionalProperties": False,
    }
    image = "projectdiscovery/httpx"      # figee par images.lock (@sha256)
    # Conteneur --read-only : cet outil ecrit son dossier de travail
    # dans /tmp et ne demarre pas sans (premiers lancements reels,
    # 20/09/2026).
    tmpfs = {"/tmp": "256m"}
    delai = 300

    def commande(self, *, cible: str) -> list[str]:
        return ["-u", cible, "-json", "-silent", "-no-color", "-title",
                "-status-code", "-tech-detect", "-web-server",
                "-follow-redirects", "-rate-limit", "10"]

    def analyser(self, sortie: str, obs: Observation) -> None:
        for r in _lignes_json(sortie):
            url = str(r.get("url", ""))
            techs = r.get("tech") or r.get("technologies") or []
            # Le titre et la banniere sont du texte controle par le site :
            # ils restent des DETAILS, jamais dans le resume.
            obs.ajouter(code="web.service", gravite="info",
                        resume=f"Service web {url} (statut {r.get('status_code')})",
                        url=url, statut=r.get("status_code"),
                        titre=str(r.get("title", ""))[:120],
                        serveur=str(r.get("webserver", ""))[:80],
                        technologies=[str(t)[:60] for t in techs][:20])
            final = str(r.get("final_url") or url)
            if final.startswith("http://"):
                obs.ajouter(code="web.http-clair", gravite="elevee",
                            resume=f"{final} est servi en HTTP clair (pas de "
                                   f"redirection vers HTTPS)", url=final)
