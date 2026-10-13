"""Tests de l'atelier de code : juges, extraction, espace, boucle, savoir.

Aucun modele, aucun reseau : le moteur est un faux qui rend des reponses
ecrites d'avance. Le banc de pieges suit la regle du doc 15 : pour chaque
regle, un exemple FAUTIF (doit etre vu) et un exemple JUSTE (ne doit pas
l'etre) — zero faux positif exige.
    ./venv/Scripts/python.exe -m pytest brain/tests_codage.py -q
"""
import re
import sys
from pathlib import Path

import pytest

from brain.codage import GRAVITE, juger_fichier, juges, savoir
from brain.codage.atelier import Atelier, message_correction, rendre_bilan
from brain.codage.espace import CheminRefuse, Espace
from brain.codage.extraction import extraire
from brain.codage.remedes import REMEDES


@pytest.fixture(autouse=True)
def _sans_outils_externes(monkeypatch):
    """Les tests jugent NOS juges : la couche 5 depend de ce qui est
    installe sur la machine. Elle a ses propres tests (lire_*, fusionner)."""
    monkeypatch.setenv("MAEL_SANS_OUTILS", "1")
    monkeypatch.setenv("MAEL_SANS_NAVIGATEUR", "1")
    monkeypatch.setenv("MAEL_SANS_EXECUTION", "1")
    # Le conseil des professeurs prend un appel au modele : les tests qui le
    # visent l'activent eux-memes.
    monkeypatch.setenv("MAEL_SANS_PROFESSEURS", "1")

PAGE_JUSTE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Accueil</title>
</head>
<body>
<main>
<h1>Bienvenue</h1>
<img src="data:image/png;base64,AAAA" alt="">
<label for="c">Courriel</label><input id="c" type="email">
<a href="https://exemple.fr" target="_blank" rel="noopener">Exemple</a>
<button type="button" id="ouvrir">Ouvrir</button>
</main>
<script>const el = document.querySelector("h1"); el.textContent = "ok";
const ouvrir = document.getElementById("ouvrir");
if (ouvrir) ouvrir.addEventListener("click", () => { el.textContent = "ouvert"; });</script>
</body>
</html>
"""


def regles(nom, texte, dossier=None):
    return {d.regle for d in juger_fichier(nom, texte, dossier)
            if d.gravite is GRAVITE.BLOQUANT}


# ------------------------------------------------------- banc de pieges
def test_page_juste_aucun_bloquant():
    assert regles("index.html", PAGE_JUSTE) == set()


PIEGES = [
    # (regle, fautif, juste) — le juste ne doit PAS declencher la regle
    ("img-alt", '<img src="a.png">', '<img src="a.png" alt="">'),
    ("champ-sans-label", '<input type="text" placeholder="nom">',
     '<label>Nom <input type="text"></label>'),
    ("champ-sans-label", '<input id="n" type="text">',
     '<input type="text" aria-label="Nom">'),
    ("nom-accessible", '<a href="#x"></a>', '<a href="#x">Aller</a>'),
    ("nom-accessible", '<button type="button"></button>',
     '<button type="button"><img src="i.svg" alt="Fermer"></button>'),
    ("href-javascript", '<a href="javascript:go()">Go</a>',
     '<a href="#go">Go</a>'),
    ("contenu-mixte", '<script src="http://cdn.x/a.js"></script>',
     '<script src="https://cdn.x/a.js" integrity="sha384-x"></script>'),
    ("id-duplique", '<p id="a">1</p><p id="a">2</p>',
     '<p id="a">1</p><p id="b">2</p>'),
    ("balise-non-fermee", "<div><span>x</div>", "<div><span>x</span></div>"),
    ("fermeture-orpheline", "<p>x</p></section>", "<section><p>x</p></section>"),
    ("mdp-en-get", '<form><label for="m">M</label>'
     '<input id="m" type="password"></form>',
     '<form method="post"><label for="m">M</label>'
     '<input id="m" type="password"></form>'),
    ("innerhtml", "<script>el.innerHTML = nom;</script>",
     "<script>el.innerHTML = '';</script>"),
    ("js-dangereux", "<script>eval(x)</script>",
     "<script>JSON.parse(x)</script>"),
]


@pytest.mark.parametrize("regle,fautif,juste", PIEGES)
def test_piege_html(regle, fautif, juste):
    assert regle in regles("f.html", fautif), f"{regle} non vu : {fautif}"
    assert regle not in regles("f.html", juste), f"faux positif : {juste}"


PIEGES_PY = [
    ("injection-sql", 'cur.execute(f"SELECT * FROM t WHERE id={i}")',
     'cur.execute("SELECT * FROM t WHERE id = ?", (i,))'),
    ("injection-sql", 'cur.execute("SELECT * FROM t WHERE n=\'%s\'" % n)',
     'cur.execute("SELECT * FROM t WHERE n = %s", (n,))'),
    ("py-dangereux", "subprocess.run(cmd, shell=True)",
     'subprocess.run(["ls", d], check=True)'),
    ("py-dangereux", "data = yaml.load(f)", "data = yaml.safe_load(f)"),
    ("py-dangereux", "requests.get(u, verify=False)", "requests.get(u)"),
    ("secret-en-dur", 'API_KEY = "a8f5f167f44f4964"',
     'API_KEY = os.environ["API_KEY"]'),
    ("py-syntaxe", "def f(:\n    pass", "def f():\n    pass"),
    ("code-inacheve", "def f():\n    # ... reste du code\n    pass",
     "def f():\n    # calcule le total\n    pass"),
]


@pytest.mark.parametrize("regle,fautif,juste", PIEGES_PY)
def test_piege_python(regle, fautif, juste):
    assert regle in regles("a.py", fautif), f"{regle} non vu : {fautif}"
    assert regle not in regles("a.py", juste), f"faux positif : {juste}"


def test_secret_factice_pas_signale():
    assert "secret-en-dur" not in regles(
        "a.py", 'password = "changeme_example"')


def test_css():
    assert "css-accolade" in regles("s.css", "a { color: red;")
    assert regles("s.css", "a { color: red; }") == set()
    assert "focus-invisible" in regles("s.css", "a:focus { outline: none; }")
    assert "focus-invisible" not in regles(
        "s.css", "a:focus { outline: none; } a:focus-visible "
                 "{ outline: 2px solid; }")


def test_fichier_reference_absent(tmp_path):
    (tmp_path / "style.css").write_text("a{}")
    html = '<link rel="stylesheet" href="style.css"><img src="x.png" alt="">'
    r = regles("i.html", html, dossier=tmp_path)
    assert "fichier-absent" in r
    defauts = [d for d in juger_fichier("i.html", html, tmp_path)
               if d.regle == "fichier-absent"]
    assert len(defauts) == 1 and "x.png" in defauts[0].message


def test_chaque_regle_bloquante_a_un_remede():
    """Un defaut sans remede fait tourner la boucle a vide."""
    vues = {r for r, _, _ in PIEGES + PIEGES_PY}
    assert vues <= set(REMEDES)


# ------------------------------------------------------------ extraction
def test_extraction_formes():
    texte = """Voici :
```html fichier=index.html
<p>a</p>
```
**css/style.css**
```css
a{}
```
```js:js/app.js
let a = 1;
```
```python
# outil.py
print(1)
```
```bash
ls -la
```"""
    e = extraire(texte)
    assert set(e.fichiers) == {"index.html", "css/style.css", "js/app.js",
                               "outil.py"}


def test_extraction_anonymes_ambigus():
    e = extraire("```html\n<p>1</p>\n```\n```html\n<p>2</p>\n```")
    assert list(e.fichiers) == ["index.html"]
    assert e.ambiguites


# ---------------------------------------------------------------- espace
@pytest.mark.parametrize("chemin", ["../x.html", "/etc/passwd",
                                    "C:/Windows/x", "a/../../b",
                                    ".git/config", ".env", ""])
def test_espace_refuse(tmp_path, chemin):
    with pytest.raises(CheminRefuse):
        Espace(tmp_path).chemin(chemin)


def test_espace_sauvegarde_avant_ecraser(tmp_path):
    e = Espace(tmp_path)
    e.ecrire("a.html", "v1")
    e.ecrire("a.html", "v2")
    e.ecrire("a.html", "v3")
    copies = list((tmp_path / ".mael" / "sauvegardes").rglob("a.html"))
    assert len(copies) == 1 and copies[0].read_text() == "v1\n"
    assert (tmp_path / "a.html").read_text() == "v3\n"


# ---------------------------------------------------------------- boucle
class FauxMoteur:
    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.recus = []

    def completer(self, *, systeme, messages, role_modele):
        from brain.backends.base import Reponse
        self.recus.append(list(messages))
        return Reponse(texte=self.reponses.pop(0), donnees=None,
                       appels_outils=[], modele="faux")


def bloc(nom, contenu):
    return f"```html fichier={nom}\n{contenu}\n```"


def test_boucle_corrige_puis_conforme(tmp_path):
    fautif = PAGE_JUSTE.replace(' alt=""', "")
    moteur = FauxMoteur([bloc("index.html", fautif),
                         "Corrige.\n" + bloc("index.html", PAGE_JUSTE)])
    bilan = Atelier(moteur, Espace(tmp_path)).ecrire("une page")
    assert bilan.conforme
    assert [t.bloquants for t in bilan.tours] == [1, 0]
    retour = moteur.recus[1][-1]["content"]
    assert "img" in retour and "forme juste" in retour   # remede transmis


def test_boucle_arrete_si_pas_de_progres(tmp_path):
    fautif = PAGE_JUSTE.replace(' alt=""', "")
    moteur = FauxMoteur([bloc("index.html", fautif)] * 3)
    bilan = Atelier(moteur, Espace(tmp_path)).ecrire("une page")
    assert not bilan.conforme
    assert len(bilan.tours) == 2 and "progresse" in bilan.arret


def test_boucle_refuse_chemin_hors_espace(tmp_path):
    moteur = FauxMoteur([bloc("../evasion.html", PAGE_JUSTE)])
    bilan = Atelier(moteur, Espace(tmp_path / "e")).ecrire("x")
    assert not (tmp_path / "evasion.html").exists()
    assert bilan.tours[0].refus and not bilan.conforme


def test_relire_sans_modele(tmp_path):
    (tmp_path / "index.html").write_text('<img src="a.png">')
    bilan = Atelier(None, Espace(tmp_path)).relire()
    assert {d.regle for d in bilan.bloquants} >= {"img-alt"}


def test_message_correction_borne():
    from brain.codage.juges import Defaut
    defauts = [Defaut("a.html", i, "img-alt", GRAVITE.BLOQUANT, "x", "n")
               for i in range(30)]
    m = message_correction(defauts)
    assert "+ 18 autre(s)" in m


# ----------------------------------------------------------------- savoir
@pytest.mark.parametrize("g", savoir.tous(), ids=lambda g: g.fichier)
def test_gabarit_passe_tous_les_juges(g):
    """Regle d'entree du savoir : un gabarit faux enseignerait la faute.
    AUCUN defaut, meme un conseil : c'est la forme a imiter."""
    defauts = juger_fichier(g.fichier, g.texte())
    assert defauts == [], "\n".join(map(str, defauts))


def test_index_et_dossier_concordent():
    """Pas de gabarit fantome dans l'index, pas de gabarit oublie hors index."""
    indexes = {g.fichier for g in savoir.tous()}
    sur_disque = {p.name for p in savoir.DOSSIER_GABARITS.iterdir()
                  if p.is_file() and p.name != "index.yaml"}
    assert indexes == sur_disque
    assert len(indexes) == 41


@pytest.mark.parametrize("g", savoir.tous(), ids=lambda g: g.fichier)
def test_gabarit_court(g):
    """Un gabarit doit tenir seul dans le budget, et dans celui d'une
    correction s'il est rattache a des regles."""
    assert len(g.texte()) <= savoir.BUDGET_CARACTERES
    if g.regles:
        assert len(g.texte()) <= savoir.BUDGET_CORRECTION, g.fichier


def test_regles_de_l_index_existent():
    """Une regle mal orthographiee dans l'index ne serait jamais servie."""
    from brain.codage.remedes import REMEDES
    connues = set(REMEDES) | {"h1", "main", "titres-sautes", "important"}
    for g in savoir.tous():
        assert set(g.regles) <= connues, (g.fichier, set(g.regles) - connues)


def test_savoir_choisit_et_respecte_le_budget():
    t = savoir.pour_prompt("un site vitrine avec formulaire de contact")
    assert "page.html" in t and "formulaire.html" in t
    assert len(t) < savoir.BUDGET_CARACTERES + 300
    assert savoir.pour_prompt("bonjour") == ""


@pytest.mark.parametrize("demande,attendu", [
    ("je veux m'inscrire sur le site", "inscription.html"),
    ("une API Express avec PostgreSQL", "express-route.js"),
    ("envoyer des photos sur mon serveur flask", "flask-televersement.py"),
    ("integrer le paiement dans une iframe", "message-fenetres.js"),
    ("afficher les resultats de recherche", "afficher-donnees.js"),
    ("des pages qui marchent sur telephone", "mise-en-page.css"),
])
def test_savoir_trouve_le_bon_gabarit(demande, attendu):
    assert attendu in [g.fichier for g in savoir.choisir(demande)]


def test_racine_sans_faux_rapprochement():
    assert not savoir._touche("formation", "formulaire")
    assert not savoir._touche("apiculteur", "api")
    assert savoir._touche("inscrire", "inscription")
    assert savoir._touche("pages", "page")


def test_correction_joint_la_forme_juste():
    from brain.codage.juges import Defaut
    m = message_correction([Defaut("i.html", 3, "champ-sans-label",
                                   GRAVITE.BLOQUANT, "x", "n")])
    assert "[savoir] forme juste complete" in m and "<label for=" in m


# ------------------------------------------- couches 3 et 4 (arbre, flux)
FLASK = "from flask import Flask, request, redirect\nimport sqlite3, subprocess, os\napp = Flask(__name__)\n"

PIEGES_FLUX = [
    # (regle, fautif, juste) — chacun dans une vraie route Flask
    ("injection-sql",
     "@app.route('/u')\ndef u():\n    i = request.args.get('id')\n"
     "    q = 'SELECT * FROM u WHERE id=' + i\n    return db.execute(q)",
     "@app.route('/u')\ndef u():\n    i = request.args.get('id')\n"
     "    return db.execute('SELECT * FROM u WHERE id = ?', (i,))"),
    ("injection-commande",
     "@app.route('/p')\ndef p():\n    h = request.form['hote']\n"
     "    return subprocess.check_output('ping -c1 ' + h, shell=True)",
     "@app.route('/p')\ndef p():\n    h = request.form['hote']\n"
     "    return subprocess.check_output(['ping', '-c1', '--', "
     "str(ipaddress.ip_address(h))])"),
    ("traversee-chemin",
     "@app.route('/f/<nom>')\ndef f(nom):\n    return open('/srv/' + nom).read()",
     "@app.route('/f/<nom>')\ndef f(nom):\n"
     "    return open('/srv/' + secure_filename(nom)).read()"),
    ("redirection-ouverte",
     "@app.route('/r')\ndef r():\n    return redirect(request.args['suite'])",
     "@app.route('/r')\ndef r():\n    return redirect('/accueil')"),
    ("injection-code",
     "@app.route('/c')\ndef c():\n    return str(eval(request.json['x']))",
     "@app.route('/c')\ndef c():\n    return str(int(request.json['x']))"),
    ("xss-serveur",
     "@app.route('/b')\ndef b():\n    n = request.args.get('n', '')\n"
     "    return render_template_string(f'<p>Bonjour {n}</p>')",
     "@app.route('/b')\ndef b():\n    n = request.args.get('n', '')\n"
     "    return render_template_string('<p>Bonjour {{ n }}</p>', n=n)"),
    ("ssrf",
     "@app.route('/s')\ndef s():\n    return requests.get(request.args['url']).text",
     "@app.route('/s')\ndef s():\n    return requests.get('https://api.exemple.fr/m').text"),
]


@pytest.mark.parametrize("regle,fautif,juste", PIEGES_FLUX)
def test_piege_contamination(regle, fautif, juste):
    assert regle in regles("app.py", FLASK + fautif), f"{regle} non vu"
    assert regle not in regles("app.py", FLASK + juste), "faux positif"


def test_contamination_cite_les_deux_lignes():
    code = FLASK + PIEGES_FLUX[0][1]
    d = next(x for x in juger_fichier("app.py", code)
             if x.regle == "injection-sql")
    assert "entree ligne 6" in d.message and d.ligne == 8


def test_contamination_traverse_les_variables():
    code = ("import os\n"
            "a = input()\nb = a.strip()\nc = f'ls {b}'\nd = [c]\n"
            "os.system(d[0])\n")
    assert "injection-commande" in regles("x.py", code)


def test_reassignation_propre_decontamine():
    code = "import os\na = input()\na = 'fixe'\nos.system(a)\n"
    r = regles("x.py", code)
    assert "injection-commande" not in r
    # os.system reste deconseille, mais n'est plus une injection
    assert "py-dangereux" in r


@pytest.mark.parametrize("code", [
    "# on n'utilise jamais eval(x) ici\nx = 1\n",
    "aide = 'evitez subprocess.run(c, shell=True)'\n",
    'doc = """cur.execute(f"SELECT {x}")"""\n',
])
def test_arbre_ignore_commentaires_et_chaines(code):
    assert regles("x.py", code) == set()


@pytest.mark.parametrize("code", [
    "from os import system as s\ns(cmd)\n",
    "import subprocess as sp\nsp.run(cmd, shell=True)\n",
    "import os\ngetattr(os, 'system')(cmd)\n",
    "from pickle import loads\nloads(donnee)\n",
])
def test_arbre_voit_les_formes_deguisees(code):
    assert "py-dangereux" in regles("x.py", code)


def test_hasard_faible_pour_un_secret():
    assert "hasard-faible" in regles(
        "x.py", "import random\ntoken = ''.join(random.choices('ab', k=32))\n")
    assert "hasard-faible" not in regles(
        "x.py", "import random\nde = random.randint(1, 6)\n")


def test_variable_sql_montee_avant():
    code = "q = 'SELECT * FROM t WHERE n=%s' % n\ncur.execute(q)\n"
    assert "injection-sql" in regles("x.py", code)
    juste = "q = 'SELECT * FROM t WHERE n=%s'\ncur.execute(q, (n,))\n"
    assert "injection-sql" not in regles("x.py", juste)


def test_eval_litteral_n_est_qu_un_conseil():
    d = juger_fichier("x.py", "x = eval('1 + 1')\n")
    assert d and all(x.gravite is GRAVITE.CONSEIL for x in d
                     if x.regle == "py-dangereux")


def test_remedes_couches_3_4():
    vues = {r for r, _, _ in PIEGES_FLUX} | {"hasard-faible"}
    assert vues <= set(REMEDES)


def test_hasard_faible_mot_entier():
    for nom in ("selection", "cycle", "monkey"):
        assert "hasard-faible" not in regles(
            "x.py", f"import random\n{nom} = random.choice(l)\n"), nom
    for nom in ("api_token", "mot_de_passe", "sel", "reset_key"):
        assert "hasard-faible" in regles(
            "x.py", f"import random\n{nom} = random.random()\n"), nom


# --------------------------------------------- couches 3 et 4 : JavaScript
from brain.codage import analyse_js

js_requis = pytest.mark.skipif(not analyse_js.disponible(),
                               reason="node ou acorn absent")

PIEGES_JS = [
    ("xss-dom",
     "const q = new URLSearchParams(location.search).get('q');\n"
     "document.querySelector('#r').innerHTML = `Resultat : ${q}`;",
     "const q = new URLSearchParams(location.search).get('q');\n"
     "document.querySelector('#r').textContent = `Resultat : ${q}`;"),
    ("xss-dom",
     "const champ = document.getElementById('nom');\n"
     "const n = champ.value.trim();\nzone.insertAdjacentHTML('beforeend', n);",
     "const champ = document.getElementById('nom');\n"
     "const n = champ.value.trim();\nzone.append(n);"),
    ("redirection-ouverte",
     "const suite = location.hash.slice(1);\nlocation.href = suite;",
     "location.href = '/accueil';"),
    ("injection-code",
     "const f = location.hash.slice(1);\nsetTimeout('go(' + f + ')', 10);",
     "setTimeout(() => go(), 10);"),
    ("injection-commande",
     "const { exec } = require('child_process');\n"
     "app.get('/p', (req, res) => exec('ping ' + req.query.h));",
     "const { execFile } = require('child_process');\n"
     "app.get('/p', (req, res) => execFile('ping', ['-c1', String(Number(req.query.h))]));"),
    ("injection-sql",
     "app.get('/u', async (req, res) => {\n"
     "  const r = await db.query(`SELECT * FROM u WHERE id = ${req.params.id}`);\n"
     "  res.json(r);\n});",
     "app.get('/u', async (req, res) => {\n"
     "  const r = await db.query('SELECT * FROM u WHERE id = $1', [req.params.id]);\n"
     "  res.json(r);\n});"),
    ("traversee-chemin",
     "app.get('/f', (req, res) => res.sendFile(req.query.f));",
     "app.get('/f', (req, res) => res.sendFile(path.basename(req.query.f), "
     "{ root: '/srv' }));"),
    ("xss-serveur",
     "app.get('/b', (req, res) => res.send(`<p>Bonjour ${req.query.n}</p>`));",
     "app.get('/b', (req, res) => res.send({ bonjour: req.query.n }));"),
    ("message-sans-origine",
     "window.addEventListener('message', (e) => { afficher(e.data); });",
     "window.addEventListener('message', (e) => {\n"
     "  if (e.origin !== 'https://a.fr') return; afficher(e.data); });"),
    ("hasard-faible",
     "const resetToken = Math.random().toString(36).slice(2);",
     "const resetToken = crypto.randomUUID();"),
]


@js_requis
@pytest.mark.parametrize("regle,fautif,juste", PIEGES_JS)
def test_piege_js(regle, fautif, juste):
    assert regle in regles("app.js", fautif), f"{regle} non vu"
    assert regle not in regles("app.js", juste), "faux positif"


@js_requis
@pytest.mark.parametrize("code", [
    "// el.innerHTML = location.hash; ne jamais faire ca\nconst a = 1;",
    "const aide = 'evitez eval(x) et document.write(y)';",
])
def test_js_ignore_commentaires_et_chaines(code):
    assert regles("a.js", code) == set()


@js_requis
def test_js_alias_require_et_import():
    assert "js-dangereux" in regles(
        "a.js", "const cp = require('node:child_process');\ncp.exec(cmd);")
    assert "js-dangereux" in regles(
        "a.mjs", "import { exec as lancer } from 'node:child_process';\n"
                 "lancer(cmd);")


@js_requis
def test_js_syntaxe_ligne_exacte():
    d = juger_fichier("a.js", "const a = 1;\nconst b = ;\n")
    assert [(x.regle, x.ligne) for x in d] == [("js-syntaxe", 2)]


@js_requis
def test_js_contamination_cite_les_deux_lignes():
    d = next(x for x in juger_fichier("a.js", PIEGES_JS[0][1])
             if x.regle == "xss-dom")
    assert "entree ligne 1" in d.message and d.ligne == 2


@js_requis
def test_js_dans_html_garde_les_bonnes_lignes():
    page = ("<p>x</p>\n<script>\nconst q = location.hash;\n"
            "document.body.innerHTML = q;\n</script>\n")
    d = next(x for x in juger_fichier("p.html", page) if x.regle == "xss-dom")
    assert d.ligne == 4


def test_js_sans_analyseur_retombe_sur_les_motifs(monkeypatch):
    """Juge en panne != « rien a signaler »."""
    monkeypatch.setattr(analyse_js, "disponible", lambda: False)
    assert "innerhtml" in regles("a.js", "el.innerHTML = nom;")


def test_remedes_js():
    vues = {r for r, _, _ in PIEGES_JS}
    assert vues <= set(REMEDES)


# ------------------------------------------- nouvelles familles (06/10)
PIEGES_DJANGO = [
    ("secret-en-dur", 'SECRET_KEY = "k8#2xq!9vz@1m"',
     'SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]'),
    ("cookie-faible", "SESSION_COOKIE_SECURE = False",
     "SESSION_COOKIE_SECURE = True"),
    ("csrf-desactive",
     "from django.views.decorators.csrf import csrf_exempt\n"
     "@csrf_exempt\ndef v(request):\n    pass",
     "def v(request):\n    pass"),
    ("xss-serveur",
     "from django.utils.safestring import mark_safe\n"
     "def v(request):\n    return mark_safe(request.GET['n'])",
     "from django.utils.html import format_html\n"
     "def v(request):\n    return format_html('<b>{}</b>', request.GET['n'])"),
    ("injection-sql",
     "def v(request):\n    return P.objects.raw("
     "f\"SELECT * FROM p WHERE c = '{request.GET['c']}'\")",
     "def v(request):\n    return P.objects.raw("
     "'SELECT * FROM p WHERE c = %s', [request.GET['c']])"),
]


@pytest.mark.parametrize("regle,fautif,juste", PIEGES_DJANGO)
def test_piege_django(regle, fautif, juste):
    assert regle in regles("views.py", fautif), f"{regle} non vu"
    assert regle not in regles("views.py", juste), "faux positif"


def test_cle_ordinaire_n_est_pas_un_secret():
    for code in ('CACHE_KEY = "produits_v2"', 'SORT_KEY = "created_at"',
                 'monkey = "abcdefghij"'):
        assert "secret-en-dur" not in regles("a.py", code), code


def test_un_secret_un_seul_defaut():
    d = [x for x in juger_fichier("a.py", 'password = "Zx81!kq9Lm"\n')
         if x.regle == "secret-en-dur"]
    assert len(d) == 1


