"""Tests de l'EXECUTION des tests d'un depot existant (essais_depot.py) —
12/10/2026, point 4.4. Tout ce qui se lit et se compare est teste sans
Docker ; l'essai reel est fait sur SWE-bench (voir le journal).
    ./venv/Scripts/python.exe -m pytest brain/tests_essais_depot.py -q
"""
import io
import json
import tarfile
from pathlib import Path

import pytest

from brain.codage import depot
from brain.codage import essais_depot as ed
from brain.codage.depot import Suite

SORTIE = """\
..F.sE                                                     [100%]
=================================== FAILURES ===================================
___________________________ test_total_somme ___________________________
tests/test_panier.py:12: in test_total_somme
    assert Panier([1, 2]).total() == 3
E   assert 2 == 3
=========================== short test summary info ============================
PASSED tests/test_panier.py::test_vide
PASSED tests/test_panier.py::test_ajout[1]
FAILED tests/test_panier.py::test_total_somme - assert 2 == 3
SKIPPED [1] tests/test_panier.py:30: pas de base
ERROR tests/test_remise.py - ImportError: cannot import name 'remise'
XFAIL tests/test_panier.py::test_futur - reason: a venir
1 failed, 2 passed, 1 skipped, 1 xfailed, 1 error in 0.12s
"""


def test_lire_les_statuts_de_pytest():
    assert ed.lire_statuts(SORTIE) == {
        "tests/test_panier.py::test_vide": "PASSED",
        "tests/test_panier.py::test_ajout[1]": "PASSED",
        "tests/test_panier.py::test_total_somme": "FAILED",
        "tests/test_remise.py": "ERROR",
        "tests/test_panier.py::test_futur": "XFAIL"}


def test_lire_la_sortie_detaillee_d_un_vieux_pytest():
    """requests 2016 (essai du 12/10) : le resume ne liste pas les reussis ;
    la sortie -v, si."""
    vieux = ("tests/test_requests.py::TestRequests::test_entry_points PASSED\n"
             "tests/test_requests.py::TestRequests::test_invalid_url"
             "[MissingSchema-hiwpefhipowhefopw] PASSED\n"
             "tests/test_requests.py::TestTimeout::test_connect FAILED\n"
             "tests/test_utils.py::test_x PASSED [ 50%]\n"
             "tests/test_utils.py::test_y xfail\n"
             "4 failed, 179 passed, 1 xfailed in 22.98 seconds\n")
    assert ed.lire_statuts(vieux) == {
        "tests/test_requests.py::TestRequests::test_entry_points": "PASSED",
        "tests/test_requests.py::TestRequests::test_invalid_url"
        "[MissingSchema-hiwpefhipowhefopw]": "PASSED",
        "tests/test_requests.py::TestTimeout::test_connect": "FAILED",
        "tests/test_utils.py::test_x": "PASSED",
        "tests/test_utils.py::test_y": "XFAIL"}


def _ex(statuts):
    return ed.Execution(lance=True, statuts=statuts)


def test_comparer_repares_regressions_toujours():
    avant = _ex({"a::t1": "FAILED", "a::t2": "PASSED", "a::t3": "PASSED",
                 "a::t4": "FAILED", "a::t5": "SKIPPED"})
    apres = _ex({"a::t1": "PASSED", "a::t2": "FAILED", "a::t3": "PASSED",
                 "a::t4": "FAILED", "a::t5": "SKIPPED", "a::nouveau": "FAILED"})
    c = ed.comparer(avant, apres)
    assert c.repares == ["a::t1"]
    assert c.regressions == ["a::t2"]
    assert c.toujours_en_echec == ["a::t4"]
    assert c.nouveaux_en_echec == ["a::nouveau"]
    assert not c.sans_regression


def test_un_module_qui_ne_s_importe_plus_est_une_regression():
    avant = _ex({"tests/test_a.py::t1": "PASSED", "tests/test_a.py::t2":
                 "PASSED"})
    apres = _ex({"tests/test_a.py": "ERROR"})
    assert ed.comparer(avant, apres).regressions == [
        "tests/test_a.py::t1", "tests/test_a.py::t2"]


