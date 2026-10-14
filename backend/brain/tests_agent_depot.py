"""Tests de l'AGENT sur un depot existant (agent_depot.py) — 12/10/2026,
point 4.5. Le modele est simule ; les tests du depot jouet sont EXECUTES
pour de vrai (pytest local a la place du conteneur), la reproduction doit
vraiment echouer avant et passer apres.
    ./venv/Scripts/python.exe -m pytest brain/tests_agent_depot.py -q
"""
import subprocess
import sys

import pytest

from brain.codage import agent_depot
from brain.codage import essais_depot as ed
from brain.tests_codage import FauxMoteur

PANIER = ("class Panier:\n"
          "    def __init__(self, lignes=None):\n"
          "        self.lignes = list(lignes or [])\n"
          "\n"
          "    def total(self):\n"
          "        s = 0\n"
          "        for l in self.lignes:\n"
          "            s = l\n"
          "        return s\n"
          "\n"
          "    def vide(self):\n"
          "        return not self.lignes\n")
TICKET = "`Panier.total` returns only the last line instead of the sum"
REPRO = ("```python fichier=tests/test_mael_ticket.py\n"
         "from boutique.panier import Panier\n\n\n"
         "def test_total_fait_la_somme():\n"
         "    assert Panier([1, 2, 3]).total() == 6\n```")
FAUSSE_REPRO = ("```python fichier=tests/test_mael_ticket.py\n"
                "from boutique.panier import Panier\n\n\n"
                "def test_vide():\n    assert Panier().vide()\n```")


def bloc(chercher, remplacer):
    return (f"FICHIER: boutique/panier.py\n<<<<<<< CHERCHER\n{chercher}\n"
            f"=======\n{remplacer}\n>>>>>>> REMPLACER\n")


JUSTE = bloc("        for l in self.lignes:\n            s = l",
             "        for l in self.lignes:\n            s += l")


@pytest.fixture
def depot_jouet(tmp_path, monkeypatch):
    fichiers = {
        "boutique/__init__.py": "",
        "boutique/panier.py": PANIER,
        "tests/__init__.py": "",
        "tests/test_panier.py": "from boutique.panier import Panier\n\n\n"
                                "def test_vide():\n    assert Panier().vide()\n"
                                "\n\ndef test_pas_vide():\n"
                                "    assert not Panier([1]).vide()\n",
        "pytest.ini": "[pytest]\n"}
    for c, t in fichiers.items():
        p = tmp_path / c
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")

    # le « conteneur » : le vrai pytest, en local, sur l'etat actuel
    def preparer(racine, suite, reseau=True):
        return ed.Environnement(image="local", suite=suite, pret=True)

    def executer_tests(env, racine, cibles=None, delai=120):
        r = subprocess.run([sys.executable, "-m", "pytest", "-v", "-rA",
                            "--tb=short", "-p", "no:cacheprovider",
                            *(cibles or [])], cwd=racine, capture_output=True,
                           text=True, timeout=delai)
        sortie = r.stdout + r.stderr
        return ed.Execution(lance=True, statuts=ed.lire_statuts(sortie),
                            code=r.returncode, sortie=sortie)
    def executer_script(env, racine, code, delai=60):
        r = subprocess.run([sys.executable, "-"], input=code, cwd=racine,
                           capture_output=True, text=True, timeout=delai)
        return ed.Execution(lance=True, code=r.returncode,
                            sortie=r.stdout + r.stderr)
    monkeypatch.setattr(ed, "preparer", preparer)
    monkeypatch.setattr(ed, "executer_tests", executer_tests)
    monkeypatch.setattr(ed, "executer_script", executer_script)
    return tmp_path


def test_resolu_et_verifie(depot_jouet):
    moteur = FauxMoteur([REPRO, JUSTE])
    decharges = []
    b = agent_depot.AgentDepot(moteur, depot_jouet,
                               decharger=lambda: decharges.append(1)
                               ).traiter(TICKET)
    assert b.verdict == "resolu-verifie", b.notes
    assert b.reproduction == "tests/test_mael_ticket.py"
    assert b.reproduction_valide
    assert b.comparaison.repares == [
        "tests/test_mael_ticket.py::test_total_fait_la_somme"]
    assert b.comparaison.regressions == []
    assert "s += l" in b.diff and "test_mael_ticket" not in b.diff
    assert "Panier([1, 2, 3])" in b.test_ajoute
    assert decharges                       # le modele libere la memoire
    # le modele a vu un test existant (style, imports) et le chemin impose
    vu = moteur.recus[0][0]["content"]
    assert "tests/test_panier.py" in vu and "tests/test_mael_ticket.py" in vu
    texte = agent_depot.rendre(b)
    assert texte.startswith("# RESOLU ET VERIFIE") and "```diff" in texte
    journal = (depot_jouet / ".mael" / "journal-ticket.md").read_text(
        encoding="utf-8")
    assert "## 1. reproduction" in journal and "## 2. correction" in journal
    assert "s += l" in journal                  # la vraie reponse, gardee


def test_une_reproduction_qui_reussit_est_refaite_puis_abandonnee(
        depot_jouet):
    moteur = FauxMoteur([FAUSSE_REPRO, FAUSSE_REPRO, JUSTE])
    b = agent_depot.AgentDepot(moteur, depot_jouet).traiter(TICKET)
    assert "REUSSIT sur le code actuel" in moteur.recus[1][-1]["content"]
    assert not b.reproduction and not b.reproduction_valide
    assert not (depot_jouet / "tests/test_mael_ticket.py").exists()
    assert any("aucun test ne reproduit" in n for n in b.notes)
    assert b.verdict == "modifie-non-verifie"     # jamais « verifie » sans preuve


