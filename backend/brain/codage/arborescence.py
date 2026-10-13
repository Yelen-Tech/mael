"""L'ARBORESCENCE STANDARD : MAEL range un projet comme un vrai projet.

Examen des 100 missions (09/10/2026), remarque du responsable : « les
dossiers ne sont pas convaincants, il n'y a pas une arborescence au
standard, meme pas celle de notre dossier sentinelle ». Les sept projets
avaient sept formes : styles.css a la racine ou dans css/, un footer.html
juge comme une page, jamais de README ni de .gitignore — et le lecteur du
plan refusait tout fichier qui n'est pas du code.

Decision du responsable (09/10) : la FORME est imposee par MAEL, pas par
le modele. Le modele dit QUELS fichiers ; MAEL dit OU ils vont :

  SITE                      API PYTHON (Flask / FastAPI)
  README.md                 README.md, requirements.txt, .gitignore,
  index.html, pages.html    .env.example
  assets/css/  assets/js/   app/__init__.py  app/main.py  app/models.py ...
  assets/images/            app/templates/  app/static/   tests/test_*.py

et de meme pour PHP, Node/Express et React. Les fichiers SIMPLES (README,
.gitignore, requirements.txt, package.json, .env.example) sont ecrits par
MAEL lui-meme, a partir des FAITS du projet (imports, variables
d'environnement lues, fichiers presents) : rien n'y est invente.
Django et Java gardent leur propre forme (celle de leurs outils).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PAGES = {".html", ".htm"}
SCRIPTS = {".js", ".mjs"}

# Un morceau de page n'est pas une page : il s'ecrit DANS chaque page
# (leviers plan-sans-fragments / fragments-sans-criteres-de-page).
_FRAGMENTS = re.compile(
    r"^(header|footer|nav|navbar|menu|entete|en-tete|en_tete|pied|"
    r"pied-de-page|pied_de_page|piedpage|sidebar|barre-laterale)$", re.I)


def est_fragment(chemin: str) -> bool:
    p = Path(chemin)
    return p.suffix.lower() in PAGES and bool(_FRAGMENTS.match(p.stem))


def type_de_projet(demande: str, fichiers: list[str]) -> str:
    """site | python | django | php | node | react | java."""
    d = demande.lower()
    ext = {Path(f).suffix.lower() for f in fichiers}
    noms = {Path(f).name.lower() for f in fichiers}
    if "django" in d or {"manage.py", "settings.py"} & noms:
        return "django"
    if ".java" in ext or "pom.xml" in noms:
        return "java"
    if ".go" in ext or "go.mod" in noms:
        return "go"
    if ".cs" in ext or any(n.endswith(".csproj") for n in noms):
        return "csharp"
    if ".jsx" in ext or re.search(r"\breact\b", d):
        return "react"
    if ".php" in ext or re.search(r"\bphp\b", d):
        return "php"
    if ".py" in ext:
        return "python"
    if re.search(r"\b(express|node(\.?js)?)\b", d) or noms & {
            "server.js", "serveur.js"}:
        return "node"
    return "site"


_SERVEUR_JS = re.compile(
    r"^(server|serveur|app|index|main|routes?|db|database|config|models?|"
    r"controllers?|middleware)$", re.I)
_PRINCIPAL_PY = {"app", "main", "server", "serveur", "api", "application"}


def _test(nom: str) -> bool:
    n = nom.lower()
    return (n.startswith("test_") or n.endswith("_test.py")
            or ".test." in n or ".spec." in n)


def ranger_base(chemin: str) -> str | None:
    """La place standard d'un fichier de BASE, quel que soit le projet :
    db/schema.sql, db/migrations/NNN_x.sql, db/seeds/x.sql ; le schema
    Prisma dans prisma/. None si ce n'est pas un fichier de base."""
    p = Path(chemin)
    nom, ext = p.name, p.suffix.lower()
    if ext == ".prisma":
        return "prisma/schema.prisma"
    if ext == ".cql":                     # Cassandra : son schema a part
        return ("db/schema.cql" if "schema" in nom.lower()
                else f"db/cql/{nom}")
    if ext != ".sql":
        return None
    bas = nom.lower()
    if "migration" in chemin.lower() or re.match(r"\d+[_-]", bas):
        return f"db/migrations/{nom}"
    if re.search(r"seed|donnee|data|fixture|jeu|exemple|initial", bas):
        return f"db/seeds/{nom}"
    if "schema" in bas or bas in {"db.sql", "base.sql", "tables.sql",
                                   "database.sql", "bdd.sql", "init.sql"}:
        return "db/schema.sql"
    return f"db/{nom}"


