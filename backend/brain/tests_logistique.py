"""Tests de la LOGISTIQUE et de l'arborescence standard (09/10/2026).

Remarque du responsable : « les dossiers ne sont pas convaincants, pas
d'arborescence au standard ». Ces tests figent la forme decidee : la
logistique range au plan, apres chaque ecriture et a la fin.
    ./venv/Scripts/python.exe -m pytest brain/tests_logistique.py -q
"""
import json

import pytest

from brain.codage import arborescence as arbo
from brain.codage.espace import Espace
from brain.codage.logistique import Logistique


@pytest.fixture(autouse=True)
def _sans_outils_externes(monkeypatch):
    monkeypatch.setenv("MAEL_SANS_OUTILS", "1")
    monkeypatch.setenv("MAEL_SANS_NAVIGATEUR", "1")
    monkeypatch.setenv("MAEL_SANS_EXECUTION", "1")
    monkeypatch.setenv("MAEL_SANS_PROFESSEURS", "1")


@pytest.mark.parametrize("demande,fichiers,sorte", [
    ("un site pour une boulangerie", ["index.html", "style.css"], "site"),
    ("une API Flask", ["app.py", "tests/test_app.py"], "python"),
    ("un formulaire PHP", ["contact.php"], "php"),
    ("une API Express", ["server.js"], "node"),
    ("une liste en React", ["App.jsx"], "react"),
    ("un site Django", ["manage.py", "settings.py"], "django"),
])
def test_type_de_projet(demande, fichiers, sorte):
    assert arbo.type_de_projet(demande, fichiers) == sorte


@pytest.mark.parametrize("sorte,avant,apres", [
    ("site", "styles.css", "assets/css/styles.css"),
    ("site", "css/style.css", "assets/css/style.css"),
    ("site", "js/main.js", "assets/js/main.js"),
    ("site", "nos-pains.html", "nos-pains.html"),
    ("python", "app.py", "app/main.py"),
    ("python", "models.py", "app/models.py"),
    ("python", "test_app.py", "tests/test_app.py"),
    ("python", "tests/test_api.py", "tests/test_api.py"),
    ("python", "templates/index.html", "app/templates/index.html"),
    ("php", "config.php", "includes/config.php"),
    ("php", "index.php", "index.php"),
    ("node", "server.js", "src/server.js"),
    ("node", "main.js", "src/main.js"),
    ("node", "menu.js", "public/js/menu.js"),
    ("node", "index.html", "public/index.html"),
    ("node", "app.test.js", "tests/app.test.js"),
    ("react", "ListeProduits.jsx", "src/components/ListeProduits.jsx"),
    ("react", "App.jsx", "src/App.jsx"),
    ("django", "views.py", "views.py"),
])
def test_ranger(sorte, avant, apres):
    assert arbo.ranger(avant, sorte) == apres


def test_morceaux_de_page_retires_du_plan():
    # Mission 004 : footer.html juge comme une page (pas de <h1>...).
    sorte, adresses, fragments = arbo.ranger_plan(
        ["index.html", "footer.html", "header.html", "services.html",
         "styles.css"], "un site pour un garage")
    assert fragments == ["footer.html", "header.html"]
    assert list(adresses.values()) == ["index.html", "services.html",
                                       "assets/css/styles.css"]


def test_deux_fichiers_au_meme_endroit_gardent_leur_chemin():
    _, adresses, _ = arbo.ranger_plan(["css/style.css", "style.css"], "site")
    assert adresses == {"css/style.css": "css/style.css",
                        "style.css": "style.css"}


# ------------------------------------------- apres chaque ecriture
def test_apres_ecriture_raccorde_les_chemins_d_habitude(tmp_path):
    e = Espace(tmp_path)
    log = Logistique(e, "un site pour une boulangerie")
    plan = log.adresser(["index.html", "styles.css", "script.js"])
    e.ecrire("index.html", '<link rel="stylesheet" href="styles.css">\n'
             '<script src="script.js" defer></script>\n'
             '<img src="images/pain.jpg" alt="Pain">\n'
             '<a href="contact.html">Contact</a>\n'
             '<a href="https://exemple.bf">Ext</a>')
    gestes = log.apres_ecriture("index.html", plan)
    texte = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert 'href="assets/css/styles.css"' in texte
    assert 'src="assets/js/script.js"' in texte
    assert 'src="assets/images/pain.jpg"' in texte
    assert 'href="contact.html"' in texte          # une page : pas touchee
    assert 'href="https://exemple.bf"' in texte     # externe : pas touche
    assert len(gestes) == 3 and all(g.startswith("logistique :")
                                    for g in gestes)


