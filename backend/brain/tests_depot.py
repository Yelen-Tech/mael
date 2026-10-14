"""Tests de l'INDEX d'un depot existant (depot.py) — 12/10/2026.

Point 4 de la feuille de route « agent autonome » : reprendre un depot
existant. L'index se fait sans modele : inventaire, symboles avec leurs
lignes, fichiers de test, commande de test par (sous-)projet, cache.
    ./venv/Scripts/python.exe -m pytest brain/tests_depot.py -q
"""
import shutil
import subprocess

import pytest

from brain.codage import depot


def _ecrire(racine, fichiers):
    for chemin, texte in fichiers.items():
        p = racine / chemin
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(texte, bytes):
            p.write_bytes(texte)
        else:
            p.write_text(texte, encoding="utf-8")


def _noms(f):
    return [(s.nom, s.sorte, s.debut, s.fin) for s in f.symboles]


# ------------------------------------------------------------------ symboles
def test_python_classes_methodes_decorateurs_avec_leurs_lignes():
    texte = ("import os\n"                        # 1
             "\n"                                 # 2
             "@outil\n"                           # 3
             "def lire(p):\n"                     # 4
             "    return open(p).read()\n"        # 5
             "\n"                                 # 6
             "class Panier:\n"                    # 7
             "    def __init__(self):\n"          # 8
             "        self.lignes = []\n"         # 9
             "\n"                                 # 10
             "    @property\n"                    # 11
             "    def total(self):\n"             # 12
             "        return sum(self.lignes)\n"  # 13
             "\n"                                 # 14
             "async def charger():\n"             # 15
             "    pass\n")                        # 16
    assert [(s.nom, s.sorte, s.debut, s.fin)
            for s in depot.symboles_python(texte)] == [
        ("lire", "fonction", 3, 5), ("Panier", "classe", 7, 13),
        ("Panier.__init__", "methode", 8, 9),
        ("Panier.total", "methode", 11, 13),
        ("charger", "fonction", 15, 16)]


def test_python_illisible_ne_casse_rien():
    assert depot.symboles_python("def (:\n") == []


def test_javascript_fonctions_classes_methodes_fleches():
    texte = ("export function total(l) {\n"        # 1
             "  return l.reduce((a, b) => a + b, 0);\n"
             "}\n"                                  # 3
             "const remise = (p, t) => {\n"         # 4
             "  if (t) { return p * t; }\n"
             "  return p;\n"
             "};\n"                                 # 7
             "class Panier {\n"                     # 8
             "  ajouter(x) {\n"                     # 9
             "    if (x) { this.l.push(x); }\n"
             "  }\n"                                # 11
             "  vider() { this.l = '}'; }\n"        # 12 : accolade en chaine
             "}\n")                                 # 13
    s = depot.symboles_motifs(texte, "javascript")
    assert [(x.nom, x.sorte, x.debut, x.fin) for x in s] == [
        ("total", "fonction", 1, 3), ("remise", "fonction", 4, 7),
        ("Panier", "classe", 8, 13), ("Panier.ajouter", "methode", 9, 11),
        ("Panier.vider", "methode", 12, 12)]


def test_les_mots_cles_ne_sont_pas_des_methodes():
    texte = "class A {\n  f() {\n    if (x) {\n    }\n    for (;;) {\n    }\n  }\n}\n"
    assert [x.nom for x in depot.symboles_motifs(texte, "javascript")] == [
        "A", "A.f"]


def test_java_classe_et_methodes():
    texte = ("package bf.mael;\n"
             "public class Facture {\n"                         # 2
             "    private int total;\n"
             "    @Override\n"
             "    public String toString() {\n"                 # 5
             "        return \"{\" + total;\n"
             "    }\n"                                          # 7
             "    public static List<Ligne> lignes(int n) throws IOException {\n"
             "        return null;\n"
             "    }\n"                                          # 10
             "}\n")
    assert _noms(depot.Fichier("F.java", "java", 0, 0, 0, False,
                               depot.symboles(texte, "java"))) == [
        ("Facture", "classe", 2, 11), ("Facture.toString", "methode", 5, 7),
        ("Facture.lignes", "methode", 8, 10)]


