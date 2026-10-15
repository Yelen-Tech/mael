"""Presentation du terminal de MAEL : couleurs, mise en page, attente.

Tout ce qui touche a l'APPARENCE est ici, et nulle part ailleurs : le reste
du programme decide QUOI dire, ce module decide COMMENT ca s'affiche. On peut
donc changer le theme, couper les couleurs ou rediriger la sortie dans un
fichier sans toucher a la logique d'audit.

Trois regles tenues par le code :

  1. les couleurs se coupent -- variable NO_COLOR, option --sans-couleur, ou
     sortie qui n'est pas un terminal (un journal ne doit pas etre truffe de
     codes d'echappement) ;
  2. le texte se replie a la largeur reelle du terminal, avec un retrait
     aligne sous le prefixe : une reponse longue reste lisible ;
  3. rien ne clignote sans raison : l'indicateur d'attente s'efface
     completement quand la reponse arrive, et se tait si la sortie est
     redirigee.

Le rendu comprend le peu de mise en forme qu'un modele produit vraiment :
titres, listes, gras, code entre accents graves et blocs ``` -- pas un
moteur Markdown complet, juste ce qui sert.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import time

# --------------------------------------------------------------------------- #
# Themes : un nom -> les couleurs ANSI. Un seul endroit a changer.
# --------------------------------------------------------------------------- #
THEMES = {
    "sombre": {
        "accent": "\033[1;96m",      # cyan vif : le nom de MAEL
        "discret": "\033[90m",       # gris : les details techniques
        "lecture": "\033[32m",
        "attention": "\033[33m",
        "danger": "\033[31m",
        "code": "\033[36m",
        "titre": "\033[1m",
        # Les deux voix de la conversation : qui parle se voit au premier
        # coup d'oeil — vert pour l'humain, cyan pour MAEL.
        "utilisateur": "\033[1;38;5;82m",
        "assistant": "\033[1;38;5;51m",
    },
    "clair": {
        "accent": "\033[1;34m",
        "discret": "\033[2;30m",
        "lecture": "\033[32m",
        "attention": "\033[33m",
        "danger": "\033[31m",
        "code": "\033[34m",
        "titre": "\033[1m",
        "utilisateur": "\033[1;38;5;28m",
        "assistant": "\033[1;34m",
    },
}
RESET = "\033[0m"
GRAS = "\033[1m"

LARGEUR_MIN, LARGEUR_DEFAUT = 40, 100

_RE_GRAS = re.compile(r"\*\*(.+?)\*\*")
_RE_CODE = re.compile(r"`([^`\n]+)`")
_RE_PUCE = re.compile(r"^\s*[-*+]\s+")
_RE_NUM = re.compile(r"^\s*(\d+)[.)]\s+")
_RE_TITRE = re.compile(r"^\s*(#{1,6})\s+(.*)$")
_RE_ANSI = re.compile(r"\033\[[0-9;]*m")


def couleurs_possibles(flux=None) -> bool:
    """Le terminal accepte-t-il la couleur ?

    NO_COLOR est une convention respectee par les outils serieux ; une sortie
    redirigee (fichier, tube) n'est pas un terminal et ne doit rien recevoir
    d'autre que du texte."""
    if os.environ.get("NO_COLOR"):
        return False
    flux = flux or sys.stdout
    try:
        if not flux.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    # Windows : une console peut etre un terminal ET imprimer les sequences
    # ANSI en toutes lettres tant qu'on ne lui a pas active le rendu virtuel.
    # Si on n'y arrive pas, on rend du texte nu -- lisible -- plutot qu'un
    # ecran de codes d'echappement. (Ajout Yelen Tech, friction L3 du 22/09.)
    #
    # La question ne se pose que pour les VRAIES sorties du processus : on
    # interroge la console du processus, pas un flux quelconque. Un flux de
    # test ou un tampon en memoire garde donc le comportement d'avant.
    if flux not in (sys.stdout, sys.stderr):
        return True
    from . import machine
    return machine.activer_sequences_ansi()


def largeur(maximum: int = LARGEUR_DEFAUT) -> int:
    """Largeur utile : celle du terminal, bornee, jamais absurde."""
    try:
        colonnes = shutil.get_terminal_size().columns
    except OSError:
        colonnes = LARGEUR_DEFAUT
    return max(LARGEUR_MIN, min(colonnes - 2, maximum))


def longueur_visible(texte: str) -> int:
    """Longueur a l'ecran : les codes de couleur n'occupent aucune colonne."""
    return len(_RE_ANSI.sub("", texte))


def regle(titre: str, style: "Style", largeur_utile: int = 0) -> str:
    """Un separateur de section : « ── titre ────────── », en discret.

    Sert a separer visuellement les moments d'un echange (reponse, commande
    proposee, verdicts) pour que l'oeil sache toujours ou il en est."""
    largeur_utile = largeur_utile or largeur()
    tete = f"── {titre} "
    corps = (tete + "─" * largeur_utile)[:largeur_utile]
    return style.teinte(corps, style.discret)


