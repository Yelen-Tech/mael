"""Pont vers analyse_js.cjs : couches 3 et 4 pour JavaScript.

L'analyse elle-meme est ecrite en JavaScript, avec acorn (vendor/acorn,
licence MIT, embarque : aucun telechargement chez l'utilisateur). Ici on ne
fait que l'appeler et relire sa reponse.

Rend None — et les juges reprennent alors les motifs et `node --check` —
quand node est absent, ou quand l'analyseur lui-meme echoue. Un juge en
panne ne doit jamais devenir un juge qui dit « rien a signaler » : None
veut dire « je n'ai pas pu », pas « c'est propre ».
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .juges import GRAVITE, Defaut

SCRIPT = Path(__file__).with_name("analyse_js.cjs")
ACORN = Path(__file__).parent / "vendor" / "acorn" / "acorn.js"
ACORN_JSX = Path(__file__).parent / "vendor" / "acorn-jsx" / "index.js"


def disponible() -> bool:
    return (bool(shutil.which("node")) and SCRIPT.exists() and ACORN.exists()
            and ACORN_JSX.exists())


def analyser(fichier: str, texte: str) -> list[Defaut] | None:
    if not texte.strip():
        return []           # rien a juger : c'est propre, et c'est vrai
    if not disponible():
        return None
    try:
        options = ["--jsx"] if fichier.lower().endswith(".jsx") else []
        r = subprocess.run([shutil.which("node"), str(SCRIPT), *options],
                           input=texte,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    try:
        brut = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return None
    defauts = []
    for x in brut:
        try:
            defauts.append(Defaut(fichier, int(x["ligne"]), str(x["regle"]),
                                  GRAVITE(x["gravite"]), str(x["message"]),
                                  str(x["norme"])))
        except (KeyError, ValueError, TypeError):
            return None     # reponse illisible = analyse non faite
    return defauts
