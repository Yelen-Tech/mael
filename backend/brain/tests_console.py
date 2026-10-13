"""Tests de la presentation (brain/console.py) et des reglages
(brain/reglages.py) : l'affichage se teste comme le reste."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from brain import console, reglages


# --------------------------------------------------------------------------- #
# Couleurs
# --------------------------------------------------------------------------- #
def test_style_sans_couleur_ne_pose_aucun_code():
    nu = console.Style("sombre", couleur=False)
    assert nu.accent == "" and nu.reset == "" and nu.gras == ""
    assert nu.teinte("bonjour", nu.accent) == "bonjour"

    colore = console.Style("sombre", couleur=True)
    assert colore.teinte("x", colore.accent).endswith(console.RESET)


def test_theme_inconnu_retombe_sur_sombre():
    assert console.Style("fuchsia").nom == "sombre"
    assert console.Style("clair").nom == "clair"


def test_no_color_coupe_la_couleur():
    import os

    class FauxFlux:
        def isatty(self):
            return True

    avant = os.environ.get("NO_COLOR")
    try:
        os.environ["NO_COLOR"] = "1"
        assert console.couleurs_possibles(FauxFlux()) is False
        del os.environ["NO_COLOR"]
        assert console.couleurs_possibles(FauxFlux()) is True
    finally:
        if avant is not None:
            os.environ["NO_COLOR"] = avant
        else:
            os.environ.pop("NO_COLOR", None)


def test_sortie_redirigee_reste_du_texte_brut():
    import io
    assert console.couleurs_possibles(io.StringIO()) is False


# --------------------------------------------------------------------------- #
# Mise en page
# --------------------------------------------------------------------------- #
_NU = console.Style("sombre", couleur=False)


def test_repli_respecte_la_largeur_et_ne_coupe_pas_les_mots():
    texte = "mot " * 40
    rendu = console.rendre(texte, _NU, largeur_utile=30)
    for ligne in rendu.splitlines():
        assert len(ligne) <= 30, ligne
    assert "mot" in rendu and "mo\nt" not in rendu


def test_un_chemin_plus_long_que_la_ligne_reste_entier():
    """Mieux vaut deborder qu'un chemin coupe en deux, incopiable."""
    chemin = "/etc/sysctl.d/99-tres-tres-long-nom-de-fichier.conf"
    rendu = console.rendre(chemin, _NU, largeur_utile=20)
    assert chemin in rendu


def test_bloc_de_code_jamais_replie():
    texte = ("voici :\n```bash\n"
             "find / -xdev -type f -perm -4000 -print 2>/dev/null | sort\n"
             "```\nvoila")
    rendu = console.rendre(texte, _NU, largeur_utile=30)
    assert "find / -xdev -type f -perm -4000 -print 2>/dev/null | sort" in rendu


def test_listes_titres_gras_et_code_en_ligne():
    texte = ("## Constat\n"
             "- premier point\n"
             "- deuxieme point\n"
             "1. etape une\n"
             "un mot **important** et `sshd -T` en ligne")
    rendu = console.rendre(texte, _NU, largeur_utile=60)
    assert "Constat" in rendu and "#" not in rendu
    assert "• premier point" in rendu
    assert "1. etape une" in rendu
    assert "**" not in rendu and "`" not in rendu
    assert "important" in rendu and "sshd -T" in rendu


def test_retrait_aligne_chaque_ligne():
    rendu = console.rendre("mot " * 30, _NU, largeur_utile=40, retrait="    ")
    assert all(l.startswith("    ") for l in rendu.splitlines() if l)


def test_longueur_visible_ignore_les_couleurs():
    colore = console.Style("sombre", couleur=True)
    assert console.longueur_visible(colore.teinte("abcd", colore.accent)) == 4


def test_regle_section_tient_la_largeur_et_nomme_la_section():
    r = console.regle("commande proposee", _NU, largeur_utile=40)
    assert console.longueur_visible(r) == 40
    assert r.startswith("── commande proposee ─")
    # sans couleur : aucun code ; avec couleur : refermee proprement
    assert "\033" not in r
    colore = console.Style("sombre", couleur=True)
    assert console.regle("x", colore, 20).endswith(console.RESET)


def test_les_deux_voix_ont_des_couleurs_distinctes():
    for theme in THEMES_NOMS:
        s = console.Style(theme, couleur=True)
        assert s.utilisateur and s.assistant
        assert s.utilisateur != s.assistant


THEMES_NOMS = ("sombre", "clair")


def test_largeur_bornee():
    assert console.largeur(maximum=60) <= 60
    assert console.largeur(maximum=10) >= console.LARGEUR_MIN


def test_attente_muette_hors_terminal():
    import io
    flux = io.StringIO()
    style = console.Style("sombre", couleur=False)
    with console.Attente("reflexion", style, flux=flux) as a:
        assert a.actif is False
    assert flux.getvalue() == ""          # aucune trace dans un journal


# --------------------------------------------------------------------------- #
# Reglages
# --------------------------------------------------------------------------- #
def test_reglages_defauts_complets():
    valeurs = reglages.defauts()
    assert set(valeurs) == set(reglages.CONNUS)
    assert valeurs["theme"] == "sombre" and valeurs["executer"] is False


