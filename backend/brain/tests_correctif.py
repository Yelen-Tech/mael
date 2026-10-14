"""Tests du CORRECTIF d'un ticket sur un depot existant (correctif.py) —
12/10/2026, point 4.3.

Le modele ne voit que les extraits designes par la localisation et repond
par des blocs CHERCHER / REMPLACER ; rien n'est applique a l'aveugle.
    ./venv/Scripts/python.exe -m pytest brain/tests_correctif.py -q
"""
import pytest

from brain.codage import correctif, depot
from brain.codage.espace import Espace
from brain.codage.retouche import Extrait
from brain.tests_codage import FauxMoteur

PANIER = ("class Panier:\n"                         # 1
          "    def __init__(self):\n"               # 2
          "        self.lignes = []\n"              # 3
          "\n"                                      # 4
          "    def total(self):\n"                  # 5
          "        s = 0\n"                         # 6
          "        for l in self.lignes:\n"         # 7
          "            s = l\n"                     # 8  <- le bug
          "        return s\n"                      # 9
          "\n"                                      # 10
          "    def vider(self):\n"                  # 11
          "        s = 0\n"                         # 12
          "        self.lignes = []\n")             # 13
TICKET = "`Panier.total` returns only the last line instead of the sum"


def _depot(tmp_path, fichiers=None):
    fichiers = fichiers or {
        "boutique/panier.py": PANIER,
        "boutique/remise.py": "def remise(p):\n    return p\n",
        "tests/test_panier.py": "from boutique.panier import Panier\n\n"
                                "def test_total():\n    assert Panier()"
                                ".total() == 0\n"}
    for c, t in fichiers.items():
        p = tmp_path / c
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    return depot.indexer(tmp_path, cache=False)


def bloc(fichier, chercher, remplacer):
    return (f"FICHIER: {fichier}\n<<<<<<< CHERCHER\n{chercher}\n=======\n"
            f"{remplacer}\n>>>>>>> REMPLACER\n")


JUSTE = bloc("boutique/panier.py",
             "        for l in self.lignes:\n            s = l",
             "        for l in self.lignes:\n            s += l")


def test_correction_appliquee_en_un_tour_avec_son_diff(tmp_path):
    idx = _depot(tmp_path)
    moteur = FauxMoteur(["Voici :\n" + JUSTE])
    r = correctif.Correcteur(moteur, tmp_path).corriger(TICKET, idx)
    assert r.corrige and r.tours == 1 and not r.refus
    assert "s += l" in (tmp_path / "boutique/panier.py").read_text()
    assert "-            s = l\n+            s += l" in r.diff
    assert r.diff.startswith("--- a/boutique/panier.py")
    vu = moteur.recus[0][0]["content"]
    assert "Panier.total" in vu or "panier.py" in vu
    assert "8|             s = l" in vu                 # extrait numerote
    assert "test_total" not in vu                       # tests non montres
    sauvegardes = list((tmp_path / ".mael" / "sauvegardes").rglob(
        "panier.py"))
    assert sauvegardes and "s = l" in sauvegardes[0].read_text()


def test_numeros_recopies_et_anglais_et_cloture_tolores(tmp_path):
    idx = _depot(tmp_path)
    reponse = ("FICHIER: `boutique/panier.py`\n```python\n<<<<<<< SEARCH\n"
               "7|         for l in self.lignes:\n8|             s = l\n"
               "=======\n        for l in self.lignes:\n"
               "            s += l\n>>>>>>> REPLACE\n```\n")
    r = correctif.Correcteur(FauxMoteur([reponse]), tmp_path).corriger(
        TICKET, idx)
    assert r.corrige and "s += l" in (tmp_path / "boutique/panier.py"
                                      ).read_text()


