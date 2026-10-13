"""Tests du CHANTIER PAR ETAPES (etapes.py, contrats.py) — 09/10/2026.

Point 3 de la feuille de route « agent autonome » : un grand projet est
decoupe par l'architecte, construit etape par etape, chaque etape recevant
les CONTRATS des precedentes ; un chantier interrompu reprend a son etape.
    ./venv/Scripts/python.exe -m pytest brain/tests_etapes.py -q
"""
import json

import pytest

from brain.codage import contrats, etapes
from brain.codage.chantier import Chantier
from brain.codage.espace import Espace
from brain.tests_codage import CSS_CHANTIER, PAGE_CHANTIER, FauxMoteur, bloc


@pytest.fixture(autouse=True)
def _sans_outils_externes(monkeypatch):
    monkeypatch.setenv("MAEL_SANS_OUTILS", "1")
    monkeypatch.setenv("MAEL_SANS_NAVIGATEUR", "1")
    monkeypatch.setenv("MAEL_SANS_EXECUTION", "1")
    monkeypatch.setenv("MAEL_SANS_PROFESSEURS", "1")


GRAND = ("une plateforme de gestion des clients d'une boutique de pagnes : "
         "base SQLite, API Flask, pages et tests")


@pytest.mark.parametrize("demande,attendu", [
    (GRAND, True),
    ("une plateforme de cours en ligne : catalogue, inscription aux cours, "
     "suivi de progression, espace formateur, pages, API Flask, SQLite et "
     "tests", True),
    ("une page de contact pour un garage", False),
    ("un site de trois pages pour une boulangerie", False),
    ("une petite API Flask qui dit bonjour", False),
])
def test_faut_il_des_etapes(demande, attendu):
    oui, raison = etapes.faut_des_etapes(demande, 8)
    assert oui is attendu and raison


def test_beaucoup_de_fichiers_prevus_veut_des_etapes():
    assert etapes.faut_des_etapes("un site", 8, prevus=12)[0]


def test_lire_les_etapes():
    e = etapes.lire_etapes("Voici :\n- Donnees : le schema des clients\n"
                           "- Serveur : l'API Flask\n- Finition : divers\n"
                           "- donnees : doublon\n")
    assert [(x.nom, x.livre) for x in e] == [
        ("Donnees", "le schema des clients"), ("Serveur", "l'API Flask")]
    e = etapes.lire_etapes(donnees={"etapes": [
        {"nom": "Base", "livre": "les tables"},
        {"nom": "API", "livre": "les routes"}]})
    assert [x.nom for x in e] == ["Base", "API"]


# --------------------------------------------------------- les contrats
def test_relever_les_contrats(tmp_path):
    (tmp_path / "db").mkdir()
    (tmp_path / "app").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "db" / "schema.sql").write_text(
        "CREATE TABLE clients (id INTEGER PRIMARY KEY, nom TEXT);")
    (tmp_path / "app" / "main.py").write_text(
        "import os\nfrom flask import Flask\napp = Flask(__name__)\n"
        "CLE = os.environ.get('CLE_API')\n"
        "@app.route('/api/clients', methods=['GET', 'POST'])\n"
        "def clients(): pass\n@app.delete('/api/clients/<int:i>')\n"
        "def supprimer(i): pass\n")
    (tmp_path / "app" / "services.py").write_text(
        "def calculer_total(c): pass\nclass Panier: pass\n")
    (tmp_path / "src" / "server.js").write_text(
        "router.get('/api/stock', f);\nmodule.exports = { router, demarrer };")
    (tmp_path / "index.html").write_text('<main id="liste"><button '
                                         'id="ajouter">+</button></main>')
    c = contrats.relever(tmp_path, ["db/schema.sql", "app/main.py",
                                    "app/services.py", "src/server.js",
                                    "index.html"])
    assert c.tables == {"clients": ["id", "nom"]}
    assert c.routes == ["GET/POST /api/clients", "DELETE /api/clients/<int:i>",
                        "GET /api/stock"]
    assert c.pages == {"index.html": ["liste", "ajouter"]}
    assert c.variables == ["CLE_API"]
    assert c.modules["app/services.py"] == ["calculer_total", "Panier"]
    assert c.modules["src/server.js"] == ["router", "demarrer"]
    t = c.texte()
    assert t.startswith("[contrats deja etablis")
    assert "clients(id, nom)" in t and "GET /api/stock" in t
    assert len(c.texte(budget=80)) <= 80


