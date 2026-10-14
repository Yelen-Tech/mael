"""Tests de la COUVERTURE de l'exemple d'un ticket (couverture.py) et de son
usage par la localisation — phase 1 du plan agentique, 15/10/2026.
    ./venv/Scripts/python.exe -m pytest brain/tests_couverture_exemple.py -q
"""
import subprocess
import sys

from brain.codage import couverture, depot, localisation


def _depot(tmp_path):
    fichiers = {
        "calc/__init__.py": "",
        "calc/outils.py": "def arrondi(x):\n    return round(x, 2)\n\n\n"
                          "def double(x):\n    return 2 * x\n",
        "calc/fractions.py": "from .outils import arrondi\n\n\n"
                             "def depuis_fraction(n, d):\n"
                             "    return arrondi(n // d)\n",
        "calc/api.py": "from .fractions import depuis_fraction\n"
                       "from .outils import double, arrondi\n\n\n"
                       "def divise(n, d, exact=False):\n"
                       "    if exact:\n"
                       "        return depuis_fraction(n, d)\n"
                       "    return arrondi(n / d)\n",
    }
    for c, t in fichiers.items():
        p = tmp_path / c
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    return depot.indexer(tmp_path, cache=False)


def _executer(tmp_path, code):
    r = subprocess.run([sys.executable, "-"], input=couverture.script(code),
                       cwd=tmp_path, capture_output=True, text=True,
                       timeout=60)
    return r, couverture.lire(r.stderr)


def test_les_imports_ne_sont_pas_traces_les_instructions_numerotees(tmp_path):
    _depot(tmp_path)
    r, c = _executer(tmp_path, "from calc.api import divise\n"
                               "print(divise(7, 2))\n"
                               "print(divise(7, 2, exact=True))\n")
    assert r.stdout.split() == ["3.5", "3"]          # l'exemple tourne tel quel
    assert ("divise", 5, 1) in c["calc/api.py"]
    assert ("depuis_fraction", 4, 2) in c["calc/fractions.py"]
    assert ("depuis_fraction", 4, 1) not in c["calc/fractions.py"]
    assert all(i in (1, 2) for f in c.values() for _, _, i in f)


def test_seule_l_instruction_fautive_compte(tmp_path):
    """Le cas qui marche (instruction 1) et le cas faux (instruction 2)
    passent tous deux par divise et arrondi : seul depuis_fraction est
    propre au cas faux."""
    _depot(tmp_path)
    _, c = _executer(tmp_path, "from calc.api import divise\n"
                               "divise(7, 2)\ndivise(7, 2, exact=True)\n")
    assert localisation.fonctions_fautives(c) == {
        "calc/fractions.py": [("depuis_fraction", 4)]}


def test_la_localisation_suit_ce_que_l_exemple_execute(tmp_path):
    """Un ticket « mauvais resultat » sans trace ni nom de fichier."""
    idx = _depot(tmp_path)
    _, c = _executer(tmp_path, "from calc.api import divise\n"
                               "divise(7, 2)\ndivise(7, 2, exact=True)\n")
    ticket = "Exact division gives a wrong result, 7/2 should be 7/2."
    lieux = localisation.localiser(idx, ticket, couverture=c)
    assert lieux[0].fichier == "calc/fractions.py"
    assert any("execute par l'exemple" in r for r in lieux[0].raisons)
    assert lieux[0].symboles[0].nom == "depuis_fraction"
    sans = localisation.localiser(idx, ticket)
    assert not sans or sans[0].fichier != "calc/fractions.py"


def test_une_sortie_sans_marque_ne_donne_rien():
    assert couverture.lire("Traceback ...\nValueError: x") == {}
    assert localisation.fonctions_fautives({}) == {}


def test_le_prelude_est_en_ascii():
    """Il part par l'entree standard d'un AUTRE Python, d'un autre
    encodage : un « » dans un commentaire cassait tout le script."""
    assert couverture._PRELUDE.isascii()
