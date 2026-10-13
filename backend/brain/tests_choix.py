"""Tests du CHOIX par le modele parmi les candidats (choix.py) — 12/10/2026,
levier 3 du point 4. Le modele ne peut qu'AVANCER des candidats ; un chemin
invente est ignore ; en cas d'echec, l'ordre calcule reste.
    ./venv/Scripts/python.exe -m pytest brain/tests_choix.py -q
"""
from brain.codage import choix
from brain.codage.localisation import Lieu, SymboleVise


def _lieux():
    return [Lieu("req/models.py", 9.0, ["definit iter_content"],
                 symboles=[SymboleVise("Response.iter_content", 3, 5, 3.0)]),
            Lieu("req/sessions.py", 4.0, ["emploie next"]),
            Lieu("req/utils.py", 3.0, ["mots du ticket"],
                 symboles=[SymboleVise("stream_decode", 1, 2, 1.0)])]


TEXTES = {"req/models.py": "class Response:\n\n    def iter_content(self, "
                           "decode_unicode=False):\n        pass\n",
          "req/utils.py": "def stream_decode(it, r):\n    return it\n"}


class Moteur:
    def __init__(self, donnees=None, texte="", panne=False):
        self.donnees, self.texte, self.panne = donnees, texte, panne
        self.recu = None

    def completer(self, *, systeme, messages, role_modele, schema=None):
        from brain.backends.base import Reponse
        if self.panne:
            raise TimeoutError("delai depasse")
        self.recu = (systeme, messages, schema)
        return Reponse(texte=self.texte, donnees=self.donnees,
                       appels_outils=[], modele="faux")


def test_le_choix_avance_les_fichiers_choisis_et_garde_les_autres():
    m = Moteur({"fichiers": ["req/utils.py"],
                "raison": "le decodage est fait dans stream_decode"})
    lieux, c = choix.choisir(m, "iter_content returns bytes", _lieux(),
                             TEXTES)
    assert [l.fichier for l in lieux] == ["req/utils.py", "req/models.py",
                                          "req/sessions.py"]
    assert c.applique and c.fichiers == ["req/utils.py"]
    assert lieux[0].raisons[0].startswith("choisi par le modele")
    systeme, messages, schema = m.recu
    assert schema is choix.SCHEMA_CHOIX                 # sortie imposee
    vu = messages[0]["content"]
    assert "def iter_content(self, decode_unicode=False):" in vu  # signature
    assert "1. req/models.py" in vu


def test_un_chemin_invente_est_ignore():
    m = Moteur({"fichiers": ["req/nexiste_pas.py"], "raison": "?"})
    lieux, c = choix.choisir(m, "t", _lieux(), TEXTES)
    assert [l.fichier for l in lieux] == ["req/models.py", "req/sessions.py",
                                          "req/utils.py"]
    assert not c.applique and not c.fichiers


def test_numero_ou_nom_court_compris():
    assert choix.lire({"fichiers": ["3", "models.py"], "raison": "r"}, "",
                      ["req/models.py", "req/sessions.py", "req/utils.py"]
                      )[0] == ["req/utils.py", "req/models.py"]


def test_panne_ou_reponse_vide_l_ordre_calcule_reste():
    for m in (Moteur(panne=True), Moteur(texte="je ne sais pas")):
        lieux, c = choix.choisir(m, "t", _lieux(), TEXTES)
        assert [l.fichier for l in lieux][0] == "req/models.py"
        assert not c.applique


def test_json_dans_le_texte_si_pas_de_donnees():
    m = Moteur(None, '{"fichiers": ["req/sessions.py"], "raison": "x"}')
    lieux, _ = choix.choisir(m, "t", _lieux(), TEXTES)
    assert lieux[0].fichier == "req/sessions.py"


def test_un_seul_candidat_pas_d_appel():
    m = Moteur({"fichiers": ["a.py"]})
    lieux, c = choix.choisir(m, "t", [Lieu("a.py", 1.0)], {})
    assert m.recu is None and not c.applique