PIEGES_REACT = [
    ("innerhtml",
     "const A = ({ h }) => <div dangerouslySetInnerHTML={{ __html: h }} />;",
     "const A = ({ h }) => <div dangerouslySetInnerHTML={{ __html: "
     "DOMPurify.sanitize(h) }} />;"),
    ("redirection-ouverte",
     "const u = new URLSearchParams(location.search).get('u');\n"
     "const A = () => <a href={u}>Suite</a>;",
     "const A = () => <a href=\"/suite\">Suite</a>;"),
    ("img-alt", "const A = () => <img src=\"a.png\" />;",
     "const A = () => <img src=\"a.png\" alt=\"\" />;"),
    ("champ-sans-label", "const A = () => <input type=\"text\" />;",
     "const A = () => <><label htmlFor=\"n\">Nom</label>"
     "<input id=\"n\" type=\"text\" /></>;"),
    ("clic-sans-clavier",
     "const A = () => <div onClick={ouvrir}>Ouvrir</div>;",
     "const A = () => <button type=\"button\" onClick={ouvrir}>Ouvrir</button>;"),
    ("nom-accessible", "const A = () => <button type=\"button\"></button>;",
     "const A = () => <button type=\"button\" aria-label=\"Fermer\"></button>;"),
]


@js_requis
@pytest.mark.parametrize("regle,fautif,juste", PIEGES_REACT)
def test_piege_react(regle, fautif, juste):
    assert regle in regles("a.jsx", fautif), f"{regle} non vu"
    assert regle not in regles("a.jsx", juste), "faux positif"


@js_requis
def test_label_apres_le_champ_compte():
    code = ("const A = () => <><input id=\"n\" type=\"text\" />"
            "<label htmlFor=\"n\">Nom</label></>;")
    assert "champ-sans-label" not in regles("a.jsx", code)


PIEGES_PHP = [
    ("injection-sql",
     "<?php\n$r = mysqli_query($db, \"SELECT * FROM u WHERE id = $id\");",
     "<?php\n$r = $pdo->prepare('SELECT * FROM u WHERE id = ?');"),
    ("injection-sql",
     "<?php\n$r = $pdo->query('SELECT * FROM u WHERE n = ' . $_GET['n']);",
     "<?php\n$r = $pdo->query('SELECT COUNT(*) FROM u');"),
    ("xss-serveur", "<?php\necho 'Bonjour ' . $_GET['nom'];",
     "<?php\necho 'Bonjour ' . htmlspecialchars($_GET['nom'], ENT_QUOTES);"),
    ("injection-commande", "<?php\nsystem('ping ' . $hote);",
     "<?php\nsystem('ping ' . escapeshellarg($hote));"),
    ("inclusion-fichier", "<?php\ninclude $_GET['page'] . '.php';",
     "<?php\ninclude __DIR__ . '/pages/accueil.php';"),
    ("redirection-ouverte", "<?php\nheader('Location: ' . $_GET['suite']);",
     "<?php\nheader('Location: /accueil');"),
    ("hash-faible", "<?php\n$h = md5($password);",
     "<?php\n$h = password_hash($password, PASSWORD_DEFAULT);"),
    ("injection-code", "<?php\neval($code);", "<?php\n$x = intval($code);"),
]


@pytest.mark.parametrize("regle,fautif,juste", PIEGES_PHP)
def test_piege_php(regle, fautif, juste):
    assert regle in regles("a.php", fautif), f"{regle} non vu"
    assert regle not in regles("a.php", juste), "faux positif"


def test_php_html_autour_ne_casse_pas_l_equilibre():
    code = "<p>L'utilisateur (voir plus bas</p>\n<?php echo 'ok'; ?>\n"
    assert "syntaxe-equilibre" not in regles("a.php", code)


def test_php_fichier_tronque():
    assert "syntaxe-equilibre" in regles(
        "a.php", "<?php\nfunction f() {\n    return 1;\n")


PIEGES_JAVA = [
    ("injection-sql",
     'ResultSet r = st.executeQuery("SELECT * FROM u WHERE id = " + id);',
     'PreparedStatement p = c.prepareStatement("SELECT * FROM u WHERE id = ?");'),
    ("injection-commande", "Runtime.getRuntime().exec(\"ping \" + hote);",
     "new ProcessBuilder(\"ping\", \"-c1\", hote).start();"),
    ("deserialisation",
     "Object o = new ObjectInputStream(entree).readObject();",
     "Commande c = mapper.readValue(entree, Commande.class);"),
    ("xxe", "DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();",
     "DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();\n"
     "f.setFeature(\"http://apache.org/xml/features/disallow-doctype-decl\", true);"),
    ("chiffrement-faible", 'Cipher c = Cipher.getInstance("AES/ECB/PKCS5Padding");',
     'Cipher c = Cipher.getInstance("AES/GCM/NoPadding");'),
    ("csrf-desactive", "http.csrf(csrf -> csrf.disable());",
     "http.csrf(Customizer.withDefaults());"),
    ("hasard-faible", "String resetToken = Long.toString(new Random().nextLong());",
     "String resetToken = Long.toString(new SecureRandom().nextLong());"),
]


@pytest.mark.parametrize("regle,fautif,juste", PIEGES_JAVA)
def test_piege_java(regle, fautif, juste):
    def envelopper(c):
        return f"class A {{\n  void f() throws Exception {{\n    {c}\n  }}\n}}\n"
    assert regle in regles("A.java", envelopper(fautif)), f"{regle} non vu"
    assert regle not in regles("A.java", envelopper(juste)), "faux positif"


def test_java_commentaire_ignore():
    code = ("class A {\n  // st.executeQuery(\"SELECT * FROM u WHERE id = \" + id);\n"
            "}\n")
    assert "injection-sql" not in regles("A.java", code)


def test_remedes_nouvelles_familles():
    vues = {r for r, _, _ in PIEGES_DJANGO + PIEGES_PHP + PIEGES_JAVA}
    vues |= {r for r, _, _ in PIEGES_REACT}
    assert vues <= set(REMEDES)


@pytest.mark.parametrize("demande,attendu", [
    ("une vue django pour voir sa commande", "django-vue.py"),
    ("un composant react qui affiche une liste", "composant-liste.jsx"),
    ("connexion en php avec session", "php-connexion.php"),
    ("lire un fichier xml en java", "java-xml.java"),
])
def test_savoir_nouvelles_familles(demande, attendu):
    assert attendu in [g.fichier for g in savoir.choisir(demande)]


# ------------------------------------------------ couche 5 (outils externes)
from brain.codage import outils


def test_lire_ruff(tmp_path):
    # chemins absolus du systeme courant (« C:/p » ne l'est pas sous Linux :
    # CI sur Linux vierge, 12/10/2026)
    a, b = (tmp_path / "app.py").as_posix(), (tmp_path / "b.py").as_posix()
    sortie = ('[{"code": "S608", "message": "Possible SQL injection", '
              f'"filename": "{a}", "location": {{"row": 7}}}},'
              f'{{"code": null, "message": "SyntaxError", "filename": "{b}",'
              ' "location": {"row": 2}}]')
    d = outils.lire_ruff(sortie, tmp_path)
    assert [(x.fichier, x.ligne, x.regle, x.gravite) for x in d] == [
        ("app.py", 7, "injection-sql", GRAVITE.BLOQUANT),
        ("b.py", 2, "py-syntaxe", GRAVITE.BLOQUANT)]
    assert d[0].sources == ("ruff",)


def test_lire_bandit_confiance_faible_n_est_qu_un_conseil():
    sortie = ('{"results": [{"filename": "a.py", "line_number": 3, '
              '"test_id": "B608", "issue_text": "sql", '
              '"issue_confidence": "LOW"}]}')
    d = outils.lire_bandit(sortie, Path("."))
    assert d[0].regle == "injection-sql" and d[0].gravite is GRAVITE.CONSEIL


def test_lire_eslint_html_validate_gitleaks_trivy():
    r = Path(".")
    assert outils.lire_eslint('[{"filePath": "a.js", "messages": [{"ruleId": '
                              'null, "line": 4, "message": "Parsing error"}]}]',
                              r)[0].regle == "js-syntaxe"
    h = outils.lire_html_validate('[{"filePath": "i.html", "messages": [{"ruleId":'
                                  ' "wcag/h37", "line": 9, "message": "alt",'
                                  ' "severity": 2}]}]', r)
    assert h[0].regle == "img-alt" and h[0].gravite is GRAVITE.BLOQUANT
    g = outils.lire_gitleaks('[{"File": "cfg.py", "StartLine": 2, '
                             '"RuleID": "generic-api-key"}]', r)
    assert g[0].regle == "secret-en-dur" and g[0].ligne == 2
    t = outils.lire_trivy('{"Results": [{"Target": "requirements.txt", '
                          '"Vulnerabilities": [{"PkgName": "django", '
                          '"InstalledVersion": "4.0", "VulnerabilityID": '
                          '"CVE-X", "Severity": "HIGH", "FixedVersion": '
                          '"4.2"}]}]}', r)
    assert t[0].gravite is GRAVITE.BLOQUANT and "4.2" in t[0].message


def test_vote_croise_rend_certain():
    from brain.codage.juges import Defaut
    m = Defaut("a.py", 7, "injection-sql", GRAVITE.BLOQUANT, "x", "n")
    e = Defaut("a.py", 8, "injection-sql", GRAVITE.BLOQUANT, "y", "ruff",
               sources=("ruff",))
    autre = Defaut("a.py", 30, "ruff:F401", GRAVITE.CONSEIL, "z", "ruff",
                   sources=("ruff",))
    r = outils.fusionner([m], [e, autre])
    assert len(r) == 2
    assert r[0].certain and r[0].sources == ("mael", "ruff")
    assert not r[1].certain
    assert "certain : mael + ruff" in str(r[0])


def test_vote_croise_exige_la_meme_famille():
    from brain.codage.juges import Defaut
    m = Defaut("a.py", 7, "injection-sql", GRAVITE.BLOQUANT, "x", "n")
    e = Defaut("a.py", 7, "secret-en-dur", GRAVITE.BLOQUANT, "y", "g",
               sources=("gitleaks",))
    r = outils.fusionner([m], [e])
    assert len(r) == 2 and not any(x.certain for x in r)


def test_outil_absent_dit_absent(monkeypatch, tmp_path):
    monkeypatch.delenv("MAEL_SANS_OUTILS")
    (tmp_path / "a.py").write_text("x = 1\n")
    monkeypatch.setattr(outils, "OUTILS", [outils.Outil(
        "fantome", "MIT", {".py"}, lambda: None,
        lambda e, r, f: [], lambda s, r: [])])
    assert outils.juger(tmp_path, ["a.py"]) == []
    assert any("fantome" in l for l in outils.limites())


def test_outil_en_panne_n_est_pas_propre(monkeypatch, tmp_path):
    monkeypatch.delenv("MAEL_SANS_OUTILS")
    (tmp_path / "a.py").write_text("x = 1\n")
    monkeypatch.setattr(outils, "OUTILS", [outils.Outil(
        "casse", "MIT", {".py"}, lambda: [sys.executable],
        lambda e, r, f: [*e, "-c", "print('pas du json')"],
        outils.lire_ruff, {0})])
    assert outils.juger(tmp_path, ["a.py"]) == []
    assert any("EN PANNE" in l and "casse" in l for l in outils.limites())


def test_sauvegardes_mael_ignorees():
    d = outils.lire_gitleaks('[{"File": ".mael/sauvegardes/x/cfg.py", '
                             '"StartLine": 1}]', Path("."))
    from brain.codage.juges import DOSSIERS_IGNORES
    assert all(set(Path(x.fichier).parts) & DOSSIERS_IGNORES for x in d)


def test_familles_pointent_vers_des_regles_connues():
    """Une famille mal orthographiee casserait le vote croise en silence."""
    connues = set(REMEDES) | {"doctype", "lang", "sri", "button-type",
                              "id-duplique", "balise-non-fermee",
                              "href-javascript", "css-accolade", ""}
    assert set(outils.FAMILLES.values()) <= connues


# ------------------------------------------------- choix par le sens
def test_pile_filtre_strict():
    """Une demande en PHP ne recoit JAMAIS un gabarit d'une autre pile serveur."""
    for g in [x for _, x, _ in savoir.classer("connexion en php avec session")]:
        assert savoir.pile_du_gabarit(g) in {"php", "html", "css", "js"}, g.fichier
    for g in [x for _, x, _ in savoir.classer("une route express pour les produits")]:
        assert savoir.pile_du_gabarit(g) in {"node", "html", "css", "js"}, g.fichier


def test_flask_accepte_les_gabarits_python_generiques():
    fichiers = [g.fichier for _, g, _ in savoir.classer(
        "requete sql dans mon application flask")]
    assert "sql.py" in fichiers
    assert not any(f.startswith(("django-", "php-", "express-")) for f in fichiers)


def test_react_ne_se_declenche_pas_sur_reactif():
    assert "react" not in savoir.piles_de("un site reactif et rapide")
    assert savoir.piles_de("une appli React") == {"react"}
    assert "java" not in savoir.piles_de("du javascript simple")


def test_synonymes_et_themes():
    assert "fichier" in savoir.themes_de(savoir._etendre("envoyer des photos"))
    assert "connexion" in savoir.themes_de("je veux me connecter avec un mot de passe")
    assert "adaptatif" in savoir.themes_de("lisible sur smartphone")


def test_diversite_des_besoins():
    choisis = [g.fichier for g in savoir.choisir(
        "un site vitrine avec une galerie de photos")]
    assert "page.html" in choisis and "galerie.html" in choisis


def test_rien_plutot_que_n_importe_quoi():
    assert savoir.choisir("bonjour, comment vas-tu ?") == []
    assert savoir.choisir("raconte-moi une histoire") == []


# ------------------------------------------- couche 6 (bac a sable)
# Lecture pure des resultats : sans navigateur, sur des sorties enregistrees.
from brain.codage import bac_a_sable

SOURCE_C6 = """<!DOCTYPE html>
<html lang="fr">
<body>
<img src="logo.png">
<p class="pale">Bienvenue</p>
<input id="courriel" type="email">
</body>
</html>
"""

AXE_ENREGISTRE = {"violations": [
    {"id": "image-alt", "impact": "critical", "help": "Images must have alt",
     "tags": ["wcag2a", "wcag111"],
     "nodes": [{"html": '<img src="logo.png">', "any": []}]},
    {"id": "color-contrast", "impact": "serious", "help": "contrast",
     "tags": ["wcag2aa", "wcag143"],
     "nodes": [{"html": '<p class="pale">', "any": [{"data": {
         "contrastRatio": 2.32, "fgColor": "#aaaaaa", "bgColor": "#ffffff",
         "expectedContrastRatio": "4.5:1"}}]}]},
    {"id": "label", "impact": "critical", "help": "Form elements must have "
     "labels", "tags": ["wcag2a", "wcag412"],
     "nodes": [{"html": '<input id="courriel" type="email">', "any": []}]},
    {"id": "regle-inconnue", "impact": "critical", "help": "?", "tags": [],
     "nodes": [{"html": "<body>", "any": []}]},
]}


def test_axe_familles_lignes_et_gravite():
    d = {x.regle: x for x in bac_a_sable.lire_axe(
        AXE_ENREGISTRE, "index.html", SOURCE_C6)}
    assert d["img-alt"].ligne == 4 and d["img-alt"].gravite == GRAVITE.BLOQUANT
    assert d["contraste"].ligne == 5 and "2.32:1" in d["contraste"].message
    assert d["contraste"].norme == "WCAG 2.2 — 1.4.3"
    assert d["champ-sans-label"].ligne == 6
    # regle inconnue de MAEL : jamais bloquante (pas de remede)
    assert d["axe:regle-inconnue"].gravite == GRAVITE.CONSEIL
    assert all(x.sources == ("axe-core",) for x in d.values())


def test_axe_ignore_les_cas_a_verifier():
    assert bac_a_sable.lire_axe({"violations": [], "incomplete": [
        {"id": "color-contrast", "nodes": [{"html": "<p>"}]}]},
        "a.html", SOURCE_C6) == []


def test_axe_et_mael_votent_ensemble():
    from brain.codage.juges import juger_fichier
    mael = juger_fichier("index.html", SOURCE_C6)
    axe = bac_a_sable.lire_axe(AXE_ENREGISTRE, "index.html", SOURCE_C6)
    r = outils.fusionner(mael, axe)
    alt = [x for x in r if x.regle == "img-alt"]
    assert len(alt) == 1 and alt[0].certain


def test_ligne_de_ne_devine_pas():
    assert bac_a_sable.ligne_de(SOURCE_C6, "<section>") == 1
    assert bac_a_sable.ligne_de(SOURCE_C6, "logo.png") == 4
    assert bac_a_sable.ligne_de("", "<p>") == 1


def test_lieu_erreur_garde_notre_code_seulement():
    base = "http://127.0.0.1:5123/"
    pile = ("TypeError: x is null\n    at f (https://cdn.exemple.com/lib.js:1:9)"
            "\n    at http://127.0.0.1:5123/js/app.js:12:5")
    assert bac_a_sable.lieu_erreur(pile, base, "index.html") == \
        ("js/app.js", 12)
    assert bac_a_sable.lieu_erreur("", base, "index.html") == \
        ("index.html", 1)


def test_bac_a_sable_desactive_le_dit(tmp_path):
    (tmp_path / "index.html").write_text(SOURCE_C6, encoding="utf-8")
    assert bac_a_sable.juger(tmp_path, ["index.html"]) == []
    assert any("non lance" in l for l in bac_a_sable.limites())


def test_couche6_regles_bloquantes_ont_un_remede():
    for famille in bac_a_sable.FAMILLES_BLOQUANTES | {"js-erreur-execution",
                                                      "fichier-absent"}:
        assert REMEDES.get(famille), famille


def test_axe_embarque_intact():
    assert bac_a_sable._axe_source() is not None



# ------------------------------------------- fiches de normes (pilier 2)
from brain.codage import normes


def test_chaque_regle_a_remede_a_sa_fiche():
    sans = [r for r in REMEDES if normes.fiche_de(r) is None]
    assert not sans, sans


def test_fiches_courtes_sourcees_uniques():
    ids = [f.id for f in normes.toutes()]
    assert len(ids) == len(set(ids))
    for f in normes.toutes():
        assert 0 < len(f.texte) <= normes.TEXTE_MAX, f.id
        assert f.source and f.ref and f.regles and f.mots, f.id


def test_fiches_choisies_par_le_sens():
    ids = {f.id for f in normes.choisir("une page de connexion avec mot de passe")}
    assert "owasp-mots-de-passe" in ids
    ids = {f.id for f in normes.choisir("requete SQL pour chercher un produit")}
    assert "owasp-injection-sql" in ids
    assert normes.choisir("bonjour") == []


def test_fiches_dans_le_budget():
    for demande in ("site vitrine avec formulaire de contact",
                    "api flask avec base de donnees et connexion"):
        assert len(normes.pour_prompt(demande)) <= normes.BUDGET_PROMPT + 80


def test_correction_donne_la_raison():
    from brain.codage.juges import Defaut
    d = Defaut("a.py", 3, "injection-sql", GRAVITE.BLOQUANT, "x", "n")
    assert "[norme] pourquoi" in message_correction([d])


# ------------------------------- contamination PHP / Java (couche 4)
# Chaque piege : un FAUTIF (la faute doit etre vue, avec la ligne d'entree)
# et son JUSTE (0 faux positif exige).
from brain.codage.contamination_php_java import analyser_java, analyser_php


def _regles(defauts):
    return {(d.regle, d.ligne) for d in defauts}


PHP_FAUTIFS = [
    # (code, regle, ligne du puits, ligne de l'entree)
    ("<?php\n$id = $_GET['id'];\n$sql = \"SELECT * FROM t WHERE id = $id\";\n"
     "$pdo->query($sql);\n", "injection-sql", 4, 2),
    ("<?php\n$nom = $_POST['nom'];\n$r = mysqli_query($c, \"SELECT 1 FROM u "
     "WHERE n = '\" . $nom . \"'\");\n", "injection-sql", 3, 2),
    ("<?php\n$q = $request->input('q');\nDB::select(\"SELECT * FROM p WHERE "
     "n LIKE '%$q%'\");\n", "injection-sql", 3, 2),
    ("<?php\n$h = $_GET['hote'];\nsystem('ping -c 1 ' . $h);\n",
     "injection-commande", 3, 2),
    ("<?php\n$f = $_GET['f'];\n$out = `cat $f`;\n", "injection-commande", 3, 2),
    ("<?php\n$p = $_GET['page'];\ninclude 'pages/' . $p . '.php';\n",
     "inclusion-fichier", 3, 2),
    ("<?php\n$f = $_GET['f'];\nreadfile('/var/docs/' . $f);\n",
     "traversee-chemin", 3, 2),
    ("<?php\n$n = $_GET['n'];\n$msg = 'Bonjour ' . $n;\necho $msg;\n",
     "xss-serveur", 4, 2),
    ("<p><?= $_GET['q'] ?></p>\n", "xss-serveur", 1, 1),
    ("<?php\n$u = $_GET['retour'];\nheader('Location: ' . $u);\n",
     "redirection-ouverte", 3, 2),
    ("<?php\n$url = $_POST['url'];\n$ch = curl_init();\n"
     "curl_setopt($ch, CURLOPT_URL, $url);\n", "ssrf", 4, 2),
    ("<?php\n$d = unserialize($_COOKIE['panier']);\n", "deserialisation",
     2, 2),
    ("<?php\nforeach ($_GET as $k => $v) {\n  echo $v;\n}\n", "xss-serveur",
     3, 2),
    ("<?php\n$c = $_GET['code'];\neval($c);\n", "injection-code", 3, 2),
]

PHP_JUSTES = [
    "<?php\n$id = (int) $_GET['id'];\n$sql = \"SELECT * FROM t WHERE id = $id\";"
    "\n$pdo->query($sql);\n",
    "<?php\n$id = intval($_GET['id']);\n$pdo->query(\"SELECT * FROM t WHERE "
    "id = $id\");\n",
    "<?php\n$st = $pdo->prepare('SELECT * FROM u WHERE n = ?');\n"
    "$st->execute([$_POST['nom']]);\n",
    "<?php\n$n = $_GET['n'];\necho htmlspecialchars($n, ENT_QUOTES, 'UTF-8');\n",
    "<p><?= htmlspecialchars($_GET['q']) ?></p>\n",
    "<?php\n$h = $_GET['hote'];\nsystem('ping -c 1 ' . escapeshellarg($h));\n",
    "<?php\n$f = basename($_GET['f']);\nreadfile('/var/docs/' . $f);\n",
    "<?php\n$p = $_GET['page'];\nif (in_array($p, ['accueil', 'contact'], "
    "true)) {\n  include 'pages/' . $p . '.php';\n}\n",
    "<?php\n$n = $_GET['n'];\n$n = 'invite';\necho $n;\n",
    "<?php\n// echo $_GET['x'];\necho 'Bonjour';\n",
    "<?php\n$x = '$_GET';\necho $x;\n",
    "<?php\nfunction a() { $id = $_GET['id']; }\nfunction b() {\n"
    "  echo $id;\n}\n",
    "<?php\n$st = $pdo->prepare('SELECT * FROM u WHERE id = :id');\n"
    "$st->execute(['id' => $_GET['id']]);\n",
]

JAVA_FAUTIFS = [
    ("class A {\n  void f(HttpServletRequest req) throws Exception {\n"
     "    String id = req.getParameter(\"id\");\n"
     "    String sql = \"SELECT * FROM t WHERE id = \" + id;\n"
     "    stmt.executeQuery(sql);\n  }\n}\n", "injection-sql", 5, 3),
    ("class A {\n  @GetMapping(\"/u\")\n"
     "  public List<U> f(@RequestParam(\"nom\") String nom) {\n"
     "    return jdbcTemplate.query(\"SELECT * FROM u WHERE n = '\" + nom + "
     "\"'\", m);\n  }\n}\n", "injection-sql", 4, 3),
    ("class A {\n  void f(HttpServletRequest r) throws Exception {\n"
     "    String h = r.getParameter(\"h\");\n"
     "    Runtime.getRuntime().exec(\"ping \" + h);\n  }\n}\n",
     "injection-commande", 4, 3),
    ("class A {\n  void f(HttpServletRequest r, HttpServletResponse s) "
     "throws Exception {\n    String n = r.getParameter(\"n\");\n"
     "    s.getWriter().println(\"<p>\" + n + \"</p>\");\n  }\n}\n",
     "xss-serveur", 4, 3),
    ("class A {\n  @GetMapping(\"/f\")\n"
     "  public byte[] f(@RequestParam String nom) throws Exception {\n"
     "    Path p = Paths.get(\"/data\", nom);\n"
     "    return Files.readAllBytes(p);\n  }\n}\n", "traversee-chemin", 4, 3),
    ("class A {\n  void f(HttpServletRequest r, HttpServletResponse s) "
     "throws Exception {\n    s.sendRedirect(r.getParameter(\"next\"));\n"
     "  }\n}\n", "redirection-ouverte", 3, 3),
    ("class A {\n  @GetMapping(\"/go\")\n"
     "  public String go(@RequestParam String next) {\n"
     "    return \"redirect:\" + next;\n  }\n}\n", "redirection-ouverte", 4, 3),
    ("class A {\n  @PostMapping(\"/apercu\")\n"
     "  public String f(@RequestBody Demande d) throws Exception {\n"
     "    URL u = new URL(d.getUrl());\n    return lire(u);\n  }\n}\n",
     "ssrf", 4, 3),
    ("class A {\n  void f(HttpServletRequest r) throws Exception {\n"
     "    StringBuilder sb = new StringBuilder(\"SELECT * FROM t WHERE n = '\");"
     "\n    sb.append(r.getParameter(\"n\"));\n"
     "    stmt.executeQuery(sb.toString());\n  }\n}\n", "injection-sql", 5, 4),
]

