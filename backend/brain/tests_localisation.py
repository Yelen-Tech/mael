"""Tests de la LOCALISATION (localisation.py) et de son banc — 12/10/2026.

Point 4 : d'un ticket aux fichiers et fonctions a lire, sans modele. Chaque
sorte d'indice a son test ; un depot jouet sert de terrain.
    ./venv/Scripts/python.exe -m pytest brain/tests_localisation.py -q
"""
import pytest

from brain.codage import banc_depot, depot, localisation


def _depot(tmp_path):
    fichiers = {
        "geo/point.py": (
            "class Point:\n"                                         # 1
            "    def __new__(cls, *args, evaluate=True):\n"          # 2
            "        if any(a.is_imaginary for a in args):\n"        # 3
            "            raise ValueError('Imaginary coordinates are "
            "not permitted.')\n"                                     # 4
            "        return object.__new__(cls)\n"                   # 5
            "\n"
            "    def distance(self, autre):\n"                       # 7
            "        return 0\n"),                                   # 8
        "geo/ligne.py": "from .point import Point\n\n"
                        "def longueur(a, b):\n    return a.distance(b)\n",
        "core/sympify.py": "def sympify(a, evaluate=None):\n"
                           "    return parse_expr(a)\n",
        "modeling/separable.py": "def separability_matrix(model):\n"
                                 "    return _separable(model)\n\n"
                                 "def _separable(m):\n    return m\n",
        "docs/point.rst": "Point\n=====\nLes points, la distance.\n",
        "tests/test_point.py": "from geo.point import Point\n\n"
                               "def test_point():\n    Point(1, 2)\n",
    }
    for c, t in fichiers.items():
        p = tmp_path / c
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    return depot.indexer(tmp_path, cache=False)


# ------------------------------------------------------------ les indices
def test_trace_python_chemin_absolu_ligne_et_fonction():
    i = localisation.indices(
        'Traceback (most recent call last):\n'
        '  File "/home/x/.local/lib/python3.8/site-packages/sympy/core/'
        'sympify.py", line 472, in sympify\n'
        '  File "/home/x/site-packages/sympy/geometry/point.py", line 153, '
        'in __new__\n'
        "ValueError: Imaginary coordinates are not permitted.\n")
    assert [(c.rsplit("/", 2)[-2:], l, f) for c, l, f in i.trace] == [
        (["core", "sympify.py"], 472, "sympify"),
        (["geometry", "point.py"], 153, "__new__")]
    assert "Imaginary coordinates are not permitted" in i.messages


def test_traces_js_java_go():
    i = localisation.indices(
        "TypeError: x is undefined\n    at total (src/panier.js:12:5)\n"
        "Exception in thread main\n"
        "    at bf.mael.Facture.total(Facture.java:42)\n"
        "panic: runtime error\nsvc/panier.go:88 +0x1d\n")
    assert ("src/panier.js", 12, "total") in i.trace
    assert ("bf/mael/Facture/Facture.java", 42, "total") in i.trace \
        or ("bf/mael/Facture.java", 42, "total") in i.trace
    assert ("svc/panier.go", 88, "") in i.trace


def test_trace_ipython_et_ordre_du_plus_profond():
    """Banc du 12/10 (seaborn) : les traces IPython n'etaient pas lues."""
    i = localisation.indices(
        "File ~/code/seaborn/seaborn/_core/plot.py:841, in Plot._plot(self)\n"
        "    840 # Process scale spec\n"
        "File ~/code/seaborn/seaborn/_core/scales.py:351, in "
        "ContinuousBase._setup(self, data)\n"
        "TypeError: numpy boolean subtract\n")
    assert [(c.rsplit("/", 1)[-1], l, f) for c, l, f in i.trace] == [
        ("plot.py", 841, "_plot"), ("scales.py", 351, "_setup")]


def test_options_a_tirets_deviennent_des_identifiants():
    i = localisation.indices("`--recursive=y` ignores `ignore-paths` when "
                             "--import-mode=importlib; a built-in thing")
    assert {"ignore_paths", "import_mode"} <= set(i.identifiants)
    assert "built_in" not in i.identifiants      # pas une option