# ------------------------------------- un grand projet, de bout en bout
SCHEMA = ("```sql fichier=schema.sql\nCREATE TABLE clients (id INTEGER "
          "PRIMARY KEY, nom TEXT NOT NULL);\n```")
API = '''```python fichier=app.py
import os
import sqlite3

from flask import Flask, jsonify

app = Flask(__name__)
BASE = os.environ.get("DATABASE_URL", "db/app.db")


@app.get("/api/clients")
def clients():
    with sqlite3.connect(BASE) as con:
        lignes = con.execute("SELECT id, nom FROM clients").fetchall()
    return jsonify([{"id": i, "nom": n} for i, n in lignes])
```'''
ARCHITECTE = ("- Donnees : le schema des clients\n"
              "- Serveur : l'API Flask des clients\n"
              "- Pages : la page qui liste les clients\n")


def _reponses():
    return [ARCHITECTE,
            "- schema.sql : la table des clients\n", SCHEMA,
            "- app.py : l'API Flask des clients\n", API,
            "- index.html : la page qui liste les clients\n",
            bloc("index.html", PAGE_CHANTIER),
            "```css fichier=style.css\n" + CSS_CHANTIER + "```"]


def test_un_grand_projet_en_trois_etapes(tmp_path):
    moteur = FauxMoteur(_reponses())
    racine = tmp_path / "pagnes"
    ch = Chantier(moteur, Espace(racine))
    bilan = ch.lancer(GRAND)
    assert [e.nom for e in ch.etapes] == ["Donnees", "Serveur", "Pages"]
    assert all(e.etat == "faite" for e in ch.etapes)
    assert [t.fichier for t in ch.taches] == [
        "db/schema.sql", "app/main.py", "app/templates/index.html",
        "app/static/css/style.css"]      # la forme Flask (arborescence.py)
    # l'etape 2 recoit la table de l'etape 1 ; l'etape 3, la route de la 2
    plan2 = moteur.recus[3][0]["content"]
    assert "[etape 2/3 : Serveur]" in plan2 and "clients(id, nom)" in plan2
    assert "Fichiers DEJA faits" in plan2 and "db/schema.sql" in plan2
    plan3 = moteur.recus[5][0]["content"]
    assert "GET /api/clients" in plan3
    assert len(bilan.etapes) == 3 and "Serveur" in bilan.etapes[1]
    assert (racine / "README.md").exists()
    assert (racine / "requirements.txt").read_text().split() == ["flask"]
    assert len(moteur.recus) == 8                 # aucun appel de trop
    etat = json.loads((racine / ".mael/chantier.json").read_text(
        encoding="utf-8"))
    assert [e["etat"] for e in etat["etapes"]] == ["faite"] * 3


def test_un_grand_projet_interrompu_reprend_a_son_etape(tmp_path):
    class MoteurQuiSArrete(FauxMoteur):
        def completer(self, **k):
            if len(self.recus) == 3:               # au plan de l'etape 2
                raise RuntimeError("coupure de courant")
            return super().completer(**k)
    racine = tmp_path / "pagnes"
    with pytest.raises(RuntimeError):
        Chantier(MoteurQuiSArrete(_reponses()), Espace(racine)).lancer(GRAND)
    reprise = FauxMoteur(_reponses()[3:])          # a partir de l'etape 2
    ch = Chantier(reprise, Espace(racine))
    bilan = ch.reprendre()
    assert [e.etat for e in ch.etapes] == ["faite"] * 3
    assert [t.fichier for t in ch.taches] == [
        "db/schema.sql", "app/main.py", "app/templates/index.html",
        "app/static/css/style.css"]      # la forme Flask (arborescence.py)
    assert "[etape 2/3 : Serveur]" in reprise.recus[0][0]["content"]
    assert len(bilan.etapes) == 2          # les deux etapes reprises


def test_un_petit_projet_garde_un_seul_plan(tmp_path):
    moteur = FauxMoteur(["- index.html : l'accueil\n- style.css : styles\n",
                         bloc("index.html", PAGE_CHANTIER),
                         "```css fichier=style.css\n" + CSS_CHANTIER + "```"])
    ch = Chantier(moteur, Espace(tmp_path))
    ch.lancer("une page d'accueil")
    assert ch.etapes == [] and len(moteur.recus) == 3