JAVA_JUSTES = [
    "class A {\n  void f(HttpServletRequest req) throws Exception {\n"
    "    String id = req.getParameter(\"id\");\n"
    "    PreparedStatement ps = c.prepareStatement(\"SELECT * FROM t WHERE "
    "id = ?\");\n    ps.setString(1, id);\n    ps.executeQuery();\n  }\n}\n",
    "class A {\n  void f(HttpServletRequest req) throws Exception {\n"
    "    int id = Integer.parseInt(req.getParameter(\"id\"));\n"
    "    stmt.executeQuery(\"SELECT * FROM t WHERE id = \" + id);\n  }\n}\n",
    "class A {\n  void f(HttpServletRequest r, HttpServletResponse s) "
    "throws Exception {\n    String n = r.getParameter(\"n\");\n"
    "    s.getWriter().println(\"<p>\" + HtmlUtils.htmlEscape(n) + \"</p>\");"
    "\n  }\n}\n",
    "class A {\n  void f(HttpServletRequest r) {\n"
    "    String n = r.getParameter(\"n\");\n    System.out.println(n);\n  }\n}\n",
    "class A {\n  @GetMapping(\"/go\")\n"
    "  public String go(@RequestParam String next) {\n"
    "    if (!AUTORISES.contains(next)) { return \"redirect:/\"; }\n"
    "    return \"redirect:\" + next;\n  }\n}\n",
    "class A {\n  void f(HttpServletRequest r) throws Exception {\n"
    "    ProcessBuilder pb = new ProcessBuilder(\"ls\", \"-l\");\n"
    "    pb.start();\n  }\n}\n",
    "class A {\n  // stmt.executeQuery(\"SELECT \" + req.getParameter(\"x\"));\n"
    "  void f() {}\n}\n",
    "class A {\n  void f(HttpServletRequest r) throws Exception {\n"
    "    String id = r.getParameter(\"id\");\n  }\n"
    "  void g() throws Exception {\n"
    "    stmt.executeQuery(\"SELECT * FROM t WHERE id = \" + id);\n  }\n}\n",
]


@pytest.mark.parametrize("code,regle,ligne,entree", PHP_FAUTIFS)
def test_contamination_php_fautif(code, regle, ligne, entree):
    d = analyser_php("a.php", code)
    assert (regle, ligne) in _regles(d), d
    vu = next(x for x in d if (x.regle, x.ligne) == (regle, ligne))
    assert f"entree ligne {entree}" in vu.message


@pytest.mark.parametrize("code", PHP_JUSTES)
def test_contamination_php_juste(code):
    assert analyser_php("a.php", code) == []


@pytest.mark.parametrize("code,regle,ligne,entree", JAVA_FAUTIFS)
def test_contamination_java_fautif(code, regle, ligne, entree):
    d = analyser_java("A.java", code)
    assert (regle, ligne) in _regles(d), d
    vu = next(x for x in d if (x.regle, x.ligne) == (regle, ligne))
    assert f"entree ligne {entree}" in vu.message


@pytest.mark.parametrize("code", JAVA_JUSTES)
def test_contamination_java_juste(code):
    assert analyser_java("A.java", code) == []


def test_contamination_une_seule_alerte_par_origine():
    code = ("class A {\n  void f(@RequestParam String n) throws Exception {\n"
            "    Path p = Paths.get(\"/d\", n);\n"
            "    Files.readAllBytes(p);\n    Files.delete(p);\n  }\n}\n")
    d = [x for x in analyser_java("A.java", code)
         if x.regle == "traversee-chemin"]
    assert len(d) == 1 and d[0].ligne == 3


def test_contamination_message_garde_par_juger_fichier():
    from brain.codage.juges import juger_fichier
    d = juger_fichier("a.php", PHP_FAUTIFS[0][0])
    sql = [x for x in d if x.regle == "injection-sql"]
    assert sql and all("entree ligne" in x.message for x in sql
                       if x.ligne == 4)


def test_bilan_nomme_le_code_serveur_non_execute(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "serveur.js").write_text(
        "const express = require('express');\n", encoding="utf-8")
    (tmp_path / "menu.js").write_text("const a = 1;\n", encoding="utf-8")
    vus = ["app.py", "serveur.js", "menu.js"]
    assert bac_a_sable.code_serveur(tmp_path, vus) == ["app.py", "serveur.js"]
    bac_a_sable.juger(tmp_path, vus)
    l = " ".join(bac_a_sable.limites())
    assert "app.py" in l and "serveur.js" in l and "menu.js" not in l


def test_bilan_muet_sans_code_serveur(tmp_path):
    (tmp_path / "menu.js").write_text("const a = 1;\n", encoding="utf-8")
    bac_a_sable.juger(tmp_path, ["menu.js"])
    assert not any("serveur" in l for l in bac_a_sable.limites())


# ---------------- premier essai reel (07/10, phi4-mini) : liens casses
def _lien_casse(fichier, lien, attr="href"):
    from brain.codage.juges import Defaut
    return Defaut(fichier, 8, "fichier-absent", GRAVITE.BLOQUANT,
                  f'{attr}="{lien}" : ce fichier n\'existe pas', "lien casse")


def test_lien_casse_vers_un_homonyme_donne_le_bon_chemin():
    m = message_correction([_lien_casse("index.html", "css/style.css")],
                           ["index.html", "style.css"])
    assert 'remplace "css/style.css" par "style.css"' in m
    assert "fichiers qui existent dans le projet : index.html, style.css" in m


def test_lien_casse_sans_fichier_demande_le_chemin_exact():
    m = message_correction([_lien_casse("index.html", "js/app.js", "src")],
                           ["index.html", "style.css"])
    assert "ecris le fichier « js/app.js »" in m


def test_lien_casse_depuis_un_sous_dossier():
    m = message_correction([_lien_casse("pages/a.html", "../css/s.css")],
                           ["pages/a.html", "s.css"])
    assert 'par "../s.css"' in m


def test_message_sans_liste_de_fichiers_reste_valable():
    m = message_correction([_lien_casse("index.html", "css/style.css")])
    assert "a faire" not in m and "css/style.css" in m


# ------------------- fidelite a la demande (second essai reel, 07/10)
from brain.codage import demande as fidelite

PAGE_ANCRE = """<!DOCTYPE html>
<html lang="fr">
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Essai</title></head>
<body><nav aria-label="Principale"><a href="{lien}">Contact</a></nav>
<main><h1>Essai</h1><section {cible}><h2>Contact</h2></section></main>
</body></html>
"""


def _regles_de(page):
    return {d.regle for d in juger_fichier("index.html", page)}


def test_ancre_sans_cible_est_vue():
    page = PAGE_ANCRE.format(lien="#contact", cible="")
    assert "ancre-absente" in _regles_de(page)


@pytest.mark.parametrize("lien,cible", [
    ("#contact", 'id="contact"'), ("#", ""), ("#top", ""),
    ("autre.html#x", ""), ("https://exemple.fr/#x", "")])
def test_ancre_juste_n_est_pas_vue(lien, cible):
    assert "ancre-absente" not in _regles_de(PAGE_ANCRE.format(lien=lien,
                                                               cible=cible))


def test_ancre_d_un_fragment_n_est_pas_jugee():
    assert "ancre-absente" not in _regles_de('<a href="#ailleurs">x</a>\n')


FORMULAIRE = ('<form method="post"><label for="a">A</label><input id="a">'
              '<label for="b">B</label><input id="b"><button>Ok</button>'
              '</form>')


def test_formulaire_disparu_est_un_contenu_perdu():
    avant = {"index.html": fidelite.compter(f"<main>{FORMULAIRE}</main>")}
    apres = {"index.html": fidelite.compter("<main><p>Bienvenue</p></main>")}
    regles = {(d.regle, d.message.split(" ")[0]) for d in
              fidelite.perdus(avant, apres)}
    assert ("contenu-perdu", "<form>") in regles
    assert ("contenu-perdu", "<input>") in regles


def test_champ_retire_est_un_contenu_perdu():
    moins = FORMULAIRE.replace('<label for="b">B</label><input id="b">', "")
    avant = {"index.html": fidelite.compter(FORMULAIRE)}
    apres = {"index.html": fidelite.compter(moins)}
    assert any("<input>" in d.message for d in fidelite.perdus(avant, apres))


def test_image_retiree_n_est_pas_un_contenu_perdu():
    avant = {"index.html": fidelite.compter('<main><img src="x.jpg" alt="">'
                                            "</main>")}
    apres = {"index.html": fidelite.compter("<main></main>")}
    assert fidelite.perdus(avant, apres) == []


def test_ajout_n_est_pas_une_perte():
    avant = {"index.html": fidelite.compter("<main></main>")}
    apres = {"index.html": fidelite.compter(f"<main>{FORMULAIRE}</main>")}
    assert fidelite.perdus(avant, apres) == []


@pytest.mark.parametrize("texte,attendu", [
    ("une page d'accueil pour une boulangerie avec un formulaire de contact",
     {"formulaire"}),
    ("un site avec un menu et une galerie de photos", {"menu", "galerie"}),
    ("une page d'inscription", {"inscription"}),
    ("un tableau de bord", set()),
    ("bonjour", set()),
])
def test_exigences_de_la_demande(texte, attendu):
    assert {m for m, _ in fidelite.exigences(texte)} == attendu


def test_demande_non_tenue_puis_tenue():
    demande = "une page avec un formulaire de contact"
    sans = {"index.html": fidelite.compter("<main><h1>x</h1></main>")}
    avec = {"index.html": fidelite.compter(f"<main>{FORMULAIRE}</main>")}
    d = fidelite.non_tenues(demande, sans)
    assert [x.regle for x in d] == ["demande-non-tenue"]
    assert "formulaire" in d[0].message
    assert fidelite.non_tenues(demande, avec) == []
    assert fidelite.non_tenues(demande, {}) == []


def test_atelier_refuse_une_correction_qui_supprime(tmp_path):
    """Le cas reel : tour 1 avec formulaire + un defaut ; tour 2 « corrige »
    en supprimant le formulaire -> l'atelier ne doit PAS dire conforme."""
    avec_form = PAGE_JUSTE.replace("<main>", f"<main>{FORMULAIRE}") \
        .replace(' alt=""', "")
    sans_form = PAGE_JUSTE
    moteur = FauxMoteur([bloc("index.html", avec_form),
                         bloc("index.html", sans_form),
                         bloc("index.html", sans_form)])
    bilan = Atelier(moteur, Espace(tmp_path)).ecrire(
        "une page avec un formulaire de contact")
    assert not bilan.conforme
    regles = {d.regle for d in bilan.bloquants}
    assert "contenu-perdu" in regles or "demande-non-tenue" in regles


def test_un_defaut_corrige_et_un_autre_apparu_est_un_progres(tmp_path):
    """Troisieme essai reel : 2 defauts, puis 2 AUTRES defauts. Meme nombre,
    mais le modele progresse : l'atelier doit lui laisser le tour suivant."""
    sans_alt = PAGE_JUSTE.replace(' alt=""', "")
    sans_lang = PAGE_JUSTE.replace(' lang="fr"', "")
    moteur = FauxMoteur([bloc("index.html", sans_alt),
                         bloc("index.html", sans_lang),
                         bloc("index.html", PAGE_JUSTE)])
    bilan = Atelier(moteur, Espace(tmp_path)).ecrire("une page")
    assert [t.bloquants for t in bilan.tours] == [1, 1, 0]
    assert bilan.conforme


# ------------- contraste : la correction calculee (quatrieme essai reel)
CSS_ESSAI4 = """body { color: #1f2937; }
header, footer {
  background-color: #007bff; /* fond */
  color: #ffffff;
}
button { background-color: #007bff; color: white; }
button:hover { background-color: #0056b3; }
"""


def test_contraste_formule_wcag():
    assert round(bac_a_sable.contraste("#ffffff", "#000000"), 1) == 21.0
    assert round(bac_a_sable.contraste("#ffffff", "#007bff"), 2) == 3.98


def test_contraste_change_le_fond_ecrit_dans_le_css():
    m = bac_a_sable.correction_contraste("#ffffff", "#007bff", 4.5,
                                         {"style.css": CSS_ESSAI4})
    assert "style.css (ligne(s) 3, 6)" in m and "remplace #007bff (fond)" in m
    juste = re.search(r"par (#[0-9a-f]{6})", m).group(1)
    assert bac_a_sable.contraste("#ffffff", juste) >= 4.5


def test_contraste_lien_par_defaut_donne_une_regle():
    m = bac_a_sable.correction_contraste("#0000ee", "#007bff", 4.5,
                                         {"style.css": CSS_ESSAI4},
                                         "header a")
    assert "ajoute header a { color: #" in m and "remplace" not in m
    juste = re.search(r"color: (#[0-9a-f]{6})", m).group(1)
    assert bac_a_sable.contraste(juste, "#007bff") >= 4.5


def test_contraste_forme_courte_et_texte():
    m = bac_a_sable.correction_contraste("#aaaaaa", "#ffffff", 4.5,
                                         {"a.css": "p { color: #AAA; }"})
    assert "remplace #aaaaaa (texte)" in m


def test_contraste_couleur_dans_un_commentaire_ignoree():
    assert bac_a_sable.lieux_couleur(
        {"a.css": "/* ancien : #007bff */\np { color: red; }"},
        "#007bff") == []


def test_trois_boutons_du_meme_bleu_une_seule_consigne():
    noeud = {"html": "<button>", "any": [{"data": {
        "contrastRatio": 3.98, "fgColor": "#ffffff", "bgColor": "#007bff",
        "expectedContrastRatio": "4.5:1"}}]}
    r = {"violations": [{"id": "color-contrast", "impact": "serious",
                         "help": "c", "tags": ["wcag143"],
                         "nodes": [noeud, noeud, noeud]}]}
    d = bac_a_sable.lire_axe(r, "index.html", "<button>a</button>" * 3,
                             feuilles={"style.css": CSS_ESSAI4})
    assert len(d) == 1 and "remplace #007bff" in d[0].message
    assert d[0].ligne == 1        # trois <button> : ligne inconnue, pas devinee


# --------------------- juges du projet entier : le selecteur mort
from brain.codage import projet