@pytest.mark.parametrize("fichiers,attendu", [
    ({"setup.py": "classifiers=['Programming Language :: Python :: 2.7',"
                  "'Programming Language :: Python :: 3.6',"
                  "'Programming Language :: Python :: 3.7']"}, "3.7"),
    ({"pyproject.toml": "[project]\nrequires-python = '>=3.8,<3.11'\n"},
     "3.10"),
    ({"setup.cfg": "[options]\npython_requires = >=3.9\n"}, "3.12"),
    ({}, "3.12")])
def test_version_de_python_du_depot(fichiers, attendu):
    assert ed.version_python(lambda n: fichiers.get(n, "")) == attendu


def test_dockerfile_python_installe_le_depot_et_ses_exigences(tmp_path):
    (tmp_path / "setup.py").write_text(
        "classifiers=['Programming Language :: Python :: 3.9']")
    (tmp_path / "requirements-dev.txt").write_text("pytest-httpbin\n")
    s = Suite("", ["python", "-m", "pytest"])
    df = ed.dockerfile(tmp_path, s)
    assert df.startswith("FROM python:3.9-slim")
    assert "-r requirements-dev.txt" in df and "-e '.[test]'" in df
    assert ed.nom_image(tmp_path, s).startswith("mael-depot-")
    # une dependance qui change -> une autre image
    avant = ed.empreinte(tmp_path, s)
    (tmp_path / "requirements-dev.txt").write_text("pytest-httpbin\nmock\n")
    assert ed.empreinte(tmp_path, s) != avant


@pytest.mark.parametrize("commande,sorte_", [
    (["npm", "test"], "node"), (["go", "test", "./..."], "go"),
    (["mvn", "-q", "test"], "maven"), (["dotnet", "test"], "dotnet"),
    (["python", "-m", "pytest"], "python"), (["cargo", "test"], "")])
def test_une_recette_par_sorte_et_les_non_eprouvees_le_disent(
        tmp_path, commande, sorte_):
    s = Suite("", commande)
    assert ed.sorte(s) == sorte_
    assert bool(ed.dockerfile(tmp_path, s)) is bool(sorte_)
    # toutes les recettes ecrites ont ete eprouvees en vrai le 13/10 : aucune
    # ne doit plus se dire « pas encore eprouvee » ; une sorte non eprouvee
    # le dirait (on simule en la retirant de l'ensemble)
    assert ed.limites(s) == []
    if sorte_:
        ed._VERIFIEES.discard(sorte_)
        try:
            assert "pas encore eprouvee" in ed.limites(s)[0]
        finally:
            ed._VERIFIEES.add(sorte_)


def test_commande_hors_ligne_limitee_aux_cibles():
    s = Suite("", ["python", "-m", "pytest"])
    c = ed.commande_hors_ligne(s, ["tests/test_a.py"])
    assert c[:3] == ["python", "-m", "pytest"] and "-rA" in c
    assert c[-1] == "tests/test_a.py"


def test_l_archive_ne_contient_ni_git_ni_mael_ni_liens(tmp_path):
    for c in ("a.py", "pkg/b.py", ".git/config", ".mael/index.json",
              "node_modules/x/i.js", "pkg/__pycache__/b.pyc"):
        p = tmp_path / c
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    with tarfile.open(fileobj=io.BytesIO(ed.archive(tmp_path))) as t:
        noms = {m.name.replace("\\", "/") for m in t.getmembers()
                if m.isfile()}
    assert noms == {"a.py", "pkg/b.py"}


def test_tests_lies_aux_fichiers_modifies(tmp_path):
    fichiers = {
        "requests/models.py": "class Response:\n    pass\n",
        "requests/utils.py": "def f():\n    pass\n",
        "tests/test_models.py": "def test_a():\n    pass\n",
        "tests/test_requests.py": "from requests.models import Response\n",
        "tests/test_autre.py": "from requests import models, utils\n",
        "tests/test_rien.py": "import os\n",
        "pytest.ini": "[pytest]\n"}
    for c, t in fichiers.items():
        p = tmp_path / c
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t)
    idx = depot.indexer(tmp_path, cache=False)
    assert sorted(ed.tests_lies(idx, ["requests/models.py"])) == [
        "tests/test_autre.py", "tests/test_models.py",
        "tests/test_requests.py"]


