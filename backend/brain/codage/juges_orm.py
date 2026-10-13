"""Les juges des ORM : les modeles du code, le schema, et les requetes.

Avec un ORM, le schema est DECLARE dans le code (une classe = une table).
Trois ecarts cassent une application a la premiere requete, et se voient par
lecture, sans modele :

  orm-table-absente    le modele vise une table absente du schema SQL
  orm-colonne-absente  le modele declare une colonne absente du schema SQL
  orm-champ-inconnu    une requete de l'ORM vise un champ que le modele n'a
                       pas (Client.objects.filter(vile=...), prisma.client.
                       findMany({ where: { vile } }))

ORM lus (09/10/2026) : SQLAlchemy et Flask-SQLAlchemy, Django (Python, par
l'arbre syntaxique) ; Prisma, Sequelize, Mongoose, TypeORM (par lecture des
declarations). Hibernate, Entity Framework, GORM, Doctrine : avec leurs
langages (point 5 de la feuille de route) — dit dans limites().
Les modeles servent aussi de schema aux requetes SQL ecrites a la main
quand le projet n'a pas de .sql (tables_orm, lu par juges_sql).
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from .juges import GRAVITE, Defaut

B = GRAVITE.BLOQUANT
NORME = "contrat modele ORM <-> schema de la base"


@dataclass
class Modele:
    classe: str
    table: str
    champs: set[str] = field(default_factory=set)        # colonnes
    autres: set[str] = field(default_factory=set)        # relations, methodes
    fichier: str = ""
    ligne: int = 1
    orm: str = ""
    cles_etrangeres: dict[str, str] = field(default_factory=dict)  # champ -> colonne
    complet: bool = True         # tous ses champs sont-ils VUS ? (sinon :
                                 # parent hors du projet, Eloquent...)

    def connait(self, nom: str) -> bool:
        if not self.complet:
            return True          # jamais de « champ inconnu » a l'aveugle
        return (nom in self.champs or nom in self.autres
                or nom in self.cles_etrangeres.values()
                or nom in {"id", "pk"})


def _serpent(nom: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", nom).lower()


# ------------------------------------------------------- Python (AST)
_COLONNES_SQLA = {"Column", "mapped_column"}
_RELATIONS = {"relationship", "backref", "synonym", "column_property",
              "hybrid_property", "association_proxy"}
_BASES_SQLA = re.compile(r"\b(Base|DeclarativeBase|db\.Model|Model|"
                         r"SQLModel)\b")


def _nom_appel(n) -> str:
    f = n.func if isinstance(n, ast.Call) else None
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


def modeles_python(nom: str, texte: str) -> list[Modele]:
    try:
        arbre = ast.parse(texte)
    except SyntaxError:
        return []
    out = []
    for c in ast.walk(arbre):
        if not isinstance(c, ast.ClassDef):
            continue
        bases = " ".join(ast.unparse(b) for b in c.bases)
        django = "models.Model" in bases
        sqla = bool(_BASES_SQLA.search(bases)) and not django
        if not (django or sqla):
            continue
        m = Modele(c.name, "", fichier=nom, ligne=c.lineno,
                   orm="django" if django else "sqlalchemy")
        for corps in c.body:
            if isinstance(corps, (ast.FunctionDef, ast.AsyncFunctionDef)):
                m.autres.add(corps.name)
                continue
            if isinstance(corps, ast.ClassDef):           # class Meta
                for x in corps.body:
                    if isinstance(x, ast.Assign) and any(
                            getattr(t, "id", "") == "db_table"
                            for t in x.targets) and isinstance(
                                x.value, ast.Constant):
                        m.table = str(x.value.value)
                continue
            cibles, valeur = [], None
            if isinstance(corps, ast.Assign):
                cibles, valeur = [t for t in corps.targets
                                  if isinstance(t, ast.Name)], corps.value
            elif isinstance(corps, ast.AnnAssign) and isinstance(
                    corps.target, ast.Name):
                cibles, valeur = [corps.target], corps.value
                if valeur is None and "Mapped" in ast.unparse(
                        corps.annotation):
                    m.champs.add(corps.target.id)
                    continue
            for t in cibles:
                if t.id == "__tablename__" and isinstance(valeur,
                                                          ast.Constant):
                    m.table = str(valeur.value)
                    continue
                appel = _nom_appel(valeur) if valeur is not None else ""
                if django and appel.endswith("Field") or appel in {
                        "ForeignKey", "OneToOneField"}:
                    if appel in {"ForeignKey", "OneToOneField"}:
                        m.cles_etrangeres[t.id] = f"{t.id}_id"
                        m.champs.add(f"{t.id}_id")
                    if appel == "ManyToManyField":
                        m.autres.add(t.id)
                    else:
                        m.champs.add(t.id)
                elif sqla and appel in _COLONNES_SQLA:
                    premier = valeur.args[0] if valeur.args else None
                    if isinstance(premier, ast.Constant) and isinstance(
                            premier.value, str):
                        m.cles_etrangeres[t.id] = premier.value
                    m.champs.add(t.id)
                else:
                    m.autres.add(t.id)
        if not m.table:
            m.table = (_serpent(c.name) if sqla else c.name.lower())
        out.append(m)
    return out


_ATTRS_STANDARD = {"query", "objects", "metadata", "__table__",
                   "__tablename__", "c", "DoesNotExist",
                   "MultipleObjectsReturned", "_meta", "id", "pk"}
_METHODES_DJANGO = {"filter", "exclude", "get", "create", "get_or_create",
                    "update_or_create", "update", "filter_by"}


def champs_vises_python(nom: str, texte: str, modeles: dict[str, Modele]
                        ) -> list[tuple[int, Modele, str]]:
    try:
        arbre = ast.parse(texte)
    except SyntaxError:
        return []
    out = []
    for n in ast.walk(arbre):
        # Client.ville (filtre SQLAlchemy, attribut de classe)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) \
                and n.value.id in modeles and isinstance(n.ctx, ast.Load):
            m = modeles[n.value.id]
            if n.attr not in _ATTRS_STANDARD and not m.connait(n.attr):
                out.append((n.lineno, m, n.attr))
        # Client.objects.filter(ville=...) / Client.query.filter_by(...)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr in _METHODES_DJANGO:
            chaine = ast.unparse(n.func.value)
            racine = chaine.split(".")[0].split("(")[0]
            cible = racine if racine in modeles else next(
                (c for c in modeles if re.search(rf"\b{c}\b", chaine)), None)
            if cible is None:
                continue
            m = modeles[cible]
            for kw in n.keywords:
                if kw.arg is None or kw.arg == "defaults":
                    continue
                champ = kw.arg.split("__")[0]
                if not m.connait(champ):
                    out.append((n.lineno, m, champ))
    return out


# ----------------------------------------- JavaScript / TypeScript, Prisma
def _accolade(texte: str, i: int) -> int:
    """Index de l'accolade fermante qui repond a celle en i."""
    prof = 0
    for j in range(i, len(texte)):
        if texte[j] in "{[(":
            prof += 1
        elif texte[j] in "}])":
            prof -= 1
            if prof == 0:
                return j
    return len(texte)


