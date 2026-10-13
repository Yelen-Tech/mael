"""Les juges de la BASE DE DONNEES : le schema, et le code qui s'en sert.

Demande du responsable (09/10/2026) : toutes les bases, avec leurs
dependances. Avant ce module, MAEL ne lisait aucun .sql et ne savait pas si
une requete visait une table qui existe. Ici, avec sqlglot (MIT, 30
dialectes), MAEL juge par LECTURE — sans modele, sans deviner :

  sql-syntaxe          le fichier ne se lit pas dans le dialecte de la base
  sql-sans-cle         une table sans cle primaire
  sql-cle-etrangere    REFERENCES vers une table ou une colonne absente
  sql-table-inconnue   une requete du CODE vise une table absente du schema
  sql-colonne-inconnue une requete du CODE vise une colonne absente
  sql-migration-ordre  migrations non numerotees, trou ou doublon

Le schema = toutes les CREATE TABLE du projet : db/schema.sql, les
migrations (dans l'ordre), et celles ecrites dans le code (une appli qui
cree ses tables au demarrage). La coherence n'est jugee que si un schema
existe : sans schema, on ne sait pas ce qui est juste.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import bases
from .juges import GRAVITE, Defaut

B = GRAVITE.BLOQUANT
C = GRAVITE.CONSEIL

try:
    import sqlglot
    from sqlglot import exp
    from sqlglot.errors import ParseError, TokenError
except ImportError:                                     # pragma: no cover
    sqlglot = None

# Ce qui trahit un dialecte quand le code n'a pas dit sa base.
_INDICES = (
    ("tsql", r"\bIDENTITY\s*\(|\bNVARCHAR\b|^\s*GO\s*$|\[dbo\]"),
    ("oracle", r"\bVARCHAR2\b|\bNUMBER\s*\(|\bNOCOPY\b|\bSYSDATE\b"),
    ("mysql", r"\bAUTO_INCREMENT\b|\bENGINE\s*=|`\w+`|\bUNSIGNED\b"),
    ("postgres", r"\bSERIAL\b|\bBIGSERIAL\b|\bRETURNING\b|\bJSONB\b|"
                 r"\bGENERATED\s+ALWAYS\s+AS\s+IDENTITY\b|::\w+"),
    ("sqlite", r"\bAUTOINCREMENT\b|\bPRAGMA\b"),
)
_DEBUT_SQL = re.compile(r"^\s*(SELECT|INSERT\s+INTO|UPDATE\s+\w+|DELETE\s+FROM|"
                        r"CREATE\s+TABLE|WITH\s+\w+\s+AS)\b", re.I)
# Chaines du code : '...', "...", `...` et les triples guillemets Python.
_CHAINES = re.compile(
    r'"""(.*?)"""|\'\'\'(.*?)\'\'\'|"((?:[^"\\\n]|\\.)*)"|'
    r"'((?:[^'\\\n]|\\.)*)'|`([^`]*)`", re.S)
_CODE = {".py", ".js", ".mjs", ".jsx", ".ts", ".php", ".java", ".go", ".cs"}


def disponible() -> bool:
    return sqlglot is not None


def dialecte(textes_sql: str, code: dict[str, str]) -> str:
    """Le dialecte sqlglot du projet : la base que le CODE utilise (pilote
    importe), sinon les indices du SQL lui-meme, sinon SQLite."""
    for b in bases.detecter("", code):
        if b.sql:
            return b.dialecte
    for nom, motif in _INDICES:
        if re.search(motif, textes_sql, re.I | re.M):
            return nom
    return "sqlite"


# Un projet range parfois un schema PAR BASE (db/h2, db/mysql, db/postgres :
# Spring PetClinic, 13/10/2026) : chacun se lit dans SON dialecte. H2,
# HSQLDB, Derby n'ont pas de dialecte sqlglot : "" = syntaxe non jugee.
_DIALECTE_CHEMIN = (("tsql", r"sqlserver|mssql|tsql"),
                    ("postgres", r"postgres(?:ql)?|pg"),
                    ("mysql", r"mysql|mariadb"), ("oracle", r"oracle"),
                    ("sqlite", r"sqlite3?"), ("", r"h2|hsqldb|hsql|derby"))


def dialecte_du_chemin(f: str) -> str | None:
    p = Path(f)
    for morceau in (*p.parts[:-1], p.stem):
        for nom, motif in _DIALECTE_CHEMIN:
            if re.fullmatch(motif, morceau.lower()) or re.fullmatch(
                    rf"(?:schema|data|init)[-_.]({motif})",
                    morceau.lower()):
                return nom
    return None


def _ligne(texte: str, fragment: str) -> int:
    i = texte.find(fragment[:40]) if fragment else -1
    return texte.count("\n", 0, i) + 1 if i >= 0 else 1


def _nom(x) -> str:
    return (x or "").strip('`"[]').lower()


# --------------------------------------------------------------- schema
class Schema:
    def __init__(self):
        self.tables: dict[str, set[str]] = {}      # table -> colonnes
        self.ou: dict[str, tuple[str, int]] = {}    # table -> (fichier, ligne)

    def connait(self) -> bool:
        return bool(self.tables)


def _instructions(texte: str, dial: str):
    """(instruction, ParseError|None). Les GO de SQL Server separent."""
    if dial == "tsql":
        texte = re.sub(r"(?im)^\s*GO\s*$", ";", texte)
    return sqlglot.parse(texte, read=dial)


def lire_fichier_sql(nom: str, texte: str, dial: str, schema: Schema
                     ) -> list[Defaut]:
    d: list[Defaut] = []
    try:
        arbres = [a for a in _instructions(texte, dial) if a is not None]
    except (ParseError, TokenError) as exc:
        ligne = 1
        erreurs = getattr(exc, "errors", None) or []
        if erreurs and erreurs[0].get("line"):
            ligne = int(erreurs[0]["line"])
        message = str(exc).split("\n")[0][:160]
        return [Defaut(nom, ligne, "sql-syntaxe", B,
                       f"SQL illisible en {dial} : {message}",
                       f"grammaire SQL ({dial})")]
    sans_chaines = re.sub(r"'(?:[^']|'')*'", "''", texte)
    double = re.search(r",\s*,", sans_chaines)
    if double:
        # sqlglot l'accepte ; aucune base ne l'accepte.
        d.append(Defaut(nom, sans_chaines.count("\n", 0, double.start()) + 1,
                        "sql-syntaxe", B, "virgule doublee « ,, » : une "
                        "colonne manque ou une virgule est de trop",
                        f"grammaire SQL ({dial})"))
    for a in arbres:
        d += _insert(nom, texte, a)
        if isinstance(a, exp.Create) and (a.kind or "").upper() == "TABLE":
            d += _table(nom, texte, a, schema)
        elif isinstance(a, exp.Alter):
            cible = a.find(exp.Table)
            t = _nom(cible.name) if cible else ""
            for col in a.find_all(exp.ColumnDef):
                schema.tables.setdefault(t, set()).add(_nom(col.name))
    return d


def _insert(nom: str, texte: str, a, ligne: int | None = None
            ) -> list[Defaut]:
    """INSERT (a, b) VALUES (1) : autant de valeurs que de colonnes, sinon
    la base refuse a l'execution (sqlglot, lui, l'accepte)."""
    if not isinstance(a, exp.Insert) or not isinstance(a.this, exp.Schema):
        return []
    n = len(a.this.expressions)
    valeurs = a.expression
    if not isinstance(valeurs, exp.Values) or not n:
        return []
    for ligne_v in valeurs.expressions:
        m = len(ligne_v.expressions) if isinstance(ligne_v, exp.Tuple) else 1
        if m != n:
            table = _nom(a.this.this.name) if a.this.this else "?"
            return [Defaut(nom, ligne or _ligne(texte, "INSERT"),
                           "sql-insert-colonnes", B,
                           f"INSERT dans « {table} » : {n} colonne(s) pour "
                           f"{m} valeur(s)", "SQL:2016 — INSERT")]
    return []


def _table(nom: str, texte: str, a, schema: Schema) -> list[Defaut]:
    cible = a.this.this if isinstance(a.this, exp.Schema) else a.this
    table = _nom(getattr(cible, "name", ""))
    colonnes = {_nom(c.name) for c in a.find_all(exp.ColumnDef)}
    schema.tables.setdefault(table, set()).update(colonnes)
    ligne = _ligne(texte, re.search(rf"(?i)create\s+table\s+(if\s+not\s+"
                                    rf"exists\s+)?[`\"\[]?{re.escape(table)}",
                                    texte).group(0)
                   if re.search(rf"(?i)create\s+table\s+(if\s+not\s+exists\s+)?"
                                rf"[`\"\[]?{re.escape(table)}", texte) else "")
    schema.ou.setdefault(table, (nom, ligne))
    sql = a.sql().upper()
    d = []
    sans_cle = "PRIMARY KEY" not in sql and not re.search(
        r"INTEGER\s+PRIMARY|AUTOINCREMENT|IDENTITY|SERIAL", sql)
    etrangeres = {_nom(c) for g in re.findall(r"FOREIGN KEY\s*\(([^)]*)\)",
                                              sql) for c in g.split(",")}
    etrangeres |= {_nom(c) for c in re.findall(
        r"([`\"\[]?\w+[`\"\]]?)\s+[^,(]*(?:\([^)]*\))?[^,(]*REFERENCES", sql)}
    if sans_cle and len(colonnes) >= 2 and colonnes <= etrangeres:
        # table de LIAISON (vet_specialties de PetClinic) : un doublon reste
        # possible, mais l'application marche — conseil, pas blocage
        d.append(Defaut(nom, ligne, "sql-sans-cle", C,
                        f"table de liaison « {table} » sans cle primaire : "
                        f"PRIMARY KEY ({', '.join(sorted(colonnes))}) "
                        "empeche les doublons",
                        "modele relationnel (Codd) — 1re forme normale"))
    elif sans_cle:
        d.append(Defaut(nom, ligne, "sql-sans-cle", B,
                        f"table « {table} » sans cle primaire : chaque ligne "
                        "doit pouvoir etre designee (id ... PRIMARY KEY)",
                        "modele relationnel (Codd) — 1re forme normale"))
    return d


def _references(fichiers_sql: dict[str, str], dial: str, schema: Schema
                ) -> list[Defaut]:
    d = []
    for nom, texte in fichiers_sql.items():
        for m in re.finditer(r"(?i)REFERENCES\s+[`\"\[]?(\w+)[`\"\]]?\s*"
                             r"(?:\(\s*[`\"\[]?(\w+)[`\"\]]?\s*\))?", texte):
            t, c = m.group(1).lower(), (m.group(2) or "").lower()
            ligne = texte.count("\n", 0, m.start()) + 1
            if t not in schema.tables:
                d.append(Defaut(nom, ligne, "sql-cle-etrangere", B,
                                f"REFERENCES {t} : la table « {t} » n'existe "
                                "pas dans le schema", "integrite referentielle"
                                " (SQL:2016 — FOREIGN KEY)"))
            elif c and c not in schema.tables[t]:
                d.append(Defaut(nom, ligne, "sql-cle-etrangere", B,
                                f"REFERENCES {t}({c}) : la colonne « {c} » "
                                f"n'existe pas (colonnes : "
                                f"{', '.join(sorted(schema.tables[t]))})",
                                "integrite referentielle (SQL:2016)"))
    return d


def _migrations(fichiers_sql: dict[str, str]) -> list[Defaut]:
    noms = sorted(f for f in fichiers_sql if "/migrations/" in f"/{f}")
    if not noms:
        return []
    d, numeros = [], []
    for f in noms:
        m = re.match(r"(\d+)", Path(f).name)
        if not m:
            d.append(Defaut(f, 1, "sql-migration-ordre", B,
                            "migration sans numero : 001_creer_clients.sql, "
                            "002_..., pour qu'on les rejoue dans l'ordre",
                            "migrations ordonnees (Flyway / golang-migrate)"))
        else:
            numeros.append((int(m.group(1)), f))
    vus = {}
    for n, f in numeros:
        if n in vus:
            d.append(Defaut(f, 1, "sql-migration-ordre", B,
                            f"numero {n:03d} deja pris par {vus[n]}",
                            "migrations ordonnees"))
        vus[n] = f
    attendus = sorted(vus)
    for a, b in zip(attendus, attendus[1:]):
        if b != a + 1:
            d.append(Defaut(vus[b], 1, "sql-migration-ordre", C,
                            f"trou dans la numerotation : {a:03d} puis "
                            f"{b:03d}", "migrations ordonnees"))
    return d


# ------------------------------------------------ le code et le schema
# Les langages de requete OBJET (JPQL de Spring/Hibernate, DQL de Doctrine)
# nomment des classes et des proprietes : les juger comme du SQL donnait
# « table client inconnue » sur un projet juste.
_OBJET = re.compile(r"(?:@Query\s*\(\s*(?:value\s*=\s*)?|"
                    r"\b(?:createQuery|createDQLQuery)\s*\(\s*)$")


def requetes_du_code(nom: str, texte: str) -> list[tuple[int, str]]:
    """(ligne, SQL) des chaines du code qui sont des requetes."""
    out = []
    for m in _CHAINES.finditer(texte):
        s = next(g for g in m.groups() if g is not None)
        if not _DEBUT_SQL.match(s):
            continue
        if _OBJET.search(texte[max(0, m.start() - 80):m.start()]) and \
                not re.match(r"[^)]*nativeQuery\s*=\s*true",
                             texte[m.end():m.end() + 200]):
            continue    # JPQL / DQL : des ENTITES, pas des tables (13/10)
        s = re.sub(r"\$\{[^}]*\}|\{[^}]*\}", "?", s)       # gabarits JS / f-strings
        s = re.sub(r"%\(\w+\)s|%s|\$\d+|:\w+|@\w+", "?", s)  # parametres
        out.append((texte.count("\n", 0, m.start()) + 1, s.replace("\\n", " ")))
    return out


def _coherence(nom: str, ligne: int, sql: str, dial: str, schema: Schema
               ) -> list[Defaut]:
    try:
        arbres = [a for a in sqlglot.parse(sql, read=dial) if a is not None]
    except (ParseError, TokenError):
        # Une requete du code est souvent un MORCEAU ("SELECT * FROM " +
        # table) : illisible seule, sans etre fausse. On ne juge que ce
        # qu'on lit en entier.
        return []
    d = []
    for a in arbres:
        if isinstance(a, exp.Create):
            continue
        d += _insert(nom, sql, a, ligne)
        ctes = {_nom(c.alias) for c in a.find_all(exp.CTE)}
        tables = {}
        for t in a.find_all(exp.Table):
            n = _nom(t.name)
            if not n or n in ctes:
                continue
            tables[n] = _nom(t.alias) or n
            if n not in schema.tables:
                d.append(Defaut(nom, ligne, "sql-table-inconnue", B,
                                f"la requete vise la table « {n} », absente "
                                f"du schema (tables : "
                                f"{', '.join(sorted(schema.tables))})",
                                "contrat code <-> schema de la base"))
        # « * » : table d'un modele ORM incomplet, colonnes non toutes connues
        connues = {n: schema.tables[n] for n in tables
                   if n in schema.tables and "*" not in schema.tables[n]}
        if not connues:
            continue
        alias = {v: k for k, v in tables.items()}
        definis = {_nom(x.alias) for x in a.find_all(exp.Alias)}
        for col in a.find_all(exp.Column):
            c = _nom(col.name)
            if not c or c == "*" or c in definis:
                continue
            qual = _nom(col.table)
            if qual:
                t = alias.get(qual, qual)
                if t in connues and c not in connues[t]:
                    d.append(_colonne(nom, ligne, c, t, connues[t]))
            elif not any(c in cols for cols in connues.values()):
                t = next(iter(connues))
                d.append(_colonne(nom, ligne, c, t, connues[t]))
    return d


def _colonne(nom, ligne, c, t, cols) -> Defaut:
    return Defaut(nom, ligne, "sql-colonne-inconnue", B,
                  f"la requete vise la colonne « {c} » de « {t} », absente "
                  f"du schema (colonnes : {', '.join(sorted(cols))})",
                  "contrat code <-> schema de la base")


# ------------------------------------------- l'execution REELLE (SQLite)
def ordre_d_application(fichiers: list[str]) -> list[str]:
    """schema.sql (les tables de depart), puis les migrations dans l'ordre
    de leur numero, puis les donnees (seeds), puis le reste de db/."""
    def rang(f):
        nom = Path(f).name
        if nom in {"schema.sql", "schema.cql"}:
            return (0, 0, f)
        if "/migrations/" in f"/{f}":
            m = re.match(r"(\d+)", nom)
            return (1, int(m.group(1)) if m else 10 ** 6, f)
        if "/seeds/" in f"/{f}":
            return (2, 0, f)
        return (3, 0, f)
    return sorted(fichiers, key=rang)


def executer_sqlite(sqls: dict[str, str], ecartes: set[str] = frozenset()
                    ) -> list[Defaut]:
    """Rejouer VRAIMENT le schema, les migrations et les donnees dans une
    base SQLite en memoire, cles etrangeres activees. Ce que SQLite refuse
    est un defaut certain : c'est la base elle-meme qui le dit."""
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys = ON")
    d = []
    try:
        for f in ordre_d_application(list(sqls)):
            if f in ecartes:
                continue                  # deja illisible : dit une fois
            try:
                con.executescript(sqls[f])
            except sqlite3.Error as exc:
                d.append(Defaut(f, 1, "sql-execution", B,
                                f"SQLite refuse ce fichier (rejoue apres "
                                f"les precedents) : {exc}",
                                "execution reelle (SQLite en memoire)",
                                sources=("mael", "sqlite")))
    finally:
        con.close()
    return d