def test_reglages_aller_retour_sur_fichier():
    with tempfile.TemporaryDirectory() as tmp:
        chemin = Path(tmp) / "reglages.json"
        valeurs = reglages.defauts() | {"theme": "clair", "largeur_max": 80}
        reglages.enregistrer(valeurs, chemin)
        relus, plaintes = reglages.charger(chemin)
        assert plaintes == []
        assert relus["theme"] == "clair" and relus["largeur_max"] == 80


def test_fichier_abime_ne_bloque_pas_le_demarrage():
    with tempfile.TemporaryDirectory() as tmp:
        chemin = Path(tmp) / "reglages.json"
        chemin.write_text("{ceci n'est pas du json", encoding="utf-8")
        valeurs, plaintes = reglages.charger(chemin)
        assert valeurs == reglages.defauts()
        assert plaintes and "illisible" in plaintes[0]


def test_valeur_impossible_refusee_et_dite():
    with tempfile.TemporaryDirectory() as tmp:
        chemin = Path(tmp) / "reglages.json"
        chemin.write_text(json.dumps({"theme": "fuchsia", "inconnu": 1,
                                      "largeur_max": "beaucoup"}),
                          encoding="utf-8")
        valeurs, plaintes = reglages.charger(chemin)
        assert valeurs["theme"] == "sombre"          # defaut garde
        assert valeurs["largeur_max"] == 100
        assert any("theme" in p for p in plaintes)
        assert any("inconnu" in p for p in plaintes)


def test_oui_non_acceptes_pour_les_reglages_a_deux_etats():
    valeurs = reglages.defauts()
    for dit, attendu in (("oui", True), ("non", False), ("1", True),
                         ("off", False)):
        nouveaux, message = reglages.modifier(valeurs, "couleurs", dit)
        assert nouveaux["couleurs"] is attendu, (dit, message)
    _, message = reglages.modifier(valeurs, "couleurs", "peut-etre")
    assert "oui ou non" in message


def test_reglage_inconnu_propose_une_piste():
    _, message = reglages.modifier(reglages.defauts(), "them", "clair")
    assert "inconnu" in message and "theme" in message


def test_ligne_de_commande_gagne_mais_n_ecrase_pas_pour_rien():
    enregistres = reglages.defauts() | {"profil": "court", "theme": "clair"}
    # une option reellement passee gagne
    final = reglages.appliquer_options(enregistres, {"profil": "complet"})
    assert final["profil"] == "complet"
    # une option absente ne doit PAS ramener le defaut
    final = reglages.appliquer_options(enregistres, {"profil": None,
                                                     "theme": ""})
    assert final["profil"] == "court" and final["theme"] == "clair"


def test_description_lisible():
    lignes = reglages.decrire(reglages.defauts())
    assert len(lignes) == len(reglages.CONNUS)
    assert any(l.startswith("theme") and "sombre" in l for l in lignes)
    assert any("non" in l for l in lignes)      # executer = non par defaut


# --------------------------------------------------------------------------- #
# L'aide ne doit pas mentir : une commande ajoutee doit y figurer
# --------------------------------------------------------------------------- #
def test_l_aide_cite_toutes_les_commandes_du_terminal():
    """Une aide qui oublie une commande est pire que pas d'aide : on croit
    savoir ce que sait faire MAEL. Le test lit le code de la boucle et exige
    que chaque « /commande » traitee soit citee dans /aide."""
    import re
    from pathlib import Path

    source = Path("core/management/commands/terminal.py").read_text(
        encoding="utf-8")
    boucle = source.split("def handle(", 1)[1].split("def _tour(", 1)[0]
    aide = source.split("def _aide(", 1)[1].split("def _parametres(", 1)[0]

    # Les formes reconnues dans la boucle : {"/x", ...}, startswith("/x")
    commandes = set(re.findall(r'"(/[a-zA-Zé?]+)"', boucle))
    # Alias et raccourcis : on n'exige que la forme longue de chaque famille.
    alias = {"/help", "/?", "/h", "/q", "/e", "/f", "/nouveau", "/systeme",
             "/réglages", "/reglages", "/paramètres", "/écarts", "/état",
             "/quit"}
    attendues = {c for c in commandes if c not in alias}
    manquantes = sorted(c for c in attendues if c not in aide)
    assert not manquantes, f"absentes de /aide : {manquantes}"


def test_l_aide_ne_cite_pas_de_commande_inexistante():
    """L'inverse : une commande retiree du code doit disparaitre de l'aide."""
    import re
    from pathlib import Path

    source = Path("core/management/commands/terminal.py").read_text(
        encoding="utf-8")
    boucle = source.split("def handle(", 1)[1].split("def _tour(", 1)[0]
    aide = source.split("def _aide(", 1)[1].split("def _parametres(", 1)[0]

    citees = {c.rstrip(",.") for c in re.findall(r'\("(/[a-z]+)', aide)}
    inconnues = sorted(c for c in citees if c not in boucle)
    assert not inconnues, f"citees dans /aide mais absentes du code : {inconnues}"