def ranger(chemin: str, sorte: str) -> str:
    """Le chemin STANDARD d'un fichier du plan, selon le type de projet."""
    p = Path(chemin)
    nom, ext = p.name, p.suffix.lower()
    base = ranger_base(chemin)
    if base is not None:
        return base
    if sorte in {"django", "java", "go", "csharp"}:
        return chemin              # leur forme propre : point 5 (langages)
    if sorte == "site":
        if ext in PAGES:
            return nom
        if ext == ".css":
            return f"assets/css/{nom}"
        if ext in SCRIPTS:
            return f"assets/js/{nom}"
        return chemin
    if sorte == "python":
        if ext == ".py":
            if _test(nom) or "tests" in p.parts:
                return f"tests/{nom}"
            if p.stem.lower() in _PRINCIPAL_PY:
                return "app/main.py"
            return f"app/{nom}"
        if ext in PAGES:
            return f"app/templates/{nom}"
        if ext == ".css":
            return f"app/static/css/{nom}"
        if ext in SCRIPTS:
            return f"app/static/js/{nom}"
        return chemin
    if sorte == "php":
        if ext == ".php":
            if p.stem.lower() in {"config", "db", "database", "connexion-bd",
                                  "fonctions", "functions", "auth"}:
                return f"includes/{nom}"
            return nom
        if ext in PAGES:
            return nom
        if ext == ".css":
            return f"assets/css/{nom}"
        if ext in SCRIPTS:
            return f"assets/js/{nom}"
        return chemin
    if sorte == "node":
        if ext in SCRIPTS:
            if _test(nom):
                return f"tests/{nom}"
            if _SERVEUR_JS.match(p.stem) or "src" in p.parts \
                    or "routes" in p.parts:
                return f"src/{nom}" if "routes" not in p.parts \
                    else f"src/routes/{nom}"
            return f"public/js/{nom}"
        if ext in PAGES:
            return f"public/{nom}"
        if ext == ".css":
            return f"public/css/{nom}"
        return chemin
    if sorte == "react":
        if ext == ".jsx":
            if p.stem in {"App", "main", "index"}:
                return f"src/{nom}"
            return f"src/components/{nom}"
        if ext in SCRIPTS:
            if _test(nom):
                return f"src/{nom}"
            return f"src/{nom}"
        if ext == ".css":
            return f"src/{nom}"
        if ext in PAGES:
            return nom                       # index.html de Vite, a la racine
        return chemin
    return chemin


def ranger_plan(fichiers: list[str], demande: str
                ) -> tuple[str, dict[str, str], list[str]]:
    """(type, {ancien: nouveau}, fragments retires) pour tout le plan.
    Deux fichiers qui tomberaient au meme endroit gardent leur chemin."""
    sorte = type_de_projet(demande, fichiers)
    fragments = [f for f in fichiers if est_fragment(f)]
    gardes = [f for f in fichiers if f not in fragments]
    cibles: dict[str, str] = {f: ranger(f, sorte) for f in gardes}
    vus: dict[str, int] = {}
    for c in cibles.values():
        vus[c] = vus.get(c, 0) + 1
    return sorte, {f: (c if vus[c] == 1 else f) for f, c in cibles.items()}, \
        fragments


# ------------------------------------------------- ce que MAEL ecrit seul
_GITIGNORE = {
    "commun": ["# Ecrit par MAEL", ".env", ".DS_Store", "Thumbs.db", ".vscode/",
               ".idea/", "*.log"],
    "python": ["__pycache__/", "*.py[cod]", ".venv/", "venv/", ".pytest_cache/",
               "*.db", "*.sqlite3", "instance/"],
    "django": ["__pycache__/", "*.py[cod]", ".venv/", "venv/", "db.sqlite3",
               "staticfiles/", "media/"],
    "node": ["node_modules/", "dist/", "coverage/", "*.db", "*.sqlite"],
    "react": ["node_modules/", "dist/", "coverage/"],
    "php": ["vendor/", "*.db", "*.sqlite", "uploads/*", "!uploads/.gitkeep"],
    "java": ["target/", "build/", "*.class", ".gradle/"],
    "go": ["bin/", "*.exe", "*.test", "vendor/"],
    "csharp": ["bin/", "obj/", "*.user", ".vs/"],
    "site": [],
}