def test_go_fonctions_methodes_types():
    texte = ("package main\n"
             "type Panier struct {\n"           # 2
             "\tLignes []int\n"
             "}\n"                              # 4
             "func (p *Panier) Total() int {\n" # 5
             "\treturn 0\n"
             "}\n"                              # 7
             "func main() {\n"                  # 8
             "}\n")
    assert [(s.nom, s.sorte, s.debut, s.fin)
            for s in depot.symboles(texte, "go")] == [
        ("Panier", "type", 2, 4), ("Total", "fonction", 5, 7),
        ("main", "fonction", 8, 9)]


def test_csharp_et_php():
    cs = ("public class Facture\n{\n    public decimal Total(int n)\n    {\n"
          "        return n;\n    }\n}\n")
    assert [(s.nom, s.debut, s.fin) for s in depot.symboles(cs, "csharp")] \
        == [("Facture", 1, 7), ("Facture.Total", 3, 6)]
    php = ("<?php\nclass Panier {\n    public function total(): int {\n"
           "        return 0;\n    }\n}\nfunction aide() {\n}\n")
    assert [(s.nom, s.debut, s.fin) for s in depot.symboles(php, "php")] == [
        ("Panier", 2, 6), ("Panier.total", 3, 5), ("aide", 7, 8)]


# -------------------------------------------------------------- inventaire
def test_inventaire_ecarte_dependances_constructions_binaires(tmp_path):
    _ecrire(tmp_path, {
        "app/main.py": "def f():\n    pass\n",
        "node_modules/x/index.js": "function f() {}\n",
        "venv/Lib/site.py": "x = 1\n",
        "build/lib/app/main.py": "x = 1\n",
        "app/logo.png": b"\x89PNG\r\n\x1a\n\0\0\0",
        "app/donnees.json": b'{"a": 1}\0',            # binaire deguise
        "app/enorme.py": "x = 1\n" * 200_000,          # > TAILLE_MAX
    })
    i = depot.indexer(tmp_path, cache=False)
    assert list(i.fichiers) == ["app/main.py"]
    assert i.ecartes == 2


@pytest.mark.skipif(not shutil.which("git"), reason="git absent")
def test_inventaire_respecte_le_gitignore(tmp_path):
    _ecrire(tmp_path, {".gitignore": "secrets/\n*.log\n",
                       "a.py": "x = 1\n", "secrets/cle.py": "K = 1\n",
                       "trace.log": "x\n"})
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert depot.inventaire(tmp_path) == [".gitignore", "a.py"]


# ------------------------------------------------------------------- tests
@pytest.mark.parametrize("chemin,attendu", [
    ("tests/test_panier.py", True), ("app/test_panier.py", True),
    ("pkg/panier_test.go", True), ("src/panier.test.js", True),
    ("src/Panier.spec.tsx", True), ("src/test/java/bf/FactureTest.java", True),
    ("Facture.Tests/FactureTests.cs", True), ("conftest.py", True),
    ("app/panier.py", False), ("src/attestation.js", False),
    ("docs/latest.md", False)])
def test_reconnaitre_un_fichier_de_test(chemin, attendu):
    assert depot.est_test(chemin) is attendu


def test_motifs_python_files_de_la_configuration(tmp_path):
    """Mesure du 12/10 sur MAEL lui-meme : ses tests s'appellent
    tests_*.py, declares dans pyproject.toml — 0 test reconnu avant."""
    _ecrire(tmp_path, {
        "backend/pyproject.toml": "[tool.pytest.ini_options]\n"
                                  "python_files = [\"tests_*.py\"]\n",
        "backend/brain/tests_panier.py": "def test_a():\n    pass\n",
        "backend/brain/panier.py": "x = 1\n"})
    i = depot.indexer(tmp_path, cache=False)
    assert [(s.dossier, s.commande, s.motifs_py) for s in i.suites] == [
        ("backend", ["python", "-m", "pytest"], ["tests_*.py"])]
    assert i.fichiers["backend/brain/tests_panier.py"].test
    assert not i.fichiers["backend/brain/panier.py"].test


def test_motifs_dans_pytest_ini_et_setup_cfg():
    assert depot.motifs_pytest(lambda n: {"pytest.ini": "[pytest]\n"
                                          "python_files = check_*.py *_t.py\n"}
                               .get(n, "")) == ["check_*.py", "*_t.py"]
    assert depot.motifs_pytest(lambda n: {"setup.cfg": "[tool:pytest]\n"
                                          "python_files = essai_*.py\n"}
                               .get(n, "")) == ["essai_*.py"]
    assert depot.motifs_pytest(lambda n: "") == []