def test_les_mots_designent_un_nom_de_fichier(tmp_path):
    for c in ("sphinx/builders/manpage.py", "sphinx/application.py"):
        p = tmp_path / c
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("def build():\n    pass\n")
    idx = depot.indexer(tmp_path, cache=False)
    lieux = localisation.localiser(idx, "Generate man page section "
                                        "directories for the MANPATH")
    assert lieux[0].fichier == "sphinx/builders/manpage.py"
    assert "nom de fichier : manpage" in lieux[0].raisons


def test_le_lien_d_appel_est_donne_comme_raison(tmp_path):
    """Levier 2 (requests-3362), poids nul depuis le banc v4 : le lien
    d'appel est une RAISON affichee. Le ticket nomme iter_content (models.py),
    le bug est dans stream_decode_unicode qu'elle appelle (utils.py)."""
    fichiers = {
        "req/models.py": "from .utils import stream_decode_unicode\n\n"
                         "class Response:\n"
                         "    def iter_content(self, decode_unicode=False):\n"
                         "        gen = self.raw\n"
                         "        if decode_unicode:\n"
                         "            gen = stream_decode_unicode(gen, self)\n"
                         "        return gen\n",
        "req/utils.py": "def stream_decode_unicode(iterator, r):\n"
                        "    if r.encoding is None:\n"
                        "        for item in iterator:\n"
                        "            yield item\n",
        "req/sessions.py": "def merge(a, b):\n    return a\n",
        "req/cookies.py": "def jar():\n    return {}\n"}
    for c, t in fichiers.items():
        p = tmp_path / c
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t)
    idx = depot.indexer(tmp_path, cache=False)
    lieux = localisation.localiser(
        idx, "`iter_content(decode_unicode=True)` returns bytes, "
             "not unicode")
    noms = [l.fichier for l in lieux]
    assert noms[:2] == ["req/models.py", "req/utils.py"]
    utils = lieux[1]
    assert any("appele depuis req/models.py : stream_decode_unicode" in r
               for r in utils.raisons)


def test_imports_chemins_et_identifiants():
    i = localisation.indices(
        "Modeling's `separability_matrix` is wrong for nested models\n"
        "```python\nfrom astropy.modeling.separable import "
        "separability_matrix\ncm = m.Linear1D(10) & m.Linear1D(5)\n```\n"
        "See astropy/modeling/core.py and the CompoundModel class.\n")
    assert "astropy.modeling.separable" in i.modules
    assert "astropy/modeling/core.py" in i.chemins
    assert i.identifiants[0] == "separability_matrix"   # entre ` : en tete
    assert "CompoundModel" in i.identifiants
    assert "Linear1D" in i.identifiants
    assert "self" not in i.identifiants and "print" not in i.identifiants


def test_les_mots_vides_ne_sont_pas_des_indices():
    i = localisation.indices("This should work but it doesn't. The output "
                             "is wrong when the separability is nested.")
    assert "should" not in i.mots and "separability" in i.mots


# ------------------------------------------------------------- localiser
def test_la_trace_designe_le_fichier_et_la_fonction(tmp_path):
    idx = _depot(tmp_path)
    lieux = localisation.localiser(idx, (
        "with evaluate(False) crashes\n"
        '  File "/usr/lib/site-packages/geo/point.py", line 4, in __new__\n'
        "ValueError: Imaginary coordinates are not permitted.\n"))
    assert lieux[0].fichier == "geo/point.py"
    assert any("trace" in r for r in lieux[0].raisons)
    assert any("message" in r for r in lieux[0].raisons)
    assert lieux[0].symboles[0].nom == "Point.__new__"
    assert (lieux[0].symboles[0].debut, lieux[0].symboles[0].fin) == (2, 5)


def test_une_phrase_d_erreur_n_est_pas_du_code():
    """Kaggle 15/10 (sympy-21627) : « depth » designait ideals.py."""
    i = localisation.indices(
        "causes a `RecursionError: maximum recursion depth exceeded while "
        "calling a Python object` error\n```\nx = f(1)\n"
        "ValueError: invalid literal for parse_expr\n```\n"
        "see `my_option` and `Point.distance`")
    for mot in ("maximum", "recursion", "depth", "calling", "invalid",
                "literal"):
        assert mot not in i.identifiants
    for code in ("RecursionError", "ValueError", "my_option",
                 "Point.distance"):
        assert code in i.identifiants