def test_sans_environnement_rien_n_est_lance():
    ex = ed.executer_tests(ed.Environnement(raison="Docker ne repond pas"),
                           ".")
    assert not ex.lance and ex.raison == "Docker ne repond pas"


# ---------------- rapports PAR TEST des autres langages (13/10/2026)
def test_go_json_par_test():
    sortie = "\n".join([
        '{"Action":"run","Package":"demo","Test":"TestAddOk"}',
        '{"Action":"pass","Package":"demo","Test":"TestAddOk","Elapsed":0}',
        '{"Action":"fail","Package":"demo","Test":"TestAddFaux"}',
        '{"Action":"skip","Package":"demo","Test":"TestPlusTard"}',
        '{"Action":"fail","Package":"demo"}',
        '{"Action":"fail","Package":"demo/casse"}', "bruit"])
    assert ed.statuts_go(sortie) == {
        "demo::TestAddOk": "PASSED", "demo::TestAddFaux": "FAILED",
        "demo::TestPlusTard": "SKIPPED",       # demo a des tests : pas ERROR
        "demo/casse": "ERROR"}                  # aucun test : ne compile pas


def test_junit_surefire_et_node_test():
    xml = (f"[ERROR] Tests run: 3\n{ed.MARQUE}\n"
           '<?xml version="1.0"?><testsuite name="demo.CalcTest">'
           '<testcase classname="demo.CalcTest" name="addOk"/>'
           '<testcase classname="demo.CalcTest" name="addFaux">'
           '<failure message="5 != 4"/></testcase>'
           '<testcase classname="demo.CalcTest" name="plusTard"><skipped/>'
           '</testcase></testsuite>'
           '<testsuite name="autre"><testcase classname="X" name="err">'
           '<error/></testcase></testsuite>')
    assert ed.statuts_langage("maven", xml) == {
        "demo.CalcTest::addOk": "PASSED", "demo.CalcTest::addFaux": "FAILED",
        "demo.CalcTest::plusTard": "SKIPPED", "X::err": "ERROR"}
    assert ed.statuts_langage("node", xml)["demo.CalcTest::addFaux"] \
        == "FAILED"


def test_trx_dotnet():
    trx = (f"{ed.MARQUE}<TestRun><Results>"
           '<UnitTestResult testId="1" testName="CalcTests.AddOk" '
           'outcome="Passed" duration="0"/>'
           '<UnitTestResult testName="CalcTests.AddFaux" outcome="Failed">'
           '<Output/></UnitTestResult>'
           '<UnitTestResult testName="CalcTests.Ignore" outcome="NotExecuted"/>'
           "</Results></TestRun>")
    assert ed.statuts_langage("dotnet", trx) == {
        "CalcTests.AddOk": "PASSED", "CalcTests.AddFaux": "FAILED",
        "CalcTests.Ignore": "SKIPPED"}


def test_jest_et_mocha_json():
    jest = (ed.MARQUE + '{"testResults": [{"name": "/travail/calc.test.js",'
            ' "assertionResults": [{"fullName": "add ok", "status": "passed"},'
            ' {"fullName": "add faux", "status": "failed"}]}]}')
    assert ed.statuts_langage("node", jest) == {
        "calc.test.js::add ok": "PASSED", "calc.test.js::add faux": "FAILED"}
    mocha = (ed.MARQUE + '{"passes": [{"fullTitle": "a ok", "file": "t/a.js"}],'
             ' "failures": [{"fullTitle": "a faux", "file": "t/a.js"}],'
             ' "pending": []}')
    assert ed.statuts_langage("node", mocha) == {
        "a.js::a ok": "PASSED", "a.js::a faux": "FAILED"}


def test_lanceur_node(tmp_path):
    def paquet(d):
        (tmp_path / "package.json").write_text(json.dumps(d))
        return ed.lanceur_node(tmp_path)
    assert paquet({"scripts": {"test": "jest --coverage"}}) == "jest"
    assert paquet({"scripts": {"test": "vitest"}}) == "vitest"
    assert paquet({"scripts": {"test": "node --test"}}) == "node-test"
    assert paquet({"scripts": {"test": "npm run x"},
                   "devDependencies": {"mocha": "10"}}) == "mocha"
    assert paquet({"scripts": {"test": "echo rien"}}) == ""