# ---------------------------------------------------------------- juger
def juger(racine: Path, vus: list[str]) -> list[Defaut]:
    if not disponible():
        return []
    racine = Path(racine)
    sqls, code = {}, {}
    for f in vus:
        ext = Path(f).suffix.lower()
        try:
            texte = (racine / f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if ext == ".sql":
            sqls[f] = texte
        elif ext in _CODE:
            code[f] = texte
    from . import juges_orm
    orm = juges_orm.modeles_du_projet(racine, vus)
    if not sqls and not orm and not any(requetes_du_code(n, t)
                                        for n, t in code.items()):
        return []
    dial = dialecte("\n".join(sqls.values()), code)
    schema = Schema()
    d: list[Defaut] = []
    # schema.sql d'abord, puis les migrations dans l'ordre, puis le reste.
    ordre = sorted(sqls, key=lambda f: (Path(f).name != "schema.sql",
                                        "/migrations/" not in f"/{f}", f))
    for f in ordre:
        df = dialecte_du_chemin(f)
        if df == "":                # H2, HSQLDB, Derby : syntaxe non jugee
            d += [x for x in lire_fichier_sql(f, sqls[f], dial, schema)
                  if x.regle != "sql-syntaxe"]
        else:
            d += lire_fichier_sql(f, sqls[f], df or dial, schema)
    requetes = {n: requetes_du_code(n, t) for n, t in code.items()}
    for n, rs in requetes.items():               # les CREATE TABLE du code
        for ligne, sql in rs:
            if re.match(r"\s*CREATE\s+TABLE", sql, re.I):
                d += lire_fichier_sql(n, sql, dial, schema)
    d += _references(sqls, dial, schema) + _migrations(sqls)
    if dial == "sqlite" and sqls:
        illisibles = {x.fichier for x in d if x.regle in {
            "sql-syntaxe", "sql-insert-colonnes"}}    # deja dits a la lecture
        d += executer_sqlite(sqls, illisibles)
    # Les ORM : modeles contre le schema SQL s'il existe ; sinon, ce sont
    # les modeles qui font le schema des requetes ecrites a la main.
    if orm:
        sql_ecrit = {t: set(c) for t, c in schema.tables.items()}
        d += juges_orm.juger(racine, vus, sql_ecrit if sqls else None)
        if not sqls:
            for t, cols in juges_orm.tables_orm(racine, vus).items():
                schema.tables.setdefault(t, set()).update(cols)
    if schema.connait():
        for n, rs in requetes.items():
            for ligne, sql in rs:
                if not re.match(r"\s*CREATE\s+TABLE", sql, re.I):
                    d += _coherence(n, ligne, sql, dial, schema)
    return d


def limites() -> list[str]:
    if not disponible():
        return ["base de donnees non jugee : sqlglot absent "
                "(pip install sqlglot)"]
    return []