def test_texte_introuvable_refuse_puis_corrige_au_tour_suivant(tmp_path):
    idx = _depot(tmp_path)
    faux = bloc("boutique/panier.py", "        for x in lignes:\n"
                "            s = x", "        pass")
    moteur = FauxMoteur([faux, JUSTE])
    r = correctif.Correcteur(moteur, tmp_path).corriger(TICKET, idx)
    assert r.corrige and r.tours == 2
    retour = moteur.recus[1][-1]["content"]
    assert "n'existe pas tel quel" in retour
    assert "etat actuel" in retour


def test_texte_ambigu_refuse(tmp_path):
    idx = _depot(tmp_path)
    ambigu = bloc("boutique/panier.py", "        s = 0", "        s = 1")
    r = correctif.Correcteur(FauxMoteur([ambigu] * 3), tmp_path).corriger(
        TICKET, idx)
    assert not r.corrige
    assert any("apparait 2 fois" in x for x in r.refus)
    assert (tmp_path / "boutique/panier.py").read_text() == PANIER


def test_fichier_non_montre_ou_de_test_refuse(tmp_path):
    _depot(tmp_path)
    e = Espace(tmp_path)
    extraits = [Extrait("boutique/panier.py", 1, 13)]
    _, refus, _ = correctif.appliquer(e, [
        correctif.Edition("boutique/remise.py", "    return p", "    return 0"),
        correctif.Edition("tests/test_panier.py", "def test_total():",
                          "def test_x():")], extraits, {"tests/test_panier.py"})
    assert "ne t'a pas ete montre" in refus[0]
    assert "fichier de test" in refus[1]
    assert (tmp_path / "boutique/remise.py").read_text().endswith(
        "return p\n")


def test_hors_des_extraits_montres_refuse(tmp_path):
    _depot(tmp_path)
    _, refus, _ = correctif.appliquer(
        Espace(tmp_path), [correctif.Edition(
            "boutique/panier.py", "    def vider(self):", "    def vide(self):")],
        [Extrait("boutique/panier.py", 4, 10)])
    assert "hors des extraits" in refus[0]


def test_python_casse_jamais_ecrit(tmp_path):
    _depot(tmp_path)
    _, refus, _ = correctif.appliquer(
        Espace(tmp_path), [correctif.Edition(
            "boutique/panier.py", "            s = l", "            s += (l")],
        [Extrait("boutique/panier.py", 1, 13)])
    assert "ne se lit plus" in refus[0]
    assert (tmp_path / "boutique/panier.py").read_text() == PANIER


def test_espace_de_trop_apres_le_numero_tolere(tmp_path):
    """Kaggle 15/10 (django-15202, matplotlib-25433) : le modele garde
    l'espace qui suit « 12| », chaque ligne decalee d'un cran ; CHERCHER
    et REMPLACER sont recales ensemble."""
    _depot(tmp_path)
    appliquees, refus, _ = correctif.appliquer(
        Espace(tmp_path), [correctif.Edition(
            "boutique/panier.py",
            "         for l in self.lignes:\n             s = l",
            "         for l in self.lignes:\n             s += l")],
        [Extrait("boutique/panier.py", 1, 13)])
    assert refus == [] and len(appliquees) == 1
    assert "        for l in self.lignes:\n            s += l\n" in (
        tmp_path / "boutique/panier.py").read_text()
    # un decalage qui n'est PAS constant reste refuse
    _, refus, _ = correctif.appliquer(
        Espace(tmp_path), [correctif.Edition(
            "boutique/panier.py", "         s = 0\n        self.lignes = []",
            "        s = 1\n        self.lignes = []")],
        [Extrait("boutique/panier.py", 1, 13)])
    assert "n'existe pas tel quel" in refus[0]


def test_remplacer_identique_refuse_avec_sa_raison(tmp_path):
    """Kaggle 15/10 (sympy-21627) : les memes lignes des deux cotes."""
    _depot(tmp_path)
    _, refus, _ = correctif.appliquer(
        Espace(tmp_path), [correctif.Edition(
            "boutique/panier.py", "            s = l", "            s = l  ")],
        [Extrait("boutique/panier.py", 1, 13)])
    assert "IDENTIQUE" in refus[0]