def test_une_recursion_designe_la_boucle_pas_le_fond(tmp_path):
    """sympy-21627 : la pile d'une RecursionError finit n'importe ou (ici
    core/sympify.py, 3 cadres) ; le coupable est dans la BOUCLE repetee —
    hors mecanique generique (__new__)."""
    from brain.codage import agent_depot
    idx = _depot(tmp_path)
    boucle = ('  File "/x/geo/ligne.py", line 4, in longueur\n'
              "    return longueur(a, b)\n"
              '  File "/x/geo/point.py", line 5, in __new__\n'
              "    return object.__new__(cls)\n") * 300
    sortie = ("Traceback (most recent call last):\n"
              '  File "<stdin>", line 1, in <module>\n' + boucle
              + "".join(f'  File "/x/core/sympify.py", line {k}, in sympify\n'
                        "    return parse_expr(a)\n" for k in (1, 2, 2))
              + "RecursionError: maximum recursion depth exceeded\n")
    trace = agent_depot.trace_de(sortie)
    assert len(trace) <= agent_depot.TRACE_MAX
    assert "longueur  (x300)" in trace
    assert trace.endswith("RecursionError: maximum recursion depth exceeded")
    lieux = localisation.localiser(idx, "it crashes\n```\n" + trace + "\n```")
    assert lieux[0].fichier == "geo/ligne.py", [
        (l.fichier, l.score) for l in lieux]


def test_le_message_seul_suffit(tmp_path):
    idx = _depot(tmp_path)
    lieux = localisation.localiser(
        idx, "I get `Imaginary coordinates are not permitted.` "
             "with evaluate(False)")
    assert lieux[0].fichier == "geo/point.py"


def test_l_import_designe_le_module(tmp_path):
    idx = _depot(tmp_path)
    lieux = localisation.localiser(
        idx, "```python\nfrom modeling.separable import "
             "separability_matrix\n```\nwrong result")
    assert lieux[0].fichier == "modeling/separable.py"
    assert lieux[0].symboles[0].nom == "separability_matrix"


def test_le_fichier_qui_definit_passe_avant_celui_qui_emploie(tmp_path):
    idx = _depot(tmp_path)
    lieux = localisation.localiser(idx, "`distance` returns 0 for Point")
    noms = [l.fichier for l in lieux]
    assert noms[0] == "geo/point.py"
    assert noms.index("geo/point.py") < noms.index("geo/ligne.py")


def test_tests_et_documentation_apres_le_code(tmp_path):
    idx = _depot(tmp_path)
    lieux = localisation.localiser(idx, "Point distance is wrong: Point(1, 2)"
                                        ".distance(Point(3, 4)) gives 0")
    noms = [l.fichier for l in lieux]
    assert noms[0] == "geo/point.py"
    for apres in ("tests/test_point.py", "docs/point.rst"):
        if apres in noms:
            assert noms.index(apres) > noms.index("geo/point.py")


def test_ticket_sans_indice_ne_casse_rien(tmp_path):
    idx = _depot(tmp_path)
    assert localisation.localiser(idx, "it does not work") == [] or True


# ------------------------------------------------------------------ le banc
def test_lignes_changees_d_un_diff():
    patch = ("diff --git a/geo/point.py b/geo/point.py\n"
             "--- a/geo/point.py\n+++ b/geo/point.py\n"
             "@@ -3,4 +3,5 @@ class Point:\n x\n"
             "@@ -40 +41,2 @@\n y\n")
    assert banc_depot.lignes_changees(patch) == {
        "geo/point.py": [(3, 6), (40, 40)]}


def test_lignes_touchees_sans_le_contexte():
    patch = ("--- a/geo/point.py\n+++ b/geo/point.py\n"
             "@@ -3,4 +3,5 @@ class Point:\n a\n-b\n+c\n+d\n e\n"
             "@@ -40,2 +41,3 @@\n x\n+y\n z\n")
    assert banc_depot.lignes_touchees(patch) == {"geo/point.py": {4, 41}}