# module importe -> paquet pip (seulement les bibliotheques tierces connues)
_PAQUETS_PY = {
    "flask": "flask", "flask_sqlalchemy": "flask-sqlalchemy",
    "flask_login": "flask-login", "flask_wtf": "flask-wtf",
    "flask_cors": "flask-cors", "fastapi": "fastapi", "uvicorn": "uvicorn",
    "pydantic": "pydantic", "sqlalchemy": "sqlalchemy", "jwt": "pyjwt",
    "dotenv": "python-dotenv", "requests": "requests", "httpx": "httpx",
    "bcrypt": "bcrypt", "passlib": "passlib", "jinja2": "jinja2",
    "werkzeug": "werkzeug", "pytest": "pytest", "itsdangerous":
    "itsdangerous", "email_validator": "email-validator", "PIL": "pillow",
    "multipart": "python-multipart", "psycopg2": "psycopg2-binary",
    "pymysql": "pymysql", "marshmallow": "marshmallow", "django": "django",
    "psycopg": "psycopg[binary]", "pymongo": "pymongo", "redis": "redis",
    "oracledb": "oracledb", "pyodbc": "pyodbc", "alembic": "alembic",
    "duckdb": "duckdb", "neo4j": "neo4j", "elasticsearch": "elasticsearch",
}
_PAQUETS_JS = {"express", "cors", "dotenv", "sqlite3", "better-sqlite3",
               "mysql2", "pg", "bcrypt", "bcryptjs", "jsonwebtoken", "multer",
               "helmet", "express-session", "express-rate-limit",
               "express-validator", "uuid", "morgan", "cookie-parser",
               "supertest", "jest", "axios", "react", "react-dom",
               "react-router-dom", "nodemailer"}


def _textes(racine: Path, ext: set[str]) -> dict[str, str]:
    out = {}
    for p in sorted(Path(racine).rglob("*")):
        rel = p.relative_to(racine).as_posix()
        if p.is_file() and p.suffix.lower() in ext and not rel.startswith(
                (".mael/", "node_modules/", "venv/", ".venv/")):
            out[rel] = p.read_text(encoding="utf-8", errors="replace")
    return out


def dependances_python(racine: Path) -> list[str]:
    vus = set()
    for t in _textes(racine, {".py"}).values():
        for m in re.finditer(r"(?m)^\s*(?:from|import)\s+([A-Za-z_]\w*)", t):
            if m.group(1) in _PAQUETS_PY:
                vus.add(_PAQUETS_PY[m.group(1)])
    if "fastapi" in vus:
        vus |= {"uvicorn"}
        if any("TestClient" in t for t in _textes(racine, {".py"}).values()):
            vus.add("httpx")
    if (Path(racine) / "tests").exists():
        vus.add("pytest")
    return sorted(vus)


def dependances_js(racine: Path) -> list[str]:
    vus = set()
    for t in _textes(racine, {".js", ".mjs", ".jsx"}).values():
        for m in re.finditer(r"""(?:require\(\s*|from\s+)['"]([^'"./][^'"]*)['"]""", t):
            nom = m.group(1)
            nom = "/".join(nom.split("/")[:2]) if nom.startswith("@") \
                else nom.split("/")[0]
            if nom in _PAQUETS_JS:
                vus.add(nom)
    return sorted(vus)


def variables_env(racine: Path) -> list[str]:
    vus = set()
    for t in _textes(racine, {".py", ".js", ".mjs", ".php"}).values():
        vus |= set(re.findall(
            r"""(?:os\.environ\.get|os\.getenv|os\.environ\[)\s*\(?\s*['"](\w+)['"]""", t))
        vus |= set(re.findall(r"process\.env\.([A-Z_][A-Z0-9_]*)", t))
        vus |= set(re.findall(r"""getenv\(\s*['"](\w+)['"]""", t))
    return sorted(vus)