PAGE_PROJET = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><title>x</title></head>
<body>
<nav id="menu" class="principal"><a href="#contact">Contact</a></nav>
<main>
<section id="contact">
<form method="post"><button type="submit" class="envoyer">Ok</button></form>
</section>
</main>
</body></html>
"""


def _projet(tmp_path, js, page=PAGE_PROJET, nom="app.js"):
    (tmp_path / "index.html").write_text(page, encoding="utf-8")
    (tmp_path / nom).write_text(js, encoding="utf-8")
    return projet.juger(tmp_path, ["index.html", nom])


def test_selecteur_mort_cas_reel_avec_la_correction(tmp_path):
    js = ("document.addEventListener('DOMContentLoaded', function() {\n"
          "  const f = document.querySelector('form#contact');\n"
          "});\n")
    d = _projet(tmp_path, js)
    assert [(x.regle, x.fichier, x.ligne) for x in d] == \
        [("selecteur-mort", "app.js", 2)]
    assert "porte par <section>" in d[0].message
    assert "index.html ligne 6" in d[0].message


@pytest.mark.parametrize("js", [
    "document.getElementById('absent').hidden = true;",
    "document.querySelectorAll('.carte').forEach(c => c.remove());",
    "document.querySelector('nav#entete a');",
    "document.getElementsByClassName('inconnue');",
])
def test_selecteur_mort_fautif(tmp_path, js):
    assert [x.regle for x in _projet(tmp_path, js)] == ["selecteur-mort"]


@pytest.mark.parametrize("js", [
    "document.getElementById('contact').hidden = false;",
    "document.querySelector('#contact form button.envoyer');",
    "document.querySelector('nav.principal > a');",
    "document.querySelectorAll('button[type=submit], button:hover');",
    "document.querySelector('form').addEventListener('submit', f);",
    # cree par le script lui-meme
    "const d = document.createElement('div'); d.id = 'bulle';\n"
    "document.body.append(d);\ndocument.getElementById('bulle');",
    "menu.classList.add('ouvert');\ndocument.querySelector('.ouvert');",
    "liste.innerHTML = '<li class=\"carte\">x</li>';\n"
    "document.querySelectorAll('.carte');",
    # construit : on ne devine pas
    "document.getElementById('ligne-' + n);",
    "document.querySelector(`#${id}`);",
    # en commentaire
    "// document.getElementById('absent');\nconst a = 1;",
])
def test_selecteur_vivant_ou_non_juge(tmp_path, js):
    assert _projet(tmp_path, js) == []


def test_serveur_node_non_juge(tmp_path):
    js = ("const express = require('express');\n"
          "document.getElementById('absent');\n")
    assert _projet(tmp_path, js, nom="serveur.js") == []


def test_sans_page_rien_a_juger(tmp_path):
    (tmp_path / "app.js").write_text("document.getElementById('x');",
                                     encoding="utf-8")
    assert projet.juger(tmp_path, ["app.js"]) == []


def test_script_dans_la_page_est_juge_a_sa_ligne(tmp_path):
    page = PAGE_PROJET.replace(
        "</main>", "</main>\n<script>\ndocument.getElementById('fantome');\n"
        "</script>")
    (tmp_path / "index.html").write_text(page, encoding="utf-8")
    d = projet.juger(tmp_path, ["index.html"])
    assert [(x.regle, x.fichier, x.ligne) for x in d] == \
        [("selecteur-mort", "index.html", 11)]


def test_selecteur_d_une_autre_page_du_projet_est_vivant(tmp_path):
    (tmp_path / "index.html").write_text(PAGE_PROJET, encoding="utf-8")
    (tmp_path / "galerie.html").write_text(
        '<main><div id="photos"></div></main>', encoding="utf-8")
    (tmp_path / "app.js").write_text("document.getElementById('photos');",
                                     encoding="utf-8")
    assert projet.juger(tmp_path, ["galerie.html", "index.html",
                                   "app.js"]) == []


def test_attribut_sur_une_balise_absente_est_mort(tmp_path):
    js = "document.querySelector('input[type=email]');"
    assert [x.regle for x in _projet(tmp_path, js)] == ["selecteur-mort"]



# ------------------------------- reparation automatique (sans modele)
from brain.codage import reparation
from brain.codage.juges import Defaut


def _d(fichier, ligne, regle, message="", gravite=GRAVITE.BLOQUANT):
    return Defaut(fichier, ligne, regle, gravite, message, "n")


def test_repare_le_contraste_avec_la_couleur_calculee(tmp_path):
    (tmp_path / "style.css").write_text(CSS_ESSAI4, encoding="utf-8")
    msg = ("contraste mesure 3.98:1 (#ffffff sur #007bff), 4.5:1 exige -> "
           "dans style.css (ligne(s) 3, 6) : remplace #007bff (fond) par "
           "#0071eb (contraste 4.6:1) [axe-core color-contrast]")
    faites = reparation.reparer(Espace(tmp_path),
                                [_d("index.html", 1, "contraste", msg)],
                                ["index.html", "style.css"])
    css = (tmp_path / "style.css").read_text(encoding="utf-8")
    assert [r.ligne for r in faites] == [3, 6]
    assert "#007bff" not in css.split("button:hover")[0]
    assert "/* fond */" in css            # le commentaire est garde
    assert "#0056b3" in css               # le reste ne bouge pas


def test_repare_le_lien_vers_le_fichier_homonyme(tmp_path):
    (tmp_path / "index.html").write_text(
        '<head>\n<link rel="stylesheet" href="css/style.css">\n</head>\n',
        encoding="utf-8")
    d = _d("index.html", 2, "fichier-absent",
           'href="css/style.css" : ce fichier n\'existe pas')
    faites = reparation.reparer(Espace(tmp_path), [d],
                                ["index.html", "style.css"])
    assert len(faites) == 1
    assert 'href="style.css"' in (tmp_path / "index.html").read_text()


def test_lien_ambigu_ou_sans_homonyme_non_repare(tmp_path):
    texte = '<script src="js/app.js"></script>\n'
    (tmp_path / "index.html").write_text(texte, encoding="utf-8")
    d = _d("index.html", 1, "fichier-absent",
           'src="js/app.js" : ce fichier n\'existe pas')
    assert reparation.reparer(Espace(tmp_path), [d], ["index.html"]) == []
    assert reparation.reparer(Espace(tmp_path), [d],
                              ["index.html", "a/app.js", "b/app.js"]) == []
    assert (tmp_path / "index.html").read_text() == texte


def test_repare_doctype_charset_viewport(tmp_path):
    (tmp_path / "index.html").write_text(
        '<html lang="fr">\n<head>\n<title>x</title>\n</head>\n',
        encoding="utf-8")
    defauts = [_d("index.html", 1, r) for r in ("doctype", "charset",
                                                 "viewport")]
    e = Espace(tmp_path)
    reparation.reparer(e, defauts, ["index.html"])
    reparation.reparer(e, defauts, ["index.html"])   # 2e passe (meme ligne)
    t = (tmp_path / "index.html").read_text()
    assert t.startswith("<!DOCTYPE html>\n<html")
    assert '<meta charset="utf-8">' in t and 'name="viewport"' in t


def test_repare_noopener_mais_pas_si_rel_existe(tmp_path):
    (tmp_path / "a.html").write_text(
        '<a href="https://x.fr" target="_blank">x</a>\n'
        '<a href="https://y.fr" target="_blank" rel="nofollow">y</a>\n',
        encoding="utf-8")
    defauts = [_d("a.html", 1, "blank-noopener", gravite=GRAVITE.CONSEIL),
               _d("a.html", 2, "blank-noopener", gravite=GRAVITE.CONSEIL)]
    faites = reparation.reparer(Espace(tmp_path), defauts, ["a.html"])
    assert [r.ligne for r in faites] == [1]


def test_ne_repare_jamais_ce_qui_demande_du_contenu(tmp_path):
    texte = '<img src="a.png">\n<html>\n'
    (tmp_path / "a.html").write_text(texte, encoding="utf-8")
    defauts = [_d("a.html", 1, "img-alt"), _d("a.html", 2, "lang"),
               _d("a.html", 1, "selecteur-mort")]
    assert reparation.reparer(Espace(tmp_path), defauts, ["a.html"]) == []
    assert (tmp_path / "a.html").read_text() == texte


def test_atelier_repare_sans_rappeler_le_modele(tmp_path, monkeypatch):
    """Le cas de l'essai 4 : seul un contraste reste -> MAEL le corrige
    lui-meme et le tour suffit : AUCUN appel de plus au modele."""
    from brain.codage import bac_a_sable as b
    page = PAGE_JUSTE.replace("</head>",
                              '<link rel="stylesheet" href="style.css">\n'
                              "</head>")
    css = "button { background-color: #007bff; color: #ffffff; }\n"
    reponse = bloc("index.html", page) + "\n```css fichier=style.css\n" \
        + css + "```"
    moteur = FauxMoteur([reponse])
    msg = ("contraste mesure 3.98:1 (#ffffff sur #007bff), 4.5:1 exige -> "
           "dans style.css (ligne(s) 1) : remplace #007bff (fond) par "
           "#0071eb (contraste 4.6:1) [axe-core color-contrast]")
    appels = []

    def juge_factice(racine, vus):
        appels.append(1)
        t = (Path(racine) / "style.css").read_text(encoding="utf-8")
        return ([_d("index.html", 1, "contraste", msg)]
                if "#007bff" in t else [])
    monkeypatch.setattr(b, "juger", juge_factice)
    bilan = Atelier(moteur, Espace(tmp_path)).ecrire("une page")
    assert bilan.conforme
    assert len(moteur.recus) == 1            # un seul appel au modele
    assert bilan.tours[0].reparations
    assert "#0071eb" in (tmp_path / "style.css").read_text()


# ---------------------------- sixieme essai reel : trois petits manques
def test_etiquette_de_nom_retiree_du_fichier():
    e = extraire("```js\n<!-- script.js -->\nconsole.log(1);\n```\n"
                 "```css\n/* style.css */\nbody { color: #111; }\n```")
    assert e.fichiers["script.js"] == "console.log(1);\n"
    assert e.fichiers["style.css"] == "body { color: #111; }\n"


def test_commentaire_utile_en_tete_garde():
    e = extraire("```js fichier=app.js\n// Menu du site\nconst a = 1;\n```")
    assert e.fichiers["app.js"].startswith("// Menu du site")


def test_formulaire_dans_une_page_orpheline_n_est_pas_tenu(tmp_path):
    (tmp_path / "index.html").write_text(
        "<main><h1>Accueil</h1></main>", encoding="utf-8")
    (tmp_path / "formulaire.html").write_text(
        f"<main>{FORMULAIRE}</main>", encoding="utf-8")
    pages = ["formulaire.html", "index.html"]
    apres = fidelite.empreinte(tmp_path)
    vis = fidelite.atteignables(tmp_path, pages)
    assert vis == {"index.html"}
    d = fidelite.non_tenues("une page avec un formulaire de contact", apres,
                            vis)
    assert len(d) == 1 and 'ajoute <a href="formulaire.html">' in d[0].message


def test_formulaire_dans_une_page_liee_est_tenu(tmp_path):
    (tmp_path / "index.html").write_text(
        '<main><a href="formulaire.html#haut">Contact</a></main>',
        encoding="utf-8")
    (tmp_path / "formulaire.html").write_text(
        f"<main>{FORMULAIRE}</main>", encoding="utf-8")
    apres = fidelite.empreinte(tmp_path)
    vis = fidelite.atteignables(tmp_path, ["formulaire.html", "index.html"])
    assert fidelite.non_tenues("un formulaire de contact", apres, vis) == []


def test_sans_accueil_toutes_les_pages_comptent(tmp_path):
    (tmp_path / "contact.html").write_text(f"<main>{FORMULAIRE}</main>",
                                           encoding="utf-8")
    assert fidelite.atteignables(tmp_path, ["contact.html"]) is None


def test_fichier_ecrit_deux_fois_est_signale_au_modele(tmp_path):
    fautif = PAGE_JUSTE.replace(' alt=""', "")
    double = bloc("index.html", fautif) + "\n" + bloc("index.html", fautif)
    moteur = FauxMoteur([double, bloc("index.html", PAGE_JUSTE)])
    Atelier(moteur, Espace(tmp_path)).ecrire("une page")
    assert "index.html deux fois" in moteur.recus[1][-1]["content"]


# ------------------------------- brique 3 : carte du projet et chantier
import json

from brain.codage.carte import carte
from brain.codage.chantier import Chantier, Tache, lire_plan


def test_plan_lu_valide_et_ordonne():
    texte = ("Voici le plan :\n"
             "- style.css : les couleurs et la mise en page\n"
             "1. `contact.html` : la page du formulaire\n"
             "* **index.html** : l'accueil\n"
             "- ../../etc/passwd : non\n"
             "- index.html : doublon\n"
             "- script.js — le menu du telephone\n"
             "- notes.docx : pas du code\n")
    plan = [(t.fichier, t.but) for t in lire_plan(texte)]
    assert plan == [("index.html", "l'accueil"),
                    ("contact.html", "la page du formulaire"),
                    ("style.css", "les couleurs et la mise en page"),
                    ("script.js", "le menu du telephone")]


def test_plan_illisible_donne_une_liste_vide():
    assert lire_plan("Je vais vous aider a faire un beau site !") == []


def test_carte_resume_ce_qui_raccorde_les_fichiers(tmp_path):
    (tmp_path / "index.html").write_text(
        '<title>Accueil</title><nav id="menu" class="principal">'
        '<a href="contact.html">C</a></nav><link href="style.css">'
        '<form method="post" action="/envoi"><input name="nom">'
        '<textarea id="msg"></textarea></form>', encoding="utf-8")
    (tmp_path / "style.css").write_text(
        "/* .ancien {} */\nnav, .principal { color: #1F2937; }\n",
        encoding="utf-8")
    (tmp_path / "app.js").write_text(
        "function ouvrir() {}\nconst fermer = () => 1;\n"
        "document.getElementById('menu');\n", encoding="utf-8")
    c = carte(tmp_path)
    assert "titre: Accueil" in c and "#menu" in c and ".principal" in c
    assert "liens: contact.html" in c and "post /envoi [nom, msg]" in c
    assert "couleurs: #1f2937" in c and ".ancien" not in c
    assert "fonctions: ouvrir, fermer" in c and "vise: menu" in c


def test_carte_respecte_son_budget(tmp_path):
    for i in range(40):
        (tmp_path / f"p{i:02}.html").write_text(
            "".join(f'<div id="bloc{i}-{k}"></div>' for k in range(30)),
            encoding="utf-8")
    c = carte(tmp_path, budget=600)
    assert len(c) < 600 + 40 * 45            # lignes « coupee » comprises
    assert "carte coupee" in c and "(+20)" in c


PAGE_CHANTIER = PAGE_JUSTE.replace(
    "</head>", '<link rel="stylesheet" href="style.css">\n</head>')
CSS_CHANTIER = "body { color: #1f2937; background: #ffffff; }\n"


def _chantier(tmp_path, reponses):
    moteur = FauxMoteur(reponses)
    return moteur, Chantier(moteur, Espace(tmp_path))


def test_chantier_complet_tache_par_tache(tmp_path):
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", PAGE_CHANTIER),
        "```css fichier=style.css\n" + CSS_CHANTIER + "```"])
    bilan = ch.lancer("une page d'accueil")
    assert bilan.conforme, rendre_bilan(bilan)
    assert [t.etat for t in ch.taches] == ["fait", "fait"]
    # index.html renvoie a style.css, prevu mais pas encore ecrit : ce
    # n'est PAS un defaut pendant la tache 1.
    assert [t.bloquants for t in bilan.tours] == [0, 0]
    etat = json.loads((tmp_path / ".mael/chantier.json").read_text("utf-8"))
    assert [t["etat"] for t in etat["taches"]] == ["fait", "fait"]
    assert "plan :" in rendre_bilan(bilan)


def test_chaque_appel_repart_d_une_conversation_neuve(tmp_path):
    reponse_index = bloc("index.html", PAGE_CHANTIER) + "\nTEXTE-DU-TOUR-1"
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- style.css : les styles\n",
        reponse_index,
        "```css fichier=style.css\n" + CSS_CHANTIER + "```"])
    ch.lancer("une page d'accueil")
    assert all(len(messages) == 1 for messages in moteur.recus)
    consigne_css = moteur.recus[2][0]["content"]
    assert "TEXTE-DU-TOUR-1" not in consigne_css     # pas d'historique
    assert "[carte du projet]" in consigne_css
    assert "- index.html (" in consigne_css           # mais la carte, oui
    assert "[fait] index.html" in consigne_css
    # La logistique range la feuille dans assets/css/ (arborescence standard).
    assert "[EN COURS] assets/css/style.css" in consigne_css
    assert "UNIQUEMENT le fichier assets/css/style.css" in consigne_css


def test_tache_corrigee_avec_le_fichier_courant(tmp_path):
    fautif = PAGE_CHANTIER.replace(' alt=""', "")
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", fautif),
        bloc("index.html", PAGE_CHANTIER),
        "```css fichier=style.css\n" + CSS_CHANTIER + "```"])
    bilan = ch.lancer("une page d'accueil")
    assert bilan.conforme
    correction = moteur.recus[2][0]["content"]
    # Defaut localise (img sans alt) : RETOUCHE, avec l'extrait numerote
    # autour de la ligne, pas le fichier entier.
    assert "[extraits a corriger]" in correction
    assert "fichier=index.html lignes=" in correction
    assert "[contenu actuel]" not in correction and "img" in correction


def test_reprise_saute_les_taches_faites(tmp_path):
    (tmp_path / "index.html").write_text(PAGE_CHANTIER, encoding="utf-8")
    (tmp_path / ".mael").mkdir()
    (tmp_path / ".mael/chantier.json").write_text(json.dumps({
        "demande": "une page d'accueil",
        "taches": [{"fichier": "index.html", "but": "l'accueil",
                    "etat": "fait"},
                   {"fichier": "style.css", "but": "les styles",
                    "etat": "a faire"}]}), encoding="utf-8")
    moteur, ch = _chantier(tmp_path, [
        "```css fichier=style.css\n" + CSS_CHANTIER + "```"])
    bilan = ch.reprendre()
    assert bilan.conforme and len(moteur.recus) == 1
    assert "UNIQUEMENT le fichier style.css" in moteur.recus[0][0]["content"]


def test_reprise_sans_chantier_le_dit(tmp_path):
    moteur, ch = _chantier(tmp_path, [])
    bilan = ch.reprendre()
    assert "aucun chantier" in bilan.arret and not moteur.recus


def test_bloc_mal_nomme_est_le_fichier_de_la_tache(tmp_path):
    moteur, ch = _chantier(tmp_path, [
        "- style.css : les styles\n",
        "```css fichier=css/style.css\n" + CSS_CHANTIER + "```"])
    ch.lancer("une feuille de style")
    assert (tmp_path / "assets/css/style.css").exists()
    assert not (tmp_path / "css/style.css").exists()


# La feuille de style commune, a son adresse standard (logistique.py).
CSS_STANDARD = "assets/css/style.css"


# ---------------- criteres par tache (verifies par MAEL) et verrouillage
from brain.codage import criteres as crit

PLAN_SITE = ["index.html", "galerie.html", "contact.html", "style.css",
             "script.js"]


def test_criteres_deduits_du_plan():
    c = crit.deduire("contact.html", "la page de contact avec un formulaire",
                     PLAN_SITE)
    textes = [x.texte for x in c]
    assert "contient formulaire (<form>)" in textes
    assert 'mene a index.html : <a href="index.html">' in textes
    assert 'mene a galerie.html : <a href="galerie.html">' in textes
    assert any(t.startswith("charge style.css") for t in textes)
    assert any(t.startswith("charge script.js") for t in textes)


def test_criteres_d_un_css_sont_libres_et_non_bloquants(tmp_path):
    c = crit.deduire("style.css", "les couleurs chaleureuses", PLAN_SITE)
    assert [x.type for x in c] == ["libre"]
    (tmp_path / "style.css").write_text("body{}", encoding="utf-8")
    assert crit.manques(tmp_path, "style.css", c) == []


def test_criteres_verifies_par_lecture(tmp_path):
    c = crit.deduire("contact.html", "un formulaire", ["index.html",
                                                       "contact.html",
                                                       "style.css"])
    (tmp_path / "contact.html").write_text(
        '<link rel="stylesheet" href="style.css"><main><h1>Contact</h1>'
        '<a href="index.html#haut">Accueil</a></main>', encoding="utf-8")
    m = crit.manques(tmp_path, "contact.html", c)
    assert [x.message for x in m] == [
        "critere de la tache non tenu : contient formulaire (<form>)"]


def test_criteres_dans_un_sous_dossier(tmp_path):
    c = crit.deduire("pages/a.html", "x", ["index.html", "pages/a.html",
                                           "css/s.css"])
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages/a.html").write_text(
        '<link href="../css/s.css"><main><h1>A</h1>'
        '<a href="../index.html">i</a></main>',
        encoding="utf-8")
    assert crit.manques(tmp_path, "pages/a.html", c) == []


def test_tache_non_validee_tant_qu_un_critere_manque(tmp_path):
    sans_lien = PAGE_CHANTIER
    avec_lien = PAGE_CHANTIER.replace(
        "<main>", '<main><a href="contact.html">Contact</a>')
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- contact.html : le contact\n",
        bloc("index.html", sans_lien),
        bloc("index.html", avec_lien),
        bloc("contact.html", PAGE_CHANTIER.replace(
            "<main>", '<main><a href="index.html">Accueil</a>')),
        "```css fichier=style.css\n" + CSS_CHANTIER + "```"])
    bilan = ch.lancer("un site de deux pages")
    t = ch.taches[0]
    assert t.etat == "fait" and t.tours == 2
    assert "mene a contact.html" in moteur.recus[2][0]["content"]
    assert "criteres 4/4" in t.verifies     # main, h1, lien, style.css
    assert bilan.conforme, rendre_bilan(bilan)


def test_criteres_montres_au_modele(tmp_path):
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil avec un menu\n",
        bloc("index.html", PAGE_CHANTIER.replace(
            "<main>", '<nav aria-label="Principale"></nav><main>')),
        "```css fichier=style.css\n" + CSS_CHANTIER + "```"])
    ch.lancer("un site")
    consigne = moteur.recus[1][0]["content"]
    assert "[criteres de la tache" in consigne
    assert "contient menu (<nav>)" in consigne


def test_fichier_verrouille_jamais_reecrit_en_finition(tmp_path,
                                                       monkeypatch):
    """Un defaut decouvert a la finition dans un fichier VALIDE : signale,
    pas de nouvel appel au modele, fichier intact."""
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", PAGE_CHANTIER),
        "```css fichier=style.css\n" + CSS_CHANTIER + "```"])
    from brain.codage import juges as j
    vrai = j.juger_projet

    def avec_defaut_final(racine, outils_externes=True, executer=True):
        d, vus = vrai(racine, outils_externes, executer=False)
        if executer:                   # seulement les juges complets
            # Un defaut NON visuel (les visuels sont pris par la tache
            # CSS, avant tout verrou) decouvert apres la validation.
            d = d + [Defaut("index.html", 3, "ancre-absente",
                            GRAVITE.BLOQUANT, "ancre morte", "HTML")]
        return d, vus
    monkeypatch.setattr(j, "juger_projet", avec_defaut_final)
    bilan = ch.lancer("une page")
    apres = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert len(moteur.recus) == 3          # plan + 2 taches, aucune finition
    # La seule retouche est celle de la logistique, a l'ecriture (avant le
    # verrou) : la feuille de style a son adresse standard.
    assert apres.strip() == PAGE_CHANTIER.replace(
        'href="style.css"', 'href="assets/css/style.css"').strip()
    assert ch.taches[0].etat == "fait"
    assert "verrouille" in bilan.arret and "index.html" in bilan.arret
    assert not bilan.conforme             # le defaut reste dit, pas cache


# ---------- premier essai du chantier : les corrections, avec rigueur
from brain.codage import images


def test_plan_sans_css_recoit_une_feuille_de_style(tmp_path):
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- contact.html : le contact\n"])
    taches = ch.planifier("un site de deux pages")
    assert [t.fichier for t in taches] == ["index.html", "contact.html",
                                           "assets/css/style.css"]
    textes = [c["texte"] for c in taches[0].criteres]
    assert any(t.startswith("charge assets/css/style.css") for t in textes)


def test_fichier_de_code_hors_plan_devient_une_tache(tmp_path):
    page = PAGE_CHANTIER.replace(
        "</body>", '<script src="js/menu.js" defer></script>\n</body>')
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", page),
        "```css fichier=style.css\n" + CSS_CHANTIER + "```",
        "```js fichier=js/menu.js\nconst a = 1;\n```"])
    bilan = ch.lancer("une page d'accueil")
    assert [t.fichier for t in ch.taches] == ["index.html", CSS_STANDARD,
                                              "assets/js/menu.js"]
    assert 'src="assets/js/menu.js"' in (tmp_path / "index.html").read_text(
        encoding="utf-8")                    # la page raccordee
    assert ch.taches[0].etat == "fait"       # pas bloquee sur js/menu.js
    assert bilan.conforme, rendre_bilan(bilan)


@pytest.mark.parametrize("nom,signature", [
    ("images/pain.jpg", b"\xff\xd8\xff"),        # vrai JPEG
    ("images/pain.png", b"\x89PNG"),
    ("images/pain.webp", b"RIFF"),
    ("images/pain.gif", b"GIF8"),
    ("images/pain.svg", b"<svg"),
])
def test_image_provisoire_dans_le_vrai_format(nom, signature):
    octets, raison = images.fabriquer(nom, 300, 200)
    assert raison == "" and octets.startswith(signature)


def test_png_pur_sans_pillow_est_un_vrai_png():
    import zlib
    o = images._png_pur(4, 3)
    assert o.startswith(b"\x89PNG\r\n\x1a\n") and o.endswith(
        b"IEND\xaeB`\x82")
    assert zlib.crc32(o[12:29]) & 0xFFFFFFFF == int.from_bytes(o[29:33],
                                                                 "big")


def test_taille_lue_dans_la_balise():
    ligne = '<img src="a.jpg" alt="x" width="300" height="200">'
    assert images.taille_dans_la_balise(ligne, "a.jpg") == (300, 200)
    assert images.taille_dans_la_balise('<img src="a.jpg">', "a.jpg") == \
        (800, 600)
    assert images.taille_dans_la_balise(
        '<img src="a.jpg" width="99999">', "a.jpg")[0] == 2000


def test_reparation_cree_l_image_provisoire(tmp_path):
    (tmp_path / "photos.html").write_text(
        '<main>\n<img src="images/croissant.jpg" alt="Croissant" '
        'width="300" height="300">\n</main>\n', encoding="utf-8")
    d = _d("photos.html", 2, "fichier-absent",
           'src="images/croissant.jpg" : ce fichier n\'existe pas')
    faites = reparation.reparer(Espace(tmp_path), [d], ["photos.html"])
    assert [(r.fichier, r.provisoire) for r in faites] == \
        [("images/croissant.jpg", True)]
    octets = (tmp_path / "images/croissant.jpg").read_bytes()
    assert octets.startswith(b"\xff\xd8\xff")
    from PIL import Image
    assert Image.open(tmp_path / "images/croissant.jpg").size == (300, 300)


def test_image_provisoire_jamais_par_dessus_un_fichier(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images/vraie.jpg").write_bytes(b"VRAIE")
    (tmp_path / "a.html").write_text('<img src="images/vraie.jpg">\n',
                                     encoding="utf-8")
    d = _d("a.html", 1, "fichier-absent",
           'src="images/vraie.jpg" : ce fichier n\'existe pas')
    assert reparation.reparer(Espace(tmp_path), [d], ["a.html"]) == []
    assert (tmp_path / "images/vraie.jpg").read_bytes() == b"VRAIE"


def test_image_provisoire_jamais_hors_de_l_espace(tmp_path):
    (tmp_path / "e").mkdir()
    (tmp_path / "e/a.html").write_text('<img src="../evasion.png">\n',
                                       encoding="utf-8")
    d = _d("a.html", 1, "fichier-absent",
           'src="../evasion.png" : ce fichier n\'existe pas')
    assert reparation.reparer(Espace(tmp_path / "e"), [d], ["a.html"]) == []
    assert not (tmp_path / "evasion.png").exists()


def test_bilan_liste_les_images_provisoires(tmp_path):
    page = PAGE_CHANTIER.replace(
        "<main>", '<main><img src="images/pain.jpg" alt="Pain" width="40" '
        'height="40">')
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", page),
        "```css fichier=style.css\n" + CSS_CHANTIER + "```"])
    bilan = ch.lancer("une page d'accueil")
    assert bilan.provisoires == ["assets/images/pain.jpg"]
    assert "IMAGES PROVISOIRES" in rendre_bilan(bilan)
    assert bilan.conforme, rendre_bilan(bilan)


@pytest.mark.parametrize("but,attendu", [
    ("Accueil avec les services et un bouton vers la galerie des pains",
     {"bouton"}),
    ("Page de contact avec un formulaire, et un lien vers la galerie",
     {"formulaire"}),
    ("une galerie de photos des pains", {"galerie"}),
    ("un menu menant a la page contact et un formulaire",
     {"menu", "formulaire"}),
])
def test_une_destination_n_est_pas_un_contenu(but, attendu):
    assert {m for m, _ in fidelite.exigences(but)} == attendu


def test_page_sans_main_ni_h1_n_est_pas_validee(tmp_path):
    c = crit.deduire("a.html", "une page", ["a.html"])
    (tmp_path / "a.html").write_text("<section>x</section>",
                                     encoding="utf-8")
    textes = [x.message for x in crit.manques(tmp_path, "a.html", c)]
    assert any("<main>" in t for t in textes)
    assert any("<h1>" in t for t in textes)


def test_finition_reverifie_les_criteres_et_compte_juste(tmp_path):
    """Une tache non validee (critere manquant) est reprise a la finition ;
    le tour de finition affiche ce qui reste VRAIMENT apres rejugement."""
    sans_lien = PAGE_CHANTIER
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- contact.html : le contact\n"
        "- style.css : les styles\n",
        bloc("index.html", sans_lien), bloc("index.html", sans_lien),
        bloc("contact.html", PAGE_CHANTIER.replace(
            "<main>", '<main><a href="index.html">Accueil</a>')),
        "```css fichier=style.css\n" + CSS_CHANTIER + "```",
        bloc("index.html", sans_lien)])           # finition : toujours rien
    bilan = ch.lancer("un site de deux pages")
    finition = bilan.tours[-1]
    assert finition.tache == "finition index.html"
    assert finition.bloquants == 1               # le lien manque toujours
    assert any(d.regle == "critere-non-tenu" for d in bilan.bloquants)
    assert ch.taches[0].etat == "a revoir"


def test_onclick_en_ligne_est_bloquant():
    page = PAGE_JUSTE.replace("<main>", '<main><button type="button" '
                              'onclick="go()">Aller</button>')
    d = [x for x in juger_fichier("index.html", page)
         if x.regle == "evenement-en-ligne"]
    assert d and d[0].gravite is GRAVITE.BLOQUANT


def test_cible_trop_petite_est_bloquante():
    r = {"violations": [{"id": "target-size", "impact": "serious",
                         "help": "t", "tags": ["wcag22aa", "wcag258"],
                         "nodes": [{"html": "<a>", "any": []}]}]}
    d = bac_a_sable.lire_axe(r, "a.html", "<a>x</a>")
    assert d[0].regle == "cible-trop-petite"
    assert d[0].gravite is GRAVITE.BLOQUANT


# ------------- second essai du chantier : extension du plan sans doublon
def test_lien_vers_le_style_prevu_sous_un_autre_chemin_est_corrige(tmp_path):
    page = PAGE_CHANTIER.replace('href="style.css"', 'href="css/style.css"')
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", page),
        "```css fichier=style.css\n" + CSS_CHANTIER + "```"])
    bilan = ch.lancer("une page d'accueil")
    assert [t.fichier for t in ch.taches] == ["index.html", CSS_STANDARD]
    assert 'href="assets/css/style.css"' in (tmp_path /
                                             "index.html").read_text()
    assert len(moteur.recus) == 3        # plan + 2 taches : aucun detour
    assert bilan.conforme, rendre_bilan(bilan)


def test_page_hors_plan_jamais_ajoutee(tmp_path):
    page = PAGE_CHANTIER.replace(
        "<main>", '<main><a href="gallery.html">Galerie</a>')
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- photos.html : la galerie\n"
        "- style.css : les styles\n",
        bloc("index.html", page), bloc("index.html", page)])
    try:
        ch.lancer("un site")
    except IndexError:
        pass                             # le faux modele n'a plus de reponse
    assert "gallery.html" not in [t.fichier for t in ch.taches]
    correction = moteur.recus[2][0]["content"]
    assert "[fichiers du plan" in correction and "photos.html" in correction


def test_second_script_jamais_ajoute(tmp_path):
    page = PAGE_CHANTIER.replace(
        "</body>", '<script src="js/app.js" defer></script>\n</body>')
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- style.css : les styles\n"
        "- script.js : le menu\n",
        bloc("index.html", page), bloc("index.html", page)])
    try:
        ch.lancer("un site")
    except IndexError:
        pass
    assert [t.fichier for t in ch.taches] == ["index.html", CSS_STANDARD,
                                              "assets/js/script.js"]


@pytest.mark.parametrize("texte,attendu", [
    ("un accueil presentant un menu de pains et des offres", set()),
    ("un menu de navigation en haut", {"menu"}),
    ("le menu du site", {"menu"}),
    ("un menu et un pied de page", {"menu", "pied de page"}),
])
def test_menu_de_pains_n_est_pas_une_navigation(texte, attendu):
    assert {m for m, _ in fidelite.exigences(texte)} == attendu


# ---- troisieme essai du chantier : lien vers l'UNIQUE fichier du role
@pytest.mark.parametrize("lien,fichiers,juste", [
    ("css/style.css", ["index.html", "styles.css"], "styles.css"),
    ("js/app.js", ["index.html", "script.js"], "script.js"),
    ("css/style.css", ["index.html", "a.css", "b.css"], None),   # ambigu
    ("galerie.html", ["index.html", "photos.html"], None),       # une page
])
def test_lien_vers_l_unique_fichier_du_meme_role(lien, fichiers, juste):
    attr = "src" if lien.endswith(".js") else "href"
    d = _d("index.html", 1, "fichier-absent",
           f'{attr}="{lien}" : ce fichier n\'existe pas')
    h = reparation.homonyme(d, fichiers)
    assert (h[2] if h else None) == juste


def test_chantier_redirige_le_style_et_le_script_du_plan(tmp_path):
    page = PAGE_JUSTE.replace(
        "</head>", '<link rel="stylesheet" href="css/style.css">\n</head>'
    ).replace("</body>", '<script src="js/app.js" defer></script>\n</body>')
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- styles.css : les styles\n"
        "- script.js : le script\n",
        bloc("index.html", page),
        "```css fichier=styles.css\n" + CSS_CHANTIER + "```",
        "```js fichier=script.js\nconst a = 1;\n```"])
    bilan = ch.lancer("une page d'accueil")
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert 'href="assets/css/styles.css"' in html
    assert 'src="assets/js/script.js"' in html
    assert ch.taches[0].etat == "fait" and ch.taches[0].tours == 1
    assert bilan.conforme, rendre_bilan(bilan)


# ---------------- troisieme essai : tache vide, CSS juge sur le rendu
CSS_BLOC = "```css fichier=style.css\n" + CSS_CHANTIER + "```"


def test_tache_sans_son_fichier_est_relancee(tmp_path):
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", PAGE_CHANTIER),
        bloc("index.html", PAGE_CHANTIER),     # au lieu de style.css !
        CSS_BLOC])
    bilan = ch.lancer("une page d'accueil")
    assert ch.taches[1].etat == "fait" and ch.taches[1].tours == 2
    relance = moteur.recus[3][0]["content"]
    assert "ne contenait PAS le fichier assets/css/style.css" in relance
    assert "tu as ecrit index.html" in relance
    assert bilan.conforme, rendre_bilan(bilan)


def test_css_juge_sur_le_rendu_avant_d_etre_verrouille(tmp_path,
                                                      monkeypatch):
    """Une cible trop petite vue par le navigateur sur une PAGE est
    corrigee dans la tache CSS — pas decouverte apres le verrou."""
    def navigateur_factice(racine, vus):
        f = Path(racine) / CSS_STANDARD
        css = f.read_text(encoding="utf-8") if f.exists() else ""
        if "min-height" in css:
            return []
        return [Defaut("index.html", 5, "cible-trop-petite",
                       GRAVITE.BLOQUANT, "cible de 18 px [axe-core]",
                       "WCAG 2.2 — 2.5.8", sources=("axe-core",))]
    monkeypatch.setattr(bac_a_sable, "juger", navigateur_factice)
    css_juste = CSS_CHANTIER + "a, button { min-height: 24px; }\n"
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", PAGE_CHANTIER),
        CSS_BLOC,
        "```css fichier=style.css\n" + css_juste + "```"])
    bilan = ch.lancer("une page d'accueil")
    assert [t.etat for t in ch.taches] == ["fait", "fait"]
    assert ch.taches[0].tours == 1            # la page n'est pas accusee
    # Depuis l'examen du 09/10, MAEL porte LUI-MEME les cibles a 24 px dans
    # la feuille (levier reparer-cibles-24px) : plus besoin d'un second tour.
    assert ch.taches[1].tours == 1
    css = (tmp_path / CSS_STANDARD).read_text(encoding="utf-8")
    assert "MAEL : zones cliquables" in css
    assert len(moteur.recus) == 3             # plan, page, CSS : rien d'autre
    assert bilan.conforme, rendre_bilan(bilan)


def test_finition_ecrit_le_fichier_jamais_ecrit(tmp_path):
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- style.css : les styles\n"
        "- script.js : le script\n",
        bloc("index.html", PAGE_CHANTIER.replace(
            "</body>", '<script src="script.js" defer></script>\n</body>')),
        CSS_BLOC,
        "Je ne sais pas.", "Toujours rien.",    # la tache script.js echoue
        "```js fichier=script.js\nconst a = 1;\n```"])   # la finition
    bilan = ch.lancer("une page d'accueil")
    assert (tmp_path / "assets/js/script.js").exists()
    assert ch.taches[2].etat == "fait"
    assert bilan.conforme, rendre_bilan(bilan)


# ---------- quatrieme essai : le but d'un script deduit des pages
PAGE_MENU = PAGE_CHANTIER.replace(
    "<main>", '<header><button type="button" id="bouton-menu" '
    'aria-expanded="false" aria-controls="menu">Menu</button>'
    '<nav id="menu" aria-label="Principale" hidden><a href="#">x</a></nav>'
    "</header><main>")


def test_but_du_script_deduit_des_commandes_des_pages(tmp_path):
    (tmp_path / "index.html").write_text(PAGE_MENU, encoding="utf-8")
    but, c = crit.pour_un_script(tmp_path, ["index.html"])
    assert "#bouton-menu ouvre et ferme #menu" in but
    assert [x.cible for x in c] == ["bouton-menu", "menu"]


def test_sans_commande_le_script_ne_doit_rien_viser(tmp_path):
    (tmp_path / "index.html").write_text(PAGE_CHANTIER, encoding="utf-8")
    but, c = crit.pour_un_script(tmp_path, ["index.html"])
    assert "ne vise AUCUN element absent" in but and c == []


def test_commande_vers_un_id_absent_ignoree(tmp_path):
    (tmp_path / "index.html").write_text(
        '<button aria-controls="fantome">x</button>', encoding="utf-8")
    assert crit.pour_un_script(tmp_path, ["index.html"])[1] == []


@pytest.mark.parametrize("js,ok", [
    ("document.getElementById('menu');", True),
    ("document.querySelector('nav#menu');", True),
    ("document.querySelector('[aria-controls=\"menu\"]');", True),
    ("// document.getElementById('menu');", False),
    ("document.getElementById('menu-2');", False),
])
def test_critere_vise(tmp_path, js, ok):
    (tmp_path / "a.js").write_text(js, encoding="utf-8")
    c = [crit.Critere("vise", "vise #menu", cible="menu")]
    assert crit.verifier(tmp_path, "a.js", c)[0][1] is ok


def test_tache_script_precisee_par_les_pages(tmp_path):
    js_faux = ("document.getElementById('galerie');\n")
    js_juste = ("const b = document.getElementById('bouton-menu');\n"
                "const m = document.getElementById('menu');\n"
                "b.addEventListener('click', () => { m.hidden = !m.hidden; "
                "b.setAttribute('aria-expanded', String(!m.hidden)); });\n")
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- style.css : les styles\n"
        "- script.js : le comportement interactif\n",
        bloc("index.html", PAGE_MENU.replace(
            "</body>", '<script src="script.js" defer></script>\n</body>')),
        CSS_BLOC,
        "```js fichier=script.js\n" + js_faux + "```",
        "```js fichier=script.js\n" + js_juste + "```"])
    bilan = ch.lancer("une page avec un menu")
    t = ch.taches[2]
    assert "#bouton-menu ouvre et ferme #menu" in t.but
    consigne = moteur.recus[3][0]["content"]
    assert "vise #bouton-menu" in consigne and "vise #menu" in consigne
    assert t.etat == "fait" and t.tours == 2
    assert bilan.conforme, rendre_bilan(bilan)


# --------------- la retouche : corriger les lignes, pas tout le fichier
from brain.codage import retouche as rt

TEXTE_30 = "\n".join(f"ligne {i}" for i in range(1, 31))


def _bl(fichier, ligne, regle="img-alt"):
    return Defaut(fichier, ligne, regle, GRAVITE.BLOQUANT, "x", "n")


def test_plages_autour_des_defauts_fusionnees():
    e = rt.plages([_bl("a.html", 10), _bl("a.html", 14), _bl("a.html", 25)],
                  "a.html", 30)
    assert [(x.debut, x.fin) for x in e] == [(7, 17), (22, 28)]


def test_extraits_numerotes():
    m = rt.montrer(TEXTE_30, [rt.Extrait("a.html", 2, 3)], "html")
    assert m == "```html fichier=a.html lignes=2-3\n2| ligne 2\n3| ligne 3\n```"


@pytest.mark.parametrize("defauts,nb,attendu", [
    ([_bl("a.html", 12)], 30, True),
    ([_bl("a.html", 12), _bl("a.html", 1, "critere-non-tenu")], 30, False),
    ([_bl("a.html", 12, "main")], 30, False),
    ([_bl("a.html", 5)], 10, False),                  # petit fichier
    ([_bl("a.html", n) for n in (4, 12, 20, 28)], 30, False),   # trop large
    ([], 30, False),
])
def test_retouche_eligible(defauts, nb, attendu):
    assert rt.eligible(defauts, "a.html", nb) is attendu


def test_retouche_appliquee_seulement_sur_la_plage_proposee(tmp_path):
    (tmp_path / "a.html").write_text(TEXTE_30 + "\n", encoding="utf-8")
    proposes = [rt.Extrait("a.html", 9, 11), rt.Extrait("a.html", 20, 21)]
    reponse = ("```retouche fichier=a.html lignes=20-21\n20| VINGT\n```\n"
               "```retouche fichier=a.html lignes=9-11\nNEUF\nDIX\nONZE\n"
               "DIX-BIS\n```\n"
               "```retouche fichier=a.html lignes=1-30\ntout efface\n```")
    faites, refus = rt.appliquer(Espace(tmp_path), reponse, proposes)
    lignes = (tmp_path / "a.html").read_text(encoding="utf-8").split("\n")
    assert len(faites) == 2
    assert lignes[8:12] == ["NEUF", "DIX", "ONZE", "DIX-BIS"]
    assert lignes[20] == "VINGT" and lignes[21] == "ligne 22"
    assert lignes[0] == "ligne 1"                    # plage 1-30 refusee
    assert any("non proposee" in r for r in refus)


def test_reponse_sans_retouche_ne_touche_a_rien(tmp_path):
    (tmp_path / "a.html").write_text(TEXTE_30 + "\n", encoding="utf-8")
    faites, refus = rt.appliquer(Espace(tmp_path), "Voici la correction.",
                                 [rt.Extrait("a.html", 9, 11)])
    assert faites == [] and refus
    assert (tmp_path / "a.html").read_text(encoding="utf-8") == TEXTE_30 + "\n"


PAGE_LONGUE = PAGE_CHANTIER.replace(
    "<main>", "<main>\n" + "\n".join(f"<p>Paragraphe {i}</p>"
                                     for i in range(12)) + "\n")


def test_chantier_corrige_par_retouche(tmp_path):
    fautif = PAGE_LONGUE.replace(' alt=""', "")
    lignes = fautif.split("\n")
    n = next(i for i, l in enumerate(lignes, 1) if "<img" in l)
    nb = len(lignes)
    debut, fin = max(1, n - rt.MARGE), min(nb, n + rt.MARGE)
    juste = "\n".join(lignes[debut - 1:fin]).replace("<img ", '<img alt="" ')
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", fautif),
        f"```retouche fichier=index.html lignes={debut}-{fin}\n{juste}\n```",
        CSS_BLOC])
    bilan = ch.lancer("une page d'accueil")
    t = ch.taches[0]
    assert t.etat == "fait" and t.tours == 2
    assert bilan.tours[1].mode.startswith("retouche")
    assert "[extraits a corriger]" in moteur.recus[2][0]["content"]
    assert "fichier=index.html lignes=" in moteur.recus[2][0]["content"]
    assert bilan.conforme, rendre_bilan(bilan)


def test_retouche_hors_plage_jamais_prise_pour_le_fichier(tmp_path):
    """Une retouche refusee (plage non proposee) ne doit JAMAIS etre lue
    comme le fichier entier : reecriture complete a la place."""
    fautif = PAGE_LONGUE.replace(' alt=""', "")
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", fautif),
        "```retouche fichier=index.html lignes=1-2\n<p>debris</p>\n```",
        bloc("index.html", PAGE_LONGUE),        # la reecriture complete
        CSS_BLOC])
    bilan = ch.lancer("une page d'accueil")
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "debris" not in html and "Paragraphe 11" in html
    assert bilan.tours[1].mode == "reecriture"
    assert bilan.conforme, rendre_bilan(bilan)


# ------- reprise du point 1 : pas de pages montrees a la tache d'un script
def test_gabarits_du_meme_type_que_le_fichier_de_la_tache():
    but = "le bouton #bouton-menu ouvre et ferme #menu, un site de 3 pages"
    assert any(g.fichier.endswith(".html") for g in savoir.choisir(but))
    pour_js = savoir.choisir(but, fichier="js/app.js")
    assert pour_js and all(g.fichier.endswith(".js") for g in pour_js)
    pour_css = savoir.choisir("la feuille de style du site",
                              fichier="style.css")
    assert all(g.fichier.endswith(".css") for g in pour_css)


def test_carte_ne_montre_pas_le_fichier_a_refaire(tmp_path):
    (tmp_path / "app.js").write_text(
        "document.getElementById('galerie');\n", encoding="utf-8")
    (tmp_path / "index.html").write_text('<main id="menu"></main>',
                                         encoding="utf-8")
    c = carte(tmp_path, sauf="app.js")
    assert "galerie" not in c and "app.js (a ecrire" in c and "#menu" in c


def test_consigne_d_un_script_sans_gabarit_de_page(tmp_path):
    def savoir_reel(texte, fichier=None):
        return savoir.pour_prompt(texte, fichier=fichier)
    moteur = FauxMoteur([
        "- index.html : l'accueil\n- style.css : les styles\n"
        "- script.js : le comportement du menu\n",
        bloc("index.html", PAGE_MENU.replace(
            "</body>", '<script src="script.js" defer></script>\n</body>')),
        CSS_BLOC,
        "```js fichier=script.js\n"
        "const b = document.getElementById('bouton-menu');\n"
        "const m = document.getElementById('menu');\n"
        "b.addEventListener('click', () => { m.hidden = !m.hidden; });\n```"])
    ch = Chantier(moteur, Espace(tmp_path), savoir=savoir_reel)
    ch.lancer("une page avec un menu")
    consigne_js = moteur.recus[3][0]["content"]
    assert "--- menu.js" in consigne_js
    assert ".html (" not in consigne_js.split("[savoir]")[1].split("[")[0]


# ------------- cinquieme essai : flux coupe, @import, 404, finition
from brain.codage.chantier import surveiller


@pytest.mark.parametrize("texte,attendu", [
    ("```js fichier=app.js\nconst a = 1;\n", "continuer"),
    ("```js fichier=app.js\nconst a = 1;\n```\n", "fini"),
    ("```html fichier=index.html\n<p>", "hors-tache"),
    ("Voici :\n```js\nconst a = 1;\n```\n", "continuer"),   # anonyme
    ("```js fichier=app.js\nx\n```\n```html fichier=index.html\n", "fini"),
])
def test_surveiller_le_flux(texte, attendu):
    assert surveiller(texte, "app.js") == attendu


class MoteurQuiDiffuse(FauxMoteur):
    """Rend chaque reponse en morceaux ; note jusqu'ou on l'a lue."""

    def __init__(self, reponses):
        super().__init__(reponses)
        self.lus = []

    def flux(self, *, systeme, messages, role_modele):
        texte = self.reponses.pop(0)
        self.recus.append(list(messages))
        lus = []
        self.lus.append(lus)

        def gen():
            for i in range(0, len(texte), 20):
                lus.append(texte[i:i + 20])
                yield texte[i:i + 20]
        return gen()


def test_generation_coupee_quand_le_modele_part_sur_un_autre_fichier(
        tmp_path):
    autres = "".join(bloc(f"p{i}.html", PAGE_CHANTIER) for i in range(4))
    moteur = MoteurQuiDiffuse([
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", PAGE_CHANTIER),
        autres,                                   # hors tache : coupe tot
        CSS_BLOC])
    ch = Chantier(moteur, Espace(tmp_path))
    bilan = ch.lancer("une page d'accueil")
    # lus[0] = index.html, lus[1] = la reponse hors tache (le plan n'est
    # pas lu en flux), lus[2] = la relance de style.css.
    lu = "".join(moteur.lus[1])
    assert len(lu) < len(autres) / 3              # coupe des le 1er bloc
    assert ch.taches[1].etat == "fait" and ch.taches[1].tours == 2
    assert bilan.conforme, rendre_bilan(bilan)


def test_generation_coupee_des_que_le_fichier_est_complet(tmp_path):
    reponse = CSS_BLOC + "\n" + bloc("index.html", PAGE_CHANTIER) * 3
    moteur = MoteurQuiDiffuse([
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", PAGE_CHANTIER), reponse])
    ch = Chantier(moteur, Espace(tmp_path))
    ch.lancer("une page d'accueil")
    assert len("".join(moteur.lus[1])) < len(CSS_BLOC) + 40


def test_import_d_un_fichier_absent_vu_et_retire(tmp_path):
    css = "@import url('mise-en-page.css');\nbody { color: #111; }\n"
    (tmp_path / "style.css").write_text(css, encoding="utf-8")
    d = [x for x in juger_fichier("style.css", css, dossier=tmp_path)
         if x.regle == "import-absent"]
    assert len(d) == 1 and d[0].ligne == 1
    faites = reparation.reparer(Espace(tmp_path), d, ["style.css"])
    assert len(faites) == 1
    assert "@import" not in (tmp_path / "style.css").read_text()
    assert "body" in (tmp_path / "style.css").read_text()


def test_import_mele_a_une_regle_jamais_supprime(tmp_path):
    css = "@import url('x.css'); body { color: #111; }\n"
    (tmp_path / "s.css").write_text(css, encoding="utf-8")
    d = _d("s.css", 1, "import-absent")
    assert reparation.reparer(Espace(tmp_path), [d], ["s.css"]) == []


def test_url_d_image_absente_dans_le_css(tmp_path):
    css = "header { background: url(images/fond.jpg); }\n"
    d = [x for x in juger_fichier("style.css", css, dossier=tmp_path)
         if x.regle == "fichier-absent"]
    assert d and 'url="images/fond.jpg"' in d[0].message


def test_404_attribue_a_la_feuille_qui_l_appelle():
    page = '<link rel="stylesheet" href="style.css">'
    css = {"style.css": "@import url('mise-en-page.css');\nbody{}\n"}
    assert bac_a_sable.origine_404("index.html", page, "mise-en-page.css",
                                   css) == ("style.css", 1, "import-absent")
    assert bac_a_sable.origine_404("index.html", page, "style.css", css)[0] \
        == "index.html"


def test_finition_confie_les_defauts_visuels_au_css(tmp_path, monkeypatch):
    """Cible trop petite vue sur index.html (verrouillee) a la finition :
    c'est style.css (non validee) qui est corrigee, pas la page."""
    moteur, ch = _chantier(tmp_path, [])
    ch.taches = [Tache("index.html", "l'accueil", etat="fait"),
                 Tache("style.css", "les styles", etat="a revoir")]
    d = Defaut("index.html", 5, "cible-trop-petite", GRAVITE.BLOQUANT, "x",
               "WCAG")
    assert ch._responsable(d) == "style.css"
    d2 = Defaut("index.html", 5, "ancre-absente", GRAVITE.BLOQUANT, "x", "n")
    assert ch._responsable(d2) == "index.html"


