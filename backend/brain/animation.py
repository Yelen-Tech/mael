"""Orbe 3D du terminal MAEL : une animation filaire pendant que le modele
reflechit.

Sur un processeur sans GPU, une reponse du modele peut prendre des minutes :
l'attente est le moment ou l'utilisateur juge le produit. L'indicateur
classique (console.Attente) dit « ca travaille » ; l'orbe le MONTRE — deux
cubes emboites en contre-rotation et un anneau de particules, projetes en
perspective et dessines en braille (2x4 points par caractere, donc un trace
plus fin que le caractere pres).

Trois regles, les memes que console.py :

  1. aucune dependance : de la trigonometrie et des sequences ANSI, rien
     d'autre — l'offre « sur site » s'installe hors ligne ;
  2. le silence hors terminal : sortie redirigee, NO_COLOR ou actif=False ->
     l'orbe ne s'affiche jamais, et il ne laisse aucune trace quand il
     s'efface (un journal ne doit pas etre truffe de codes d'echappement) ;
  3. le modele n'attend pas l'animation : le rendu tourne dans un fil separe,
     exactement comme console.Attente.

Le calcul est borne : ~30 segments echantillonnes, un cadre tient en dessous
du millieme de seconde. Sur la machine la plus lente, l'orbe coute moins que
le clignotement du curseur qu'il remplace.
"""
from __future__ import annotations

import math
import sys
import threading
import time

from brain import console

# --------------------------------------------------------------------------- #
# Windows : les sequences ANSI (couleurs, curseur) ne sont comprises que si le
# mode « terminal virtuel » est active sur la console. Il ne l'est pas par
# defaut sous cmd/PowerShell : sans lui, l'utilisateur voit « ?25h » et « 13A »
# s'imprimer en clair. On l'active nous-memes, une fois, et on VERIFIE — si la
# console refuse (hote exotique), l'orbe s'abstient plutot que de salir
# l'ecran.
# --------------------------------------------------------------------------- #
_vt = None


def vt_pret() -> bool:
    """Rend True si le terminal sait interpreter les sequences ANSI.

    Sur Linux/macOS : toujours vrai. Sous Windows : on active
    ENABLE_VIRTUAL_TERMINAL_PROCESSING sur stdout, puis on relit le mode —
    actif ou pas, c'est la console qui a le dernier mot."""
    global _vt
    if _vt is not None:
        return _vt
    import os
    if os.name != "nt":
        _vt = True
        return _vt
    try:
        import ctypes
        noyau = ctypes.windll.kernel32
        # Les signatures sont obligatoires : sans elles, ctypes tronque le
        # HANDLE 64 bits en int 32 bits et GetConsoleMode echoue en silence.
        noyau.GetStdHandle.restype = ctypes.c_void_p
        noyau.GetStdHandle.argtypes = [ctypes.c_ulong]
        noyau.GetConsoleMode.argtypes = [ctypes.c_void_p,
                                         ctypes.POINTER(ctypes.c_ulong)]
        noyau.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        h = noyau.GetStdHandle(0xFFFFFFF5)   # STD_OUTPUT_HANDLE = (DWORD)-11
        mode = ctypes.c_ulong()
        if not h or not noyau.GetConsoleMode(h, ctypes.byref(mode)):
            _vt = False                      # pas une console Windows (MinTTY…)
            return _vt
        if not mode.value & 0x0004:          # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            noyau.SetConsoleMode(h, mode.value | 0x0004)
            noyau.GetConsoleMode(h, ctypes.byref(mode))
        _vt = bool(mode.value & 0x0004)
    except Exception:                        # noqa: BLE001 — jamais de crash
        _vt = False                          #   pour de l'affichage
    return _vt

# --------------------------------------------------------------------------- #
# Geometrie : un cube exterieur, un cube interieur en contre-rotation, et un
# anneau de particules en orbite. Coordonnees dans [-1, 1].
# --------------------------------------------------------------------------- #
_SOMMETS = [(x, y, z) for z in (-1.0, 1.0) for y in (-1.0, 1.0)
            for x in (-1.0, 1.0)]
_ARETES = ((0, 1), (1, 3), (3, 2), (2, 0), (4, 5), (5, 7), (7, 6), (6, 4),
           (0, 4), (1, 5), (3, 7), (2, 6))