def test_un_module_python_dans_app_recoit_son_init(tmp_path):
    e = Espace(tmp_path)
    log = Logistique(e, "une API Flask")
    plan = log.adresser(["app.py", "test_app.py"])
    e.ecrire("app/main.py", "from flask import Flask\napp = Flask(__name__)\n")
    log.apres_ecriture("app/main.py", plan)
    assert (tmp_path / "app/__init__.py").exists()


# ------------------------------------------------------------- en fin
def test_fin_d_un_site_readme_avec_arborescence(tmp_path):
    e = Espace(tmp_path / "boulangerie")
    log = Logistique(e, "un site pour une boulangerie de Ouagadougou")
    log.adresser(["index.html", "style.css"])
    e.ecrire("index.html", "<h1>x</h1>")
    e.ecrire("assets/css/style.css", "body{}")
    ecrits = log.finir(["assets/images/pain.jpg"])
    assert ecrits == ["README.md"]                 # un site : pas de .gitignore
    r = (tmp_path / "boulangerie/README.md").read_text(encoding="utf-8")
    assert r.startswith("# Un site pour une boulangerie")
    assert "├── assets/" in r and "style.css" in r and "index.html" in r
    assert "Ouvrir `index.html`" in r and "assets/images/pain.jpg" in r


def test_fin_d_une_api_python(tmp_path):
    e = Espace(tmp_path / "api")
    log = Logistique(e, "une API FastAPI de taches")
    log.adresser(["main.py", "test_main.py"])
    e.ecrire("app/main.py", "import os\nfrom fastapi import FastAPI\n"
             "from pydantic import BaseModel\napp = FastAPI()\n"
             "CLE = os.environ.get('CLE_SECRETE')\n")
    e.ecrire("tests/test_main.py", "from fastapi.testclient import "
             "TestClient\nfrom app.main import app\n")
    ecrits = log.finir()
    racine = tmp_path / "api"
    assert set(ecrits) == {".gitignore", ".env.example", "requirements.txt",
                           "app/__init__.py", "README.md"}
    assert (racine / "requirements.txt").read_text().split() == [
        "fastapi", "httpx", "pydantic", "pytest", "uvicorn"]
    assert (racine / ".env.example").read_text() == "CLE_SECRETE=\n"
    assert "__pycache__/" in (racine / ".gitignore").read_text()
    r = (racine / "README.md").read_text(encoding="utf-8")
    assert "uvicorn app.main:app --reload" in r and "python -m pytest" in r
    assert "`CLE_SECRETE`" in r


def test_fin_d_une_api_node_package_json(tmp_path):
    e = Espace(tmp_path / "api-node")
    log = Logistique(e, "une API Express")
    log.adresser(["server.js"])
    e.ecrire("src/server.js", "const express = require('express');\n"
             "const db = require('./db');\nconst p = process.env.PORT;\n")
    log.finir()
    paquet = json.loads((tmp_path / "api-node/package.json").read_text())
    assert paquet["dependencies"] == {"express": "*"}
    assert paquet["scripts"]["start"] == "node src/server.js"


def test_fin_n_ecrase_jamais(tmp_path):
    e = Espace(tmp_path)
    log = Logistique(e, "une API Flask")
    log.adresser(["app.py"])
    e.ecrire("app/main.py", "from flask import Flask\n")
    e.ecrire("README.md", "# le mien")
    log.finir()
    assert (tmp_path / "README.md").read_text().strip() == "# le mien"


# ------------------------------------------- toute la chaine, en vrai
from brain.codage.chantier import Chantier
from brain.tests_codage import CSS_CHANTIER, PAGE_CHANTIER, FauxMoteur, bloc


def test_chantier_complet_donne_un_projet_range(tmp_path):
    page = PAGE_CHANTIER                               # appelle style.css
    moteur = FauxMoteur([
        "- index.html : l'accueil\n- footer.html : le pied de page\n"
        "- style.css : les styles\n",
        bloc("index.html", page),
        "```css fichier=style.css\n" + CSS_CHANTIER + "```"])
    racine = tmp_path / "boulangerie"
    ch = Chantier(moteur, Espace(racine))
    bilan = ch.lancer("une page d'accueil pour une boulangerie")
    assert [t.fichier for t in ch.taches] == ["index.html",
                                              "assets/css/style.css"]
    assert (racine / "assets/css/style.css").exists()
    assert not (racine / "style.css").exists()
    assert not (racine / "footer.html").exists()
    assert 'href="assets/css/style.css"' in (racine / "index.html"
                                             ).read_text(encoding="utf-8")
    assert (racine / "README.md").exists()
    assert any("footer.html retire du plan" in g for g in bilan.logistique)
    assert any("pied de page ecrits dans chaque page" in s
               for s in bilan.suppositions)
    assert bilan.conforme
    assert len(moteur.recus) == 3          # plan + 2 taches : aucun detour