def cles_objet(texte: str, i: int) -> list[str]:
    """Les cles de PREMIER niveau de l'objet JS qui s'ouvre en i."""
    fin = _accolade(texte, i)
    corps = texte[i + 1:fin]
    cles, prof, morceau = [], 0, ""
    for ch in corps + ",":
        if ch in "{[(":
            prof += 1
        elif ch in "}])":
            prof -= 1
        if ch == "," and prof == 0:
            m = re.match(r"\s*(?:['\"]?([A-Za-z_$][\w$]*)['\"]?\s*:|"
                         r"([A-Za-z_$][\w$]*)\s*$|\.\.\.)", morceau)
            if m and (m.group(1) or m.group(2)):
                cles.append(m.group(1) or m.group(2))
            morceau = ""
        else:
            morceau += ch
    return cles


def modeles_prisma(nom: str, texte: str) -> list[Modele]:
    out = []
    for m in re.finditer(r"(?m)^model\s+(\w+)\s*\{", texte):
        fin = _accolade(texte, m.end() - 1)
        corps = texte[m.end():fin]
        mo = Modele(m.group(1), m.group(1), fichier=nom,
                    ligne=texte.count("\n", 0, m.start()) + 1, orm="prisma")
        carte = re.search(r'@@map\(\s*"([^"]+)"', corps)
        if carte:
            mo.table = carte.group(1)
        for ligne in corps.splitlines():
            l = re.match(r"\s*(\w+)\s+(\w+)(\[\])?(\?)?(.*)$", ligne)
            if not l or l.group(1).startswith("@"):
                continue
            nom_champ, genre, liste, reste = (l.group(1), l.group(2),
                                              l.group(3), l.group(5))
            if "@relation" in reste or liste or genre[:1].isupper() and \
                    genre not in {"String", "Int", "BigInt", "Float",
                                  "Decimal", "Boolean", "DateTime", "Json",
                                  "Bytes"}:
                mo.autres.add(nom_champ)              # relation
                continue
            colonne = re.search(r'@map\(\s*"([^"]+)"', reste)
            mo.champs.add(nom_champ)
            if colonne:
                mo.cles_etrangeres[nom_champ] = colonne.group(1)
        out.append(mo)
    return out