_PARTICULES = 8                      # points sur l'anneau orbital
_ECHANTILLONS = 14                   # points traces par arete

# Du bleu profond (loin) au blanc-cyan (pres) : la profondeur se lit en
# couleur, c'est ce qui donne le volume. Palette 256 couleurs.
_PROFONDEUR = (25, 31, 37, 45, 51, 15)

# Braille : chaque caractere est une grille de 2x4 points. Bit de chaque
# point, selon sa position dans le caractere.
_BITS = {(0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (0, 3): 0x40,
         (1, 0): 0x08, (1, 1): 0x10, (1, 2): 0x20, (1, 3): 0x80}

LARGEUR, HAUTEUR = 26, 13            # en caracteres (52x52 points braille)


def _rotation(x: float, y: float, z: float, a: float, b: float):
    """Lacet (a, autour de Y) puis tangage (b, autour de X)."""
    ca, sa, cb, sb = math.cos(a), math.sin(a), math.cos(b), math.sin(b)
    x, z = x * ca + z * sa, -x * sa + z * ca
    y, z = y * cb - z * sb, y * sb + z * cb
    return x, y, z


def _projeter(p, rayon: float, distance: float = 4.0, focale: float = 2.3):
    """Perspective : les points proches s'ecartent, les lointains se
    resserrent. Rend (px, py, z) en coordonnees-points braille."""
    x, y, z = p
    f = focale / (z + distance)
    return x * f * rayon, -y * f * rayon, z


def _cadre(angle: float, largeur: int, hauteur: int,
           couleurs: bool) -> list[str]:
    """Un instantane de l'orbe : `hauteur` lignes d'au plus `largeur`
    colonnes, colorees par profondeur si `couleurs`."""
    cellules: dict[tuple[int, int], list] = {}   # (cx, cy) -> [bits, z min]
    cx0, cy0 = largeur, hauteur * 2              # centre, en points braille
    # Le sommet le plus lointain vaut au plus sqrt(3)*focale/(distance-sqrt(3))
    # fois le rayon : le facteur 1.85 garantit que rien ne sort du cadre.
    rayon = max(4.0, min(largeur, hauteur * 2) / 1.85)

    def marquer(p):
        px, py, z = _projeter(p, rayon)
        pix, piy = round(px) + cx0, round(py) + cy0
        cx, cy = pix // 2, piy // 4
        if 0 <= cx < largeur and 0 <= cy < hauteur:
            entree = cellules.setdefault((cx, cy), [0, 99.0])
            entree[0] |= _BITS[(pix % 2, piy % 4)]
            entree[1] = min(entree[1], z)

    # Deux cubes emboites, en contre-rotation : le « noyau ».
    for echelle, va, vb, da, db in ((1.00, 1.00, 0.60, 0.0, 0.35),
                                    (0.55, -1.50, -1.05, 0.6, 0.50)):
        a, b = angle * va + da, angle * vb + db
        pts = [_rotation(x * echelle, y * echelle, z * echelle, a, b)
               for x, y, z in _SOMMETS]
        for i, j in _ARETES:
            (x0, y0, z0), (x1, y1, z1) = pts[i], pts[j]
            for k in range(_ECHANTILLONS + 1):
                t = k / _ECHANTILLONS
                marquer((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t,
                         z0 + (z1 - z0) * t))

    # Anneau orbital de particules, incline comme un anneau de Saturne.
    for k in range(_PARTICULES):
        t = 2 * math.pi * k / _PARTICULES + angle * 0.9
        marquer(_rotation(1.55 * math.cos(t), 0.0, 1.55 * math.sin(t),
                          0.0, 0.45))

    lignes = []
    teinte_max = len(_PROFONDEUR) - 1
    for cy in range(hauteur):
        morceaux, actif, derniere = [], None, -1
        for cx in range(largeur):
            bits, z = cellules.get((cx, cy), (0, 99.0))
            if bits:
                # z dans [-1.7, 1.7] environ : proche -> teinte claire.
                teinte = _PROFONDEUR[min(teinte_max, max(0, round(
                    (1.0 - (z + 1.7) / 3.4) * teinte_max)))]
            else:
                teinte = None
            if couleurs and teinte != actif:
                morceaux.append(f"\033[38;5;{teinte}m" if teinte is not None
                                else console.RESET)
                actif = teinte
            morceaux.append(chr(0x2800 + bits) if bits else " ")
            if bits:
                derniere = len(morceaux)
        if derniere < 0:
            lignes.append("")
        else:
            corps = morceaux[:derniere]
            if couleurs and actif is not None:
                corps.append(console.RESET)
            lignes.append("".join(corps))
    return lignes


def cadres(largeur: int = LARGEUR, hauteur: int = HAUTEUR,
           couleurs: bool = True, pas: float = 0.13):
    """Generateur infini de cadres. `pas` est la vitesse de rotation."""
    angle = 0.0
    while True:
        yield _cadre(angle, largeur, hauteur, couleurs)
        angle += pas


class Orbe:
    """Indicateur d'attente anime : l'orbe 3D sous la ligne de message.

    Meme contrat que console.Attente (gestionnaire de contexte, propriete
    `secondes`, silencieux hors terminal) pour etre interchangeable. A la
    sortie, tout est efface : il ne reste rien a l'ecran."""

    def __init__(self, message: str, style: console.Style, flux=None,
                 intervalle: float = 0.09, actif: bool | None = None,
                 hauteur: int = HAUTEUR, largeur: int = LARGEUR):
        self.message = message
        self.style = style
        self.flux = flux or sys.stdout
        self.intervalle = intervalle
        self.hauteur = max(5, hauteur)
        self.largeur = max(10, largeur)
        # Meme garde que console.Attente : jamais d'animation hors d'un
        # terminal, et une demande explicite (actif=False) prime toujours.
        # vt_pret() : sans sequences ANSI, l'orbe s'abstient (sinon l'ecran
        # se couvre de « ?25h » et « 13A » en clair).
        self.actif = console.couleurs_possibles(self.flux) \
            and (actif is not False) and vt_pret()
        self._arret = threading.Event()
        self._fil: threading.Thread | None = None
        self._lignes_ecrites = 0
        self.debut = 0.0

    def _ecrire(self, lignes: list[str]):
        if self._lignes_ecrites:
            # Remonter a la premiere ligne du dessin precedent.
            self.flux.write(f"\033[{self._lignes_ecrites - 1}A\r")
        self.flux.write("\n".join("\033[2K" + l for l in lignes))
        self.flux.flush()
        self._lignes_ecrites = len(lignes)

    def _tourner(self):
        images = console.Attente.IMAGES
        gen = cadres(largeur=self.largeur, hauteur=self.hauteur,
                     couleurs=bool(self.style.couleur))
        i = 0
        while not self._arret.is_set():
            secondes = time.perf_counter() - self.debut
            tete = self.style.teinte(
                f"  {images[i % len(images)]} {self.message} "
                f"({secondes:.0f} s)", self.style.discret)
            corps = [self.style.teinte("  ", self.style.discret) + l
                     if l else "" for l in next(gen)]
            self._ecrire([tete, *corps])
            i += 1
            self._arret.wait(self.intervalle)

    def __enter__(self) -> "Orbe":
        self.debut = time.perf_counter()
        if self.actif:
            self.flux.write("\033[?25l")      # curseur cache pendant l'anim
            self._fil = threading.Thread(target=self._tourner, daemon=True)
            self._fil.start()
        return self

    def __exit__(self, *exc) -> None:
        self._arret.set()
        if self._fil:
            self._fil.join(timeout=1)
        if self.actif:
            n = self._lignes_ecrites
            if n:
                # Effacer chaque ligne puis revenir en haut : aucune trace.
                self.flux.write(f"\033[{n - 1}A\r"
                                + "\n".join(["\033[2K"] * n)
                                + f"\033[{n - 1}A\r")
            self.flux.write("\033[?25h")      # curseur rendu
            self.flux.flush()

    @property
    def secondes(self) -> float:
        return time.perf_counter() - self.debut


if __name__ == "__main__":
    # Demonstration : python -m brain.animation  (Ctrl+C pour sortir)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    with Orbe("MAEL reflechit", console.Style("sombre", True)) as o:
        try:
            while o.secondes < 30:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