def arbre(racine: Path) -> str:
    """L'arborescence reelle, facon `tree` (sans .mael ni JOURNAL)."""
    racine = Path(racine)
    lignes = [f"{racine.name}/"]

    def descendre(dossier: Path, prefixe: str):
        enfants = sorted(
            (p for p in dossier.iterdir()
             if p.name not in {".mael", "JOURNAL.md", "__pycache__",
                               "node_modules"}),
            key=lambda p: (p.is_file(), p.name.lower()))
        for i, p in enumerate(enfants):
            dernier = i == len(enfants) - 1
            lignes.append(f"{prefixe}{'└── ' if dernier else '├── '}"
                          f"{p.name}{'/' if p.is_dir() else ''}")
            if p.is_dir():
                descendre(p, prefixe + ("    " if dernier else "│   "))
    descendre(racine, "")
    return "\n".join(lignes)


_LANCER = {
    "site": "Ouvrir `index.html` dans un navigateur (aucune installation).",
    "python": ("```\npython -m venv .venv\n.venv\\Scripts\\activate   "
               "(Windows)  ou  source .venv/bin/activate\n"
               "pip install -r requirements.txt\n{commande}\n```"),
    "django": ("```\npip install -r requirements.txt\npython manage.py "
               "migrate\npython manage.py runserver\n```"),
    "php": "```\nphp -S localhost:8000\n```\npuis ouvrir http://localhost:8000",
    "node": "```\nnpm install\nnpm start\n```",
    "react": "```\nnpm install\nnpm run dev\n```",
    "java": "```\nmvn -q package\n```",
    "go": "```\ngo mod tidy\ngo run .\n```",
    "csharp": "```\ndotnet restore\ndotnet run\n```",
}
_TESTER = {"python": "```\npython -m pytest\n```",
           "django": "```\npython manage.py test\n```",
           "node": "```\nnpm test\n```", "react": "```\nnpm test\n```"}


def _commande_python(racine: Path) -> str:
    principal = Path(racine) / "app" / "main.py"
    texte = principal.read_text(encoding="utf-8", errors="replace") \
        if principal.exists() else ""
    if "FastAPI(" in texte:
        return "uvicorn app.main:app --reload"
    return "flask --app app.main run"


# --------------------------------------------- la BASE DE DONNEES (09/10)
def bases_du_projet(racine: Path, demande: str) -> list:
    """Les bases du projet : nommees dans la demande, reconnues dans le code
    (pilotes), sinon SQLite si la demande parle de donnees a garder."""
    from . import bases as bd
    code = _textes(racine, {".py", ".js", ".mjs", ".jsx", ".ts", ".php",
                            ".java", ".go", ".cs"})
    trouvees = bd.detecter(demande, code)
    if not trouvees and (bd.base_par_defaut(demande)
                         or _textes(racine, {".sql"})):
        trouvees = [bd.PAR_ID["sqlite"]]
    return trouvees


def _variable_env(b) -> str:
    return {"mongodb": "MONGODB_URI", "redis": "REDIS_URL",
            "elasticsearch": "ELASTICSEARCH_URL", "neo4j": "NEO4J_URI",
            "cassandra": "CASSANDRA_URL"}.get(b.id, "DATABASE_URL")


def compose(liste) -> str:
    """docker-compose.yml : un service par base qui a un serveur."""
    services = [b for b in liste if b.image]
    if not services:
        return ""
    l = ["# Ecrit par MAEL : les bases du projet. Lancer : docker compose up -d",
         "services:"]
    volumes = []
    for b in services:
        l += [f"  {b.id}:", f"    image: {b.image}", "    restart: unless-stopped",
              "    ports:", f'      - "{b.port}:{b.port}"']
        if b.env_docker:
            l.append("    environment:")
            l += [f"      {k}: \"{v}\"" for k, v in b.env_docker]
        donnees = {"postgres": "/var/lib/postgresql/data",
                   "mysql": "/var/lib/mysql", "mariadb": "/var/lib/mysql",
                   "sqlserver": "/var/opt/mssql",
                   "oracle": "/opt/oracle/oradata", "mongodb": "/data/db",
                   "redis": "/data", "cassandra": "/var/lib/cassandra",
                   "neo4j": "/data",
                   "elasticsearch": "/usr/share/elasticsearch/data"}[b.id]
        l += ["    volumes:", f"      - {b.id}-donnees:{donnees}"]
        volumes.append(b.id)
    l += ["volumes:"] + [f"  {v}-donnees:" for v in volumes]
    return "\n".join(l) + "\n"