_SEQ_DEFINE = re.compile(r"""\.define\(\s*['"](\w+)['"]\s*,\s*\{""")
_SEQ_INIT = re.compile(r"""\b(\w+)\.init\(\s*\{""")
_MONGOOSE = re.compile(r"""(?:const|let|var)\s+(\w+)\s*=\s*new\s+(?:mongoose\.)?Schema\(\s*\{""")
_MONGOOSE_MODEL = re.compile(r"""model\(\s*['"](\w+)['"]\s*,\s*(\w+)""")
_TYPEORM = re.compile(r"""@Entity\(\s*(?:['"](\w+)['"])?[^)]*\)\s*(?:export\s+)?class\s+(\w+)""")


def modeles_js(nom: str, texte: str) -> list[Modele]:
    out = []
    for m in _SEQ_DEFINE.finditer(texte):
        i = m.end() - 1
        mo = Modele(m.group(1), m.group(1), set(cles_objet(texte, i)),
                    fichier=nom, ligne=texte.count("\n", 0, m.start()) + 1,
                    orm="sequelize")
        apres = texte[_accolade(texte, i):_accolade(texte, i) + 200]
        t = re.search(r"""tableName\s*:\s*['"](\w+)['"]""", apres)
        mo.table = t.group(1) if t else mo.table
        out.append(mo)
    for m in _SEQ_INIT.finditer(texte):
        i = m.end() - 1
        mo = Modele(m.group(1), m.group(1), set(cles_objet(texte, i)),
                    fichier=nom, ligne=texte.count("\n", 0, m.start()) + 1,
                    orm="sequelize")
        apres = texte[_accolade(texte, i):_accolade(texte, i) + 300]
        t = re.search(r"""tableName\s*:\s*['"](\w+)['"]""", apres)
        mo.table = t.group(1) if t else mo.table
        out.append(mo)
    schemas = {m.group(1): set(cles_objet(texte, m.end() - 1))
               for m in _MONGOOSE.finditer(texte)}
    for m in _MONGOOSE_MODEL.finditer(texte):
        if m.group(2) in schemas:
            out.append(Modele(m.group(1), m.group(1).lower() + "s",
                              schemas[m.group(2)] | {"_id"}, fichier=nom,
                              ligne=texte.count("\n", 0, m.start()) + 1,
                              orm="mongoose"))
    for m in _TYPEORM.finditer(texte):
        i = texte.find("{", m.end())
        corps = texte[i:_accolade(texte, i)]
        champs = set(re.findall(r"@(?:Primary(?:Generated)?Column|Column|"
                                r"CreateDateColumn|UpdateDateColumn)\([^)]*\)"
                                r"\s*(\w+)", corps))
        autres = set(re.findall(r"@(?:ManyToOne|OneToMany|ManyToMany|"
                                r"OneToOne)\([^)]*\)\s*(\w+)", corps))
        out.append(Modele(m.group(2), m.group(1) or _serpent(m.group(2)),
                          champs, autres, fichier=nom,
                          ligne=texte.count("\n", 0, m.start()) + 1,
                          orm="typeorm"))
    return out


