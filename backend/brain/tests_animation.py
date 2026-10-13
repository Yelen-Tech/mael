"""Tests de l'orbe 3D (brain/animation.py) : le dessin se teste comme le
reste — dimensions, silence hors terminal, effacement sans trace."""
from __future__ import annotations

import io
import time

from brain import animation, console


class _FauxTerminal(io.StringIO):
    def isatty(self):
        return True


# --------------------------------------------------------------------------- #
# Les cadres
# --------------------------------------------------------------------------- #
def test_cadre_a_la_bonne_taille():
    cadre = next(animation.cadres(largeur=20, hauteur=10, couleurs=False))
    assert len(cadre) == 10
    assert all(console.longueur_visible(l) <= 20 for l in cadre)


def test_cadre_sans_couleur_ne_pose_aucun_code():
    cadre = next(animation.cadres(couleurs=False))
    assert "\033" not in "\n".join(cadre)


def test_cadre_non_vide():
    # un orbe invisible serait un bug, pas une esthetique
    cadre = next(animation.cadres(couleurs=False))
    assert any(c not in " ⠀" for ligne in cadre for c in ligne)


def test_l_orbe_tourne():
    gen = animation.cadres(couleurs=False)
    premier = next(gen)
    for _ in range(5):
        plus_loin = next(gen)
    assert premier != plus_loin


def test_la_profondeur_colore_le_dessin():
    cadre = next(animation.cadres(couleurs=True))
    teintes = {code for ligne in cadre
               for code in __import__("re").findall(r"38;5;(\d+)", ligne)}
    assert len(teintes) >= 2          # proche et lointain ne se confondent pas


# --------------------------------------------------------------------------- #
# L'orbe en contexte
# --------------------------------------------------------------------------- #
def test_orbe_muet_hors_terminal():
    flux = io.StringIO()
    with animation.Orbe("reflexion", console.Style("sombre", couleur=False),
                        flux=flux) as o:
        assert o.actif is False
    assert flux.getvalue() == ""      # aucune trace dans un journal


def test_orbe_respecte_la_demande_de_silence():
    import os
    avant = os.environ.pop("NO_COLOR", None)
    try:
        flux = _FauxTerminal()
        with animation.Orbe("reflexion", console.Style("sombre", couleur=True),
                            flux=flux, actif=False) as o:
            assert o.actif is False
        assert flux.getvalue() == ""
    finally:
        if avant is not None:
            os.environ["NO_COLOR"] = avant


def test_orbe_anime_puis_efface_et_rend_le_curseur():
    import os
    avant = os.environ.pop("NO_COLOR", None)   # un NO_COLOR ambiant fausserait
    avant_vt = animation._vt                   # le test, pas le produit
    animation._vt = True        # la console de test n'est pas une console reelle
    try:
        flux = _FauxTerminal()
        with animation.Orbe("reflexion", console.Style("sombre", couleur=True),
                            flux=flux, intervalle=0.02) as o:
            assert o.actif is True
            time.sleep(0.15)
            assert o.secondes > 0
        sortie = flux.getvalue()
        assert "reflexion" in sortie
        assert "\033[2K" in sortie        # chaque ligne effacee
        assert "\033[?25l" in sortie and sortie.rstrip().endswith("\033[?25h")
    finally:
        if avant is not None:
            os.environ["NO_COLOR"] = avant
        animation._vt = avant_vt


def test_sans_terminal_virtuel_l_orbe_s_abstient():
    """Sous Windows sans mode VT, les sequences d'effacement s'imprimeraient
    en clair (« ?25h », « 13A ») : l'orbe prefere ne rien afficher."""
    avant_vt = animation._vt
    animation._vt = False
    try:
        flux = _FauxTerminal()
        with animation.Orbe("reflexion", console.Style("sombre", couleur=True),
                            flux=flux) as o:
            assert o.actif is False
        assert flux.getvalue() == ""
    finally:
        animation._vt = avant_vt