def test_une_regression_repart_au_modele(depot_jouet):
    casse = bloc("    def vide(self):\n        return not self.lignes",
                 "    def vide(self):\n        return False") + JUSTE
    moteur = FauxMoteur([REPRO, casse, bloc(
        "    def vide(self):\n        return False",
        "    def vide(self):\n        return not self.lignes")])
    b = agent_depot.AgentDepot(moteur, depot_jouet).traiter(TICKET)
    retour = moteur.recus[2][0]["content"]
    assert "REGRESSIONS" in retour and "test_vide" in retour
    assert b.tours == 2 and b.verdict == "resolu-verifie"
    assert "return not self.lignes" in (depot_jouet / "boutique/panier.py"
                                        ).read_text()


def test_correction_qui_ne_repare_pas_echec_dit(depot_jouet):
    rien = bloc("    def vide(self):\n        return not self.lignes",
                "    def vide(self):\n        return len(self.lignes) == 0")
    # 2e tour : le modele n'apporte rien d'applicable (3 essais refuses)
    moteur = FauxMoteur([REPRO, rien, rien, "je ne sais pas", "toujours pas"])
    b = agent_depot.AgentDepot(moteur, depot_jouet).traiter(TICKET)
    assert b.verdict == "echec"
    assert "test_total_fait_la_somme" in moteur.recus[2][0]["content"]
    assert agent_depot.rendre(b).startswith("# NON RESOLU")


def test_sans_execution_corrige_non_verifie(depot_jouet):
    moteur = FauxMoteur([REPRO, JUSTE])
    b = agent_depot.AgentDepot(moteur, depot_jouet,
                               executer=False).traiter(TICKET)
    assert b.verdict == "modifie-non-verifie"
    assert any("NON execute" in n for n in b.notes)


def test_un_test_existant_n_est_jamais_ecrase(depot_jouet):
    (depot_jouet / "tests/test_mael_ticket.py").write_text("# a moi\n")
    b = agent_depot.AgentDepot(FauxMoteur([JUSTE]), depot_jouet
                               ).traiter(TICKET)
    assert (depot_jouet / "tests/test_mael_ticket.py").read_text() == \
        "# a moi\n"
    assert any("existe deja" in n for n in b.notes)


def test_en_tete_de_bloc_recopie_dans_le_test_retire():
    """Kaggle 15/10 (sympy-21627)."""
    assert agent_depot._sans_entete(
        "fichier=sympy/core/tests/test_mael_ticket.py\n```python\n"
        "from sympy import S\n\ndef test_a():\n    assert S(1)\n```\n") == (
        "from sympy import S\n\ndef test_a():\n    assert S(1)")
    assert agent_depot._sans_entete("import os\n") == "import os\n"


def test_exemples_du_ticket():
    ticket = ("The following code causes a `RecursionError`:\n```\n"
              "expr =sympify(\"cosh(acos(-i + acosh(-g + i)))\")\n"
              "expr.is_zero\n```\nSession:\n```python\n>>> x = f(1)\n"
              ">>> for i in x:\n...     print(i)\n1\n```\n"
              "```\nTraceback (most recent call last):\n  File \"a.py\", "
              "line 1\n```\n```bash\npip install x\n```\n```\nnot python(\n```")
    assert agent_depot.exemples(ticket) == [
        'expr =sympify("cosh(acos(-i + acosh(-g + i)))")\nexpr.is_zero',
        "x = f(1)\nfor i in x:\n    print(i)"]
    assert agent_depot.trace_de("bla\nTraceback (most recent call last):\n"
                                "  File \"x.py\", line 2\nValueError: v\n"
                                ).endswith("ValueError: v")
    assert agent_depot.trace_de("tout va bien") == ""


def test_l_exemple_du_ticket_est_execute_et_sa_trace_localise(depot_jouet):
    """Le ticket ne cite ni fichier ni trace ; la session (sans son import)
    plante dans boutique/calcul.py : c'est la qu'il faut regarder."""
    (depot_jouet / "boutique/__init__.py").write_text(
        "from .remise import appliquer\n")
    (depot_jouet / "boutique/remise.py").write_text(
        "from .calcul import moyenne\n\n\ndef appliquer(prix, taux):\n"
        "    return moyenne(prix) * taux\n")
    (depot_jouet / "boutique/calcul.py").write_text(
        "def moyenne(xs):\n    return sum(xs) / len(xs)\n")
    ticket = ("Discount on an empty basket crashes the shop.\n"
              "```python\n>>> appliquer([], 10)\n```")
    moteur = FauxMoteur(["rien"] * 8)
    b = agent_depot.AgentDepot(moteur, depot_jouet).traiter(ticket)
    # les deux cadres du depot passent devant tout le reste
    assert {l.fichier for l in b.lieux[:2]} == {"boutique/calcul.py",
                                                "boutique/remise.py"}
    assert any("ZeroDivisionError" in n for n in b.notes), b.notes
    assert "TRACE OBTENUE PAR MAEL" in moteur.recus[0][0]["content"]


def test_dossier_des_tests():
    from brain.codage import depot
    idx = depot.Index("/x", {
        "pkg/a.py": depot.Fichier("pkg/a.py", "python", 0, 0, 1, False),
        "testing/test_a.py": depot.Fichier("testing/test_a.py", "python",
                                           0, 0, 1, True),
        "testing/test_b.py": depot.Fichier("testing/test_b.py", "python",
                                           0, 0, 1, True)}, [])
    assert agent_depot._dossier_des_tests(idx, None, []) == "testing"
    assert agent_depot._dossier_des_tests(idx, None, ["t/x/test_c.py"]) \
        == "t/x"