_APPLIQUER_SCHEMA = {
    "sqlite": "sqlite3 db/app.db < db/schema.sql",
    "postgres": "psql \"$DATABASE_URL\" -f db/schema.sql",
    "mysql": "mysql -h 127.0.0.1 -u app -p app < db/schema.sql",
    "mariadb": "mariadb -h 127.0.0.1 -u app -p app < db/schema.sql",
    "sqlserver": "sqlcmd -S localhost -U sa -i db/schema.sql",
    "oracle": "sqlplus app@localhost:1521/FREEPDB1 @db/schema.sql",
    "duckdb": "duckdb db/analyse.duckdb < db/schema.sql",
}


def readme_base(racine: Path, liste) -> list[str]:
    if not liste:
        return []
    l = ["", "## Base de donnees", ""]
    for b in liste:
        l.append(f"- **{b.nom}** ({b.famille}) — adresse dans "
                 f"`{_variable_env(b)}` (voir `.env.example`)")
    if any(b.image for b in liste):
        l += ["", "Demarrer les bases : `docker compose up -d`"]
    if (Path(racine) / "db" / "schema.sql").exists():
        sql = next((b for b in liste if b.sql), None)
        if sql and sql.id in _APPLIQUER_SCHEMA:
            l += ["", "Creer les tables :", "```",
                  _APPLIQUER_SCHEMA[sql.id], "```"]
    if (Path(racine) / "db" / "migrations").is_dir():
        l += ["", "Les migrations `db/migrations/` s'appliquent dans l'ordre "
              "de leur numero (001, 002...)."]
    return l


def tables_du_schema(racine: Path) -> dict[str, set[str]]:
    """Les tables et colonnes deja ecrites dans db/ (schema + migrations)."""
    from . import juges_sql
    if not juges_sql.disponible():
        return {}
    sqls = _textes(racine, {".sql"})
    if not sqls:
        return {}
    dial = juges_sql.dialecte("\n".join(sqls.values()), {})
    schema = juges_sql.Schema()
    for f in sorted(sqls, key=lambda f: (Path(f).name != "schema.sql", f)):
        juges_sql.lire_fichier_sql(f, sqls[f], dial, schema)
    return schema.tables


def consigne_base(racine: Path, liste, fichier: str) -> str:
    """Ce que le modele doit savoir de LA base pour ce fichier."""
    if not liste:
        return ""
    ext = Path(fichier).suffix.lower()
    sql = next((b for b in liste if b.sql), None)
    l = []
    if ext == ".sql" and sql:
        l.append(f"base : {sql.nom} — ecris dans SON dialecte "
                 f"({sql.dialecte}) ; chaque table a une cle primaire ; une "
                 "cle etrangere vise une table deja creee ; db/schema.sql = "
                 "les tables de DEPART, puis chaque changement = "
                 "db/migrations/NNN_nom.sql (rejouees dans l'ordre APRES le "
                 "schema), db/seeds/ = des donnees d'exemple (en dernier)")
    elif ext in {".py", ".js", ".mjs", ".ts", ".php", ".java", ".go", ".cs"}:
        for b in liste:
            l.append(f"base {b.nom} : lis son adresse dans la variable "
                     f"d'environnement {_variable_env(b)} (jamais en dur)")
        if sql:
            l.append("requetes PREPAREES (parametres ?, %s, $1, :nom), "
                     "jamais de texte colle a une requete")
    tables = tables_du_schema(racine) if ext != ".sql" or "migrations" in \
        fichier else {}
    if tables and sql:
        l.append("tables du schema (ton code est juge contre elles) : "
                 + " ; ".join(f"{t}({', '.join(sorted(c))})"
                              for t, c in sorted(tables.items())))
    return " ; ".join(l)


