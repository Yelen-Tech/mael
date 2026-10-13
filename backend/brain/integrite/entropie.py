"""Module 2 du noyau d'integrite : entropie de Shannon.

But : reperer du contenu INJECTE ou OBSCURCI dans les fichiers scelles
(fiches YAML, scripts des playbooks). Un blob base64, une charge chiffree ou
compilee se trahit par une entropie anormalement haute pour du texte
relisible par un humain.

Deux mesures :
  entropie(texte)   -- bits/octet, distribution des octets (0 a 8)
  analyser(chemin)  -- entropie globale + tokens longs au-dela du seuil

Seuils calibres sur le corpus reel (fiches + scripts, 19/09/2026) :
token le plus riche = 4,92 bits/octet (regex rsyslog), fichier le plus
riche = 5,63 (playbooks fichiers-motif, filtres audit b32/b64). Un blob
aleatoire d'1 Ko mesure ~7,8, un token base64 de 400 c ~5,9. Les empreintes
SHA-256 legitimes (~3,8 en hexa) sont exclues par motif. Voir
tests_integrite.py.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# Seuils (bits/octet). Un token long au-dela de SEUIL_TOKEN est signale ;
# le fichier entier au-dela de SEUIL_FICHIER est signale.
SEUIL_TOKEN = 5.5
SEUIL_FICHIER = 5.8

# Un token « long » : suite de 20+ caracteres sans espace.
_RE_TOKEN = re.compile(r"\S{20,}")

# Tokens legitimes, exclus de l'analyse : empreintes MD5/SHA-1/SHA-256
# (longueurs EXACTES 32/40/64) et dates ISO.
# Relecture 19/09/2026 (Claude) : exclure tout hexa >= 32 laissait passer
# une charge encodee en hexa (4 bits/octet au plus : jamais au-dela du
# seuil d'entropie). Les encodages sont donc aussi reperes par leur FORME.
_RE_HEX = re.compile(r"^(?:[0-9a-f]{32}|[0-9a-f]{40}|[0-9a-f]{64})$")
_RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_RE_HEX_LONG = re.compile(r"^(?:[0-9a-fA-F]{2}){33,}$")          # > 64 car.
_RE_B64 = re.compile(r"^[A-Za-z0-9+/]{40,}={0,2}$")


def _encodage_suspect(t: str) -> str | None:
    """Forme d'un blob encode, quelle que soit son entropie."""
    if _RE_HEX_LONG.match(t) and not _RE_HEX.match(t.lower()):
        return "hexadecimal long"
    if (_RE_B64.match(t) and re.search(r"[A-Z]", t) and re.search(r"[a-z]", t)
            and re.search(r"\d", t)):
        return "base64"
    return None


@dataclass
class Anomalie:
    """Un token ou un fichier dont l'entropie depasse le seuil."""
    ou: str                    # « fichier » ou « ligne N »
    extrait: str               # debut du token concerne
    valeur: float              # entropie mesuree (bits/octet)


def entropie(texte: str | bytes) -> float:
    """Entropie de Shannon en bits/octet. 0.0 sur une entree vide."""
    octets = texte.encode("utf-8") if isinstance(texte, str) else bytes(texte)
    if not octets:
        return 0.0
    n = len(octets)
    return -sum((c / n) * math.log2(c / n)
                for c in Counter(octets).values())


def _tokens_suspects(lignes: list[str]) -> list[Anomalie]:
    """Tokens longs a haute entropie, hors motifs legitimes (hexa, dates)."""
    trouves = []
    for i, ligne in enumerate(lignes, 1):
        for m in _RE_TOKEN.finditer(ligne):
            t = m.group(0).strip("'\"")
            if _RE_HEX.match(t.lower()) or _RE_DATE.match(t):
                continue
            forme = _encodage_suspect(t)
            if forme:
                trouves.append(Anomalie(f"ligne {i}", f"[{forme}] {t[:40]}",
                                        round(entropie(t), 2)))
                continue
            e = entropie(t)
            if e > SEUIL_TOKEN:
                trouves.append(Anomalie(f"ligne {i}", t[:40], round(e, 2)))
    return trouves


def analyser(chemin: Path) -> list[Anomalie]:
    """Anomalies d'entropie d'un fichier texte (vide = rien a signaler)."""
    brut = chemin.read_bytes()
    if b"\x00" in brut:                       # binaire : pas notre affaire ici
        return [Anomalie("fichier", "<binaire>", 8.0)]
    texte = brut.decode("utf-8", errors="replace")
    anomalies = _tokens_suspects(texte.splitlines())
    globale = entropie(brut)
    if globale > SEUIL_FICHIER:
        anomalies.append(Anomalie("fichier", chemin.name, round(globale, 2)))
    return anomalies


def analyser_arborescence(racine: Path, motif: str) -> dict[str, list[Anomalie]]:
    """Analyse tous les fichiers `motif` sous `racine` (ex. « *.yaml »)."""
    return {str(c): a for c in sorted(racine.rglob(motif))
            if (a := analyser(c))}