def test_changer_seulement_des_commentaires_refuse(tmp_path):
    """Essai reel du 12/10 : phi4-mini « corrigeait » en reecrivant des
    commentaires."""
    (tmp_path / "a.py").write_text("def f():\n    # ancien commentaire\n"
                                   "    return 1\n")
    _, refus, _ = correctif.appliquer(Espace(tmp_path), [correctif.Edition(
        "a.py", "    # ancien commentaire\n    return 1",
        "    # nouveau commentaire, plus clair\n    return  1")],
        [Extrait("a.py", 1, 3)])
    assert "ne touche que des commentaires" in refus[0]
    assert "ancien commentaire" in (tmp_path / "a.py").read_text()


@pytest.mark.parametrize("remplacer,regle", [
    ("        return eval(texte)", "eval"),
    ("        return subprocess.run(texte, shell=True)", "shell"),
    ("        return db.execute(f\"SELECT * FROM t WHERE n = '{texte}'\")",
     "SQL")])
def test_un_correctif_qui_introduit_un_defaut_de_securite_est_refuse(
        tmp_path, remplacer, regle):
    """Remarque du responsable (12/10) : MAEL est d'abord un outil de
    securite — un correctif ne doit jamais introduire eval, shell=True,
    du SQL colle..."""
    avant = ("import subprocess\n\n\nclass Lecteur:\n"
             "    def lire(self, texte, db=None):\n"
             "        return texte.strip()\n")
    (tmp_path / "a.py").write_text(avant)
    _, refus, _ = correctif.appliquer(Espace(tmp_path), [correctif.Edition(
        "a.py", "        return texte.strip()",
        remplacer.replace("db.", "db."))], [Extrait("a.py", 1, 6)])
    assert refus and "INTRODUIT un defaut" in refus[0], refus
    assert (tmp_path / "a.py").read_text() == avant


def test_un_defaut_deja_present_n_est_pas_reproche(tmp_path):
    avant = ("def f(x):\n    y = eval(x)\n    return y + 1\n")
    (tmp_path / "a.py").write_text(avant)
    appliquees, refus, _ = correctif.appliquer(
        Espace(tmp_path), [correctif.Edition("a.py", "    return y + 1",
                                             "    return y + 2")],
        [Extrait("a.py", 1, 3)])
    assert appliquees and not refus           # eval etait deja la


def test_deux_editions_meme_fichier_extraits_recales(tmp_path):
    _depot(tmp_path)
    appliquees, refus, recales = correctif.appliquer(
        Espace(tmp_path), [
            correctif.Edition("boutique/panier.py", "        self.lignes = []\n"
                              "\n    def total(self):",
                              "        self.lignes = []\n        self.n = 0\n"
                              "\n    def total(self):"),
            correctif.Edition("boutique/panier.py", "            s = l",
                              "            s += l")],
        [Extrait("boutique/panier.py", 1, 13)])
    assert len(appliquees) == 2 and not refus
    assert recales == [Extrait("boutique/panier.py", 1, 14)]
    t = (tmp_path / "boutique/panier.py").read_text()
    assert "self.n = 0" in t and "s += l" in t


def test_le_style_du_fichier_est_garde_crlf_et_sans_ligne_finale(tmp_path):
    """Essai du 12/10 : Espace ecrivait toujours en \\n avec une ligne
    finale — sur un fichier en \\r\\n, changer 2 lignes les changeait
    toutes."""
    (tmp_path / "a.py").write_bytes(b"def f():\r\n    x = 1\r\n    return x")
    correctif.appliquer(Espace(tmp_path), [correctif.Edition(
        "a.py", "    x = 1", "    x = 2")], [Extrait("a.py", 1, 3)])
    assert (tmp_path / "a.py").read_bytes() == \
        b"def f():\r\n    x = 2\r\n    return x"
    (tmp_path / "b.py").write_bytes(b"x = 1\ny = 2\n")
    correctif.appliquer(Espace(tmp_path), [correctif.Edition(
        "b.py", "y = 2", "y = 3")], [Extrait("b.py", 1, 2)])
    assert (tmp_path / "b.py").read_bytes() == b"x = 1\ny = 3\n"