@pytest.mark.parametrize("gabarit", ["menu.js", "valider-formulaire.js",
                                     "fetch-api.js", "message-fenetres.js"])
def test_gabarits_js_ne_plantent_pas_sans_leurs_elements(gabarit):
    """Un script charge sur TOUTES les pages doit verifier que ses elements
    existent : notre savoir enseignait le plantage (menu.js, 5e essai)."""
    texte = (savoir.DOSSIER_GABARITS / gabarit).read_text(encoding="utf-8")
    acces = re.findall(r"(?:getElementById|querySelector)\([^)]*\)", texte)
    assert acces
    assert re.search(r"if\s*\(\s*!?\s*\w+\s*(?:&&|\|\||\))", texte) or \
        re.search(r"if\s*\(\s*\w+\s*\)", texte)


# ------------- comprendre la demande (raisonnement profond, piece 1)
from brain.codage.comprehension import comprendre, distance


@pytest.mark.parametrize("demande,exige", [
    ("un site avec un formulaire de contact et une galerie",
     {"formulaire", "galerie"}),
    ("un site avec un formulere de contacte et une gallerie",
     {"formulaire", "galerie"}),
    ("site boulangeri, page contct avec formulair, galeri foto",
     {"formulaire", "galerie"}),
    ("a website with a contact form and a photo gallery",
     {"formulaire", "galerie"}),
    ("a site with a navbar and a login page", {"menu", "connexion"}),
    # francais : « table » d'un restaurant n'est PAS un tableau HTML
    ("un site de restaurant pour reserver une table", set()),
    ("le menu de la semaine du restaurant", set()),
])
def test_banc_des_demandes_mal_ecrites(demande, exige):
    assert {m for m, _ in fidelite.exigences(comprendre(demande).texte)} \
        == exige


@pytest.mark.parametrize("demande,pages", [
    ("un site pour une boulangerie avec trois pages : un accueil, une "
     "galerie, et une page de contact avec un formulaire", 3),
    ("un site de 4 pages", 4),
    ("une seule page pour mon CV", 1),
    ("a three pages website", 3),
    ("une page de contact", None),            # decrit une page, ne compte pas
])
def test_nombre_de_pages(demande, pages):
    assert comprendre(demande).nb_pages == pages


def test_contradiction_signalee():
    c = comprendre("un site d'une seule page avec trois pages")
    assert c.nb_pages is None
    assert any("CONTRADICTION" in s and "1, 3" in s for s in c.suppositions)


def test_demande_vague_signalee():
    assert comprendre("fais moi un truc bien pour ma boutique").vague
    assert not comprendre("un site de 3 pages avec une galerie").vague


def test_corrections_ecrites_et_prudentes():
    c = comprendre("un formulere et une gallerie")
    assert "« formulere » lu comme « formulaire »" in c.suppositions
    assert "« gallerie » lu comme « galerie »" in c.suppositions
    # mots courts et mots sans voisin : jamais « corriges »
    # « pagnes » (le tissu) devenait « pages » : piege garde a vie.
    for phrase in ("un site pour ma boutique de pagnes et de bijoux",
                   "des photos de nos menus, des videos et des boutons",
                   "une gallerie marchande en ville"):
        assert all("pagnes" not in x for x in comprendre(phrase).corrections)
    assert comprendre("un site pour ma boutique de pagnes").corrections == []


def test_distance_d_edition():
    assert distance("galerie", "gallerie") == 1
    assert distance("formulaire", "formulair") == 1
    assert distance("contact", "contcat") == 1            # transposition
    assert distance("abc", "xyz") == 3


def test_demande_mal_ecrite_tenue_par_le_juge(tmp_path):
    apres = {"index.html": fidelite.compter("<main><h1>x</h1></main>")}
    d = fidelite.non_tenues("un site avec un formulere de contacte", apres)
    assert [x.regle for x in d] == ["demande-non-tenue"]


def test_plan_relance_si_le_nombre_de_pages_ne_tient_pas(tmp_path):
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- contact.html : le contact\n",
        "- index.html : l'accueil\n- galerie.html : la galerie\n"
        "- contact.html : le contact\n"])
    taches = ch.planifier("un site de trois pages")
    assert [t.fichier for t in taches if t.fichier.endswith(".html")] == [
        "index.html", "galerie.html", "contact.html"]
    assert "EXACTEMENT 3 page(s)" in moteur.recus[0][0]["content"]
    assert "il en faut EXACTEMENT 3" in moteur.recus[1][0]["content"]


def test_plan_toujours_faux_devient_une_supposition(tmp_path):
    deux = "- index.html : l'accueil\n- contact.html : le contact\n"
    moteur, ch = _chantier(tmp_path, [deux, deux])
    ch.planifier("un site de trois pages")
    assert any("2 page(s) HTML au lieu des 3" in s for s in ch.suppositions)