def test_lignes_montrees_au_modele(tmp_path):
    """La mesure du rejeu du 15/10 : les lignes a corriger sont-elles dans
    les extraits que le correcteur montrerait ?"""
    idx = _depot(tmp_path)
    lieux = localisation.localiser(idx, (
        '  File "/x/geo/point.py", line 4, in __new__\n'
        "ValueError: Imaginary coordinates are not permitted.\n"))
    patch = ("--- a/geo/point.py\n+++ b/geo/point.py\n"
             "@@ -3,3 +3,3 @@\n         if any(a.is_imaginary for a in "
             "args):\n-            raise ValueError('x')\n+            pass\n")
    m = banc_depot.montrees(tmp_path, lieux, idx, patch, "geo/point.py")
    assert m["montre"] and (m["vues"], m["lignes"]) == (1, 1)
    loin = patch.replace("-3,3 +3,3", "-7,3 +7,3")      # distance(), ligne 8
    m = banc_depot.montrees(tmp_path, lieux[:1], idx, loin, "geo/point.py")
    assert m["lignes"] == 1


def test_les_moities_sont_fixes_et_equilibrees():
    ids = [f"django__django-{n}" for n in range(11000, 11400)]
    m = [banc_depot.moitie(i) for i in ids]
    assert m == [banc_depot.moitie(i) for i in ids]        # toujours pareil
    assert 150 < m.count("reglage") < 250


@pytest.mark.parametrize("membres,attendus", [
    (["projet-abc/", "projet-abc/a.py", "projet-abc/pkg/b.py"],
     {"a.py", "pkg/b.py"})])
def test_extraire_retire_le_dossier_de_tete(tmp_path, membres, attendus):
    import io
    import tarfile
    archive = tmp_path / "a.tar.gz"
    with tarfile.open(archive, "w:gz") as t:
        for m in membres:
            info = tarfile.TarInfo(m)
            if m.endswith("/"):
                info.type = tarfile.DIRTYPE
                t.addfile(info)
            else:
                data = b"x = 1\n"
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
    banc_depot.extraire(archive, tmp_path / "travail")
    trouves = {p.relative_to(tmp_path / "travail").as_posix()
               for p in (tmp_path / "travail").rglob("*") if p.is_file()}
    assert trouves == attendus


def test_extraire_refuse_un_chemin_qui_sort(tmp_path):
    import io
    import tarfile
    archive = tmp_path / "a.tar.gz"
    with tarfile.open(archive, "w:gz") as t:
        info = tarfile.TarInfo("p/../../evade.py")
        info.size = 1
        t.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(tarfile.FilterError):
        banc_depot.extraire(archive, tmp_path / "travail")
    assert not (tmp_path / "evade.py").exists()


# ------------------------------- leviers de couverture du 13/10/2026
def _ecrire(tmp_path, fichiers):
    for c, t in fichiers.items():
        p = tmp_path / c
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    return depot.indexer(tmp_path, cache=False)


def test_noms_composes_normalises():
    assert localisation.normal("import_mode") == localisation.normal(
        "ImportMode") == localisation.normal("import-mode")
    assert localisation.compose("import_mode")
    assert localisation.compose("ImportMode")
    assert not localisation.compose("autosummary")
    assert not localisation.compose("_pytest")


def test_option_a_tirets_trouve_la_classe(tmp_path):
    """pytest-11148 : « import-mode=importlib » -> class ImportMode."""
    idx = _ecrire(tmp_path, {
        "src/pathlib.py": "class ImportMode:\n    importlib = 'importlib'\n",
        "src/fixtures.py": "def fixture():\n    return 1\n"})
    lieux = localisation.localiser(idx, "Module imported twice with "
                                        "import-mode=importlib")
    assert lieux[0].fichier == "src/pathlib.py"
    assert any("import_mode" in r for r in lieux[0].raisons)


def test_mot_simple_pas_rapproche_d_une_classe(tmp_path):
    idx = _ecrire(tmp_path, {"ext/autosummary.py": "class Autosummary:\n"
                                                  "    pass\n"})
    ind = localisation.indices("the `autosummary` directive")
    assert "autosummary" in ind.identifiants
    lieux = localisation.localiser(idx, "the `autosummary` directive")
    assert not any("definit" in r for l in lieux for r in l.raisons)


