"""Ou MAEL cherche ses outils externes (php, javac, eslint, trivy...).

Missions du 08/10/2026 : « php absent », « javac absent », « eslint,
html-validate, stylelint, gitleaks, trivy absents » dans TOUS les journaux.
Or un JDK existait deja sur la machine (dans un dossier de build Android),
simplement hors du PATH. MAEL cherche donc, dans l'ordre :

  1. le PATH ;
  2. SON dossier d'outils (MAEL_OUTILS, sinon backend/outils-externes/) :
     bin/, node_modules/.bin/ (outils npm), php/ ;
  3. des emplacements deja connus de la machine (JDK d'Android).

Rien n'est installe ici : c'est BESOINS-DE-MAEL.md (angles_morts.py) qui dit
au responsable quoi installer, ou et pourquoi. Le dossier d'outils evite de
toucher au PATH du systeme.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]


def dossier_outils() -> Path:
    return Path(os.environ.get("MAEL_OUTILS") or BACKEND / "outils-externes")


# Emplacements connus hors du dossier d'outils (ajoutes quand on les voit).
CONNUS = {
    "javac": [Path.home() / "android-build" / "jdk" / "bin"],
    "java": [Path.home() / "android-build" / "jdk" / "bin"],
}


def trouver(nom: str) -> str | None:
    """Le chemin de l'outil, ou None. Le PATH d'abord : un outil installe
    par l'utilisateur garde la priorite."""
    chemin = shutil.which(nom)
    if chemin:
        return chemin
    base = dossier_outils()
    dossiers = [base / "bin", base / "node_modules" / ".bin", base / nom,
                *CONNUS.get(nom, [])]
    for d in dossiers:
        chemin = shutil.which(nom, path=str(d))
        if chemin:
            return chemin
    return None