def test_commande_garde_le_code_de_sortie():
    from brain.codage.depot import Suite
    c = ed.commande_hors_ligne(Suite("", ["mvn", "test"]), [])
    assert c[:2] == ["sh", "-c"] and "c=$?" in c[2] and c[2].endswith(
        "exit $c")
    assert ed.commande_hors_ligne(Suite("", ["go", "test", "./..."]), [])[
        :3] == ["go", "test", "-json"]


def test_suite_dotnet_depuis_le_dossier_commun():
    """Calc/ (code) + Calc.Tests/ (tests) : UNE suite, a leur racine commune
    — la suite « Calc/ » ne lancait aucun test (banc reel du 13/10)."""
    chemins = ["src/Calc/Calc.csproj", "src/Calc/Calc.cs",
               "src/Calc.Tests/Calc.Tests.csproj", "src/Calc.Tests/T.cs"]
    s = depot.suites_de_test(Path("."), chemins)
    assert [(x.dossier, x.commande) for x in s] == [("src", ["dotnet", "test"])]
    avec_sln = chemins + ["App.sln"]
    assert [x.dossier for x in depot.suites_de_test(Path("."), avec_sln)] == [""]


def test_rapport_vide_n_est_pas_tout_passe(monkeypatch):
    class R:
        def __init__(self, code=0, out=b""):
            self.returncode, self.stdout, self.stderr = code, out, b""
    sortie = ("Build succeeded.\n" + ed.MARQUE + "\n").encode()
    appels = iter([R(), R(), R(0, sortie), R()])
    monkeypatch.setattr(ed, "_docker", lambda *a, **k: next(appels))
    monkeypatch.setattr(ed, "archive", lambda r: b"")
    env = ed.Environnement(image="x", suite=Suite("", ["dotnet", "test"]),
                           pret=True)
    ex = ed.executer_tests(env, Path("."))
    assert ex.statuts == {} and "aucun test" in ex.raison


# ---------------------------------------------- mode hote (15/10, Kaggle)
def test_mode_hote_se_choisit_par_la_variable(monkeypatch):
    monkeypatch.delenv("MAEL_ESSAIS", raising=False)
    assert not ed.mode_hote()
    monkeypatch.setenv("MAEL_ESSAIS", "hote")
    assert ed.mode_hote()


def test_mode_hote_meme_recette_que_l_image(tmp_path):
    (tmp_path / "setup.py").write_text("")
    (tmp_path / "requirements-dev.txt").write_text("x\n")
    etapes = ed.installations_python(tmp_path)
    assert etapes[0] == ([["pytest"]], True)
    assert ([["-r", "requirements-dev.txt"]], False) in etapes
    assert etapes[-1] == ([["-e", ".[test]"], ["-e", ".[testing]"],
                           ["-e", "."]], True)


def test_mode_hote_refuse_un_autre_langage(tmp_path, monkeypatch):
    monkeypatch.setenv("MAEL_ESSAIS", "hote")
    monkeypatch.setenv("MAEL_ENVS", str(tmp_path / "envs"))
    env = ed.preparer(tmp_path, Suite(dossier="", commande=["go", "test"]))
    assert not env.pret and "seul Python" in env.raison


def test_mode_hote_python_trop_vieux_prend_le_plus_proche(tmp_path,
                                                         monkeypatch):
    """Kaggle 15/10 (sympy-12236) : uv ne fournit pas Python 3.5."""
    import subprocess
    (tmp_path / "depot").mkdir()
    (tmp_path / "depot/setup.py").write_text(
        "classifiers=['Programming Language :: Python :: 3.5']\n")
    demandes = []

    def run(cmd, **kw):
        if "venv" in cmd:
            v = cmd[cmd.index("--python") + 1]
            demandes.append(v)
            return subprocess.CompletedProcess(cmd, 0 if v == "3.7" else 2,
                                               b"", b"introuvable")
        return subprocess.CompletedProcess(cmd, 1, b"", b"stop")
    monkeypatch.setattr(ed.subprocess, "run", run)
    monkeypatch.setattr(ed, "_uv", lambda: ["uv"])
    monkeypatch.setenv("MAEL_ENVS", str(tmp_path / "envs"))
    env = ed.Environnement(suite=Suite(dossier="", commande=["python", "-m",
                                                             "pytest"]))
    ed._preparer_hote(tmp_path / "depot", env.suite, env, True)
    assert demandes == ["3.5", "3.6", "3.7"]
    assert "installation echouee" in env.raison      # le venv, lui, est fait