def test_aucun_bloc_lisible(tmp_path):
    idx = _depot(tmp_path)
    r = correctif.Correcteur(FauxMoteur(["Je pense que..."] * 3),
                             tmp_path).corriger(TICKET, idx)
    assert not r.corrige and r.tours == 3
    assert "aucune modification lisible" in r.refus[0]


# ------------------------------------------ petits modeles (essai du 12/10)
class MoteurJSON:
    """Un moteur qui recoit le schema (sortie imposee) et rend des donnees."""

    def __init__(self, reponses):
        self.reponses, self.schemas = list(reponses), []

    def completer(self, *, systeme, messages, role_modele, schema=None):
        from brain.backends.base import Reponse
        self.schemas.append(schema)
        donnees, texte = self.reponses.pop(0)
        return Reponse(texte=texte, donnees=donnees, appels_outils=[],
                       modele="faux")


def test_petit_modele_reponse_imposee_par_le_schema(tmp_path):
    from brain.codage.envergure import Envergure
    idx = _depot(tmp_path)
    moteur = MoteurJSON([({"editions": [{
        "fichier": "boutique/panier.py",
        "chercher": "        for l in self.lignes:\n            s = l",
        "remplacer": "        for l in self.lignes:\n            s += l"}]},
        "")])
    r = correctif.Correcteur(moteur, tmp_path, envergure=Envergure(
        milliards=3.8, contexte=8192)).corriger(TICKET, idx)
    assert moteur.schemas[0] is correctif.SCHEMA_EDITIONS
    assert r.corrige and "s += l" in r.diff


def test_un_grand_modele_garde_le_format_libre(tmp_path):
    from brain.codage.envergure import Envergure
    c = correctif.Correcteur(None, tmp_path,
                             envergure=Envergure(milliards=70, contexte=1 << 17))
    assert not c.contraint
    assert not correctif.Correcteur(None, tmp_path).contraint  # inconnu


def test_fonction_reecrite_au_lieu_d_un_bloc_recuperee(tmp_path):
    """Ce que phi4-mini a vraiment fait le 12/10 : une fonction reecrite,
    sans indentation de classe, dans un bloc ```python."""
    idx = _depot(tmp_path)
    reponse = ("Voici la correction :\n```python\ndef total(self):\n"
               "    s = 0\n    for l in self.lignes:\n        s += l\n"
               "    return s\n```\n")
    r = correctif.Correcteur(FauxMoteur([reponse]), tmp_path).corriger(
        TICKET, idx)
    assert r.corrige, r.refus
    t = (tmp_path / "boutique/panier.py").read_text()
    assert "    def total(self):\n        s = 0\n        for l in self.lignes" \
        ":\n            s += l\n        return s\n" in t      # reindentee
    assert "    def vider(self):" in t                       # le reste intact


def test_fonction_reecrite_inconnue_refusee(tmp_path):
    idx = _depot(tmp_path)
    reponse = "```python\ndef autre():\n    pass\n```"
    r = correctif.Correcteur(FauxMoteur([reponse] * 3), tmp_path).corriger(
        TICKET, idx)
    assert not r.corrige
    assert (tmp_path / "boutique/panier.py").read_text() == PANIER