def annexes(racine: Path, sorte: str, demande: str,
            provisoires: list[str] = ()) -> dict[str, str]:
    """Les fichiers simples que MAEL ecrit lui-meme : {chemin: contenu}.
    Seulement ceux qui n'existent pas deja (on n'ecrase jamais)."""
    racine = Path(racine)
    out: dict[str, str] = {}
    from . import bases as bd
    liste = bases_du_projet(racine, demande)
    langue = bd.langage_du_projet(sorte)
    pilotes = sorted({p for b in liste for p in b.pilotes_pour(langue)})
    titre = re.sub(r"\s+", " ", demande.strip()).split(":")[0][:80]
    titre = titre[:1].upper() + titre[1:]
    lancer = _LANCER.get(sorte, "")
    if sorte == "python":
        lancer = lancer.format(commande=_commande_python(racine))
    readme = [f"# {titre}", "", "## Ce que c'est", "", demande.strip(), "",
              "## Arborescence", "", "```", arbre(racine), "```", "",
              "## Lancer le projet", "", lancer]
    if sorte in _TESTER and (racine / "tests").exists() or sorte in {
            "node", "react"} and any(_test(p.name) for p in racine.rglob("*")):
        readme += ["", "## Lancer les tests", "", _TESTER[sorte]]
    env = variables_env(racine)
    # Les adresses des bases, avec une valeur d'EXEMPLE (jamais un secret).
    valeurs = {_variable_env(b): b.url for b in liste if b.url}
    env = sorted(set(env) | set(valeurs))
    readme += readme_base(racine, liste)
    if env:
        readme += ["", "## Configuration", "",
                   "Copier `.env.example` en `.env` et le remplir :",
                   *[f"- `{v}`" for v in env]]
    if provisoires:
        readme += ["", "## A remplacer", "",
                   "Images provisoires posees par MAEL (a remplacer par les "
                   "vraies) :", *[f"- `{p}`" for p in provisoires]]
    readme += ["", "---", "", "Projet ecrit avec MAEL (Yelen Tech) : chaque "
               "fichier a ete juge (normes, accessibilite, securite) ; le "
               "detail est dans `.mael/`.", ""]
    out["README.md"] = "\n".join(readme)
    lignes = _GITIGNORE["commun"] + _GITIGNORE.get(sorte, [])
    if sorte != "site":
        out[".gitignore"] = "\n".join(lignes) + "\n.mael/\n"
    if env:
        out[".env.example"] = "".join(f"{v}={valeurs.get(v, '')}\n"
                                      for v in env)
    if compose(liste):
        out["docker-compose.yml"] = compose(liste)
    if sorte == "php":
        exigences = {"php": ">=8.1"}
        exigences.update({p: "*" for p in pilotes})
        out["composer.json"] = json.dumps(
            {"name": "mael/" + (re.sub(r"[^a-z0-9-]+", "-",
                                       racine.name.lower()).strip("-")
                                or "projet"),
             "type": "project", "require": exigences}, indent=2) + "\n"
    if sorte in {"python", "django"}:
        deps = sorted(set(dependances_python(racine)) | set(pilotes))
        if deps:
            out["requirements.txt"] = "\n".join(deps) + "\n"
        if (racine / "app").is_dir() and not (racine / "app" /
                                              "__init__.py").exists():
            out["app/__init__.py"] = ""
    if sorte in {"node", "react"}:
        deps = sorted(set(dependances_js(racine)) | set(pilotes))
        dev = [d for d in deps if d in {"jest", "supertest"}]
        if sorte == "node":
            principal = next((f for f in ("src/server.js", "src/app.js",
                                          "src/index.js", "server.js")
                              if (racine / f).exists()), "src/server.js")
            scripts = {"start": f"node {principal}"}
            if any(_test(p.name) for p in racine.rglob("*.js")):
                scripts["test"] = "jest"
                dev = sorted(set(dev) | {"jest"})
        else:
            deps = sorted(set(deps) | {"react", "react-dom"})
            scripts = {"dev": "vite", "build": "vite build"}
            dev = sorted(set(dev) | {"vite", "@vitejs/plugin-react"})
        paquet = {"name": re.sub(r"[^a-z0-9-]+", "-", racine.name.lower())
                  .strip("-") or "projet", "version": "1.0.0",
                  "private": True, "scripts": scripts,
                  "dependencies": {d: "*" for d in deps if d not in dev},
                  "devDependencies": {d: "*" for d in dev}}
        if sorte == "react":
            paquet["type"] = "module"
        out["package.json"] = json.dumps(paquet, indent=2,
                                         ensure_ascii=False) + "\n"
    out.update(fichiers_de_construction(racine, sorte, pilotes))
    return {k: v for k, v in out.items() if not (racine / k).exists()}