class Style:
    """Les couleurs d'un theme, ou rien du tout si la couleur est coupee."""

    def __init__(self, theme: str = "sombre", couleur: bool = True):
        self.nom = theme if theme in THEMES else "sombre"
        self.couleur = couleur
        self._palette = THEMES[self.nom]

    def __getattr__(self, nom: str) -> str:
        palette = object.__getattribute__(self, "_palette")
        if nom not in palette:
            raise AttributeError(nom)
        return palette[nom] if self.couleur else ""

    @property
    def reset(self) -> str:
        return RESET if self.couleur else ""

    @property
    def gras(self) -> str:
        return GRAS if self.couleur else ""

    def teinte(self, texte: str, couleur: str) -> str:
        """Colore un fragment, sans jamais oublier de refermer."""
        return f"{couleur}{texte}{self.reset}" if self.couleur else texte


def _replier(texte: str, largeur_utile: int) -> list[str]:
    """Replie un paragraphe sans couper au milieu d'un mot.

    Un mot plus long que la ligne (un chemin, une empreinte) reste entier :
    mieux vaut deborder que rendre un chemin incopiable."""
    lignes, courante = [], ""
    for mot in texte.split():
        if not courante:
            courante = mot
        elif longueur_visible(courante) + 1 + longueur_visible(mot) <= largeur_utile:
            courante += " " + mot
        else:
            lignes.append(courante)
            courante = mot
    if courante:
        lignes.append(courante)
    return lignes or [""]


def rendre(texte: str, style: Style, largeur_utile: int = 0,
           retrait: str = "") -> str:
    """Met en forme la reponse du modele pour un terminal.

    Traite ce qu'un modele produit vraiment : blocs de code, titres, listes,
    gras et code en ligne. Le reste passe tel quel, replie a la bonne
    largeur."""
    largeur_utile = largeur_utile or largeur()
    utile = max(20, largeur_utile - len(retrait))
    sortie: list[str] = []
    dans_bloc = False

    for ligne in texte.splitlines():
        depouillee = ligne.strip()

        if depouillee.startswith("```"):
            dans_bloc = not dans_bloc
            langue = depouillee[3:].strip()
            barre = style.teinte("│", style.discret)
            if dans_bloc and langue:
                sortie.append(f"{retrait}{barre} "
                              + style.teinte(langue, style.discret))
            continue

        if dans_bloc:
            # Le code ne se replie jamais : une commande coupee en deux est
            # une commande fausse quand on la recopie.
            sortie.append(f"{retrait}{style.teinte('│', style.discret)} "
                          + style.teinte(ligne.rstrip(), style.code))
            continue

        if not depouillee:
            sortie.append("")
            continue

        titre = _RE_TITRE.match(ligne)
        if titre:
            sortie.append(retrait + style.teinte(titre.group(2).strip(),
                                                 style.titre))
            continue

        prefixe, corps = "", depouillee
        puce = _RE_PUCE.match(ligne)
        numero = _RE_NUM.match(ligne)
        if puce:
            prefixe = "• "
            corps = _RE_PUCE.sub("", depouillee, count=1)
        elif numero:
            prefixe = f"{numero.group(1)}. "
            corps = _RE_NUM.sub("", depouillee, count=1)

        corps = _RE_GRAS.sub(
            lambda m: style.teinte(m.group(1), style.gras), corps)
        corps = _RE_CODE.sub(
            lambda m: style.teinte(m.group(1), style.code), corps)

        creux = " " * len(prefixe)
        for i, morceau in enumerate(_replier(corps, utile - len(prefixe))):
            sortie.append(retrait + (prefixe if i == 0 else creux) + morceau)

    return "\n".join(sortie)


class Attente:
    """Indicateur d'activite pendant que le modele reflechit.

    S'efface entierement a la fin (aucune trace dans un copier-coller), et
    ne s'affiche pas du tout si la sortie n'est pas un terminal."""

    IMAGES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, message: str, style: Style, flux=None,
                 intervalle: float = 0.12, actif: bool | None = None):
        self.message = message
        self.style = style
        self.flux = flux or sys.stdout
        self.intervalle = intervalle
        # actif=False : l'utilisateur n'en veut pas. Meme demande, il ne
        # s'affiche jamais hors d'un terminal.
        self.actif = couleurs_possibles(self.flux) and (actif is not False)
        self._arret = threading.Event()
        self._fil: threading.Thread | None = None
        self.debut = 0.0

    def _tourner(self):
        i = 0
        while not self._arret.is_set():
            image = self.IMAGES[i % len(self.IMAGES)]
            secondes = time.perf_counter() - self.debut
            texte = f"  {image} {self.message} ({secondes:.0f} s)"
            self.flux.write("\r" + self.style.teinte(texte, self.style.discret))
            self.flux.flush()
            i += 1
            self._arret.wait(self.intervalle)

    def __enter__(self) -> "Attente":
        self.debut = time.perf_counter()
        if self.actif:
            self._fil = threading.Thread(target=self._tourner, daemon=True)
            self._fil.start()
        return self

    def __exit__(self, *exc) -> None:
        self._arret.set()
        if self._fil:
            self._fil.join(timeout=1)
        if self.actif:
            self.flux.write("\r" + " " * (len(self.message) + 24) + "\r")
            self.flux.flush()

    @property
    def secondes(self) -> float:
        return time.perf_counter() - self.debut