def test_les_extraits_suivent_la_priorite_pas_l_ordre_des_lignes(tmp_path):
    """Essai du 12/10 : Response.__init__ (debut du fichier, sans rapport)
    mangeait le budget ; iter_content, la fonction du ticket, jamais
    montree."""
    from brain.codage.localisation import Lieu, SymboleVise
    long_init = "    def __init__(self):\n" + "".join(
        f"        self.a{n} = {n}  # commentaire assez long pour peser\n"
        for n in range(60))
    texte = ("class Response:\n" + long_init + "\n"
             "    def iter_content(self, decode_unicode=False):\n"
             "        return self.raw\n")
    _depot(tmp_path, {"models.py": texte})
    debut_iter = texte.split("\n").index(
        "    def iter_content(self, decode_unicode=False):") + 1
    lieu = Lieu("models.py", 5.0, symboles=[
        SymboleVise("Response.iter_content", debut_iter, debut_iter + 1, 3.0),
        SymboleVise("Response.__init__", 2, 62, 0.5)])
    (e, *_) = correctif.choisir_extraits(tmp_path, [lieu], 1_000)
    assert e.debut <= debut_iter <= e.fin


# ----------------------------------------------------------- les extraits
def test_extraits_sous_budget_sans_tests(tmp_path):
    from brain.codage import localisation
    idx = _depot(tmp_path)
    lieux = localisation.localiser(idx, TICKET)
    ex = correctif.choisir_extraits(tmp_path, lieux, 6_000, idx)
    assert ex and all(not e.fichier.startswith("tests/") for e in ex)
    assert any(e.fichier == "boutique/panier.py" and e.debut <= 8 <= e.fin
               for e in ex)
    petit = correctif.choisir_extraits(tmp_path, lieux, 120, idx)
    assert len(petit) == 1                     # au moins un, coupe


def test_fonction_trop_longue_fenetre_autour_de_la_trace(tmp_path):
    from brain.codage.localisation import Lieu, SymboleVise
    corps = "def f():\n" + "".join(f"    x{n} = {n}\n" for n in range(400))
    _depot(tmp_path, {"a.py": corps})
    lieu = Lieu("a.py", 1.0, lignes=[300],
                symboles=[SymboleVise("f", 1, 401, 5.0)])
    (e,) = correctif.choisir_extraits(tmp_path, [lieu], 100_000)
    assert e.debut <= 300 <= e.fin and e.fin - e.debut <= 2 * \
        correctif.FENETRE


def test_le_budget_suit_le_modele():
    from brain.codage.envergure import Envergure
    assert Envergure(milliards=3.8, contexte=8192).budget_extraits == 6_000
    assert Envergure(milliards=70, contexte=131072).budget_extraits == 120_000


def test_les_tours_ne_s_empilent_pas_et_tiennent_dans_le_contexte(tmp_path):
    """Kaggle 15/10 : au 3e tour, 46 352 jetons demandes pour 32 768 — les
    extraits de chaque tour s'ajoutaient aux precedents. Chaque demande est
    maintenant UN message, sous la limite, quel que soit le tour."""
    from brain.codage.envergure import Envergure
    gros = "".join(f"def f{i}(x):\n    return x + {i}  # {'z' * 60}\n\n"
                   for i in range(3_000))
    idx = _depot(tmp_path, {"boutique/panier.py": PANIER + gros,
                            "boutique/autre.py": gros})
    env = Envergure(milliards=30, contexte=32_768)
    faux = bloc("boutique/panier.py", "rien de tel", "pass")
    moteur = FauxMoteur([faux, faux, faux])
    c = correctif.Correcteur(moteur, tmp_path, envergure=env)
    r = c.corriger(TICKET + " " + "detail " * 8_000, idx)
    limite = correctif.limite_demande(env)
    assert len(moteur.recus) == c.tours >= 3 and not r.corrige
    for messages in moteur.recus:
        assert len(messages) == 1
        assert len(messages[0]["content"]) <= limite
    assert "n'existe pas tel quel" in moteur.recus[-1][0]["content"]
    assert "TICKET" in moteur.recus[-1][0]["content"]
