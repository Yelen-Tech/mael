"""Le banc de la CHAINE sans modele : plan -> specialistes (vrais juges) ->
conseil -> le RETOUR exact que le modele recevrait pour corriger.

Demande du responsable (08/10/2026) : « on fait le lot des problemes
inedits en utilisant uniquement ceux qui font le plan, les specialistes et
le conseil, pour voir quel retour le conseil donnerait au modele ; durcis
les questions ». 10 cas valides par lui. Sans modele, personne ne produit
le plan ni les fichiers : ils sont ecrits A LA FACON de phi4-mini, d'apres
ses erreurs reelles des missions du 08/10/2026.

Trois mesures par cas : les JUGES ont-ils vu le defaut ? le CONSEIL a-t-il
donne le bon retour ? ce retour est-il HONNETE (confiance basse s'il ne
sait pas) ?

    python -c "from brain.codage import banc_chaine as b; print(b.rapport())"
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from . import conseil_juges as cj
from . import specialistes
from .criteres import deduire, manques
from .juges import GRAVITE


def page(titre: str, liens: list[str], contenu: str = "",
         script: str = "", css: str = "style.css") -> str:
    nav = "".join(f'<li><a href="{l}">{l.split(".")[0]}</a></li>'
                  for l in liens)
    js = f'<script src="{script}" defer></script>\n' if script else ""
    return (f'<!DOCTYPE html>\n<html lang="fr">\n<head>\n<meta charset="utf-8">'
            f'\n<meta name="viewport" content="width=device-width, '
            f'initial-scale=1">\n<title>{titre}</title>\n<link rel="stylesheet"'
            f' href="{css}">\n{js}</head>\n<body>\n<nav aria-label="Menu">'
            f'<ul>{nav}</ul></nav>\n<main>\n<h1>{titre}</h1>\n{contenu}\n'
            '</main>\n</body>\n</html>\n')


CSS = ("body { color: #1f2937; background: #ffffff; font: 1rem/1.5 "
       "system-ui; }\na { color: #1d4ed8; }\n")
TROIS = ["index.html", "catalogue.html", "contact.html"]

CAS = [
    {"id": "1-contrat-api-rompu",
     "demande": "une petite boutique de trois pages (accueil, catalogue, "
                "contact) avec un script qui charge le catalogue depuis "
                "une API en Python Flask",
     "plan": {"index.html": "l'accueil", "catalogue.html": "le catalogue",
              "contact.html": "le contact", "style.css": "les styles",
              "js/catalogue.js": "charge le catalogue depuis l'API",
              "app.py": "l'API Flask des produits"},
     "fichiers": {
         "index.html": page("Accueil", TROIS),
         "catalogue.html": page("Catalogue", TROIS,
                                '<ul id="liste"></ul>', "js/catalogue.js"),
         "contact.html": page("Contact", TROIS),
         "style.css": CSS,
         "js/catalogue.js": (
             'const liste = document.getElementById("liste");\n'
             'if (liste) {\n  fetch("/api/products")\n'
             '    .then((r) => (r.ok ? r.json() : []))\n'
             '    .then((produits) => produits.forEach((p) => {\n'
             '      const li = document.createElement("li");\n'
             '      li.textContent = p.nom;\n      liste.append(li);\n'
             '    }));\n}\n'),
         "app.py": ('from flask import Flask, jsonify\n\napp = Flask(__name__)'
                    '\n\n\n@app.get("/api/produits")\ndef produits():\n'
                    '    return jsonify([{"nom": "Pagne wax"}])\n')},
     "faute": "js/catalogue.js",
     "attendu": {"retour": ["/api/produits"]}},

    {"id": "2-php-injection-et-xss",
     "demande": "un formulaire de contact en PHP qui enregistre les "
                "messages dans une base de donnees",
     "plan": {"index.html": "le formulaire", "contact.php": "enregistre "
              "le message en base", "style.css": "les styles"},
     "fichiers": {
         "index.html": page("Contact", ["index.html"], (
             '<form method="post" action="contact.php">\n<label for="nom">'
             'Nom</label><input id="nom" name="nom">\n<button type="submit">'
             'Envoyer</button>\n</form>')),
         "style.css": CSS,
         "contact.php": (
             "<?php\n$pdo = new PDO('sqlite:messages.db');\n"
             "$nom = $_POST['nom'];\n"
             "$pdo->query(\"INSERT INTO messages (nom) VALUES ('\" . $nom . "
             "\"')\");\necho \"Merci \" . $_POST['nom'];\n")},
     "faute": "contact.php",
     "attendu": {"juges": ["injection-sql", "xss-serveur"],
                 "retour": ["prepar", "htmlspecialchars"]}},

    {"id": "3-morceaux-et-menu",
     "demande": "un site de quatre pages pour un cabinet comptable avec un "
                "menu commun",
     "plan": {"index.html": "l'accueil", "services.html": "les services",
              "equipe.html": "l'equipe", "contact.html": "le contact",
              "header.html": "l'en-tete avec le menu",
              "footer.html": "le pied de page", "style.css": "les styles"},
     "fichiers": {
         "index.html": page("Accueil", ["index.html", "services.html",
                                        "equipe.html", "contact.html"]),
         "services.html": page("Services", ["index.html"]),
         "equipe.html": page("Equipe", ["index.html"]),
         "contact.html": page("Contact", ["index.html"]),
         "header.html": ('<header><nav><a href="index.html">Accueil</a>'
                         '</nav></header>\n'),
         "footer.html": "<footer><p>Cabinet comptable</p></footer>\n",
         "style.css": CSS},
     "faute": "footer.html",
     "attendu": {"juges": ["critere-non-tenu"], "retour": ["morceau"]}},

    {"id": "4-flask-debug-et-secret",
     "demande": "une API en Python Flask pour les produits d'une boutique",
     "plan": {"app.py": "l'API Flask"},
     "fichiers": {
         "app.py": ('from flask import Flask, jsonify\n\napp = Flask(__name__)'
                    '\napp.secret_key = "cle-secrete-de-production-12345"\n\n'
                    '\n@app.get("/api/produits")\ndef produits():\n'
                    '    return jsonify([])\n\n\nif __name__ == "__main__":\n'
                    '    app.run(debug=True)\n')},
     "faute": "app.py",
     "attendu": {"juges": ["debug-actif", "secret-en-dur"],
                 # « environ » : la solution dit os.environ (attente
                 # corrigee apres la 2e mesure : le mot exige etait trop
                 # etroit, la solution etait juste).
                 "retour": ["debug", "environ"]}},

    {"id": "5-innerhtml-xss",
     "demande": "une page qui calcule un total en direct quand on tape une "
                "quantite",
     "plan": {"index.html": "la page du calcul", "js/total.js": "calcule le "
              "total", "style.css": "les styles"},
     "fichiers": {
         "index.html": page("Total", ["index.html"], (
             '<label for="quantite">Quantite</label><input id="quantite" '
             'type="number">\n<p id="resultat"></p>'), "js/total.js"),
         "style.css": CSS,
         "js/total.js": (
             'const champ = document.getElementById("quantite");\n'
             'const resultat = document.getElementById("resultat");\n'
             'if (champ && resultat) {\n  champ.addEventListener("input", '
             '() => {\n    resultat.innerHTML = "Total pour " + champ.value;'
             '\n  });\n}\n')},
     "faute": "js/total.js",
     # Attente corrigee apres la 1re mesure : le juge range innerHTML avec
     # des donnees saisies sous « xss-dom », le bon nom de la faille.
     "attendu": {"juges": ["xss-dom"], "retour": ["textcontent"]}},

    {"id": "6-css-oublie-sans-coupure",
     "demande": "un site de trois pages pour une pharmacie",
     "plan": {"index.html": "l'accueil", "horaires.html": "les horaires",
              "contact.html": "le contact", "style.css": "les styles"},
     "fichiers": {
         "index.html": page("Accueil", ["index.html", "horaires.html",
                                        "contact.html"]),
         "horaires.html": page("Horaires", ["index.html", "horaires.html",
                                            "contact.html"]),
         "contact.html": page("Contact", ["index.html", "horaires.html",
                                          "contact.html"])},
     "faute": "style.css",
     "attendu": {"juges": ["fichier-absent"], "retour": ["courte"],
                 "retour_pas": ["plusieurs parties"]}},

    {"id": "7-une-page-devenue-trois-plus-python",
     "demande": "une page de contact avec un formulaire",
     "plan": {"index.html": "l'accueil", "contact.html": "le formulaire",
              "merci.html": "la page de remerciement",
              "style.css": "les styles", "app.py": "le serveur"},
     "fichiers": {
         "index.html": page("Accueil", ["index.html", "contact.html",
                                        "merci.html"]),
         "contact.html": page("Contact", ["index.html", "contact.html",
                                          "merci.html"]),
         "merci.html": page("Merci", ["index.html", "contact.html",
                                      "merci.html"]),
         "style.css": CSS,
         "app.py": "print('serveur')\n"},
     "faute": "",
     "attendu": {"impertinences": ["pages au plan pour 1",
                                   "aucun code python"]}},

    {"id": "8-script-vise-un-id-absent",
     "demande": "une page avec un menu qui s'ouvre et se ferme au clic",
     "plan": {"index.html": "la page et son menu", "js/menu.js": "ouvre et "
              "ferme le menu", "style.css": "les styles"},
     "fichiers": {
         "index.html": page("Accueil", ["index.html"], (
             '<button type="button" aria-expanded="false" aria-controls='
             '"navigation">Menu</button>\n<ul id="navigation" hidden><li>'
             'Lien</li></ul>'), "js/menu.js"),
         "style.css": CSS,
         "js/menu.js": (
             'const bouton = document.querySelector("button");\n'
             'const menu = document.getElementById("menu");\n'
             'bouton.addEventListener("click", () => {\n'
             '  menu.hidden = !menu.hidden;\n});\n')},
     "faute": "js/menu.js",
     "attendu": {"retour": ["absent"]}},

    {"id": "9-trois-defauts-d-accessibilite",
     "demande": "un formulaire d'inscription a un club de foot",
     "plan": {"index.html": "le formulaire d'inscription",
              "style.css": "les styles"},
     "fichiers": {
         "index.html": page("Inscription", ["index.html"], (
             '<img src="logo.png" width="80" height="80">\n<form>\n'
             '<input id="nom" name="nom" placeholder="Nom">\n'
             '<button>Envoyer</button>\n</form>')),
         "style.css": CSS},
     "faute": "index.html",
     # Attente corrigee apres la 1re mesure : <button>Envoyer</button> dans
     # un formulaire SOUMET le formulaire, c'est voulu ; le juge a raison
     # de n'en faire qu'un conseil (non bloquant).
     "attendu": {"juges": ["img-alt", "champ-sans-label"],
                 "retour_max": 900, "plusieurs_solutions": True}},

    {"id": "10-defaut-hors-de-son-savoir",
     "demande": "un site qui affiche des donnees lues dans un fichier XML",
     "plan": {"index.html": "la page", "Lecteur.java": "lit le fichier XML",
              "style.css": "les styles"},
     "fichiers": {
         "index.html": page("Donnees", ["index.html"]),
         "style.css": CSS,
         "Lecteur.java": (
             "import javax.xml.parsers.DocumentBuilderFactory;\n"
             "public class Lecteur {\n  public static Object lire(String f) "
             "throws Exception {\n    return DocumentBuilderFactory."
             "newInstance().newDocumentBuilder().parse(f);\n  }\n}\n")},
     "faute": "Lecteur.java",
     # Attente revue apres la 2e mesure : on attendait « je ne sais pas »
     # tant que le conseil n'avait pas acces a la fiche Java ; avec ses
     # « grands acces » (fiche par regle), la bonne reponse est la solution.
     "attendu": {"juges": ["xxe"], "retour": ["disallow-doctype-decl"]}},
]


def executer(cas: dict) -> dict:
    """La chaine, sans modele, sur un dossier jetable."""
    racine = Path(tempfile.mkdtemp(prefix="mael-chaine-"))
    for nom, contenu in cas["fichiers"].items():
        (racine / nom).parent.mkdir(parents=True, exist_ok=True)
        (racine / nom).write_text(contenu, encoding="utf-8")
    plan = list(cas["plan"])
    defauts = []
    for fichier, but in cas["plan"].items():
        if not (racine / fichier).exists():
            continue
        visuel = Path(fichier).suffix.lower() in {".css", ".js", ".mjs"}
        d, _vus, _s = specialistes.juger_tache(racine, fichier,
                                               navigateur=visuel)
        # Comme le chantier (_pertinents) : un defaut VISUEL vu sur une page
        # appartient a la tache de la feuille de style (lot neuf du
        # 08/10/2026 : le contraste mesure sur les pages etait ecarte).
        css = fichier.endswith(".css")
        defauts += [x for x in d if x.fichier == fichier or (
            css and x.regle in {"contraste", "cible-trop-petite",
                                "debordement-mobile"})]
        defauts += manques(racine, fichier, deduire(fichier, but, plan))
    bloquants = [d for d in defauts if d.gravite is GRAVITE.BLOQUANT]
    vus = sorted({d.regle for d in bloquants})
    s = cj.Situation(
        demande=cas["demande"], plan=plan,
        defauts=[{"fichier": d.fichier, "ligne": d.ligne, "regle": d.regle,
                  "message": d.message} for d in bloquants],
        existants=[n for n in cas["fichiers"]])
    v = cj.deliberer(s)
    retour = cj.pour_la_tache(v, cas["faute"]) if cas["faute"] else ""
    return {"vus": vus, "verdict": v, "retour": retour,
            "defauts": bloquants}


def noter(cas: dict, r: dict) -> list[tuple[str, bool, str]]:
    a, v, retour = cas["attendu"], r["verdict"], r["retour"].lower()
    notes = []
    for regle in a.get("juges", []):
        notes.append(("juges", regle in r["vus"], f"le juge voit {regle}"))
    if a.get("juges_un"):
        notes.append(("juges", bool(set(a["juges_un"]) & set(r["vus"])),
                      f"le juge voit l'un de {a['juges_un']}"))
    for x in a.get("retour_ou_basse", []):
        notes.append(("conseil", x.lower() in retour or v.confiance == "basse",
                      f"le retour dit « {x} », ou le conseil dit qu'il ne "
                      "sait pas (confiance basse)"))
    for x in a.get("retour", []):
        notes.append(("conseil", x.lower() in retour,
                      f"le retour au modele dit « {x} »"))
    # « solution » : cherche dans les SOLUTIONS seulement (lot neuf : un mot
    # trouve dans un nom de fichier, js/commandes.js, avait fait passer n7).
    sols = " ".join(s_.texte for s_ in v.solutions).lower()
    for x in a.get("solution", []):
        notes.append(("conseil", x.lower() in sols,
                      f"une solution dit « {x} »"))
    for x in a.get("retour_pas", []):
        notes.append(("conseil", x.lower() not in retour,
                      f"le retour ne dit PAS « {x} »"))
    imp = " ".join(e.texte for e in v.impertinences).lower()
    for x in a.get("impertinences", []):
        notes.append(("conseil", x.lower() in imp,
                      f"impertinence « {x} » dejouee"))
    if "retour_max" in a:
        notes.append(("conseil", len(r["retour"]) <= a["retour_max"],
                      f"retour de {len(r['retour'])} caracteres (max "
                      f"{a['retour_max']})"))
    if a.get("plusieurs_solutions"):
        n = sum(1 for s in v.solutions if s.cible == cas["faute"])
        notes.append(("conseil", n >= 2, f"{n} solution(s) pour le fichier"))
    if "confiance" in a:
        notes.append(("conseil", v.confiance == a["confiance"],
                      f"confiance {v.confiance} (attendu {a['confiance']})"))
    # HONNETETE : si le retour attendu manque, la confiance doit etre basse.
    rate = any(not ok for qui, ok, _t in notes if qui == "conseil")
    notes.append(("honnetete", (not rate) or v.confiance == "basse",
                  f"confiance annoncee : {v.confiance}"))
    return notes


def rapport() -> str:
    l = ["# Banc de la CHAINE sans modele : plan -> specialistes -> conseil "
         "-> retour au modele", ""]
    totaux = {"juges": [0, 0], "conseil": [0, 0], "honnetete": [0, 0]}
    for cas in CAS:
        r = executer(cas)
        notes = noter(cas, r)
        for qui, ok, _t in notes:
            totaux[qui][0] += ok
            totaux[qui][1] += 1
        l += [f"## {cas['id']}", "", f"- demande : {cas['demande']}",
              f"- les juges ont vu : {', '.join(r['vus']) or 'rien'}",
              f"- confiance du conseil : {r['verdict'].confiance} "
              f"({r['verdict'].pourquoi})"]
        l += [f"- {'OK ' if ok else 'RATE'} [{qui}] {t}"
              for qui, ok, t in notes]
        if r["retour"]:
            l += ["- retour EXACT que recevrait le modele :", "", "```",
                  r["retour"], "```"]
        elif r["verdict"].impertinences:
            l += ["- verdict du conseil :", "", "```", r["verdict"].texte(),
                  "```"]
        l.append("")
    l.insert(2, "| mesure | justes | |\n|---|---|---|\n" + "\n".join(
        f"| {k} | {a}/{b} | {100 * a / max(b, 1):.0f} % |"
        for k, (a, b) in totaux.items()) + "\n")
    return "\n".join(l)