_OPS_JS = (r"findMany|findFirst|findUnique|create|createMany|update|"
           r"updateMany|upsert|delete|deleteMany|count|aggregate|findAll|"
           r"findOne|findByPk|destroy|find|findOneAndUpdate|countDocuments|"
           r"updateOne|deleteOne")


def champs_vises_js(nom: str, texte: str, modeles: dict[str, Modele]
                    ) -> list[tuple[int, Modele, str]]:
    out = []
    par_acces = {}
    for m in modeles.values():
        par_acces[m.classe] = m
        if m.orm == "prisma":
            par_acces[m.classe[:1].lower() + m.classe[1:]] = m
    motif = re.compile(rf"\b(?:prisma\.)?(\w+)\.({_OPS_JS})\(\s*\{{")
    for a in motif.finditer(texte):
        m = par_acces.get(a.group(1))
        if m is None:
            continue
        i = a.end() - 1
        ligne = texte.count("\n", 0, a.start()) + 1
        cles = cles_objet(texte, i)
        corps = texte[i:_accolade(texte, i)]
        a_verifier = []
        if m.orm in {"prisma", "sequelize", "typeorm"}:
            for enveloppe in ("where", "data"):
                e = re.search(rf"\b{enveloppe}\s*:\s*\{{", corps)
                if e:
                    a_verifier += cles_objet(corps, e.end() - 1)
            if m.orm == "sequelize" and a.group(2) == "create":
                a_verifier += cles
        else:                                           # mongoose : filtre direct
            a_verifier = [c for c in cles if not c.startswith("$")]
        for c in a_verifier:
            if c in {"AND", "OR", "NOT"} or c.startswith("$"):
                continue
            if not m.connait(c):
                out.append((ligne, m, c))
    return out


# ---------------------------------------------------------------- juger
def modeles_du_projet(racine: Path, vus: list[str]) -> list[Modele]:
    out = []
    for f in vus:
        ext = Path(f).suffix.lower()
        try:
            texte = (Path(racine) / f).read_text(encoding="utf-8",
                                                 errors="replace")
        except OSError:
            continue
        if ext == ".py":
            out += modeles_python(f, texte)
        elif ext == ".prisma":
            out += modeles_prisma(f, texte)
        elif ext in {".js", ".mjs", ".ts"}:
            out += modeles_js(f, texte)
    from . import juges_orm_langages
    return out + juges_orm_langages.modeles(racine, vus)


def tables_orm(racine: Path, vus: list[str]) -> dict[str, set[str]]:
    """Les tables que les modeles DECLARENT (colonnes reelles). Un modele
    incomplet marque sa table d'un « * » : toutes ses colonnes ne sont pas
    connues, les requetes sur elle ne sont pas jugees colonne par colonne."""
    t: dict[str, set[str]] = {}
    for m in modeles_du_projet(racine, vus):
        if m.orm == "mongoose":
            continue
        colonnes = {m.cles_etrangeres.get(c, c) for c in m.champs} | {"id"}
        if not m.complet:
            colonnes.add("*")
        t.setdefault(m.table.lower(), set()).update(x.lower()
                                                   for x in colonnes)
    return t


