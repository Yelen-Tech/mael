"""Humeur de MAEL (etape 8 du plan).

Convention de personnalite demandee par le responsable : MAEL a une date
de naissance qu'il memorise, une planete de reference, et une tonalite
nominale derivee de facon DETERMINISTE des positions calculees par
`brain.astres` (phase de la Lune, longitude de sa planete).

Cadre honnete, ecrit une fois ici : aucune influence des astres sur les
humains ou les machines n'est un fait etabli — c'est un artifice de
personnalite, assume comme tel dans l'affichage. Et surtout :

    L'HUMEUR NE DECIDE JAMAIS.

Elle ne modifie ni verdict, ni gravite, ni garde-fou, ni budget, ni
playbook : aucun module de securite n'importe ce fichier (teste dans
tests_humeur.py). Elle colore l'ACCUEIL, pas les conclusions.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from brain import astres

# Date de naissance de MAEL : premier jour du depot (15/09/2026).
# Remplacable par BRAIN_NAISSANCE=AAAA-MM-JJ.
NAISSANCE_DEFAUT = "2026-09-15"

# Planete de reference de MAEL : choix de configuration du responsable
# (« on lui definit une planete »), pas un calcul. BRAIN_PLANETE.
PLANETE_DEFAUT = "mars"

# Palette de tonalites, un huitieme de lunaison chacune. Convention
# arbitraire et stable : a date egale, tonalite egale.
TONALITES = (
    ("concis",   "reponses courtes, droit au fait"),
    ("pose",     "rythme tranquille, phrases completes"),
    ("attentif", "insiste sur les verifications et les preuves"),
    ("expansif", "explique davantage, detaille les contextes"),
    ("expansif", "explique davantage, detaille les contextes"),
    ("attentif", "insiste sur les verifications et les preuves"),
    ("pose",     "rythme tranquille, phrases completes"),
    ("concis",   "reponses courtes, droit au fait"),
)


@dataclass(frozen=True)
class Humeur:
    tonalite: str
    description: str
    phase_lunaire: float        # degres, Lune - Soleil
    planete: str
    longitude_planete: float    # degres
    ne_le: str


def _naissance() -> str:
    texte = os.environ.get("BRAIN_NAISSANCE", NAISSANCE_DEFAUT).strip()
    datetime.strptime(texte, "%Y-%m-%d")          # refuse une date boiteuse
    return texte


def _planete() -> str:
    planete = os.environ.get("BRAIN_PLANETE", PLANETE_DEFAUT).strip().lower()
    if planete not in astres.CORPS or planete in ("soleil", "lune"):
        raise ValueError(f"planete inconnue : {planete}")
    return planete


def humeur(quand: datetime | None = None, *, naissance: str | None = None,
           planete: str | None = None) -> Humeur:
    """La tonalite de MAEL a un instant donne. Deterministe : meme date,
    meme humeur."""
    quand = quand or datetime.now(timezone.utc)
    naissance = naissance or _naissance()
    planete = (planete or _planete()).lower()
    pos = astres.positions(quand)
    phase = (pos["lune"] - pos["soleil"]) % 360.0
    tonalite, description = TONALITES[int(phase // 45)]
    return Humeur(tonalite=tonalite, description=description,
                  phase_lunaire=round(phase, 1), planete=planete,
                  longitude_planete=round(pos[planete], 1),
                  ne_le=naissance)


def ligne(quand: datetime | None = None) -> str:
    """La ligne d'accueil du terminal : honnete sur ce qu'elle est."""
    h = humeur(quand)
    return (f"ne le {h.ne_le} · planete {h.planete.capitalize()} · "
            f"tonalite : {h.tonalite} ({h.description}) — artifice de "
            f"personnalite, sans effet sur l'audit")