def test_mode_hote_execute_avant_apres_sur_la_copie(tmp_path, monkeypatch):
    """L'execution reelle : pytest tourne dans le dossier de travail de
    l'environnement, sur l'etat ACTUEL du depot (le python du banc fait
    office d'environnement : rien a telecharger)."""
    import sys
    depot_ = tmp_path / "depot"
    depot_.mkdir()
    (depot_ / "mini.py").write_text("def ajoute(a, b):\n    return a - b\n")
    (depot_ / "test_mini.py").write_text(
        "from mini import ajoute\n\ndef test_ajoute():\n"
        "    assert ajoute(2, 2) == 4\n\ndef test_zero():\n"
        "    assert ajoute(0, 0) == 0\n")
    monkeypatch.setattr(ed, "_python_de", lambda d: Path(sys.executable))
    monkeypatch.setattr(ed, "_SANS_RESEAU", [])
    env = ed.Environnement(suite=Suite(dossier="", commande=["python", "-m",
                                                             "pytest"]),
                           pret=True, hote=str(tmp_path / "env"))
    avant = ed.executer_tests(env, depot_)
    assert avant.statuts == {"test_mini.py::test_ajoute": "FAILED",
                             "test_mini.py::test_zero": "PASSED"}
    (depot_ / "mini.py").write_text("def ajoute(a, b):\n    return a + b\n")
    apres = ed.executer_tests(env, depot_)
    c = ed.comparer(avant, apres)
    assert c.repares == ["test_mini.py::test_ajoute"] and not c.regressions


def test_la_copie_garde_bin_mais_pas_les_binaires_ni_les_venvs(tmp_path):
    """Banc du 15/10 : sympy declare bin/isympy dans setup.py ; la copie
    l'ecartait, « pip install -e . » echouait, aucun test sympy ne
    tournait."""
    import io
    import tarfile
    for c in ("bin/isympy", "setup.py", "App/obj/x.json", "App/bin/App.dll",
              "env/pyvenv.cfg", "env/lib/x.py", "coverage/report.py"):
        (tmp_path / c).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / c).write_text("x")
    with tarfile.open(fileobj=io.BytesIO(ed.archive(tmp_path))) as t:
        noms = set(t.getnames())
    assert {"bin/isympy", "setup.py", "coverage/report.py"} <= noms
    assert not any(n.startswith(("App/bin", "env")) for n in noms)


def test_django_libelles_et_statuts():
    """Le lanceur de Django (SWE-bench : 114 tickets sur 300) : libelles
    a partir des chemins, et sortie unittest lue avec les MEMES
    identifiants que pytest. Sortie reelle du 15/10 (validators)."""
    assert ed.libelle_django("tests/validators/tests.py") == "validators.tests"
    assert ed.libelle_django(
        "tests/forms_tests/field_tests/test_urlfield.py::T::test_a") == (
        "forms_tests.field_tests.test_urlfield.T.test_a")
    sortie = (
        "test_message_dict (validators.tests.TestValidators) ... ok\n"
        "test_url (forms_tests.tests.UrlTests.test_url)\n"
        "Docstring du test ... FAIL\n"
        "test_validators (validators.tests.TestValidators) ... skipped "
        "'Pillow is required'\n"
        "test_mael_ticket (unittest.loader._FailedTest) ... ERROR\n"
        "======\nERROR: test_validators (validators.tests.TestValidators) "
        "[URLValidator] (value='http://[::1:2::3]:8080/')\n")
    assert ed.statuts_django(sortie) == {
        "tests/validators/tests.py::TestValidators::test_message_dict":
            "PASSED",
        "tests/forms_tests/tests.py::UrlTests::test_url": "FAILED",
        "tests/validators/tests.py::TestValidators::test_validators": "ERROR",
        "tests/test_mael_ticket.py": "ERROR"}
    s = Suite(dossier="", commande=["python", "tests/runtests.py"])
    assert ed.commande_hors_ligne(s, ["tests/validators/tests.py"])[-1] == (
        "validators.tests")