def test_suppositions_montrees_au_modele_et_au_bilan(tmp_path):
    moteur, ch = _chantier(tmp_path, [
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", PAGE_CHANTIER), CSS_BLOC])
    bilan = ch.lancer("une page d'acceuil avec une gallerie")
    assert "[demande comprise par MAEL]" in moteur.recus[0][0]["content"]
    assert "[suppositions de MAEL" in moteur.recus[1][0]["content"]
    assert "« gallerie » lu comme « galerie »" in rendre_bilan(bilan)


def test_galerie_marchande_n_est_pas_une_galerie_d_images():
    assert fidelite.exigences("une boutique dans la galerie marchande") == []
    assert fidelite.exigences(comprendre("une gallerie marchande").texte) == []
    assert [m for m, _ in fidelite.exigences("une galerie d'art")] == \
        ["galerie"]


# ------- sixieme essai : generation sans fin (3 600 jetons, 22 minutes)
from brain.codage import chantier as module_chantier


def test_generation_trop_longue_coupee():
    texte = "```html fichier=index.html\n" + "<p>texte</p>\n" * 1000
    assert surveiller(texte, "index.html") == "trop-long"


def test_generation_en_boucle_coupee():
    texte = ("```html fichier=index.html\n<main>\n"
             + "<p>Bienvenue</p>\n<br>\n" * 6)
    assert surveiller(texte, "index.html") == "boucle"


def test_liste_normale_n_est_pas_une_boucle():
    texte = "```html fichier=index.html\n<ul>\n" + "".join(
        f"<li>Pain {i}</li>\n" for i in range(12))
    assert surveiller(texte, "index.html") == "continuer"


def test_relance_dit_pourquoi_la_generation_a_ete_coupee(tmp_path,
                                                         monkeypatch):
    # Juste au-dessus d'une vraie page : la page passe, le flot sans fin non.
    monkeypatch.setattr(module_chantier, "LONGUEUR_MAX",
                        len(bloc("index.html", PAGE_CHANTIER)) + 50)
    sans_fin = "```css fichier=style.css\n" + "".join(
        f".c{i} {{ color: #111; }}\n" for i in range(400))
    moteur = MoteurQuiDiffuse([
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", PAGE_CHANTIER), sans_fin, CSS_BLOC])
    ch = Chantier(moteur, Espace(tmp_path))
    bilan = ch.lancer("une page d'accueil")
    assert "TROP LONGUE" in moteur.recus[3][0]["content"]
    assert ch.taches[1].etat == "fait" and bilan.conforme


# ---------------- le savoir adapte au plan (liens et scripts du projet)
from brain.codage.chantier import adapter_savoir

GABARIT_MENU = """--- menu.html ---
<header>
  <nav id="menu" aria-label="Principale" hidden>
    <ul>
      <li><a href="/">Accueil</a></li>
      <li><a href="/produits">Produits</a></li>
    </ul>
  </nav>
</header>
<script src="menu.js" defer></script>
"""


def test_savoir_adapte_aux_pages_du_plan():
    s = adapter_savoir(GABARIT_MENU, ["index.html", "photos.html"],
                       "index.html")
    assert '<a href="photos.html">Photos</a>' in s
    assert "/produits" not in s and "menu.js" not in s


def test_savoir_adapte_depuis_un_sous_dossier():
    s = adapter_savoir(GABARIT_MENU, ["index.html", "pages/contact.html"],
                       "pages/contact.html")
    assert 'href="../index.html"' in s and 'href="contact.html"' in s


def test_savoir_sans_menu_ni_script_inchange():
    brut = "--- base.css ---\nbody { color: #111; }\n"
    assert adapter_savoir(brut, ["index.html"], "style.css") == brut


# ------------- couche 7 : la justesse par l'execution (sans Docker ici)
from brain.codage import execution

APP_FLASK = '''from flask import Flask
app = Flask(__name__)


@app.route("/")
def accueil():
    return "ok"


@app.route("/produits/<int:id>")
def produit(id):
    return str(id)


@app.route("/contact", methods=["POST"])
def contact():
    return "merci"
'''


def test_fumee_importe_chaque_module_et_appelle_les_routes_get():
    code = execution.fumee({"app.py": APP_FLASK, "outils/calcul.py": "x=1",
                            "test_app.py": "def test(): pass"})
    assert "MODULES = ['app', 'outils.calcul']" in code
    assert "('app', 'app', '/')" in code
    assert "/produits" not in code          # route avec parametre : non
    assert "/contact" not in code           # POST seulement : non
    compile(code, "fumee", "exec")           # le test genere est du Python


def test_fumee_vide_sans_python():
    assert execution.fumee({"index.html": "<p>"}) == ""


SORTIE_PYTEST = """F.                                                                       [100%]
=================================== FAILURES ===================================
__________________________________ test_total __________________________________
test_app.py:5: in test_total
    assert calcul.total([1, 2]) == 3
calcul.py:2: in total
    return sum(x) + 1
E   assert 4 == 3
=========================== short test summary info ============================
FAILED test_app.py::test_total - assert 4 == 3
1 failed, 1 passed in 0.12s
"""


def test_lire_pytest_vise_la_ligne_fautive_du_projet():
    d, comptes = execution.lire_pytest(
        SORTIE_PYTEST, {"app.py", "calcul.py", "test_app.py"})
    assert comptes == {"passed": 1, "failed": 1, "error": 0}
    assert [(x.fichier, x.ligne, x.regle) for x in d] == \
        [("calcul.py", 2, "test-echoue")]
    assert "test_total" in d[0].message and "assert 4 == 3" in d[0].message
    assert d[0].gravite is GRAVITE.BLOQUANT


def test_lire_pytest_erreur_d_import():
    sortie = ("E\n==== ERRORS ====\n___ ERROR collecting test_app.py ___\n"
              "app.py:3: in <module>\n    import inexistant\n"
              "E   ModuleNotFoundError: No module named 'inexistant'\n"
              "==== short test summary info ====\n"
              "ERROR test_app.py - ModuleNotFoundError: No module named "
              "'inexistant'\n1 error in 0.05s\n")
    d, comptes = execution.lire_pytest(sortie, {"app.py", "test_app.py"})
    assert comptes["error"] == 1
    assert d and d[0].fichier == "app.py" and d[0].ligne == 3


def test_rien_a_executer_sans_python(tmp_path):
    (tmp_path / "index.html").write_text("<p>", encoding="utf-8")
    assert execution.executer(tmp_path, ["index.html"]) == []
    assert execution.limites() == []


def test_docker_absent_le_dit(tmp_path, monkeypatch):
    monkeypatch.delenv("MAEL_SANS_EXECUTION", raising=False)
    monkeypatch.setattr(execution, "docker_pret",
                        lambda: "Docker ne repond pas (Docker Desktop arrete ?)")
    (tmp_path / "app.py").write_text(APP_FLASK, encoding="utf-8")
    assert execution.executer(tmp_path, ["app.py"]) == []
    assert any("NON executes" in l and "Docker" in l
               for l in execution.limites())


def test_memoire_insuffisante_le_dit(tmp_path, monkeypatch):
    monkeypatch.delenv("MAEL_SANS_EXECUTION", raising=False)
    monkeypatch.setattr(execution, "docker_pret", lambda: "")
    monkeypatch.setattr(execution, "memoire_libre_go", lambda: 0.6)
    (tmp_path / "app.py").write_text(APP_FLASK, encoding="utf-8")
    assert execution.executer(tmp_path, ["app.py"]) == []
    assert any("memoire insuffisante (0.6 Go" in l
               for l in execution.limites())


def test_memoire_libre_se_lit():
    m = execution.memoire_libre_go()
    assert m is None or m > 0


# ------------- le mode MISSIONS : MAEL execute et documente lui-meme
from brain.codage.missions import Missions

MISSIONS_YAML = """missions:
  - id: 01-accueil
    titre: une page d'accueil
    demande: une page d'accueil
    attendu: une page conforme
  - id: 02-accueil-bis
    titre: une seconde page
    demande: une page d'accueil
"""


def _reponses_une_page():
    return ["- index.html : l'accueil\n- style.css : les styles\n",
            bloc("index.html", PAGE_CHANTIER), CSS_BLOC]


def test_missions_executees_et_documentees(tmp_path):
    (tmp_path / "missions.yaml").write_text(MISSIONS_YAML, encoding="utf-8")
    moteur = FauxMoteur(_reponses_une_page() * 2)
    racine = tmp_path / "MAEL-missions"
    ms = Missions(moteur, racine, tmp_path / "missions.yaml").lancer()
    assert [m.etat for m in ms] == ["faite", "faite"]
    assert [m.verdict for m in ms] == ["CONFORME", "CONFORME"]
    j = (racine / "01-accueil" / "JOURNAL.md").read_text(encoding="utf-8")
    for titre in ("## Mon plan", "## Deroule", "## Ce que je n'ai PAS pu",
                  "## Mes chiffres", "une page conforme"):
        assert titre in j
    assert (racine / "01-accueil" / "index.html").exists()
    r = (racine / "RAPPORT.md").read_text(encoding="utf-8")
    assert "Missions terminees : 2 / 2 — conformes : 2" in r
    assert "[01-accueil](01-accueil/JOURNAL.md)" in r


def test_missions_reprise_ne_refait_pas(tmp_path):
    (tmp_path / "missions.yaml").write_text(MISSIONS_YAML, encoding="utf-8")
    racine = tmp_path / "M"
    Missions(FauxMoteur(_reponses_une_page() * 2), racine,
             tmp_path / "missions.yaml").lancer()
    moteur = FauxMoteur([])                  # aucune reponse : rien a refaire
    ms = Missions(moteur, racine, tmp_path / "missions.yaml").lancer()
    assert [m.etat for m in ms] == ["faite", "faite"] and not moteur.recus


def test_une_mission_qui_plante_n_arrete_pas_les_suivantes(tmp_path):
    (tmp_path / "missions.yaml").write_text(MISSIONS_YAML, encoding="utf-8")

    class MoteurCapricieux(FauxMoteur):
        def completer(self, **k):
            if not self.recus:
                self.recus.append("plante")
                raise RuntimeError("le modele s'est arrete")
            return super().completer(**k)
    moteur = MoteurCapricieux(_reponses_une_page())
    racine = tmp_path / "M"
    ms = Missions(moteur, racine, tmp_path / "missions.yaml").lancer()
    assert ms[0].etat == "echec" and ms[1].verdict == "CONFORME"
    j = (racine / "01-accueil" / "JOURNAL.md").read_text(encoding="utf-8")
    assert "La mission a plante" in j and "le modele s'est arrete" in j


@pytest.mark.parametrize("lien,juste", [
    ("/gallery", "gallery.html"), ("/contact", "contact.html"),
    ("/", "index.html"), ("/produits", None),
])
def test_lien_de_serveur_vers_la_page_de_meme_nom(lien, juste):
    d = _d("index.html", 16, "fichier-absent",
           f'href="{lien}" : ce fichier n\'existe pas')
    h = reparation.homonyme(d, ["index.html", "gallery.html",
                                "contact.html"])
    assert (h[2] if h else None) == juste


# ------------- MAEL SE RELIT : ses echecs, son diagnostic, ses lecons
import json as _json

import yaml as _yaml

from brain.codage import lecons as lc


def test_le_lecteur_du_plan_dit_pourquoi_il_ecarte_une_ligne():
    rep = lc.expliquer_plan("- /app/api.py : l'API Flask\n"
                            "- tests/test_api.py : les tests\n"
                            "Voici mon plan.\n- notes.docx : la doc\n"
                            "- tests/test_api.py : encore")
    # Depuis le 09/10 le « / » du debut est retire (plan-chemins-tolerants).
    assert [ok for _l, ok, _r in rep] == [True, True, False, False, False]
    assert "pas au format" in rep[2][2]
    assert "extension .docx" in rep[3][2] and "doublon" in rep[4][2]


@pytest.mark.parametrize("fichier,message,famille", [
    ("photos.html", "critere de la tache non tenu : mene a contact.html : x",
     "lien-navigation-manquant"),
    ("footer.html", "critere de la tache non tenu : a un <main> (x)",
     "fragment-traite-en-page"),
    ("about.html", "critere de la tache non tenu : a un <h1> (x)",
     "structure-de-page"),
    ("a.html", "critere de la tache non tenu : charge style.css : x",
     "ressource-non-chargee"),
    ("a.html", 'href="style.css" : ce fichier n\'existe pas (lien casse)',
     "fichier-du-plan-jamais-ecrit"),
    ("a.html", 'href="/mentions" : ce fichier n\'existe pas (lien casse)',
     "lien-casse"),
    ("app.js", "erreur a l'execution : Cannot read properties of null",
     "script-plante"),
    ("a.html", "contraste mesure 2.63:1", "contraste"),
])
def test_les_echecs_sont_ranges_par_famille(fichier, message, famille):
    c = lc.Constat("m", fichier, 1, message)
    assert lc.classer(c, {"a.html", "style.css"}, {"a.html"}) == famille


def test_le_diagnostic_se_lit_et_un_format_non_tenu_est_garde():
    f = lc.Famille("plan-illisible", "t")
    lc.lire_diagnostic("**CAUSE** : le plan exige un caractere\n"
                       "ORIGINE : Programme (le lecteur)\n"
                       "**LEVIER** : 1. plan-chemins-tolerants", f)
    assert (f.origine, f.levier) == ("programme", "plan-chemins-tolerants")
    assert f.lecon.startswith("faire accepter au lecteur du plan")
    a = lc.Famille("plan-illisible", "t")
    lc.lire_diagnostic("CAUSE : c\nORIGINE : programme\nLEVIER : AUCUN\n"
                       "LEÇON : un lecteur du plan qui lit aussi un arbre", a)
    assert a.levier == "AUCUN" and a.lecon.startswith("un lecteur du plan")
    g = lc.Famille("y", "t")
    lc.lire_diagnostic("Je pense que c'est le modele.", g)
    assert not g.lecon and g.brut == "Je pense que c'est le modele."


JOURNAL_RATE = """# Mission 01-site

## Deroule (chaque appel au modele)

| tour | tache | mode | duree | bloquants | notes |
|---|---|---|---|---|---|
| 1 | index.html | ecriture | 90 s | 0 | — |
| 2 | style.css | ecriture | 600 s | 1 | generation coupee (trop-long) |

## Ce qui reste a corriger

- `index.html:1` critere de la tache non tenu : mene a contact.html : <a href="contact.html"> (critere)
- `index.html:7` href="style.css" : ce fichier n'existe pas (lien casse)

## Ce que je n'ai PAS pu verifier
"""


def _racine_missions(tmp_path):
    racine = tmp_path / "MAEL-missions"
    (racine / "01-site" / ".mael").mkdir(parents=True)
    (racine / "02-api").mkdir()
    (racine / "01-site" / "JOURNAL.md").write_text(JOURNAL_RATE,
                                                   encoding="utf-8")
    (racine / "01-site" / "index.html").write_text(
        '<link rel="stylesheet" href="style.css"><a href="index.html">',
        encoding="utf-8")
    (racine / "01-site" / ".mael" / "chantier.json").write_text(_json.dumps(
        {"taches": [
            {"fichier": "index.html", "but": "l'accueil", "etat": "a revoir",
             "tours": 2, "criteres": [
                 {"texte": "mene a contact.html : <a href=\"contact.html\">"}]},
            {"fichier": "style.css", "but": "les styles", "etat": "a revoir",
             "tours": 1, "secondes": 600}]}), encoding="utf-8")
    (racine / "missions-etat.json").write_text(_json.dumps({
        "01-site": {"verdict": "NON CONFORME", "demande": "un site"},
        "02-api": {"verdict": "RIEN PRODUIT",
                   "demande": "une API Flask avec ses tests"}}),
        encoding="utf-8")
    return racine


DIAG = "CAUSE : {c}\nORIGINE : {o}\nLEVIER : {l}"
NAV_OK = DIAG.format(c="le modele n'a pas suivi le critere de sa consigne",
                     o="modele", l="1")       # rappel-criteres-en-fin
CSS_OK = DIAG.format(c="chaque ecriture de style.css a ete coupee, trop "
                     "longue", o="modele", l="fichier-court-demande")
PLAN_OK = DIAG.format(c="le modele n'a ecrit aucune ligne au format liste "
                      "de fichiers", o="modele", l="**plan-selon-la-demande**")


def test_mael_se_relit_et_ecrit_ses_lecons(tmp_path):
    racine = _racine_missions(tmp_path)
    moteur = FauxMoteur([
        "Voici mon plan : une API et ses tests.",  # plan rejoue
        NAV_OK, CSS_OK, PLAN_OK])
    familles = lc.SeRelire(moteur, racine).lancer()
    assert {f.cle for f in familles} == {"lien-navigation-manquant",
                                         "fichier-du-plan-jamais-ecrit",
                                         "plan-illisible"}
    assert all(f.essais == 1 and not f.refus for f in familles)
    # la preuve du plan : rejoue, garde, et explique ligne par ligne
    assert (racine / "02-api" / ".mael" / "plan-brut.txt").exists()
    plan = next(f for f in familles if f.cle == "plan-illisible")
    assert "pas au format" in plan.preuves[0]
    assert "aucune ligne de la reponse" in plan.faits[0].texte
    # la consigne et le fichier reel sont montres au modele
    nav = next(f for f in familles if f.cle == "lien-navigation-manquant")
    assert "criteres ecrits dans la consigne" in nav.preuves[0]
    assert ("vraiment presents dans le fichier : index.html, style.css"
            in nav.preuves[0])
    css = next(f for f in familles if f.cle == "fichier-du-plan-jamais-ecrit")
    assert "generation coupee (trop-long)" in css.preuves[0]
    assert "COUPES par MAEL (trop-long)" in css.faits[0].texte
    # chaque diagnostic dans une conversation neuve, faits etablis compris
    assert all(len(m) == 1 for m in moteur.recus)
    assert "FAITS ETABLIS" in moteur.recus[1][0]["content"]
    bilan = (racine / "BILAN-DE-MAEL.md").read_text(encoding="utf-8")
    assert "Levier choisi" in bilan and "accepte au 1e essai" in bilan
    assert "LEVIERS possibles" in moteur.recus[1][0]["content"]
    l = _yaml.safe_load((racine / "lecons.yaml").read_text(encoding="utf-8"))
    assert len(l["lecons"]) == 3
    assert all(x["etat"] == "proposee" for x in l["lecons"])
    assert {x["levier"] for x in l["lecons"]} == {
        "rappel-criteres-en-fin", "fichier-court-demande",
        "plan-selon-la-demande"}


def _famille_nav():
    f = lc.Famille("lien-navigation-manquant", "menu incomplet")
    f.ajouter_fait(lc.etablir_fait(
        "lien-navigation-manquant",
        lc.Constat("m", "photos.html", 1, "critere de la tache non tenu : "
                   "mene a contact.html : <a> (critere de la tache)"),
        {"criteres": [{"texte": "mene a contact.html : <a>"}]}))
    return f


# Les diagnostics REELS de phi4-mini du 08/10/2026 : le juge les refuse.
@pytest.mark.parametrize("cause,levier,raison", [
    ("le contraste insuffisant rend le texte difficile a lire",
     "rappel-criteres-en-fin", "ta CAUSE ne s'appuie sur aucun fait"),
    # 4e essai reel : la cause repetait le titre de la faiblesse
    ("une page ne mene pas aux autres pages du plan (menu incomplet)",
     "rappel-criteres-en-fin", "ta CAUSE ne s'appuie sur aucun fait"),
])
def test_le_juge_refuse_un_diagnostic_faux(cause, levier, raison):
    f = _famille_nav()
    f.cause, f.levier = cause, levier
    assert any(raison in r for r in lc.juger_diagnostic(f))


def test_une_cause_qui_recopie_la_faiblesse_est_refusee():
    # 5e essai reel : acceptee a tort, le titre contient « lien », « existe »
    f = lc.Famille("lien-casse", lc.TITRES["lien-casse"])
    f.ajouter_fait(lc.etablir_fait("lien-casse", lc.Constat(
        "04", "footer.html", 5, 'href="/mentions-legales" : ce fichier '
        "n'existe pas"), None))
    lc.lire_diagnostic("CAUSE : un lien vers un fichier qui n'existe pas\n"
                       "LEVIER : reparer-lien-hors-plan", f)
    assert any("recopie la faiblesse" in r for r in lc.juger_diagnostic(f))
    lc.lire_diagnostic("CAUSE : footer.html vise /mentions-legales, une page "
                       "absente du plan\nLEVIER : reparer-lien-hors-plan", f)
    assert lc.juger_diagnostic(f) == []


def test_l_origine_est_celle_du_levier_et_plus_une_question():
    f = _famille_nav()
    # une ligne ORIGINE ecrite quand meme par le modele est ignoree
    lc.lire_diagnostic(NAV_OK.replace("ORIGINE : modele", "ORIGINE : code"), f)
    assert f.origine == "consigne"            # rappel-criteres-en-fin
    assert lc.juger_diagnostic(f) == []
    assert "ORIGINE" not in lc.SYSTEME_DIAGNOSTIC.split("Un LEVIER")[0]


# 4e essai reel : le BON levier, refuse pour une origine fausse. Sans la
# question ORIGINE, ces deux diagnostics passent.
@pytest.mark.parametrize("famille,fait,cause,levier", [
    ("fragment-traite-en-page",
     lambda: lc.etablir_fait("fragment-traite-en-page", lc.Constat(
         "04", "header.html", 1, "critere de la tache non tenu : a un "
         "<main> (x)"), None),
     "Les morceaux de page sont traites comme des pages completes et la "
     "consigne leur exige un <main>", "fragments-sans-criteres-de-page"),
    ("script-plante",
     lambda: lc.etablir_fait("script-plante", lc.Constat(
         "06", "faq.js", 47, "erreur a l'execution : Cannot read properties "
         "of null"), None),
     "Le script ajoute un ecouteur a un element n'existant pas (null).",
     "script-garde-ses-elements"),
])
def test_le_bon_levier_passe_sans_question_d_origine(famille, fait, cause,
                                                     levier):
    f = lc.Famille(famille, "t")
    f.ajouter_fait(fait())
    lc.lire_diagnostic(f"CAUSE : {cause}\nLEVIER : {levier}", f)
    assert lc.juger_diagnostic(f) == []


def _famille_plan():
    f = lc.Famille("plan-illisible", "plan vide")
    f.ajouter_fait(lc.fait_chemins_barre(2, 2))     # le fait du 08/10
    return f


# Les diagnostics ACCEPTES a tort au 2e essai reel du 08/10/2026.
def test_le_juge_refuse_une_lecon_a_contresens():
    f = _famille_plan()
    f.cause = ("Le lecteur du plan de MAEL n'exclut pas correctement les "
               "chemins commencant par « / » comme requis.")
    f.origine, f.levier = "consigne", "AUCUN"
    f.lecon = ("Je vais m'assurer que le lecteur du plan respecte strictement "
               "les consignes de chemin, en excluant uniquement les chemins "
               "qui commencent par « / ».")
    raisons = lc.juger_diagnostic(f)
    assert any("contresens" in r and "GARDER" in r for r in raisons)
    f.origine = "programme"
    f.lecon = "le lecteur du plan retire le « / » du debut d'un chemin"
    assert lc.juger_diagnostic(f) == []
    # le meme diagnostic par un LEVIER : rien de libre a juger
    f.levier = "plan-chemins-tolerants"
    assert lc.juger_diagnostic(f) == []


def test_ajouter_a_la_consigne_un_critere_deja_ecrit_est_un_contresens():
    f = _famille_nav()
    f.cause = "le modele n'a pas suivi les consignes de liens dans les pages."
    f.origine, f.levier = "consigne", "AUCUN"
    f.lecon = ("je vais verifier que chaque lien est correctement insere dans "
               "la consigne avant de l'envoyer au modele.")
    assert any("DEJA ecrit dans la consigne" in r
               for r in lc.juger_diagnostic(f))


def test_le_juge_refuse_une_lecon_generale():
    f = lc.Famille("contraste", "t", cause="c", origine="modele",
                   levier="AUCUN", lecon="Assurez-vous toujours que le contraste respecte les "
                         "normes WCAG, en particulier le seuil de 4.5:1.")
    assert any("LECON est generale" in r for r in lc.juger_diagnostic(f))


def test_le_levier_doit_etre_dans_la_liste_de_la_faiblesse():
    f = _famille_nav()
    lc.lire_diagnostic(NAV_OK.replace("LEVIER : 1", "LEVIER : palette-mesuree"),
                       f)
    assert any("n'est pas dans la liste" in r for r in lc.juger_diagnostic(f))
    g = _famille_nav()
    lc.lire_diagnostic(NAV_OK.replace("LEVIER : 1", "LEVIER : 9"), g)
    assert g.levier.startswith("?")
    assert any("n'est pas dans la liste" in r for r in lc.juger_diagnostic(g))


def test_le_levier_corrige_ce_que_les_faits_designent():
    f = lc.Famille("plan-illisible", "t")
    f.ajouter_fait(lc.Fait("seul le programme est en faute", ("programme",),
                           r"lecteur"))
    lc.lire_diagnostic("CAUSE : le lecteur du plan ecarte tout\n"
                       "LEVIER : plan-chemins-relatifs", f)
    assert any("change la consigne, mais le fait etabli designe le "
               "programme" in r for r in lc.juger_diagnostic(f))
    lc.lire_diagnostic("CAUSE : le lecteur du plan ecarte tout\n"
                       "LEVIER : plan-chemins-tolerants", f)
    assert lc.juger_diagnostic(f) == []


# Le diagnostic du fait historique du 08/10 (chemins en « / » ecartes).
PLAN_BARRE = DIAG.format(c="le lecteur du plan ecarte les chemins qui "
                         "commencent par /", o="programme",
                         l="**plan-chemins-tolerants**")


def test_aucun_levier_sans_proposition_est_refuse_avec_il_est_note():
    f = _famille_plan()
    lc.lire_diagnostic(PLAN_BARRE.replace("**plan-chemins-tolerants**",
                                          "AUCUN"), f)
    assert any("levier qui manque" in r for r in lc.juger_diagnostic(f))
    g = _famille_plan()
    lc.lire_diagnostic(PLAN_BARRE.replace("**plan-chemins-tolerants**", "AUCUN")
                       + "\nLECON : le lecteur du plan lit aussi un arbre de "
                       "dossiers", g)
    assert lc.juger_diagnostic(g) == []


def test_chaque_faiblesse_a_ses_leviers():
    from brain.codage import leviers
    for cle in lc.TITRES:
        if cle != "autre":
            assert leviers.pour(cle), cle
    for l in leviers.CATALOGUE:
        assert l.origine in {"consigne", "programme"}
        assert set(l.familles) <= set(lc.TITRES)


@pytest.mark.parametrize("reponse,attendu", [
    ("2", "menu-commun-a-recopier"), ("2. menu-commun-a-recopier",
     "menu-commun-a-recopier"), ("`reparer-liens-du-menu`",
     "reparer-liens-du-menu"), ("aucun.", "AUCUN"), ("7", ""),
    ("je ne sais pas", ""),
])
def test_le_choix_du_levier_se_lit(reponse, attendu):
    from brain.codage import leviers
    assert leviers.lire(reponse, leviers.pour(
        "lien-navigation-manquant")) == attendu


def test_le_juge_accepte_un_diagnostic_appuye_sur_les_faits():
    f = _famille_nav()
    lc.lire_diagnostic(NAV_OK, f)
    assert lc.juger_diagnostic(f) == []


def test_un_diagnostic_refuse_est_refait_avec_les_raisons(tmp_path):
    racine = _racine_missions(tmp_path)
    faux = DIAG.format(c="le contraste est faible", o="code",
                       l="respecte toujours les normes")
    moteur = FauxMoteur(["Voici mon plan : une API et ses tests.",
                         faux, NAV_OK,          # refuse, puis accepte
                         faux, faux,            # refuse deux fois
                         PLAN_OK])
    familles = {f.cle: f for f in lc.SeRelire(moteur, racine).lancer()}
    nav = familles["lien-navigation-manquant"]
    assert nav.essais == 2 and not nav.refus
    relance = moteur.recus[2][0]["content"]
    assert "[REFUSE par le juge de MAEL]" in relance
    assert "n'est pas dans la liste" in relance
    css = familles["fichier-du-plan-jamais-ecrit"]
    assert css.essais == 2 and css.refus
    l = _yaml.safe_load((racine / "lecons.yaml").read_text(encoding="utf-8"))
    etats = {x["famille"]: x["etat"] for x in l["lecons"]}
    assert etats == {"lien-navigation-manquant": "proposee",
                     "plan-illisible": "proposee",
                     "fichier-du-plan-jamais-ecrit": "refusee par le juge"}
    bilan = (racine / "BILAN-DE-MAEL.md").read_text(encoding="utf-8")
    assert "REFUSE apres 2 essai(s), lecon NON retenue" in bilan
    assert "accepte au 2e essai" in bilan


def test_une_lecon_validee_n_est_jamais_ecrasee(tmp_path):
    chemin = tmp_path / "lecons.yaml"
    chemin.write_text(_yaml.safe_dump({"lecons": [
        {"famille": "contraste", "lecon": "ancienne", "etat": "validee"}]}),
        encoding="utf-8")
    f = lc.Famille("contraste", "t", lecon="nouvelle", origine="modele",
                   cause="c")
    g = lc.Famille("script-plante", "t", lecon="verifie l'element",
                   origine="modele", cause="c")
    lc.ecrire_lecons(chemin, [f, g])
    l = {x["famille"]: x for x in _yaml.safe_load(
        chemin.read_text(encoding="utf-8"))["lecons"]}
    assert l["contraste"]["lecon"] == "ancienne"
    assert l["script-plante"]["etat"] == "proposee"


def test_un_plan_illisible_laisse_sa_trace_et_sa_raison(tmp_path):
    (tmp_path / "missions.yaml").write_text(
        "missions:\n  - id: 01-api\n    demande: une API\n", encoding="utf-8")
    racine = tmp_path / "M"
    Missions(FauxMoteur(["Voici mon plan : une API et ses tests."]), racine,
             tmp_path / "missions.yaml").lancer()
    assert (racine / "01-api" / ".mael" / "plan-brut.txt").read_text(
        encoding="utf-8") == "Voici mon plan : une API et ses tests."
    j = (racine / "01-api" / "JOURNAL.md").read_text(encoding="utf-8")
    assert "**Arret** : le chef de chantier n'a donne aucun plan lisible" in j


# ------------- APPLIQUER les lecons (leviers) puis les VERIFIER
from brain.codage import leviers as lv
from brain.codage.chantier import _debut_sain
from brain.codage.verification import FAIT, RAPPORT_VERIF, Verification


def test_les_leviers_consigne_parlent_selon_le_fichier():
    actifs = {"liens-du-plan-seulement", "palette-mesuree",
              "cibles-24px-dans-la-consigne"}
    pages = ["index.html", "contact.html"]
    html = dict(lv.consignes(actifs, "contact.html", pages))
    assert "index.html, contact.html" in html["liens-du-plan-seulement"]
    css = dict(lv.consignes(actifs, "style.css", pages))
    assert set(css) == {"palette-mesuree", "cibles-24px-dans-la-consigne"}
    assert "#1f2937 sur #ffffff (14.7:1)" in css["palette-mesuree"]
    assert lv.consignes(actifs, "app.js", pages) == []
    assert lv.consignes(set(), "style.css", pages) == []


def test_la_palette_donnee_est_vraiment_mesuree():
    from brain.codage.bac_a_sable import contraste
    for _nom, couleur, fond, ratio in lv.PALETTE:
        assert abs(contraste(couleur, fond) - ratio) < 0.01
        assert ratio >= 4.5


def test_seules_les_lecons_retenues_et_programmees_sont_appliquees(tmp_path):
    chemin = tmp_path / "lecons.yaml"
    chemin.write_text(_yaml.safe_dump({"lecons": [
        {"levier": "palette-mesuree", "etat": "validee"},
        {"levier": "cibles-24px-dans-la-consigne", "etat": "proposee"},
        {"levier": "menu-commun-a-recopier", "etat": "validee"}]}),
        encoding="utf-8")       # le 3e est programme depuis le 09/10
    assert lv.retenus(chemin, {"validee"}) == {"palette-mesuree",
                                              "menu-commun-a-recopier"}
    assert lv.retenus(tmp_path / "absent.yaml", {"validee"}) == set()


def test_le_chantier_met_ses_lecons_dans_la_consigne(tmp_path):
    ch = Chantier(FauxMoteur([]), Espace(tmp_path),
                  leviers={"liens-du-plan-seulement"})
    ch.taches = [Tache("index.html", "l'accueil"),
                 Tache("contact.html", "le contact")]
    consigne = ch._consigne(ch.taches[0])
    assert "[lecons de MAEL" in consigne
    assert "index.html, contact.html" in consigne
    assert ch.leviers_utilises == {"liens-du-plan-seulement": 1}
    sans = Chantier(FauxMoteur([]), Espace(tmp_path))
    sans.taches = ch.taches
    assert "[lecons de MAEL" not in sans._consigne(sans.taches[0])


def test_le_debut_garde_s_arrete_a_un_endroit_sain():
    css = "```css fichier=style.css\nbody { color: #111; }\nh1 { marg"
    assert _debut_sain(css, "style.css") == "body { color: #111; }"
    boucle = ("```html fichier=a.html\n<p>un</p>\n<li>x</li>\n<li>x</li>\n"
              "<li>x</li>\n<li>")
    assert _debut_sain(boucle, "a.html") == "<p>un</p>\n<li>x</li>"
    assert _debut_sain("pas de bloc", "a.css") == ""


def test_un_fichier_coupe_est_ecrit_en_plusieurs_parties(tmp_path,
                                                          monkeypatch):
    from brain.codage import chantier as chmod
    # la page passe ; la feuille de style, plus longue, est coupee
    limite = len(bloc("index.html", PAGE_CHANTIER)) + 40
    monkeypatch.setattr(chmod, "LONGUEUR_MAX", limite)
    debut = "```css fichier=style.css\n" + "".join(
        f".c{i} {{ color: #1f2937; }}\n" for i in range(limite // 20))
    moteur = MoteurQuiDiffuse([
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", PAGE_CHANTIER),
        debut,                                            # coupe : trop long
        "```css fichier=style.css\nbody { background: #ffffff; }\n```"])
    ch = Chantier(moteur, Espace(tmp_path),
                  leviers={"ecrire-en-plusieurs-fois"})
    bilan = ch.lancer("une page d'accueil")
    css = (tmp_path / CSS_STANDARD).read_text(encoding="utf-8")
    assert css.startswith(".c0 { color: #1f2937; }")
    assert "body { background: #ffffff; }" in css
    assert ch.leviers_utilises["ecrire-en-plusieurs-fois"] == 1
    assert any("ecrit en 2 parties" in r for t in bilan.tours
               for r in t.reparations)
    suite = moteur.recus[3][0]["content"]
    assert "SEULEMENT la suite" in suite and ".c" in suite
    assert bilan.leviers == {"ecrire-en-plusieurs-fois": 1}


def test_sans_la_lecon_un_fichier_coupe_n_est_pas_assemble(tmp_path,
                                                           monkeypatch):
    from brain.codage import chantier as chmod
    # la page passe ; la feuille de style, plus longue, est coupee
    limite = len(bloc("index.html", PAGE_CHANTIER)) + 40
    monkeypatch.setattr(chmod, "LONGUEUR_MAX", limite)
    debut = "```css fichier=style.css\n" + "".join(
        f".c{i} {{ color: #1f2937; }}\n" for i in range(limite // 20))
    moteur = MoteurQuiDiffuse([
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", PAGE_CHANTIER), debut, CSS_BLOC])
    ch = Chantier(moteur, Espace(tmp_path))
    ch.lancer("une page d'accueil")
    assert "TROP LONGUE" in moteur.recus[3][0]["content"]   # relance normale
    assert ch.leviers_utilises == {}


def _racine_a_verifier(tmp_path):
    racine = tmp_path / "MAEL-missions"
    (racine / "01-accueil").mkdir(parents=True)
    (racine / "01-accueil" / "JOURNAL.md").write_text(
        "# Mission\n\n## Ce qui reste a corriger\n\n"
        "- `index.html:5` href=\"/mentions-legales\" : ce fichier n'existe "
        "pas (lien casse) (x)\n\n## Ce que je n'ai PAS pu verifier\n",
        encoding="utf-8")
    (racine / "missions-etat.json").write_text(_json.dumps({
        "01-accueil": {"id": "01-accueil", "titre": "une page",
                       "demande": "une page d'accueil", "attendu": "",
                       "verdict": "NON CONFORME", "bloquants": 1,
                       "secondes": 600}}), encoding="utf-8")
    (racine / "lecons.yaml").write_text("# entete gardee\n" + _yaml.safe_dump(
        {"lecons": [
            {"famille": "lien-casse", "levier": "liens-du-plan-seulement",
             "missions": ["01-accueil"], "etat": "proposee"},
            {"famille": "fichier-du-plan-jamais-ecrit",
             "levier": "ecrire-en-plusieurs-fois",
             "missions": ["01-accueil"], "etat": "proposee"},
            {"famille": "contraste", "levier": "palette-mesuree",
             "missions": ["01-accueil"], "etat": "refusee par le juge"}]}),
        encoding="utf-8")
    return racine


def test_verifier_relance_compare_et_tranche(tmp_path):
    racine = _racine_a_verifier(tmp_path)
    moteur = FauxMoteur(_reponses_une_page())
    verdicts = {v.levier: v for v in Verification(moteur, racine).lancer()}
    lien = verdicts["liens-du-plan-seulement"]
    assert (lien.avant, lien.apres, lien.verdict) == (1, 0, "validee")
    assert lien.servi >= 1 and lien.bloquants_apres == 0
    # jamais coupe cette fois : le levier n'a pas joue, il ne prouve rien
    assert verdicts["ecrire-en-plusieurs-fois"].verdict == "non eprouvee"
    assert "palette-mesuree" not in verdicts      # refusee : pas verifiee
    d = _yaml.safe_load((racine / "lecons.yaml").read_text(encoding="utf-8"))
    etats = {l["levier"]: l["etat"] for l in d["lecons"]}
    assert etats == {"liens-du-plan-seulement": "validee",
                     "ecrire-en-plusieurs-fois": "proposee",
                     "palette-mesuree": "refusee par le juge"}
    assert (racine / "lecons.yaml").read_text(
        encoding="utf-8").startswith("# entete gardee")
    # la reference n'est pas touchee ; la verification est a part
    assert (racine / "01-accueil" / "JOURNAL.md").read_text(
        encoding="utf-8").count("mentions-legales") == 1
    v1 = racine / "verification-1"
    assert (v1 / FAIT).exists() and (v1 / "01-accueil" / "index.html").exists()
    r = (racine / RAPPORT_VERIF).read_text(encoding="utf-8")
    assert "**VALIDEE**" in r and "ne prouve pas" in r
    j = (v1 / "01-accueil" / "JOURNAL.md").read_text(encoding="utf-8")
    assert "## Les lecons que j'ai appliquees" in j
    # les missions suivantes appliquent d'office la lecon VALIDEE
    assert Missions(FauxMoteur([]), racine,
                    racine / "x.yaml").leviers == {"liens-du-plan-seulement"}


def test_une_lecon_qui_ne_fait_pas_reculer_sa_faiblesse_est_rejetee():
    v = lc_verdict = __import__("brain.codage.verification",
                                fromlist=["Verdict"]).Verdict(
        "palette-mesuree", "contraste", ["05"], avant=1, apres=1, servi=2,
        bloquants_avant=3, bloquants_apres=2)
    assert v.verdict == "rejetee"
    v.apres, v.bloquants_apres = 0, 5
    assert lc_verdict.verdict == "incertaine"


# ------------- ANGLES MORTS : ce que MAEL n'a pas pu verifier, ses BESOINS
from brain.codage import angles_morts as am
from brain.codage import bac_a_sable as bas
from brain.codage import emplacements
from brain.codage.missions import Mission, rapport, verdict_dit

SECTION_PAS_PU = """# Mission

## Ce que je n'ai PAS pu verifier

- PHP : syntaxe controlee par equilibre seulement (php absent)
- Java : syntaxe controlee par equilibre seulement (javac absent)
- outils externes absents (non lances) : eslint, stylelint, trivy
- pages ouvertes dans un navigateur (ordinateur + telephone, hors ligne) : 2
- pages NON ouvertes (leurs verdicts manquent) : index.html (TimeoutError)
- 6 page(s) non ouverte(s) : budget de 120 s ou 20 pages atteint
- code serveur LU mais non execute (couches 1 a 5) : contact.php

## Mes chiffres
"""


def test_les_angles_morts_se_lisent_et_leur_pertinence_se_juge():
    angles = am.lire_journal(SECTION_PAS_PU, "08",
                             ["index.html", "contact.php", "style.css"])
    par = {(a.genre, a.objet): a for a in angles}
    assert par[("outil-absent", "php")].pertinent          # il y a du PHP
    assert not par[("outil-absent", "javac")].pertinent    # pas de Java
    assert not par[("outil-absent", "eslint")].pertinent   # pas de script
    assert par[("outil-absent", "stylelint")].pertinent
    assert not par[("outil-absent", "trivy")].pertinent    # pas de manifeste
    assert ("page-expiree", "index.html") in par
    assert ("pages-hors-budget", "6 page(s)") in par
    assert ("code-non-execute", "contact.php") in par
    assert not any(a.objet.startswith("pages ouvertes") for a in angles)


def _racine_angles(tmp_path):
    racine = tmp_path / "M"
    for mid, fichiers in (("08", ["index.html", "contact.php"]),
                          ("09", ["index.html"])):
        (racine / mid).mkdir(parents=True)
        for f in fichiers:
            (racine / mid / f).write_text("x", encoding="utf-8")
        (racine / mid / "JOURNAL.md").write_text(SECTION_PAS_PU,
                                                 encoding="utf-8")
    return racine


def test_mael_ecrit_ses_besoins_par_priorite(tmp_path, monkeypatch):
    monkeypatch.setenv("MAEL_OUTILS", str(tmp_path / "outils"))
    monkeypatch.setattr(emplacements.shutil, "which",
                        lambda nom, path=None: None)    # rien sur la machine
    racine = _racine_angles(tmp_path)
    texte, angles = am.rediger(racine, ["08", "09"])
    assert (racine / am.BESOINS).exists()
    besoins = {b.outil: b for b in am.besoins(angles, racine)}
    assert besoins["php"].missions == ["08"]                # seul 08 a du PHP
    assert besoins["javac"].missions == []
    assert "### php — 1 mission(s) concernee(s)" in texte
    assert "windows.php.net" in texte and str(tmp_path / "outils") in texte
    assert "Absents, mais sans effet" in texte and "`javac`" in texte
    assert "SOUS RESERVE" in texte and "contact.php" in texte
    assert "`reessayer-page-expiree`" in texte
    assert "`budget-selon-les-pages`" in texte
    assert "je n'installe rien moi-meme" in texte


def test_un_outil_hors_du_path_est_trouve_dans_le_dossier_de_mael(tmp_path,
                                                                  monkeypatch):
    monkeypatch.setenv("MAEL_OUTILS", str(tmp_path))
    monkeypatch.setenv("PATH", "")
    import os
    import stat
    bin_npm = tmp_path / "node_modules" / ".bin"
    bin_npm.mkdir(parents=True)
    # Windows : eslint.cmd ; Linux / macOS : eslint executable (CI Linux,
    # 12/10/2026)
    nom = "eslint.cmd" if os.name == "nt" else "eslint"
    (bin_npm / nom).write_text("@echo off" if os.name == "nt"
                               else "#!/bin/sh\n", encoding="utf-8")
    (bin_npm / nom).chmod((bin_npm / nom).stat().st_mode | stat.S_IEXEC)
    assert emplacements.trouver("eslint").lower().endswith(nom)
    assert emplacements.trouver("outil-qui-n-existe-pas") is None


def test_les_juges_php_java_restent_sans_outil_pendant_les_tests():
    from brain.codage import juges_php_java
    assert juges_php_java._externe("javac") is None       # MAEL_SANS_OUTILS


def test_un_angle_mort_corrigeable_devient_une_lecon_proposee(tmp_path):
    angles = am.lire_journal(SECTION_PAS_PU, "04", ["index.html"])
    fs = {f.cle: f for f in lc.familles_des_angles_morts(angles)}
    assert fs["page-expiree"].levier == "reessayer-page-expiree"
    assert fs["pages-hors-budget"].levier == "budget-selon-les-pages"
    lc.ecrire_lecons(tmp_path / "lecons.yaml", list(fs.values()))
    l = _yaml.safe_load((tmp_path / "lecons.yaml").read_text(
        encoding="utf-8"))["lecons"]
    assert {x["levier"]: x["etat"] for x in l} == {
        "reessayer-page-expiree": "proposee",
        "budget-selon-les-pages": "proposee"}
    assert all(x["missions"] == ["04"] for x in l)


def test_le_budget_du_navigateur_suit_les_pages_avec_la_lecon(monkeypatch):
    monkeypatch.setattr(bas, "LECONS", set())
    assert bas.budget_pour(8) == bas.BUDGET                 # comme avant
    monkeypatch.setattr(bas, "LECONS", {"budget-selon-les-pages"})
    assert bas.budget_pour(1) == bas.BUDGET
    assert bas.budget_pour(8) == 8 * bas.BUDGET_PAR_PAGE
    assert bas.budget_pour(40) == bas.BUDGET_MAX


def test_un_conforme_sur_du_code_non_execute_est_sous_reserve():
    m = Mission("08", "php", "x", etat="faite", verdict="CONFORME",
                reserves=["code serveur LU mais non execute : contact.php"])
    n = Mission("02", "site", "x", etat="faite", verdict="CONFORME")
    assert verdict_dit(m) == "CONFORME (sous reserve)"
    assert verdict_dit(n) == "CONFORME"
    r = rapport([m, n])
    assert "conformes : 2 (dont 1 sous reserve)" in r
    assert "| CONFORME (sous reserve) |" in r


def test_la_verification_compte_aussi_les_angles_morts(tmp_path):
    racine = _racine_angles(tmp_path)
    (racine / "missions-etat.json").write_text(_json.dumps(
        {"08": {}, "09": {}}), encoding="utf-8")
    v = am.vues(racine, ["08", "09"])
    assert v[("pages-hors-budget", "08")] == 1
    from brain.codage.verification import _vues
    assert _vues(racine)[("page-expiree", "09")] == 1


# ------------- SPECIALISTES : le premier filtre au-dessus des juges
from brain.codage import specialistes as sp


@pytest.mark.parametrize("fichier,nom", [
    ("index.html", "html"), ("css/style.css", "css"), ("js/app.js", "js"),
    ("app.py", "python"), ("contact.php", "php"), ("A.java", "java"),
    ("notes.txt", None),
])
def test_chaque_tache_a_son_specialiste(fichier, nom):
    s = sp.pour(fichier)
    assert (s.nom if s else None) == nom


def _projet_specialistes(tmp_path):
    (tmp_path / "css").mkdir()
    (tmp_path / "index.html").write_text(PAGE_JUSTE.replace(
        "</head>", '<link rel="stylesheet" href="css/style.css">\n</head>'),
        encoding="utf-8")
    (tmp_path / "contact.html").write_text(
        PAGE_JUSTE.replace(' alt=""', ""), encoding="utf-8")  # fautive
    (tmp_path / "css" / "style.css").write_text(CSS_CHANTIER,
                                                encoding="utf-8")
    return tmp_path


def test_seules_les_pages_qui_chargent_le_fichier_sont_ouvertes(tmp_path):
    racine = _projet_specialistes(tmp_path)
    vus = ["index.html", "contact.html", "css/style.css"]
    assert sp.pages_qui_chargent(racine, "css/style.css", vus) == [
        "index.html"]


def test_le_specialiste_ne_convoque_que_ses_juges(tmp_path, monkeypatch):
    from brain.codage import bac_a_sable, outils
    racine = _projet_specialistes(tmp_path)
    appels = {}
    monkeypatch.setattr(outils, "juger", lambda r, vus, seulement=None:
                        appels.setdefault("outils", []).append(
                            (list(vus), set(seulement or ()))) or [])
    monkeypatch.setattr(bac_a_sable, "juger", lambda r, vus:
                        appels.setdefault("nav", []).append(list(vus)) or [])
    _d, vus, s = sp.juger_tache(racine, "css/style.css")
    assert s.nom == "css" and sorted(vus) == sorted(
        ["index.html", "contact.html", "css/style.css"])
    assert appels["outils"] == [(["css/style.css"], {"stylelint"})]
    assert appels["nav"] == [["index.html", "css/style.css"]]
    appels.clear()
    defauts, _v, s = sp.juger_tache(racine, "index.html")
    assert s.nom == "html" and "nav" not in appels     # pas de navigateur
    assert appels["outils"] == [(["index.html"], {"html-validate"})]
    assert all(d.fichier != "contact.html" for d in defauts
               if d.regle == "img-alt")                  # pas les autres


def test_le_specialiste_voit_ce_que_le_jury_complet_voit(tmp_path):
    racine = _projet_specialistes(tmp_path)
    complet, _ = juger_projet_complet(racine)
    for fichier in ("contact.html", "index.html", "css/style.css"):
        miens, _v, _s = sp.juger_tache(racine, fichier, navigateur=False)

        def cle(d):
            return (d.fichier, d.ligne, d.regle)
        attendus = {cle(d) for d in complet if d.fichier == fichier}
        if fichier == "contact.html":
            assert any(r == "img-alt" for _f, _l, r in attendus)
        assert attendus <= {cle(d) for d in miens}, fichier


def juger_projet_complet(racine):
    from brain.codage import juges as j
    return j.juger_projet(racine, executer=False)


def test_le_chantier_appelle_les_specialistes_et_mesure(tmp_path):
    moteur = FauxMoteur(_reponses_une_page())
    ch = Chantier(moteur, Espace(tmp_path))
    bilan = ch.lancer("une page d'accueil")
    assert bilan.conforme
    assert bilan.specialistes == {"html": 1, "css": 1}
    assert bilan.jugement > 0


def test_sans_specialistes_le_jury_complet_comme_avant(tmp_path,
                                                         monkeypatch):
    monkeypatch.setenv("MAEL_SANS_SPECIALISTES", "1")
    ch = Chantier(FauxMoteur(_reponses_une_page()), Espace(tmp_path))
    bilan = ch.lancer("une page d'accueil")
    assert bilan.conforme and bilan.specialistes == {}


# ------------- SAVOIR-FAIRE : comment, pourquoi, recent, dependances
from datetime import date as _date

from brain.codage import fraicheur as fr
from brain.codage import savoir_faire as sf


def test_chaque_fiche_de_savoir_faire_est_complete_et_sourcee():
    from brain.codage.remedes import REMEDES
    fiches = sf.toutes()
    assert len(fiches) >= 15
    noms = {s.nom for s in sp.SPECIALISTES} | {"projet", "conseil"}
    for f in fiches:
        assert f.specialiste in noms, f.id
        assert f.comment and f.pourquoi and f.mots, f.id
        assert f.url.startswith("https://"), f.id
        assert (_date.fromisoformat(f.revoir_apres)
                > _date.fromisoformat(f.verifie_le)), f.id
        assert set(f.juges) <= set(REMEDES), (f.id, set(f.juges) - set(
            REMEDES))
        # Aucun numero de version ecrit en dur : il perimerait en silence
        # (le 08/10/2026, pytest 9 etait sorti, la fiche disait pytest 8).
        texte = " ".join(f.comment) + f.pourquoi + " ".join(
            d["pourquoi"] for d in f.dependances)
        assert not re.search(r"(?i)\b(pytest|flask|php|eslint|sqlalchemy)"
                             r" \d", texte), f.id
    assert len({f.id for f in fiches}) == len(fiches)


def test_le_conteneur_de_tests_suit_la_version_actuelle_de_pytest():
    plages = fr.plages_du_conteneur()
    assert plages["pytest"] == ">=9,<10" and plages["flask"] == ">=3,<4"
    assert fr.dans_la_plage("9.1.1", plages["pytest"])
    assert not fr.dans_la_plage("9.1.1", ">=8,<9")


@pytest.mark.parametrize("nom,derniere,utilisee,probleme", [
    ("pytest", "9.1.1", ">=8,<9", True),     # le cas reel du 08/10/2026
    ("pytest", "9.1.1", ">=9,<10", False),
    ("flask", "3.1.3", ">=3,<4", False),
    ("eslint", "10.12.0", "10.12.0", False),
    ("html-validate", "11.16.2", "10.9.0", True),
    ("php", "8.5.11", "8.4.26", True),       # une branche de retard
    ("php", "8.4.27", "8.4.26", False),      # un correctif : pas un probleme
    ("stylelint", "17.16.0", "", True),      # pas installe
])
def test_maeL_compare_ce_qu_il_utilise_a_la_derniere_version(
        nom, derniere, utilisee, probleme):
    assert bool(fr.comparer(nom, derniere, utilisee)) is probleme


def test_une_fiche_perimee_n_est_plus_donnee_et_le_dit():
    releve = fr.Releve(date="2026-10-08")
    plus_tard = _date(2028, 1, 1)                  # toutes les revues passees
    choix = sf.choisir("style.css", "couleurs lisibles et boutons", releve,
                       plus_tard)
    assert choix.fiches == [] and choix.ecartees
    assert all("date de revue passee" in r for _f, r in choix.ecartees)
    mort = fr.Releve(date="2026-10-08", sources_mortes=[
        "https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum"])
    choix = sf.choisir("style.css", "couleurs lisibles contraste", mort)
    assert "contraste-mesure" not in [f.id for f in choix.fiches]
    assert any(f.id == "contraste-mesure" and "source introuvable" in r
               for f, r in choix.ecartees)


def test_le_savoir_faire_de_la_tache_tient_dans_son_budget():
    releve = fr.Releve(date="2026-10-08", versions={"flask": "3.1.3",
                                                    "pytest": "9.1.1"})
    texte, choix = sf.pour_tache("app.py", "une API Flask des produits avec "
                                 "SQLite et des tests", releve)
    assert len(texte) <= sf.BUDGET
    assert texte.startswith("[savoir-faire python")
    for mot in ("COMMENT :", "POURQUOI :", "source :", "verifie le",
                "IL FAUT :"):
        assert mot in texte
    assert "versions actuelles (verifiees le 2026-10-08)" in texte
    assert "pytest 9.1.1" in texte
    # le savoir d'un AUTRE specialiste n'y est pas
    assert "htmlspecialchars" not in texte and "aria-expanded" not in texte


def test_une_dependance_absente_sur_la_machine_est_dite(monkeypatch):
    monkeypatch.setattr(sf, "_extensions_php",
                        lambda: frozenset({"pdo", "session"}))
    _t, choix = sf.pour_tache("contact.php", "enregistrer les messages en "
                              "base avec PDO", fr.Releve())
    absentes = sf.dependances_absentes(choix.fiches)
    assert any("pdo_sqlite" in a and "php.ini" in a for a in absentes)
    monkeypatch.setattr(sf, "_extensions_php", lambda: None)   # pas de php
    assert sf.dependances_absentes(choix.fiches) == []


def test_un_savoir_non_reverifie_est_un_probleme():
    assert "JAMAIS verifie" in fr.problemes_hors_ligne(fr.Releve())[0]
    vieux = fr.Releve(date="2026-08-01")
    assert "il y a 68 jours" in fr.problemes_hors_ligne(
        vieux, _date(2026, 10, 8))[0]
    assert fr.problemes_hors_ligne(fr.Releve(date="2026-10-01"),
                                   _date(2026, 10, 8)) == []


def test_rafraichir_note_versions_problemes_et_sources(tmp_path, monkeypatch):
    dernieres = {"pytest": "10.0.0", "flask": "3.1.3", "sqlalchemy": "2.1.4",
                 "fastapi": "0.142.4", "httpx": "0.28.1", "eslint": "10.12.0",
                 "stylelint": "17.16.0", "html-validate": "11.16.2",
                 "php": "8.5.11"}
    monkeypatch.setattr(fr, "derniere_version", lambda n: dernieres[n])
    monkeypatch.setattr(fr, "_version_outil", lambda n: {
        "eslint": "10.12.0", "stylelint": "17.16.0", "html-validate": "11.16.2",
        "php": "8.5.11"}[n])

    def lire(url):
        if "morte" in url:
            raise OSError("404")
        return b"ok"
    monkeypatch.setattr(fr, "_lire_url", lire)
    r = fr.rafraichir(["https://ex.org/vive", "https://ex.org/morte"],
                      chemin=tmp_path / "f.json")
    assert r.sources_mortes == ["https://ex.org/morte"]
    assert len(r.problemes) == 1 and "pytest 10.0.0" in r.problemes[0]
    assert fr.charger(tmp_path / "f.json").versions["php"] == "8.5.11"


def test_la_tache_recoit_le_savoir_faire_de_son_specialiste(tmp_path,
                                                            monkeypatch):
    monkeypatch.setattr(fr, "FICHIER", tmp_path / "absent.json")
    moteur = FauxMoteur(_reponses_une_page())
    ch = Chantier(moteur, Espace(tmp_path / "p"))
    bilan = ch.lancer("une page d'accueil avec une galerie de photos")
    consigne_page = moteur.recus[1][0]["content"]
    assert "[savoir-faire html" in consigne_page
    assert "POURQUOI : WCAG 2.2" in consigne_page
    assert ch.savoir_faire_utilise
    assert any("savoir-faire : savoir-faire JAMAIS verifie" in l
               for l in bilan.limites)


def test_les_besoins_disent_si_le_savoir_est_recent(tmp_path, monkeypatch):
    monkeypatch.setattr(fr, "FICHIER", tmp_path / "absent.json")
    racine = _racine_angles(tmp_path)
    texte, _a = am.rediger(racine, ["08"])
    assert "## Mon savoir-faire : est-il recent ?" in texte
    assert "PROBLEME : savoir-faire JAMAIS verifie" in texte
    angles = am.lire_journal(
        "## Ce que je n'ai PAS pu verifier\n\n- dependance absente sur la "
        "machine : extension PHP pdo_sqlite — le pilote\n\n## Fin\n", "08",
        ["contact.php"])
    assert angles[0].genre == "dependance-absente"
    assert angles[0].objet == "pdo_sqlite"


# ------------- plus de savoir-faire : gabarits, contextes JS, long projet
def test_les_fiches_couvrent_tous_les_specialistes_et_leurs_gabarits():
    from brain.codage import savoir as sv
    fiches = sf.toutes()
    assert len(fiches) >= 45
    par = {s.nom: [f for f in fiches if f.specialiste == s.nom]
           for s in sp.SPECIALISTES}
    assert all(par[n] for n in ("html", "css", "js", "python", "php", "java"))
    gabarits = {g.fichier for g in sv.tous()}
    lies = {f.gabarit for f in fiches if f.gabarit}
    assert lies <= gabarits, lies - gabarits       # chaque lien existe
    assert len(lies) >= 25                          # la plupart couverts


@pytest.mark.parametrize("fichier,texte,contexte", [
    ("js/app.js", "le bouton ouvre et ferme le menu", "navigateur"),
    ("js/catalogue.js", "charge le catalogue depuis l'API", "navigateur"),
    ("server.js", "serveur Express avec une route API", "serveur"),
    ("Liste.jsx", "affiche les produits", "react"),
    ("app.js", "un composant React", "react"),
])
def test_le_specialiste_js_distingue_page_serveur_et_react(fichier, texte,
                                                           contexte):
    assert sf.contexte_js(fichier, texte) == contexte
    choix = sf.choisir(fichier, texte, fr.Releve())
    assert all(f.contexte in {contexte, ""} for f in choix.fiches)


def test_un_script_de_page_ne_recoit_pas_le_savoir_d_un_serveur():
    texte, _c = sf.pour_tache("js/catalogue.js", "charge le catalogue de "
                              "l'API produits", fr.Releve())
    assert "fetch" in texte and "helmet" not in texte


def test_le_plan_d_un_long_projet_recoit_la_conduite_de_projet():
    texte, choix = sf.pour_plan(
        "une petite boutique en ligne : trois pages, un script qui charge le "
        "catalogue depuis une API, l'API en Python Flask avec une base "
        "SQLite, avec des tests", fr.Releve())
    assert texte.startswith("[savoir-faire du chef de chantier")
    assert len(texte) <= sf.BUDGET
    assert {f.specialiste for f in choix.fiches} == {"projet"}
    assert "contrats-entre-fichiers" in [f.id for f in choix.fiches]


def test_le_chef_de_chantier_recoit_la_conduite_de_projet(tmp_path):
    moteur = FauxMoteur(_reponses_une_page())
    Chantier(moteur, Espace(tmp_path)).lancer(
        "le site complet de plusieurs pages d'une association")
    assert "[savoir-faire du chef de chantier" in moteur.recus[0][0][
        "content"]


# ------------- PROFESSEURS : le conseil qui raisonne avant le plan
from brain.codage import professeurs as pr

DEMANDE_API = ("une API web en Python avec Flask pour gerer les produits "
               "d'une boutique, stockes dans une base de donnees SQLite : "
               "lister les produits, voir un produit, ajouter un produit et "
               "le supprimer, avec des tests automatiques")


def test_chaque_professeur_a_son_identite_et_sa_bibliotheque():
    assert set(pr.CONSEIL) == set(pr.PROFESSEURS)
    for nom, p in pr.CONSEIL.items():
        assert p.fort and p.principe and p.bibliotheque, nom
    avis, _f, _c = pr.conseil(DEMANDE_API)
    assert [a.professeur for a in avis] == list(pr.PROFESSEURS)
    for a in avis:
        assert a.texte().startswith(f"[{a.professeur.upper()} — fort :")
        assert a.points and all("(source : " in x for x in a.points), a


@pytest.mark.parametrize("demande,langages,pages,interactif", [
    (DEMANDE_API, {"python"}, None, False),           # mission 07 : AUCUNE page
    ("un site pour une boulangerie avec trois pages", {"html"}, 3, False),
    ("un site d'une seule page avec trois pages pour une association, avec "
     "un formulaire d'inscription", {"html"}, None, False),   # pas « script »
    ("une petite boutique en ligne : trois pages, un script qui charge le "
     "catalogue depuis une API en Python Flask", {"html", "python"}, 3, True),
    ("un formulaire de contact en PHP qui enregistre en base avec PDO",
     {"html", "php"}, None, False),
])
def test_le_professeur_realite_etablit_les_bons_faits(demande, langages,
                                                      pages, interactif):
    f = pr.etablir(demande)
    assert f.langages == langages and f.nb_pages == pages
    assert f.interactif is interactif


def test_le_professeur_calcul_cite_ses_mesures_et_sa_marge():
    a = pr.calcul(pr.etablir(DEMANDE_API))
    assert any("+/- 50 %" in x and "10 missions" in x for x in a.points)
    assert any("LONGUEUR_MAX" in x for x in a.points)


def test_le_juge_du_plan_verifie_le_plan_rendu():
    f = pr.etablir(DEMANDE_API)
    assert any(".py" in r for r in pr.juger_plan(["index.html",
                                                  "style.css"], f))
    assert any("tests/test_app.py" in r for r in pr.juger_plan(
        ["app.py"], f))
    assert pr.juger_plan(["app.py", "tests/test_app.py"], f) == []
    site = pr.etablir("un site avec trois pages")
    assert any("aucun code python" in r for r in pr.juger_plan(
        ["index.html", "style.css", "app.py"], site))


# ------------- la DELIBERATION ENTRE PROFESSEURS (sans modele)
from brain.codage import deliberation as dl


def test_le_banc_des_professeurs_reste_juste():
    """Le banc (banc_professeurs.yaml) : chaque probleme a sa bonne reponse
    ecrite a la main ; une regression d'un professeur fait echouer ici."""
    from brain.codage import banc_professeurs as bp
    r = bp.evaluer()
    assert not r.ecarts, bp.rapport(r)
    assert sum(r.total.values()) >= 185


def test_la_deliberation_ne_fait_aucun_appel_au_modele(tmp_path, monkeypatch):
    monkeypatch.delenv("MAEL_SANS_PROFESSEURS")
    moteur = FauxMoteur(["- app.py : l'API Flask\n- tests/test_app.py : les "
                         "tests"])
    ch = Chantier(moteur, Espace(tmp_path))
    taches = ch.planifier(DEMANDE_API)
    assert len(moteur.recus) == 1                      # le plan seulement
    assert [t.fichier for t in taches] == ["app/main.py", "tests/test_app.py"]
    plan = moteur.recus[0][0]["content"]
    assert "[decisions du conseil des professeurs]" in plan
    assert "nature : creer" in plan and "[connaissance]" in plan
    assert ch.appels_conseil == 0


def test_chaque_element_de_la_deliberation_a_son_professeur_et_sa_source():
    d = dl.deliberer("Mon API Flask répond en 4 secondes, c'est trop lent.")
    assert d.nature == "diagnostiquer" and len(d.hypotheses) >= 2
    for e in d.tous():
        assert e.professeur in pr.PROFESSEURS and e.source, e
    assert any(e.texte == "4 secondes = 4000 ms" and e.professeur ==
               "calcul" for e in d.decisions)
    assert d.refus == []


def test_le_juge_du_conseil_refuse_une_deliberation_trop_sure():
    d = dl.deliberer("Ma boutique doit accepter Orange Money et Moov Money.")
    d.confiance = "haute"                              # malgre les besoins
    assert any("confiance haute" in r for r in dl.juger(d))
    d2 = dl.deliberer("Mon API Flask répond en 4 secondes, c'est trop lent.")
    d2.hypotheses = d2.hypotheses[:1]
    assert any("deux hypotheses" in r for r in dl.juger(d2))
    d3 = dl.deliberer("Je veux une page qui affiche la météo de "
                      "Ouagadougou en direct.")
    d3.ne_pas = []
    assert any("inventer" in r for r in dl.juger(d3))


def test_un_probleme_que_la_bibliotheque_ne_couvre_pas_le_dit():
    d = dl.deliberer("Programme un robot qui joue aux echecs sur une "
                     "carte Arduino.")
    assert d.confiance == "basse"
    assert any("preciser" in b.texte for b in d.besoins)


def test_un_plan_en_barre_est_garde_sans_relance(tmp_path, monkeypatch):
    # 09/10 : le « / » est retire par le lecteur (plan-chemins-tolerants) ;
    # avant, le doyen faisait refaire tout le plan (un appel de plus).
    monkeypatch.delenv("MAEL_SANS_PROFESSEURS")
    moteur = FauxMoteur(["- /app.py : l'API\n- /tests/test_app.py : tests"])
    ch = Chantier(moteur, Espace(tmp_path))
    taches = ch.planifier(DEMANDE_API)
    assert [t.fichier for t in taches] == ["app/main.py", "tests/test_app.py"]
    assert len(moteur.recus) == 1 and ch.appels_conseil == 0


def test_un_plan_illisible_est_refait_par_le_doyen(tmp_path, monkeypatch):
    monkeypatch.delenv("MAEL_SANS_PROFESSEURS")
    moteur = FauxMoteur(["Voici mon plan : une API et ses tests.",
                         "- app.py : l'API Flask\n- tests/test_app.py : les "
                         "tests"])
    ch = Chantier(moteur, Espace(tmp_path))
    taches = ch.planifier(DEMANDE_API)
    assert [t.fichier for t in taches] == ["app/main.py", "tests/test_app.py"]
    assert "aucune ligne au format" in moteur.recus[1][0]["content"]
    assert ch.appels_conseil == 1                     # la relance du plan


def test_une_api_planifiee_en_pages_est_refaite(tmp_path, monkeypatch):
    monkeypatch.delenv("MAEL_SANS_PROFESSEURS")
    moteur = FauxMoteur(["- index.html : l'accueil\n- style.css : styles",
                         "- app.py : l'API\n- tests/test_app.py : tests"])
    taches = Chantier(moteur, Espace(tmp_path)).planifier(DEMANDE_API)
    assert {t.fichier for t in taches} == {"app/main.py",
                                           "tests/test_app.py"}
    assert "le fichier .py" in moteur.recus[1][0]["content"]

def test_face_a_l_inconnu_le_conseil_dit_qu_il_ne_sait_pas():
    """Phase de test du 08/10/2026 (problemes inedits) : 7 fausses
    assurances sur 12 avant les regles d'honnetete, 0 apres. Une regression
    ici, c'est le conseil qui recommence a repondre a cote avec assurance."""
    from brain.codage import banc_professeurs as bp
    lignes, rapport = bp.evaluer_inedits()
    assert all(x["honnete"] for x in lignes), rapport
    pirate = next(x for x in lignes if x["id"] == "site-pirate")
    assert pirate["confiance"] == "basse"


# ------------- le CONSEIL SUR LES VERDICTS DES JUGES
from brain.codage import conseil_juges as cj


def test_le_conseil_cherche_le_savoir_par_la_regle_du_defaut():
    s = cj.Situation(
        demande="un site de trois pages", plan=["index.html", "a.html",
                                                "b.html", "css/site.css"],
        existants=["index.html", "a.html", "b.html", "css/site.css"],
        defauts=[{"fichier": "a.html", "ligne": 3, "regle": "contraste",
                  "message": "contraste mesure 2.1:1, 4.5:1 exige"}])
    v = cj.deliberer(s)
    assert [x.cible for x in v.solutions] == ["css/site.css"]  # pas a.html
    assert "levier palette-mesuree" in v.solutions[0].source
    assert v.confiance == "haute"


def test_un_defaut_sans_solution_connue_rend_la_confiance_basse():
    s = cj.Situation(demande="un site", plan=["index.html"],
                     existants=["index.html"],
                     defauts=[{"fichier": "index.html", "ligne": 1,
                               "regle": "inconnue", "message":
                               "un defaut que personne ne connait"}])
    v = cj.deliberer(s)
    assert v.confiance == "basse" and "sans solution" in v.pourquoi


def test_le_texte_du_conseil_dit_ou_corriger_et_pourquoi():
    s = cj.Situation(
        demande="un site avec trois pages",
        plan=["index.html", "a.html", "b.html", "c.html", "style.css"],
        existants=["index.html", "a.html"],
        defauts=[{"fichier": "a.html", "ligne": 7, "regle": "fichier-absent",
                  "message": 'href="style.css" : ce fichier n\'existe pas'}])
    texte = cj.deliberer(s).texte()
    assert "4 pages au plan pour 3 demandee(s)" in texte
    assert "dans style.css :" in texte and "a ne PAS faire" in texte


# ------------- le conseil BRANCHE dans le chantier (point 3)
# Deux fois le meme lien sur la ligne : un cas que la reparation sure ne
# tranche pas (09/10 : le cas simple, un seul lien, est repare par MAEL
# lui-meme) — c'est donc au modele, guide par le conseil.
PAGE_LIEN_HORS_PLAN = PAGE_CHANTIER.replace(
    "</main>", '<p><a href="mentions-legales.html">Mentions</a> et '
    '<a href="mentions-legales.html">CGU</a></p>\n</main>')


def test_lien_hors_plan_simple_repare_sans_le_modele(tmp_path):
    page = PAGE_CHANTIER.replace(
        "</main>", '<a href="mentions-legales.html">Mentions</a>\n</main>')
    moteur = FauxMoteur([
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", page), CSS_BLOC])
    ch = Chantier(moteur, Espace(tmp_path))
    bilan = ch.lancer("une page d'accueil")
    assert "mentions-legales" not in (tmp_path / "index.html").read_text(
        encoding="utf-8")
    assert len(moteur.recus) == 3 and bilan.conforme


def test_le_modele_lit_le_verdict_du_conseil_avant_de_corriger(
        tmp_path, monkeypatch):
    monkeypatch.delenv("MAEL_SANS_PROFESSEURS")
    moteur = FauxMoteur([
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", PAGE_LIEN_HORS_PLAN),       # lien hors du plan
        bloc("index.html", PAGE_CHANTIER),             # corrige
        CSS_BLOC])
    ch = Chantier(moteur, Espace(tmp_path))
    bilan = ch.lancer("une page d'accueil")
    correction = moteur.recus[2][0]["content"]
    assert "[le conseil des professeurs a delibere sur ces defauts]" in \
        correction
    assert "hors du plan" in correction and "a ne PAS faire" in correction
    assert ch.verdicts_conseil >= 1
    assert bilan.conforme


def test_le_verdict_dans_la_consigne_reste_dans_son_budget():
    s = cj.Situation(
        demande="un site", plan=["index.html", "header.html", "footer.html",
                                 "nav.html", "style.css"],
        existants=["index.html"],
        defauts=[{"fichier": f, "ligne": 1, "regle": "critere-non-tenu",
                  "message": "critere de la tache non tenu : a un <main> (x)"}
                 for f in ("header.html", "footer.html", "nav.html")])
    texte = cj.pour_la_tache(cj.deliberer(s), "footer.html")
    assert 0 < len(texte) <= cj.BUDGET_TACHE


def test_une_action_du_programme_ne_va_pas_au_modele():
    """« Ne plus exiger <main> d'un morceau de page » est une action du
    PROGRAMME de MAEL : le modele n'en ferait rien ; il recoit
    l'impertinence (ce qu'est footer.html), pas cette action."""
    s = cj.Situation(
        demande="un site", plan=["index.html", "footer.html", "style.css"],
        existants=["index.html", "footer.html"],
        defauts=[{"fichier": "footer.html", "ligne": 1,
                  "regle": "critere-non-tenu", "message":
                  "critere de la tache non tenu : a un <main> (x)"}])
    v = cj.deliberer(s)
    assert any(x.levier == "fragments-sans-criteres-de-page"
               for x in v.solutions)
    texte = cj.pour_la_tache(v, "footer.html")
    assert "MORCEAU de page" in texte and "ne plus exiger" not in texte
    assert "ne plus exiger" in v.texte()          # mais il est au journal


def test_un_defaut_visuel_dit_au_modele_ou_il_se_corrige():
    s = cj.Situation(
        demande="un site", plan=["index.html", "style.css"],
        existants=["index.html", "style.css"],
        defauts=[{"fichier": "index.html", "ligne": 9, "regle": "contraste",
                  "message": "contraste mesure 2.1:1, 4.5:1 exige"}])
    texte = cj.pour_la_tache(cj.deliberer(s), "index.html")
    assert "se corrige dans style.css, pas dans index.html" in texte


def test_le_journal_garde_le_verdict_final_du_conseil(tmp_path, monkeypatch):
    monkeypatch.delenv("MAEL_SANS_PROFESSEURS")
    (tmp_path / "missions.yaml").write_text(
        "missions:\n  - id: 01-accueil\n    demande: une page d'accueil\n",
        encoding="utf-8")
    moteur = FauxMoteur([
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", PAGE_LIEN_HORS_PLAN),
        bloc("index.html", PAGE_LIEN_HORS_PLAN),       # pas corrige
        CSS_BLOC, bloc("index.html", PAGE_LIEN_HORS_PLAN)])
    racine = tmp_path / "M"
    Missions(moteur, racine, tmp_path / "missions.yaml").lancer()
    j = (racine / "01-accueil" / "JOURNAL.md").read_text(encoding="utf-8")
    assert "## Ce que conclut le conseil des professeurs" in j
    assert "hors du plan" in j


def test_sans_professeurs_aucune_deliberation_dans_la_correction(tmp_path):
    moteur = FauxMoteur([
        "- index.html : l'accueil\n- style.css : les styles\n",
        bloc("index.html", PAGE_LIEN_HORS_PLAN),
        bloc("index.html", PAGE_CHANTIER), CSS_BLOC])
    ch = Chantier(moteur, Espace(tmp_path))
    ch.lancer("une page d'accueil")
    assert "[le conseil des professeurs" not in moteur.recus[2][0]["content"]
    assert ch.verdicts_conseil == 0


# ------------- banc de la chaine : juges et conseil renforces (08/10/2026)
from brain.codage import projet as prj


def test_le_juge_des_contrats_voit_un_appel_sans_route(tmp_path):
    (tmp_path / "index.html").write_text(PAGE_JUSTE, encoding="utf-8")
    (tmp_path / "app.py").write_text(
        'from flask import Flask\napp = Flask(__name__)\n\n'
        '@app.get("/api/produits")\ndef liste():\n    return []\n\n'
        '@app.get("/api/produits/<int:id>")\ndef un(id):\n    return {}\n',
        encoding="utf-8")
    (tmp_path / "cat.js").write_text(
        'fetch("/api/products").then((r) => r.json());\n'
        'fetch("/api/produits");\nfetch("/api/produits/12");\n',
        encoding="utf-8")
    d = prj.contrats_api(tmp_path, ["index.html", "app.py", "cat.js"])
    assert [(x.ligne, x.regle) for x in d] == [(1, "contrat-api")]
    assert "/api/produits" in d[0].message


def test_sans_serveur_au_projet_aucun_contrat_a_juger(tmp_path):
    (tmp_path / "cat.js").write_text('fetch("/api/x");\n', encoding="utf-8")
    assert prj.contrats_api(tmp_path, ["cat.js"]) == []


@pytest.mark.parametrize("ligne", [
    'app.secret_key = "cle-secrete-de-production-12345"',
    'app.config["SECRET_KEY"] = "autre-cle-de-production-6789"',
])
def test_une_cle_secrete_flask_ecrite_en_dur_est_vue(ligne):
    texte = f"from flask import Flask\napp = Flask(__name__)\n{ligne}\n"
    assert "secret-en-dur" in regles("app.py", texte)


def test_le_mode_debug_de_flask_est_range_en_debug_actif():
    texte = "from flask import Flask\napp = Flask(__name__)\napp.run(debug=True)\n"
    assert "debug-actif" in regles("app.py", texte)


def test_le_conseil_puise_dans_la_fiche_de_la_regle_pour_chaque_defaut():
    s = cj.Situation(
        demande="un formulaire de contact en PHP", plan=["contact.php"],
        existants=["contact.php"],
        defauts=[{"fichier": "contact.php", "ligne": 4,
                  "regle": "injection-sql", "message": "requete concatenee"},
                 {"fichier": "contact.php", "ligne": 5,
                  "regle": "xss-serveur", "message": "affichage brut"}])
    v = cj.deliberer(s)
    textes = " ".join(x.texte for x in v.solutions)
    assert "prepare" in textes and "htmlspecialchars" in textes
    assert all(x.source.startswith("fiche ") for x in v.solutions)
    assert v.confiance == "haute"


def test_le_banc_de_la_chaine_reste_juste(monkeypatch):
    """Les 10 cas durcis valides par le responsable : la chaine plan ->
    specialistes -> conseil donne au modele le bon retour (sans modele,
    sans navigateur ni outils dans les tests)."""
    from brain.codage import banc_chaine as bc
    for cas in bc.CAS:
        notes = bc.noter(cas, bc.executer(cas))
        rates = [t for qui, ok, t in notes if not ok and qui != "juges"]
        assert not rates, (cas["id"], rates)


# ------------- lot neuf de la chaine : generalisation (08/10/2026)
def test_sans_etape_qui_parle_de_la_regle_le_remede_du_juge_sert():
    s = cj.Situation(demande="un formulaire de connexion",
                     plan=["index.html"], existants=["index.html"],
                     defauts=[{"fichier": "index.html", "ligne": 4,
                               "regle": "mdp-en-get",
                               "message": "mot de passe envoye en GET"}])
    v = cj.deliberer(s)
    assert "post" in v.solutions[0].texte.lower()
    assert "remede du juge" in v.solutions[0].source


def test_une_fiche_d_un_autre_langage_ne_sert_jamais():
    s = cj.Situation(demande="une API Flask", plan=["app.py"],
                     existants=["app.py"],
                     defauts=[{"fichier": "app.py", "ligne": 7,
                               "regle": "xss-serveur",
                               "message": "HTML construit avec la requete"}])
    texte = " ".join(x.texte for x in cj.deliberer(s).solutions)
    assert "htmlspecialchars" not in texte and "escape" in texte


def test_un_fichier_present_sous_un_autre_chemin_se_corrige_par_le_chemin():
    s = cj.Situation(demande="un site de trois pages",
                     plan=["index.html", "style.css"],
                     existants=["index.html", "style.css"],
                     defauts=[{"fichier": "index.html", "ligne": 7,
                               "regle": "fichier-absent", "message":
                               'href="css/style.css" : ce fichier n\'existe '
                               "pas (lien casse)"}])
    v = cj.deliberer(s)
    assert "corriger le chemin : css/style.css -> style.css" in \
        v.solutions[0].texte
    assert not any("inventer" in e.texte for e in v.ne_pas)


def test_le_conseil_donne_la_vraie_route_du_serveur():
    s = cj.Situation(demande="une page qui charge les commandes",
                     plan=["index.html", "c.js", "main.py"],
                     existants=["index.html", "c.js", "main.py"],
                     defauts=[{"fichier": "c.js", "ligne": 2,
                               "regle": "contrat-api", "message":
                               'fetch("/api/commandes") : aucune route du '
                               "serveur ne repond a ce chemin (routes : "
                               "/commandes, /clients)"}])
    assert "appeler /commandes" in cj.deliberer(s).solutions[0].texte


def test_une_route_flask_qui_renvoie_du_html_avec_la_requete_est_un_xss():
    ko = ('from flask import Flask, request\napp = Flask(__name__)\n\n'
          '@app.get("/b")\ndef b():\n    nom = request.args.get("nom")\n'
          '    return f"<h1>Bonjour {nom}</h1>"\n')
    assert "xss-serveur" in regles("app.py", ko)
    sur = ko.replace('{nom}', '{escape(nom)}').replace(
        "from flask import Flask, request",
        "from flask import Flask, request\nfrom markupsafe import escape")
    assert "xss-serveur" not in regles("app.py", sur)


@pytest.mark.skipif(not juges.node_disponible(),
                    reason="l'analyse fine du JavaScript (acorn) demande node "
                           "(CI Linux sans node, 12/10/2026)")
def test_le_lot_neuf_de_la_chaine_reste_juste():
    from brain.codage import banc_chaine as bc
    from brain.codage import banc_chaine_neuf as bn
    # n6 (contraste) demande le NAVIGATEUR, desactive dans les tests : il
    # reste mesure par le banc reel (banc_chaine_neuf.rapport()).
    for cas in [c for c in bn.CAS if c["id"] != "n6-contraste-dans-le-css"]:
        notes = bc.noter(cas, bc.executer(cas))
        rates = [t for qui, ok, t in notes if not ok and qui != "juges"]
        assert not rates, (cas["id"], rates)