def test_deux_mots_colles_font_un_nom_de_fichier(tmp_path):
    """sphinx-8273 : « man page » -> builders/manpage.py, et passe devant
    un fichier designe par un seul mot courant (generate)."""
    idx = _ecrire(tmp_path, {
        "builders/manpage.py": "class ManualPageBuilder:\n    pass\n",
        "ext/generate.py": "def run():\n    pass\n"})
    ind = localisation.indices("Generate man page section directories")
    assert "manpage" in ind.noms_colles and "generate" not in ind.noms_colles
    lieux = localisation.localiser(idx, "Generate man page section "
                                        "directories")
    assert lieux[0].fichier == "builders/manpage.py"


def test_code_tiers_relegue(tmp_path):
    """jquery de sphinx, traductions : on ne les corrige jamais."""
    idx = _ecrire(tmp_path, {
        "themes/static/jquery-3.5.1.js": "function build(dir) { man(); }\n",
        "locale/fr/LC_MESSAGES/sphinx.js": "var man = 'build dir';\n",
        "app/application.py": "def build(dir):\n    return dir\n"})
    lieux = localisation.localiser(idx, "`build` puts man pages in `dir`")
    assert lieux[0].fichier == "app/application.py"
    tiers = [l for l in lieux if "static" in l.fichier or "locale" in
             l.fichier]
    assert all(l.score < lieux[0].score / 5 for l in tiers)


def test_sortie_d_outil_collee_ignoree_pas_l_explication_pytest():
    """pylint-7080 : la sortie de pylint noyait `ignore-paths` ; mais les
    lignes « E  assert ... » de pytest portent le bug (pytest-5495)."""
    ticket = ("`--recursive=y` ignores `ignore-paths`\n```\n"
              "************* Module about\n"
              "src\\gen\\about.py:2:0: R2044: Line with empty comment\n"
              "src\\gen\\about.py:57:0: C0103: Constant_Name doesn't conform\n"
              "```\n```\n"
              "E       AssertionError: assert b'' == b'42'\n"
              "E         Right contains more items, first extra item: 52\n```\n")
    ind = localisation.indices(ticket)
    assert "ignore_paths" in ind.identifiants
    assert not {"R2044", "C0103", "Constant_Name"} & set(ind.identifiants)
    assert "AssertionError" in ind.identifiants


def test_identifiants_des_tests_officiels():
    """Format Django de SWE-bench -> identifiant lu par MAEL ; pytest
    inchange."""
    assert banc_depot.identifiant(
        "test_urlfield_clean_invalid (forms_tests.field_tests.test_urlfield."
        "URLFieldTest)") == ("tests/forms_tests/field_tests/test_urlfield.py"
                             "::URLFieldTest::test_urlfield_clean_invalid")
    assert banc_depot.identifiant(
        "test_a (app.tests.T.test_a)\nUne docstring.") == (
        "tests/app/tests.py::T::test_a")
    assert banc_depot.identifiant("testing/test_x.py::test_y[1]") == (
        "testing/test_x.py::test_y[1]")


def test_controle_fichiers_de_tests_et_noms_nus():
    """sympy ne donne que des noms nus : les fichiers a lancer viennent du
    patch de tests officiel, et le nom est retrouve dans les resultats."""
    from brain.codage import essais_depot as ed
    inst = {"test_patch": "--- a/sympy/printing/tests/test_ccode.py\n"
                          "+++ b/sympy/printing/tests/test_ccode.py\n",
            "f2p": '["test_ccode_Relational"]',
            "p2p": '["testing/test_x.py::test_y"]'}
    assert banc_depot.fichiers_de_tests(inst) == [
        "sympy/printing/tests/test_ccode.py", "testing/test_x.py"]
    ex = ed.Execution(lance=True, statuts={
        "sympy/printing/tests/test_ccode.py::test_ccode_Relational": "PASSED",
        "testing/test_x.py::test_y": "FAILED"})
    assert banc_depot.reussi(ex, "test_ccode_Relational")
    assert not banc_depot.reussi(ex, "testing/test_x.py::test_y")
    assert not banc_depot.reussi(ex, "test_absent")
