"""Banniere du produit MAEL (Yelen Tech), affichee en tete du terminal.

Reprise du logo fourni (gemini-code-1789716906457.py, rendu avec rich) :
- 1re ligne corrigee (il manquait un espace avant le haut du « A », ce qui
  decalait A, E et L d'une colonne) ;
- rendu en ANSI pur, sans dependance : le terminal utilise deja ces
  couleurs, et l'offre sur site doit s'installer sans Internet.
"""
from __future__ import annotations

LOGO = [
    "███╗   ███╗ █████╗ ███████╗██╗     ",
    "████╗ ████║██╔══██╗██╔════╝██║     ",
    "██╔████╔██║███████║█████╗  ██║     ",
    "██║╚██╔╝██║██╔══██║██╔══╝  ██║     ",
    "██║ ╚═╝ ██║██║  ██║███████╗███████╗",
    "╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝╚══════╝",
]
SOUS_TITRE = "Noyau d'Intégrité & Audit de Conformité Local"
CREDITS = "Yelen Tech • Modèle Sécurisé 100% Air-Gapped"

_BLEU = "\033[94m"          # cadre (bright_blue)
_OR = "\033[1;38;5;220m"    # sous-titre (bold gold1)
_GRIS = "\033[2;37m"        # credits (dim white)
_RESET = "\033[0m"

# Le logo n'est plus d'un seul cyan : chaque ligne prend une teinte de la
# palette 256 couleurs, du bleu profond (haut) au cyan vif (bas). Ce degrade
# vertical donne du volume au lettrage — l'effet « 3D » de la banniere.
_DEGRADE = ["\033[1;38;5;%dm" % c for c in (25, 31, 37, 45, 51, 15)]


def lignes(couleurs: bool = True) -> list[str]:
    """Le panneau, ligne par ligne (cadre arrondi, marge d'un espace)."""
    c = (lambda code, t: f"{code}{t}{_RESET}") if couleurs else (lambda _, t: t)
    logo = [(_DEGRADE[i] if couleurs else None, l) for i, l in enumerate(LOGO)]
    contenu = logo + [(None, ""), (_OR, SOUS_TITRE), (_GRIS, CREDITS)]
    largeur = max(len(t) for _, t in contenu)
    sortie = [c(_BLEU, "╭" + "─" * (largeur + 2) + "╮")]
    for code, texte in contenu:
        rempli = texte.ljust(largeur)
        corps = c(code, rempli) if code and texte else rempli
        sortie.append(c(_BLEU, "│ ") + corps + c(_BLEU, " │"))
    sortie.append(c(_BLEU, "╰" + "─" * (largeur + 2) + "╯"))
    return sortie


def texte(couleurs: bool = True) -> str:
    return "\n".join(lignes(couleurs))


def devoler(flux, couleurs: bool = True, delai: float = 0.045) -> None:
    """Revele le panneau ligne par ligne, de haut en bas.

    Le resultat final est strictement identique a texte() : seule
    l'apparition est animee. A n'appeler que sur un vrai terminal — une
    sortie redirigee prend le texte() statique, sans temporisation."""
    import time
    for ligne in lignes(couleurs):
        flux.write("\n" + ligne)
        flux.flush()
        if delai:
            time.sleep(delai)


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    print(texte())
