"""Tests de l'interface plein ecran (brain/interface.py) : l'ecran alterne
est pris et rendu, la zone defile, la barre reste a sa place."""
from __future__ import annotations

import io

from brain import console, interface


def _style():
    return console.Style("sombre", couleur=True)


def test_l_ecran_alterne_est_pris_puis_rendu():
    flux = io.StringIO()
    with interface.Interface(_style(), flux=flux):
        pass
    sortie = flux.getvalue()
    assert sortie.startswith("\033[?1049h")       # ecran alterne pris
    assert sortie.endswith("\033[0m\033[r\033[?1049l")  # et rendu proprement


def test_la_zone_de_defilement_epargne_la_barre():
    flux = io.StringIO()
    with interface.Interface(_style(), flux=flux) as itf:
        # la zone s'arrete avant la barre (3 lignes) + la marge (1 ligne)
        assert f"\033[1;{itf.hauteur - 4}r" in flux.getvalue()


def test_ecrire_se_place_en_bas_de_zone():
    flux = io.StringIO()
    with interface.Interface(_style(), flux=flux) as itf:
        itf.ecrire("bonjour")
    sortie = flux.getvalue()
    assert f"\033[{itf.bas_zone};1H" in sortie and "bonjour" in sortie


def test_la_barre_est_dessinee_aux_trois_dernieres_lignes():
    flux = io.StringIO()
    with interface.Interface(_style(), flux=flux) as itf:
        itf.dessiner_barre()
    sortie = flux.getvalue()
    bas = itf.hauteur
    assert f"\033[{bas - 2};1H" in sortie      # tete
    assert f"\033[{bas - 1};1H" in sortie      # champ
    assert f"\033[{bas};1H" in sortie          # pied
    assert "╭─ vous" in sortie and sortie.count("╰") == 1


def test_fluxzone_ajoute_le_saut_de_ligne_comme_django():
    flux = io.StringIO()
    with interface.Interface(_style(), flux=flux) as itf:
        zone = interface.FluxZone(itf)
        zone.write("un")
        zone.write("deux\n")
    sortie = flux.getvalue()
    assert "un\n" in sortie
    assert "deux\n" in sortie and "deux\n\n" not in sortie