def test_une_suite_par_sous_projet(tmp_path):
    _ecrire(tmp_path, {
        "README.md": "# monorepo\n",
        "api/pyproject.toml": "[tool.pytest.ini_options]\n",
        "api/app.py": "x = 1\n",
        "web/package.json": '{"scripts": {"test": "jest"}}',
        "web/src/a.js": "function a() {}\n",
        "outils/package.json": '{"scripts": {"test": "echo \\"Error: no test '
                               'specified\\" && exit 1"}}',
        "svc/go.mod": "module svc\n\ngo 1.26.0\n",
        "svc/main.go": "package main\nfunc main() {\n}\n"})
    i = depot.indexer(tmp_path, cache=False)
    assert [(s.dossier, s.commande) for s in i.suites] == [
        ("api", ["python", "-m", "pytest"]), ("svc", ["go", "test", "./..."]),
        ("web", ["npm", "test"])]          # outils : « no test specified »


def test_projet_python_avec_tests_js_a_cote(tmp_path):
    """Django : package.json (« grunt test ») a la racine d'un projet
    Python ; un .py doit tomber sur la suite Python (Kaggle, 15/10)."""
    _ecrire(tmp_path, {
        "package.json": '{"scripts": {"test": "grunt test --verbose"}}',
        "setup.py": "", "django/core/validators.py": "x = 1\n",
        "tests/validators/tests.py": "def test_a():\n    pass\n",
        "js_tests/tests.js": "QUnit.test('a', function () {});\n"})
    i = depot.indexer(tmp_path, cache=False)
    assert [s.commande[0] for s in i.suites] == ["npm", "python"]
    assert depot.suite_du_fichier(
        i.suites, "django/core/validators.py").commande[0] == "python"
    assert depot.suite_du_fichier(
        i.suites, "js_tests/tests.js").commande[0] == "npm"


@pytest.mark.parametrize("fichiers,commande", [
    ({"pom.xml": "<project/>"}, ["mvn", "-q", "test"]),
    ({"build.gradle": "", "gradlew": ""}, ["./gradlew", "test"]),
    ({"App.csproj": "<Project/>"}, ["dotnet", "test"]),
    ({"Cargo.toml": "[package]\n"}, ["cargo", "test"]),
    ({"phpunit.xml.dist": "<phpunit/>"}, ["vendor/bin/phpunit"]),
    ({"setup.py": "", "tests/test_a.py": ""}, ["python", "-m", "pytest"]),
    ({"setup.py": "", "a.py": ""}, None)])     # pas de test : rien d'invente
def test_commande_de_test_ecrite_dans_le_depot(tmp_path, fichiers, commande):
    _ecrire(tmp_path, fichiers)
    i = depot.indexer(tmp_path, cache=False)
    assert (i.suites[0].commande if i.suites else None) == commande


# -------------------------------------------------------------------- cache
def test_le_cache_ne_relit_que_les_fichiers_changes(tmp_path, monkeypatch):
    _ecrire(tmp_path, {"a.py": "def a():\n    pass\n",
                       "b.py": "def b():\n    pass\n"})
    depot.indexer(tmp_path)
    assert (tmp_path / ".mael" / "index.json").exists()
    lus = []
    vrai = depot.symboles
    monkeypatch.setattr(depot, "symboles",
                        lambda t, l: lus.append(t) or vrai(t, l))
    (tmp_path / "b.py").write_text("def b():\n    pass\n\ndef c():\n"
                                   "    pass\n", encoding="utf-8")
    i = depot.indexer(tmp_path)
    assert len(lus) == 1                                 # seul b.py relu
    assert [s.nom for s in i.fichiers["b.py"].symboles] == ["b", "c"]
    assert [s.nom for s in i.fichiers["a.py"].symboles] == ["a"]
    assert ".mael/index.json" not in i.fichiers          # jamais indexe


def test_cache_d_une_autre_version_ignore(tmp_path):
    _ecrire(tmp_path, {"a.py": "def a():\n    pass\n",
                       ".mael/index.json": '{"version": -1, "fichiers": '
                                           '{"a.py": {}}}'})
    assert [s.nom for s in depot.indexer(tmp_path).fichiers["a.py"].symboles
            ] == ["a"]
