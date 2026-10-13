"""Chaque defaut porte son remede : la correction type, courte, verifiee.

Dire « faux » a un petit modele ne suffit pas : il corrige au hasard, ou
recommence la meme faute ailleurs. Lui montrer LA forme juste fait converger
la boucle en un tour au lieu de trois (terme n de la loi, doc 15).

Regle d'entree : chaque regle bloquante a son remede (verifie par les
tests) ; un defaut sans remede fait tourner la boucle a vide.
"""
from __future__ import annotations

REMEDES: dict[str, str] = {
    "doctype": '<!DOCTYPE html> en toute premiere ligne',
    "lang": '<html lang="fr">',
    "charset": '<meta charset="utf-8"> en premier dans <head>',
    "viewport": '<meta name="viewport" content="width=device-width, '
                'initial-scale=1">',
    "zoom-bloque": 'retirer user-scalable=no et maximum-scale du viewport',
    "title": '<title>Nom precis de la page</title>',
    "img-alt": '<img src="..." alt="description utile"> '
               '(alt="" si purement decorative)',
    "champ-sans-label": '<label for="courriel">Courriel</label> '
                        '<input id="courriel" name="courriel" type="email">',
    "nom-accessible": '<a href="..." aria-label="Ouvrir le menu">...</a> '
                      'ou un texte visible dans le lien/bouton',
    "blank-noopener": '<a href="..." target="_blank" rel="noopener noreferrer">',
    "href-javascript": '<button type="button" id="ouvrir">...</button> + '
                       'addEventListener("click", ...) dans le script',
    "button-type": '<button type="button"> (ou type="submit" dans un '
                   'formulaire)',
    "evenement-en-ligne": 'retirer onclick=... ; dans le script : '
                          'element.addEventListener("click", fonction)',
    "contenu-mixte": 'https:// ou un chemin relatif',
    "sri": '<script src="https://..." integrity="sha384-..." '
           'crossorigin="anonymous"></script>, ou copier le script en local',
    "mdp-en-get": '<form method="post" action="...">',
    "fichier-absent": 'creer le fichier reference, ou corriger le chemin',
    "id-duplique": 'un id unique par element (classe si c\'est un style '
                   'partage)',
    "balise-non-fermee": 'fermer la balise au bon niveau d\'imbrication',
    "fermeture-orpheline": 'retirer la fermeture en trop ou ajouter '
                           'l\'ouvrante',
    "focus-invisible": ':focus-visible { outline: 3px solid #1a5fb4; '
                       'outline-offset: 2px; }',
    "css-accolade": 'equilibrer { et }',
    "innerhtml": 'el.textContent = valeur;  ou  const li = '
                 'document.createElement("li"); li.textContent = valeur; '
                 'liste.append(li);',
    "js-dangereux": 'JSON.parse pour des donnees ; une fonction pour '
                    'setTimeout(() => ..., ms)',
    "js-syntaxe": 'corriger la ligne indiquee ; le fichier doit etre '
                  'complet et valide',
    "py-syntaxe": 'corriger la ligne indiquee',
    "injection-sql": 'cur.execute("SELECT * FROM t WHERE id = ?", (ident,))',
    "py-dangereux": 'subprocess.run(["prog", arg], check=True) sans shell ; '
                    'yaml.safe_load ; json au lieu de pickle ; verify=True',
    "injection-commande": 'subprocess.run(["convert", nom_sur], check=True) '
                          '— liste d\'arguments, jamais de shell ; valider '
                          'la valeur contre une liste permise',
    "injection-code": 'ne jamais executer une entree : ast.literal_eval '
                      'pour une valeur, une table {nom: fonction} pour un '
                      'choix',
    "traversee-chemin": 'nom = secure_filename(nom); chemin = (BASE / '
                        'nom).resolve(); verifier BASE in chemin.parents',
    "xss-serveur": 'render_template("page.html", nom=nom) (echappement '
                   'automatique) ; html.escape(valeur) sinon',
    "ssrf": 'n\'appeler que des hotes d\'une liste permise : '
            'urlparse(url).hostname in HOTES_PERMIS',
    "redirection-ouverte": 'rediriger vers url_for("page") ou verifier que '
                           'la cible est un chemin relatif du site',
    "deserialisation": 'json.loads(donnee) au lieu de pickle/marshal',
    "csrf-desactive": 'retirer @csrf_exempt ; {% csrf_token %} dans le '
                      'formulaire, en-tete X-CSRFToken pour fetch',
    "cookie-faible": 'SESSION_COOKIE_SECURE = True ; CSRF_COOKIE_SECURE = '
                     'True ; SESSION_COOKIE_HTTPONLY = True',
    "debug-actif": 'DEBUG = os.environ.get("DJANGO_DEBUG") == "1"',
    "hotes-ouverts": 'ALLOWED_HOSTS = ["mon-site.bf", "www.mon-site.bf"]',
    "inclusion-fichier": 'include __DIR__ . "/pages/" . $pages_permises[$cle] '
                         '— une liste fixe, jamais le chemin recu',
    "xxe": 'f.setFeature("http://apache.org/xml/features/'
           'disallow-doctype-decl", true);',
    "clic-sans-clavier": '<button type="button" onClick={...}>...</button> '
                         'au lieu de <div onClick>',
    "chiffrement-faible": 'Cipher.getInstance("AES/GCM/NoPadding") avec un '
                          'IV aleatoire de 12 octets',
    "cors-ouvert": '@CrossOrigin(origins = "https://mon-site.bf")',
    "syntaxe-equilibre": 'fermer chaque { ( [ et chaque chaine ; ecrire le '
                         'fichier ENTIER',
    "hash-faible": 'mots de passe : werkzeug.security.generate_password_hash '
                   '/ bcrypt / argon2 ; empreinte : hashlib.sha256',
    "hasard-faible": 'secrets.token_urlsafe(32) / secrets.choice(...)',
    "xss-dom": 'el.textContent = valeur;  (ou DOMPurify.sanitize(html) si '
               'du HTML est vraiment voulu)',
    "message-sans-origine": 'window.addEventListener("message", (e) => { '
                            'if (e.origin !== "https://site-attendu.fr") '
                            'return; ... })',
    "postmessage-etoile": 'cible.postMessage(donnee, "https://site-attendu.fr")',
    "secret-en-dur": 'os.environ["NOM_DU_SECRET"] (Python) / '
                     'process.env.NOM_DU_SECRET (Node) ; jamais dans le code',
    "code-inacheve": 'ecrire le fichier ENTIER, sans « ... » ni resume',
    "ancre-absente": '<a href="#contact">Contact</a> ... <section '
                     'id="contact"> : la cible porte le meme id',
    "import-absent": "retirer la ligne @import d'un fichier qui n'existe pas "
                     "(tout le style va dans la feuille du plan)",
    "selecteur-mort": "viser un element qui existe : '#contact' pour "
                      '<section id="contact"> ; ou ajouter l\'id a '
                      "l'element voulu dans la page",
    "contrat-api": "appeler exactement le chemin d'une route du serveur "
                   "(meme orthographe, meme langue : /api/produits des deux "
                   "cotes) ; ou ajouter la route manquante au serveur",
    "critere-non-tenu": "ajouter exactement ce que le critere indique (la "
                        "balise, le lien ou le chargement donne), sans "
                        "retirer le reste",
    # fidelite a la demande (demande.py)
    "contenu-perdu": 'reprendre le fichier du tour precedent et ne changer '
                     'QUE les lignes du defaut ; ne rien supprimer',
    "demande-non-tenue": 'ajouter l\'element demande (ex. <form method="post"'
                         '> avec ses <label> et champs) sans retirer le reste',
    # couche 6 (navigateur, axe-core)
    "contraste": 'texte normal >= 4.5:1, grand texte >= 3:1 : ex. color: '
                 '#1f2937 sur #ffffff (et non #9ca3af)',
    "js-erreur-execution": "verifier que l'element existe avant usage "
                           '(const el = document.getElementById("x"); '
                           'if (el) ...) et charger le script avec defer',
    "aria-invalide": "retirer l'attribut ARIA inutile ; un element natif "
                     "(<button>, <nav>, <label>) vaut mieux qu'un role",
    "debordement-mobile": 'img, video { max-width: 100%; height: auto; } ; '
                          'pas de largeur fixe en px ; '
                          'overflow-wrap: anywhere sur les longs mots',
    "cible-trop-petite": "zones cliquables d'au moins 24 x 24 px "
                         '(min-width / min-height / padding)',
    # La base de donnees (juges_sql.py, 09/10/2026).
    "sql-syntaxe": "reecrire l'instruction dans le dialecte de la base du "
                   "projet (une instruction par ;, virgules et parentheses "
                   "fermees)",
    "sql-sans-cle": "id INTEGER PRIMARY KEY (SQLite), id BIGSERIAL PRIMARY "
                    "KEY (PostgreSQL), id INT AUTO_INCREMENT PRIMARY KEY "
                    "(MySQL), id INT IDENTITY(1,1) PRIMARY KEY (SQL Server)",
    "sql-cle-etrangere": "REFERENCES table_existante(colonne_existante) ; "
                         "creer d'abord la table visee (ordre du schema)",
    "sql-table-inconnue": "viser une table du schema (db/schema.sql), ou "
                          "l'ajouter au schema par une nouvelle migration",
    "sql-colonne-inconnue": "viser une colonne du schema, ou l'ajouter par "
                            "une migration (ALTER TABLE ... ADD COLUMN)",
    "sql-migration-ordre": "db/migrations/001_xxx.sql, 002_xxx.sql... : un "
                           "numero par migration, sans trou ni doublon",
    "sql-execution": "lire le message de la base : table deja creee "
                     "(IF NOT EXISTS), colonne en double, cle etrangere "
                     "vers une ligne absente (inserer le parent d'abord)",
    "orm-table-absente": "__tablename__ / db_table / @@map / tableName = "
                         "la table du schema, ou ajouter la table par une "
                         "migration",
    "orm-colonne-absente": "ajouter la colonne au schema par une migration "
                           "(ALTER TABLE ... ADD COLUMN), ou la retirer du "
                           "modele",
    "orm-champ-inconnu": "viser un champ declare dans le modele (le nom "
                         "exact), ou le declarer d'abord",
    "prisma-sans-id": "id Int @id @default(autoincrement()) (ou @@id([a, "
                      "b]) pour une cle composee)",
    "prisma-relation": "viser un model du schema (le declarer) ou un type "
                       "Prisma (String, Int, DateTime...)",
    "prisma-datasource": 'datasource db { provider = "postgresql" url = '
                         'env("DATABASE_URL") }',
    "cql-sans-cle": "PRIMARY KEY ((cle_de_partition), colonne_de_tri)",
    "cql-allow-filtering": "une table par requete, cle de partition = le "
                           "filtre",
    "cypher-injection": "session.run('MATCH (c:Client {nom: $nom}) RETURN c',"
                        " nom=valeur)",
    "cypher-sans-etiquette": "MATCH (c:Client) ... (une etiquette, et un "
                             "index sur la propriete filtree)",
    "nosql-injection": "construire le filtre champ par champ, chaque "
                       "valeur verifiee comme une chaine : find({nom: "
                       "String(req.body.nom)}) ; ou mongo-sanitize",
    "nosql-where": "un filtre MongoDB ($eq, $gt, $in, $regex echappe) au "
                   "lieu de $where",
    "redis-keys": "SCAN 0 MATCH prefixe:* COUNT 100, par lots",
    "sql-insert-colonnes": "autant de valeurs que de colonnes : INSERT INTO "
                           "t (a, b) VALUES (?, ?)",
    # Le juge du sens (sens.py, 09/10/2026).
    "texte-provisoire": "le vrai contenu tire de la demande (nom, adresse, "
                        "telephone, horaires) ; s'il est inconnu, retirer "
                        "l'element plutot que laisser « Pied de page »",
    "bouton-sans-effet": "le script vise le bouton (id) et lui donne son "
                         "action : document.getElementById('x')"
                         ".addEventListener('click', ...) ; sinon le retirer",
}


def remede(regle: str) -> str:
    return REMEDES.get(regle, "")