def _nom_projet(racine: Path) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", Path(racine).name.lower()).strip("-") \
        or "projet"


def fichiers_de_construction(racine: Path, sorte: str, pilotes: list[str]
                             ) -> dict[str, str]:
    """pom.xml (Java), go.mod (Go), <nom>.csproj (C#) avec les pilotes de
    la base, aux versions relevees (bases.VERSIONS). La forme complete de
    ces langages vient au point 5 ; ici, ce qu'il faut pour se connecter."""
    from .bases import GO_VERSION, VERSIONS
    nom = _nom_projet(racine)
    if sorte == "java":
        deps = "".join(
            "    <dependency>\n"
            f"      <groupId>{p.split(':')[0]}</groupId>\n"
            f"      <artifactId>{p.split(':')[1]}</artifactId>\n"
            f"      <version>{VERSIONS[p]}</version>\n"
            "    </dependency>\n" for p in pilotes if p in VERSIONS)
        return {"pom.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
            "  <modelVersion>4.0.0</modelVersion>\n"
            "  <groupId>bf.mael</groupId>\n"
            f"  <artifactId>{nom}</artifactId>\n"
            "  <version>1.0.0</version>\n"
            "  <properties>\n"
            "    <maven.compiler.release>21</maven.compiler.release>\n"
            "    <project.build.sourceEncoding>UTF-8"
            "</project.build.sourceEncoding>\n"
            "  </properties>\n"
            "  <dependencies>\n" + deps + "  </dependencies>\n"
            "</project>\n")}
    if sorte == "go":
        deps = "".join(f"\t{p} {VERSIONS[p]}\n" for p in pilotes
                       if p in VERSIONS)
        return {"go.mod": f"module {nom}\n\ngo {GO_VERSION}\n"
                + (f"\nrequire (\n{deps})\n" if deps else "")}
    if sorte == "csharp":
        refs = "".join(f'    <PackageReference Include="{p}" '
                       f'Version="{VERSIONS[p]}" />\n' for p in pilotes
                       if p in VERSIONS)
        return {f"{nom}.csproj": (
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <PropertyGroup>\n"
            "    <OutputType>Exe</OutputType>\n"
            "    <TargetFramework>net10.0</TargetFramework>\n"
            "    <Nullable>enable</Nullable>\n"
            "  </PropertyGroup>\n"
            + (f"  <ItemGroup>\n{refs}  </ItemGroup>\n" if refs else "")
            + "</Project>\n")}
    return {}


def consigne(sorte: str, fichier: str) -> str:
    """Ce que le modele doit savoir de la forme du projet pour CE fichier."""
    ext = Path(fichier).suffix.lower()
    l = []
    if sorte == "site" and ext in PAGES:
        l.append("les feuilles de style sont dans assets/css/, les scripts "
                 "dans assets/js/, les images dans assets/images/")
    if sorte == "python" and ext == ".py":
        l.append("le code est le paquet app/ (app/__init__.py existe) : "
                 "importe avec « from app.models import ... » ; un test "
                 "importe l'application avec « from app.main import app »")
    if sorte == "python" and ext in PAGES:
        l.append("c'est un gabarit de app/templates/ ; styles et scripts "
                 "viennent de app/static/ (url_for('static', ...))")
    if sorte == "node" and ext in SCRIPTS and fichier.startswith("src/"):
        l.append("le serveur sert le dossier public/ (express.static) ; "
                 "le code serveur est dans src/")
    if sorte in {"site", "php", "node"} and ext in PAGES | {".php"}:
        l.append("l'en-tete, le menu et le pied de page s'ecrivent DANS "
                 "chaque page (pas de fichier header.html ou footer.html)")
    return " ; ".join(l)
