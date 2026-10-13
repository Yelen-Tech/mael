"""La SANTE du moteur : reconnaitre un moteur abime, le relancer, le dire.

Examen des 100 missions (08-09/10/2026) : apres sept missions, le serveur
Ollama — jamais relance depuis des heures — s'est mis a repondre du
CHARABIA (« and and Mark teacher Tu as le 1 1 1 … ») ou rien du tout, puis
des erreurs 500 et des delais de 20 minutes. MAEL l'a pris pour de vraies
reponses : 75 missions comptees comme ses echecs, alors que c'etait le
moteur. Rechargé a neuf, le meme modele repondait de nouveau juste.

D'ou trois regles :
  - une reponse vide ou du charabia n'est pas une reponse : on decharge le
    modele (son processus est arrete, sa memoire abimee avec lui) et on
    redemande UNE fois ;
  - si le moteur reste abime, ce n'est pas un echec de MAEL : MoteurEnPanne
    est leve, la mission est marquee « PANNE DU MOTEUR » et sera refaite ;
  - le detecteur est PRUDENT : du code, du CSS, du JSON ou une prose
    repetitive restent des reponses. Il ne juge que la forme (mots-outils
    en rafale, fragments sans structure), jamais le fond.
"""
from __future__ import annotations

import re
from collections import Counter

# La SONDE : une question dont la reponse est sure. Pas « reponds MAEL
# PRET » : un modele SAIN repondait « OK » ou s'excusait (essai du 09/10) ;
# un calcul simple, lui, est toujours juste quand le moteur va bien.
SONDE_SYSTEME = "Tu es un assistant."
SONDE = "Combien font 2 + 3 ? Reponds par le nombre seul."


def sonde_juste(texte: str) -> bool:
    t = texte or ""
    return re.search(r"(?<!\d)5(?!\d)", t) is not None or "cinq" in t.lower()


class MoteurEnPanne(RuntimeError):
    """Le moteur ne repond plus correctement, meme apres une relance."""


_MOT = re.compile(r"[^\W\d_]+", re.UNICODE)
# Signes de structure : un vrai texte en a (ponctuation de fin, code).
_STRUCTURE = re.compile(r"[.!?;:{}()<>=\[\]\"`#/]|\n\s*[-*\d]")


def charabia(texte: str) -> str:
    """La raison si `texte` est du charabia (ou vide), sinon ""."""
    t = (texte or "").strip()
    if not t:
        return "reponse vide"
    mots = [m.lower() for m in _MOT.findall(t)]
    if len(mots) < 25:
        return ""                        # trop court pour juger : on laisse
    compte = Counter(mots)
    _, n_premier = compte.most_common(1)[0]
    # 1) Un mot qui fait plus du quart du texte (« and and and … »).
    domine = n_premier / len(mots) > 0.25
    # 2) Des mots minuscules en rafale (« 1 1 1 », « le is Tu as le »).
    courts = sum(len(m) <= 3 for m in mots) / len(mots) > 0.6
    # 3) Peu de structure pour la longueur : une vraie reponse a de la
    #    ponctuation ou du code au moins tous les 40 mots.
    signes = len(_STRUCTURE.findall(t))
    deserte = signes < len(mots) / 40
    if (domine and courts) or (courts and deserte) or (domine and deserte):
        return (f"charabia ({len(mots)} mots, « {compte.most_common(1)[0][0]} »"
                f" x{n_premier}, {signes} signe(s) de structure)")
    return ""
