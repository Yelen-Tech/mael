"""Lot NEUF de la chaine (plan -> specialistes -> conseil -> retour au
modele), valide par le responsable le 08/10/2026. Ecrit APRES les
corrections du premier lot ; le code n'est PAS retouche avant la mesure.
Pieges : la fiche d'un autre langage (cas 9), un fichier present sous un
autre chemin (cas 10), des regles sans fiche (cas 3, 4 : honnetete).

    python -c "from brain.codage import banc_chaine_neuf as b; print(b.rapport())"
"""
from __future__ import annotations

from . import banc_chaine as bc
from .banc_chaine import CSS, page

CAS = [
    {"id": "n1-express-sql-concatenee",
     "demande": "un serveur Express qui liste les commandes d'un client",
     "plan": {"server.js": "le serveur Express et ses routes"},
     "fichiers": {"server.js": (
         'const express = require("express");\n'
         'const db = require("./db");\nconst app = express();\n'
         'app.get("/api/commandes/:client", (req, res) => {\n'
         '  db.all("SELECT * FROM commandes WHERE client = \'" + '
         'req.params.client + "\'", (err, rows) => res.json(rows));\n});\n'
         'app.listen(3000);\n')},
     "faute": "server.js",
     "attendu": {"juges": ["injection-sql"], "retour": ["param"],
                 "retour_pas": ["$pdo", "htmlspecialchars"]}},

    {"id": "n2-react-html-brut",
     "demande": "un composant React qui affiche des articles de blog",
     "plan": {"Article.jsx": "affiche un article"},
     "fichiers": {"Article.jsx": (
         'export function Article({ html }) {\n'
         '  return <article dangerouslySetInnerHTML={{ __html: html }} />;\n'
         '}\n')},
     "faute": "Article.jsx",
     "attendu": {"juges_un": ["innerhtml", "xss-dom"],
                 "retour": ["dompurify"]}},

    {"id": "n3-blank-sans-noopener",
     "demande": "une page avec des liens vers nos reseaux sociaux",
     "plan": {"index.html": "la page et ses liens", "style.css": "styles"},
     "fichiers": {
         "index.html": page("Accueil", ["index.html"], (
             '<a href="https://facebook.com/exemple" target="_blank">'
             'Facebook</a>')),
         "style.css": CSS},
     "faute": "index.html",
     # Attente revue apres la 1re mesure, en le disant : depuis 2021 les
     # navigateurs appliquent noopener par defaut a target="_blank" ; le
     # juge a raison d'en faire un CONSEIL non bloquant. Rien a corriger.
     "attendu": {}},

    {"id": "n4-subprocess-shell",
     "demande": "un script Python qui convertit un fichier envoye par "
                "l'utilisateur",
     "plan": {"convertir.py": "convertit le fichier"},
     "fichiers": {"convertir.py": (
         "import subprocess\nimport sys\n\nnom = sys.argv[1]\n"
         "subprocess.run('convert ' + nom + ' sortie.pdf', shell=True)\n")},
     "faute": "convertir.py",
     "attendu": {"juges_un": ["injection-commande", "py-dangereux"],
                 "retour_ou_basse": ["liste"]}},

    {"id": "n5-page-sans-lang-ni-title",
     "demande": "une page d'accueil",
     "plan": {"index.html": "l'accueil"},
     "fichiers": {"index.html": (
         '<!DOCTYPE html>\n<html>\n<head>\n<meta charset="utf-8">\n'
         '<meta name="viewport" content="width=device-width, '
         'initial-scale=1">\n</head>\n<body>\n<main>\n<h1>Bienvenue</h1>\n'
         '</main>\n</body>\n</html>\n')},
     "faute": "index.html",
     "attendu": {"juges": ["lang", "title"], "retour": ["lang", "title"]}},

    {"id": "n6-contraste-dans-le-css",
     "demande": "un site de deux pages pour un photographe",
     "plan": {"index.html": "l'accueil", "galerie.html": "la galerie",
              "style.css": "les styles"},
     "fichiers": {
         "index.html": page("Accueil", ["index.html", "galerie.html"],
                            "<p>Des photos de mariage et de bapteme.</p>"),
         "galerie.html": page("Galerie", ["index.html", "galerie.html"],
                              "<p>Nos plus belles images.</p>"),
         "style.css": ("body { color: #bbbbbb; background: #ffffff; "
                       "font: 1rem/1.5 system-ui; }\n")},
     "faute": "style.css",
     "attendu": {"juges": ["contraste"], "retour": ["mesur"]}},

    {"id": "n7-contrat-fastapi-prefixe",
     "demande": "une page qui charge les commandes depuis une API FastAPI",
     "plan": {"index.html": "la page des commandes", "js/commandes.js":
              "charge les commandes", "main.py": "l'API FastAPI"},
     "fichiers": {
         "index.html": page("Commandes", ["index.html"],
                            '<ul id="liste"></ul>', "js/commandes.js"),
         "js/commandes.js": (
             'const liste = document.getElementById("liste");\n'
             'if (liste) {\n  fetch("/api/commandes").then((r) => r.json())'
             '\n    .then((cs) => cs.forEach((c) => {\n'
             '      const li = document.createElement("li");\n'
             '      li.textContent = c.numero; liste.append(li);\n'
             '    }));\n}\n'),
         "main.py": ('from fastapi import FastAPI\n\napp = FastAPI()\n\n\n'
                     '@app.get("/commandes")\ndef commandes():\n'
                     '    return []\n')},
     "faute": "js/commandes.js",
     # Controle durci apres la 1re mesure (passe par chance : le mot etait
     # dans le nom du fichier) : la route reelle dans une SOLUTION.
     "attendu": {"juges": ["contrat-api"], "solution": ["/commandes"]}},

    {"id": "n8-mot-de-passe-en-get",
     "demande": "un formulaire de connexion",
     "plan": {"index.html": "le formulaire de connexion",
              "style.css": "les styles"},
     "fichiers": {
         "index.html": page("Connexion", ["index.html"], (
             '<form method="get" action="connexion">\n<label for="c">'
             'Courriel</label><input id="c" name="c" type="email">\n'
             '<label for="m">Mot de passe</label><input id="m" name="m" '
             'type="password">\n<button type="submit">Entrer</button>\n'
             '</form>')),
         "style.css": CSS},
     "faute": "index.html",
     "attendu": {"juges": ["mdp-en-get"], "retour": ["post"]}},

    {"id": "n9-xss-en-python-piege-php",
     "demande": "une API Flask qui renvoie une page de bienvenue avec le nom "
                "passe dans l'adresse",
     "plan": {"app.py": "l'API Flask"},
     "fichiers": {"app.py": (
         "from flask import Flask, request\n\napp = Flask(__name__)\n\n\n"
         "@app.get('/bienvenue')\ndef bienvenue():\n"
         "    nom = request.args.get('nom', '')\n"
         "    return f'<h1>Bonjour {nom}</h1>'\n")},
     "faute": "app.py",
     "attendu": {"juges_un": ["xss-serveur"],
                 "retour_pas": ["htmlspecialchars"],
                 "retour_ou_basse": ["escape"]}},

    {"id": "n10-chemin-faux-pas-fichier-absent",
     "demande": "un site de trois pages pour une ecole",
     "plan": {"index.html": "l'accueil", "classes.html": "les classes",
              "contact.html": "le contact", "style.css": "les styles"},
     "fichiers": {
         "index.html": page("Accueil", ["index.html", "classes.html",
                                        "contact.html"], css="css/style.css"),
         "classes.html": page("Classes", ["index.html", "classes.html",
                                          "contact.html"], css="css/style.css"),
         "contact.html": page("Contact", ["index.html", "classes.html",
                                          "contact.html"], css="css/style.css"),
         "style.css": CSS},
     "faute": "index.html",
     "attendu": {"juges": ["fichier-absent"], "retour": ["chemin"],
                 "retour_pas": ["inventer"]}},
]


def rapport() -> str:
    sauve = bc.CAS
    try:
        bc.CAS = CAS
        texte = bc.rapport()
    finally:
        bc.CAS = sauve
    return texte.replace("# Banc de la CHAINE", "# LOT NEUF — Banc de la CHAINE",
                         1)