def juger(racine: Path, vus: list[str], schema: dict[str, set[str]] | None
          = None) -> list[Defaut]:
    from . import juges_orm_langages
    racine = Path(racine)
    modeles = modeles_du_projet(racine, vus)
    if not modeles:
        return []
    d = []
    if schema:
        for m in modeles:
            if m.orm in {"mongoose", "django"}:
                continue        # Mongo sans schema SQL ; Django : ses migrations
            t = m.table.lower()
            if t not in schema:
                d.append(Defaut(m.fichier, m.ligne, "orm-table-absente", B,
                                f"le modele {m.classe} ({m.orm}) vise la table "
                                f"« {t} », absente du schema (tables : "
                                f"{', '.join(sorted(schema))})", NORME))
                continue
            for c in sorted(m.champs):
                col = m.cles_etrangeres.get(c, c).lower()
                if col not in schema[t]:
                    d.append(Defaut(m.fichier, m.ligne, "orm-colonne-absente",
                                    B, f"le modele {m.classe} declare la "
                                    f"colonne « {col} », absente de la table "
                                    f"« {t} » (colonnes : "
                                    f"{', '.join(sorted(schema[t]))})",
                                    NORME))
    par_classe = {m.classe: m for m in modeles}
    for f in vus:
        ext = Path(f).suffix.lower()
        try:
            texte = (racine / f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if ext == ".py":
            vises = champs_vises_python(f, texte, par_classe)
        elif ext in {".js", ".mjs", ".ts"}:
            vises = champs_vises_js(f, texte, par_classe)
        elif ext in juges_orm_langages.EXTENSIONS:
            vises = juges_orm_langages.champs_vises(f, texte, par_classe)
            if ext == ".php":
                d += _php(f, texte, par_classe, schema)
        else:
            continue
        for ligne, m, champ in vises:
            d.append(Defaut(f, ligne, "orm-champ-inconnu", B,
                            f"{m.classe} n'a pas de champ « {champ} » "
                            f"(champs : {', '.join(sorted(m.champs))})",
                            NORME))
    return d


def _php(f: str, texte: str, par_classe: dict[str, Modele],
         schema: dict[str, set[str]] | None) -> list[Defaut]:
    """Eloquent : cle hors $fillable (perdue en silence) ; colonne d'une
    requete absente du schema SQL."""
    from . import juges_orm_langages as jl
    texte = jl.sans_commentaires(texte, docblocks=True)
    d = [Defaut(f, ligne, "orm-champ-inconnu", B,
                f"{m.classe}::create : « {c} » n'est pas dans $fillable "
                f"({', '.join(m.remplissables)}) — Laravel l'ignore en "
                f"silence, la valeur n'est jamais enregistree", NORME)
         for ligne, m, c in jl.hors_fillable_php(f, texte, par_classe)]
    for ligne, m, c in jl.colonnes_visees_php(f, texte, par_classe):
        cols = (schema or {}).get(m.table.lower())
        if cols and "*" not in cols and c.lower() not in cols:
            d.append(Defaut(f, ligne, "orm-champ-inconnu", B,
                            f"{m.classe} : la requete vise la colonne "
                            f"« {c} », absente de la table « {m.table} » "
                            f"(colonnes : {', '.join(sorted(cols))})", NORME))
    return d


def limites() -> list[str]:
    return ["ORM Java/C#/Go/PHP : conventions de nommage par defaut de "
            "Spring Boot, EF Core, GORM, Laravel et Symfony ; une strategie "
            "de nommage personnalisee n'est pas lue",
            "requetes GORM (chaines SQL) et JPQL (@Query) non jugees ; "
            "Eloquent : colonnes des requetes jugees contre le schema SQL "
            "seulement"]
