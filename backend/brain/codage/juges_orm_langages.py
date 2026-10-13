"""Les modeles ORM de Java, C#, Go et PHP (point 5, 13/10/2026).

Meme contrat que juges_orm (qui les appelle) : une classe = une table, ses
champs = des colonnes ; trois ecarts se voient par lecture, sans modele.

  Java  Hibernate / JPA (@Entity, @Table, @Column, @JoinColumn) ; requetes
        DERIVEES de Spring Data (findByVilleAndNom : chaque propriete doit
        exister — Spring refuse de demarrer sinon).
  C#    Entity Framework Core (DbSet<T> du DbContext, [Table], [Column],
        [NotMapped], ToTable) ; LINQ sur un DbSet (db.Clients.Where(c =>
        c.Vile == ...) : c'est le compilateur qui le dirait, mais MAEL ne
        compile pas toujours).
  Go    GORM (gorm.Model, gorm:"column:x", TableName()).
  PHP   Eloquent ($table, $fillable ; Client::create([...]) avec une cle
        hors $fillable : Laravel l'ignore EN SILENCE, la donnee est perdue ;
        Client::where('col') contre le schema SQL) et Doctrine (#[ORM\\...]).

Les conventions de nommage par defaut sont celles des cadres les plus
employes : Spring Boot (snake_case), EF Core (nom du DbSet / de la
propriete ; snake_case si UseSnakeCaseNamingConvention), GORM (snake_case
au pluriel), Laravel (snake_case au pluriel), Symfony (snake_case).

Un modele dont on ne voit pas tout (parent hors du projet, type incorpore
inconnu, Eloquent sans liste de colonnes) est INCOMPLET : on ne dit jamais
« champ inconnu » sur lui — un faux defaut coute plus cher qu'un silence.
"""
from __future__ import annotations

import re
from pathlib import Path

from .juges_orm import Modele, _accolade


def serpent(nom: str) -> str:
    """CamelCase -> snake_case, sigles compris (UserID -> user_id,
    HTTPServer -> http_server), comme Spring, GORM et Laravel."""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", nom)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.lower()


def pluriel(mot: str) -> str:
    """Le pluriel anglais regulier (GORM, Laravel)."""
    if re.search(r"[^aeiou]y$", mot):
        return mot[:-1] + "ies"
    if re.search(r"(s|x|z|ch|sh)$", mot):
        return mot + "es"
    return mot + "s"


def _ligne(texte: str, i: int) -> int:
    return texte.count("\n", 0, i) + 1


def sans_commentaires(texte: str, docblocks: bool = False) -> str:
    """Les commentaires // et /* */ remplaces par des blancs (les lignes
    restent a leur place). Un commentaire « a base class for objects »
    etait lu comme la classe « for » (Spring PetClinic, 13/10/2026).
    `docblocks` : garder les /** */ (annotations Doctrine)."""
    out, i, n = [], 0, len(texte)
    while i < n:
        c = texte[i]
        if c in "\"'`":                          # chaine : recopiee telle quelle
            j = i + 1
            while j < n and texte[j] != c:
                j += 2 if texte[j] == "\\" and c != "`" else 1
            out.append(texte[i:j + 1])
            i = j + 1
        elif texte.startswith("//", i):
            j = texte.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif texte.startswith("/*", i) and not (
                docblocks and texte.startswith("/**", i)):
            j = texte.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", texte[i:j]))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _instructions(corps: str) -> list[tuple[int, str]]:
    """Les instructions de PREMIER niveau d'un corps de classe (terminees
    par « ; ») : les champs. Les blocs (methodes) sont sautes."""
    out, prof, debut = [], 0, 0
    for i, ch in enumerate(corps):
        if ch in "{([":
            prof += 1
        elif ch in "})]":
            prof -= 1
            if prof == 0 and ch == "}":
                debut = i + 1                  # fin d'une methode
        elif ch == ";" and prof == 0:
            out.append((debut, corps[debut:i]))
            debut = i + 1
    return out


_ANNOT_JAVA = re.compile(r"@([\w.]+)(\((?:[^()]|\([^()]*\))*\))?")


def _nom_arg(args: str | None, cle: str = "name") -> str:
    if not args:
        return ""
    m = re.search(rf"\b{cle}\s*=\s*\"([^\"]+)\"", args)
    if m:
        return m.group(1)
    m = re.match(r"\(\s*\"([^\"]+)\"\s*\)", args)      # @Table("x")
    return m.group(1) if m and cle in {"name", "value"} else ""


# --------------------------------------------------------------- Java
_CLASSE_JAVA = re.compile(r"\bclass\s+(\w+)(?:\s*<[^>]*>)?"
                          r"(?:\s+extends\s+([\w.]+))?[^{;]*\{")
_RELATIONS_JAVA = {"OneToMany", "ManyToMany", "OneToOne", "ManyToOne",
                   "ElementCollection", "Embedded", "EmbeddedId"}


def _champs_java(corps: str) -> tuple[set, set, dict]:
    champs, autres, colonnes = set(), set(), {}
    for _, inst in _instructions(corps):
        annots = {a.group(1).split(".")[-1]: a.group(2)
                  for a in _ANNOT_JAVA.finditer(inst)}
        nu = _ANNOT_JAVA.sub(" ", inst).split("=", 1)[0].strip()
        mots = re.findall(r"[\w<>\[\],.?]+", nu)
        if len(mots) < 2 or "(" in nu or "Transient" in annots or \
                {"static", "transient"} & set(mots):
            continue
        nom = mots[-1]
        if not re.fullmatch(r"[A-Za-z_]\w*", nom):
            continue
        rel = _RELATIONS_JAVA & set(annots)
        if rel:
            jointure = _nom_arg(annots.get("JoinColumn"))
            porte = rel & {"ManyToOne", "OneToOne"} and "mappedBy" not in (
                annots.get("OneToOne") or "")
            if porte:
                champs.add(nom)
                colonnes[nom] = jointure or serpent(nom) + "_id"
            else:
                autres.add(nom)
            continue
        champs.add(nom)
        colonnes[nom] = _nom_arg(annots.get("Column")) or serpent(nom)
    return champs, autres, colonnes


def modeles_java(nom: str, texte: str,
                 parents: dict[str, tuple] | None = None) -> list[Modele]:
    out = []
    for m in _CLASSE_JAVA.finditer(texte):
        avant = texte[:m.start()]
        coupe = max(avant.rfind(";"), avant.rfind("}"))
        entete = avant[coupe + 1:]
        annots = {a.group(1).split(".")[-1]: a.group(2)
                  for a in _ANNOT_JAVA.finditer(entete)}
        if "Entity" not in annots:
            continue
        i = m.end() - 1
        champs, autres, colonnes = _champs_java(texte[i + 1:_accolade(
            texte, i)])
        classe, parent = m.group(1), m.group(2)
        table = (_nom_arg(annots.get("Table")) or _nom_arg(annots["Entity"])
                 or serpent(classe))
        mo = Modele(classe, table, champs, autres, fichier=nom,
                    ligne=_ligne(texte, m.start()), orm="jpa",
                    cles_etrangeres=colonnes)
        vus = {classe}
        while parent:                       # la chaine des @MappedSuperclass
            parent = parent.split(".")[-1]
            p = (parents or {}).get(parent)
            if p is None or parent in vus:
                mo.complet = False
                break
            vus.add(parent)
            mo.champs |= p[0]
            mo.autres |= p[1]
            mo.cles_etrangeres.update(p[2])
            parent = p[3]
        out.append(mo)
    return out


def parents_java(texte: str) -> dict[str, tuple]:
    """Les @MappedSuperclass : leurs champs passent aux entites filles.
    Rend nom -> (champs, autres, colonnes, parent)."""
    out = {}
    for m in _CLASSE_JAVA.finditer(texte):
        avant = texte[:m.start()]
        entete = avant[max(avant.rfind(";"), avant.rfind("}")) + 1:]
        if re.search(r"@(?:[\w.]+\.)?MappedSuperclass\b", entete):
            i = m.end() - 1
            out[m.group(1)] = (*_champs_java(texte[i + 1:_accolade(texte, i)]),
                               m.group(2))
    return out


_DEPOT_JAVA = re.compile(r"\binterface\s+\w+\s+extends\s+(?:[\w.]*\.)?"
                         r"(?:Jpa|Crud|PagingAndSorting|ListCrud|"
                         r"ListPagingAndSorting|Reactive\w*)?Repository\s*<"
                         r"\s*(\w+)\s*,[^>]*>[^{]*\{")
_METHODE_DERIVEE = re.compile(
    r"\b(?:find|read|get|query|search|stream|count|exists|delete|remove)"
    r"(?:First|Top|Distinct|All|\d)*\w*?By([A-Z]\w*)\s*\(")
_OPERATEURS = sorted("""IsNotNull NotNull IsNull Null IsNotIn NotIn IsIn In
IsBetween Between IsLessThanEqual LessThanEqual IsLessThan LessThan
IsGreaterThanEqual GreaterThanEqual IsGreaterThan GreaterThan IsAfter After
IsBefore Before IsNotLike NotLike IsLike Like IsStartingWith StartingWith
StartsWith IsEndingWith EndingWith EndsWith IsNotContaining NotContaining
IsContaining Containing Contains IsNot Not IsTrue True IsFalse False
IsNotEmpty NotEmpty IsEmpty Empty Exists IsNear Near IsWithin Within
MatchesRegex Matches Regex Equals Is""".split(), key=len, reverse=True)


def _propriete(partie: str, m: Modele) -> str | None:
    """Rend la propriete INCONNUE, ou None si elle existe."""
    partie = re.sub(r"(?:AllIgnoreCase|IgnoreCase|IgnoringCase)$", "", partie)

    def connue(p: str) -> bool:
        if not p:
            return True
        nom = p if p[:2].isupper() else p[:1].lower() + p[1:]
        if m.connait(nom):
            return True
        # chemin imbrique : ClientVille -> client.ville, ou Client_Ville
        tete = p.split("_", 1)[0]
        for k in range(1, len(tete)):
            if tete[k].isupper():
                t = tete[:k]
                if m.connait(t[:1].lower() + t[1:]):
                    return True
        return "_" in p and m.connait(tete[:1].lower() + tete[1:])
    if connue(partie):
        return None
    for op in _OPERATEURS:
        if partie.endswith(op) and connue(partie[:-len(op)]):
            return None
    p = partie
    for op in _OPERATEURS:
        if p.endswith(op) and len(p) > len(op):
            p = p[:-len(op)]
            break
    return p[:1].lower() + p[1:]


def champs_vises_java(nom: str, texte: str, modeles: dict[str, Modele]
                      ) -> list[tuple[int, Modele, str]]:
    out = []
    for d in _DEPOT_JAVA.finditer(texte):
        m = modeles.get(d.group(1))
        if m is None or not m.complet:
            continue
        i = d.end() - 1
        corps = texte[i:_accolade(texte, i)]
        for meth in _METHODE_DERIVEE.finditer(corps):
            if "@Query" in corps[max(0, meth.start() - 400):meth.start()
                                 ].rsplit(";", 1)[-1]:
                continue                       # requete ecrite : pas derivee
            criteres = meth.group(1).split("OrderBy", 1)[0]
            for partie in re.split(r"(?<=[a-z0-9])(?:And|Or)(?=[A-Z])",
                                   criteres):
                inconnue = _propriete(partie, m)
                if inconnue:
                    out.append((_ligne(texte, i + meth.start()), m,
                                inconnue))
    return out


# ----------------------------------------------------------------- C#
_CLASSE_CS = re.compile(r"\bclass\s+(\w+)(?:\s*<[^>]*>)?(?:\s*:\s*([^{]+))?"
                        r"\s*\{")
_PROPRIETE_CS = re.compile(
    r"((?:\[[^\]]*\]\s*)*)public\s+(?:virtual\s+|required\s+|override\s+|"
    r"new\s+)*([\w.<>\[\],?\s]+?)\s+(\w+)\s*\{\s*(?:get|init)")
_SIMPLES_CS = {"int", "long", "short", "byte", "sbyte", "bool", "string",
               "decimal", "double", "float", "char", "uint", "ulong",
               "ushort", "object", "Guid", "DateTime", "DateTimeOffset",
               "DateOnly", "TimeOnly", "TimeSpan", "byte[]", "Int32",
               "Int64", "String", "Boolean", "Decimal"}
_COLLECTIONS = re.compile(r"^(?:I?Collection|I?List|IEnumerable|HashSet|"
                          r"ISet|IReadOnlyCollection|IReadOnlyList)<")


def modeles_cs(fichiers: dict[str, str]) -> list[Modele]:
    """EF Core : les entites sont les T des DbSet<T> du projet."""
    tout = "\n".join(fichiers.values())
    tables = {}                                    # entite -> nom du DbSet
    for d in re.finditer(r"\bDbSet<\s*(\w+)\s*>\s+(\w+)", tout):
        tables.setdefault(d.group(1), d.group(2))
    if not tables:
        return []
    to_table = dict(re.findall(r"Entity<\s*(\w+)\s*>\(\)\s*\.\s*ToTable\("
                               r"\s*\"(\w+)\"", tout))
    # IEntityTypeConfiguration<X> : builder.ToTable("x") (eShopOnWeb)
    for f, t in fichiers.items():
        for c in re.finditer(r"IEntityTypeConfiguration<\s*(\w+)\s*>[^{]*\{",
                             t):
            i = c.end() - 1
            nom_t = re.search(r"\.ToTable\(\s*\"(\w+)\"",
                              t[i:_accolade(t, i)])
            if nom_t:
                to_table.setdefault(c.group(1), nom_t.group(1))
    snake = "UseSnakeCaseNamingConvention" in tout
    enums = set(re.findall(r"\benum\s+(\w+)", tout))
    classes = {}                                   # nom -> (fichier, m, texte)
    for f, t in fichiers.items():
        for m in _CLASSE_CS.finditer(t):
            classes.setdefault(m.group(1), (f, m, t))

    def proprietes(nom: str, vus: set) -> tuple[set, set, dict, bool]:
        f, m, t = classes[nom]
        i = m.end() - 1
        corps = t[i:_accolade(t, i)]
        champs, autres, colonnes, complet = set(), set(), {}, True
        for p in _PROPRIETE_CS.finditer(corps):
            attrs, genre, nomp = p.group(1), p.group(2).strip(), p.group(3)
            if "NotMapped" in attrs:
                continue
            base = genre.rstrip("?")
            if _COLLECTIONS.match(base) or (base in classes and base not in
                                            enums and base not in _SIMPLES_CS):
                autres.add(nomp)                   # navigation
                continue
            if base not in _SIMPLES_CS and base not in enums and \
                    "." not in base:
                autres.add(nomp)                   # type possede inconnu
                complet = False
                continue
            col = re.search(r"Column\(\s*\"(\w+)\"", attrs)
            champs.add(nomp)
            colonnes[nomp] = col.group(1) if col else (
                serpent(nomp) if snake else nomp)
        for parent in (m.group(2) or "").split(","):
            parent = parent.strip().split("<")[0]
            if not parent or re.fullmatch(r"I[A-Z]\w*", parent):
                continue                           # une interface
            if parent in classes and parent not in vus:
                c2, a2, k2, ok2 = proprietes(parent, vus | {parent})
                champs |= c2
                autres |= a2
                colonnes.update(k2)
                complet = complet and ok2
            else:
                complet = False
        return champs, autres, colonnes, complet

    out = []
    for entite, dbset in tables.items():
        if entite not in classes:
            continue
        f, m, t = classes[entite]
        champs, autres, colonnes, complet = proprietes(entite, {entite})
        avant = t[:m.start()]
        attr = re.search(r"\[Table\(\s*\"(\w+)\"[^\]]*\]\s*(?:public\s+|"
                         r"internal\s+|sealed\s+|partial\s+)*$", avant)
        table = (to_table.get(entite) or (attr.group(1) if attr else "")
                 or (serpent(dbset) if snake else dbset))
        mo = Modele(entite, table, champs, autres, fichier=f,
                    ligne=_ligne(t, m.start()), orm="efcore",
                    cles_etrangeres=colonnes)
        mo.complet = complet
        mo.acces = dbset
        out.append(mo)
    return out


_LINQ = re.compile(r"\.(\w+)\s*\.\s*(?:Where|First|FirstOrDefault|Single|"
                   r"SingleOrDefault|Any|All|Count|LongCount|OrderBy|"
                   r"OrderByDescending|Sum|Max|Min|Average|"
                   r"(?:First|FirstOrDefault|Single|SingleOrDefault|Any|All|"
                   r"Count|Sum|Max|Min|Average)Async)\(\s*(\w+)\s*=>")


def champs_vises_cs(nom: str, texte: str, modeles: dict[str, Modele]
                    ) -> list[tuple[int, Modele, str]]:
    par_acces = {getattr(m, "acces", ""): m for m in modeles.values()
                 if m.orm == "efcore"}
    out = []
    for q in _LINQ.finditer(texte):
        m = par_acces.get(q.group(1))
        if m is None or not m.complet:
            continue
        ouverture = texte.rfind("(", q.start(), q.end())
        corps = texte[q.end():_accolade(texte, ouverture)]
        for c in re.finditer(rf"\b{re.escape(q.group(2))}\.(\w+)", corps):
            if not m.connait(c.group(1)):
                out.append((_ligne(texte, q.start()), m, c.group(1)))
    return out


# ----------------------------------------------------------------- Go
_STRUCT_GO = re.compile(r"\btype\s+(\w+)\s+struct\s*\{")
_SIMPLES_GO = {"string", "bool", "int", "int8", "int16", "int32", "int64",
               "uint", "uint8", "uint16", "uint32", "uint64", "float32",
               "float64", "byte", "rune", "[]byte"}
_MODELE_GORM = {"id": "ID", "created_at": "CreatedAt",
                "updated_at": "UpdatedAt", "deleted_at": "DeletedAt"}


def modeles_go(fichiers: dict[str, str]) -> list[Modele]:
    tout = "\n".join(fichiers.values())
    if "gorm" not in tout:
        return []
    alias = set(re.findall(r"\btype\s+(\w+)\s+(?:string|bool|u?int\d*|"
                           r"float\d+|\[\]byte)\b", tout))
    structs = {}
    for f, t in fichiers.items():
        for m in _STRUCT_GO.finditer(t):
            i = m.end() - 1
            structs[m.group(1)] = (f, m, t[i + 1:_accolade(t, i)], t)
    migres = set(re.findall(r"AutoMigrate\(([^)]*)\)", tout))
    migres = set(re.findall(r"&(\w+)\{", " ".join(migres)))
    noms_table = dict(re.findall(
        r"func\s*\(\s*(?:\w+\s+)?\*?(\w+)\s*\)\s*TableName\(\)\s*string\s*"
        r"\{\s*return\s+\"(\w+)\"", tout))
    retenus = {n for n, (_, _, corps, _) in structs.items()
               if "gorm.Model" in corps or 'gorm:"' in corps or n in migres
               or n in noms_table}
    for _ in range(3):              # les structs liees a un modele en sont
        for n in list(retenus):
            for genre in re.findall(r"(?m)^\s*[A-Z]\w*\s+(?:\[\])?\*?(\w+)",
                                    structs[n][2]):
                if genre in structs and genre not in alias:
                    retenus.add(genre)
    out = []
    for nom, (f, m, corps, t) in structs.items():
        if nom not in retenus:
            continue
        champs, autres, colonnes, complet = set(), set(), {}, True
        for ligne in corps.splitlines():
            ligne = ligne.split("//", 1)[0].strip()
            if not ligne:
                continue
            etiquette = re.search(r'gorm:"([^"]*)"', ligne)
            etiquette = etiquette.group(1) if etiquette else ""
            ligne_nue = re.sub(r"`[^`]*`", "", ligne).strip()
            mots = ligne_nue.split()
            if len(mots) == 1:                      # type incorpore
                if mots[0] == "gorm.Model":
                    for col, champ in _MODELE_GORM.items():
                        champs.add(champ)
                        colonnes[champ] = col
                elif "embedded" not in etiquette:
                    complet = False
                continue
            champ, genre = mots[0], mots[1]
            if not champ[:1].isupper() or re.match(r"-(?:;|:all|$)",
                                                   etiquette):
                continue
            base = genre.lstrip("*")
            if base.startswith("[]") and base != "[]byte" or \
                    base in structs and base not in alias:
                autres.add(champ)                   # relation
                continue
            if base not in _SIMPLES_GO and base not in alias and \
                    "." not in base:
                autres.add(champ)
                complet = False
                continue
            col = re.search(r"(?:^|;)column:(\w+)", etiquette)
            champs.add(champ)
            colonnes[champ] = col.group(1) if col else serpent(champ)
        mo = Modele(nom, noms_table.get(nom) or pluriel(serpent(nom)), champs,
                    autres, fichier=f, ligne=_ligne(t, m.start()), orm="gorm",
                    cles_etrangeres=colonnes)
        mo.complet = complet
        out.append(mo)
    return out


# ---------------------------------------------------------------- PHP
_CLASSE_PHP = re.compile(r"\bclass\s+(\w+)(?:\s+extends\s+([\w\\]+))?"
                         r"[^{]*\{")
_RELATIONS_PHP = r"(?:hasMany|hasOne|belongsTo|belongsToMany|morph\w+|" \
                 r"hasManyThrough|hasOneThrough)"


def _liste_php(corps: str, propriete: str) -> list[str] | None:
    m = re.search(rf"\${propriete}\s*=\s*(?:\[|array\()", corps)
    if not m:
        return None
    fin = _accolade(corps, m.end() - 1)
    return re.findall(r"""['"](\w+)['"]""", corps[m.end():fin])


def modeles_php(nom: str, texte: str) -> list[Modele]:
    out = []
    for m in _CLASSE_PHP.finditer(texte):
        i = m.end() - 1
        corps = texte[i:_accolade(texte, i)]
        avant = texte[:m.start()]
        entete = avant[max(avant.rfind(";"), avant.rfind("}")) + 1:]
        classe, parent = m.group(1), (m.group(2) or "").split("\\")[-1]
        if "ORM\\Entity" in entete:                 # Doctrine
            out.append(_doctrine(nom, texte, m, entete, corps))
            continue
        if parent not in {"Model", "Authenticatable", "Pivot"}:
            continue
        t = re.search(r"""\$table\s*=\s*['"](\w+)['"]""", corps)
        remplissables = _liste_php(corps, "fillable")
        mo = Modele(classe, t.group(1) if t else pluriel(serpent(classe)),
                    set(remplissables or []), fichier=nom,
                    ligne=_ligne(texte, m.start()), orm="eloquent")
        mo.autres = set(re.findall(rf"function\s+(\w+)\s*\([^)]*\)\s*"
                                   rf"(?::\s*[\w\\]+\s*)?\{{\s*return\s+"
                                   rf"\$this->{_RELATIONS_PHP}\(", corps))
        mo.complet = False          # Eloquent ne liste pas toutes ses colonnes
        mo.remplissables = remplissables
        mo.gardes = _liste_php(corps, "guarded")
        out.append(mo)
    return out


def _arg_php(args: str, cle: str) -> str:
    m = re.search(rf"\b{cle}\s*[:=]\s*['\"](\w+)['\"]", args or "")
    return m.group(1) if m else ""


def _doctrine(nom, texte, m, entete, corps) -> Modele:
    classe = m.group(1)
    t = re.search(r"ORM\\Table\(([^)]*)\)", entete)
    mo = Modele(classe, _arg_php(t.group(1), "name") if t else "",
                fichier=nom, ligne=_ligne(texte, m.start()), orm="doctrine")
    mo.table = mo.table or serpent(classe)
    morceaux = re.split(r"(?=(?:private|protected|public)\s+(?:readonly\s+)?"
                        r"(?:\??[\w\\]+\s+)?\$\w+)", corps)
    annots = ""
    for k, morceau in enumerate(morceaux):
        p = re.match(r"(?:private|protected|public)\s+(?:readonly\s+)?"
                     r"(?:\??[\w\\]+\s+)?\$(\w+)", morceau)
        if p and k:
            prop = p.group(1)
            col = re.search(r"ORM\\Column(\([^)]*\))?", annots)
            rel = re.search(r"ORM\\(ManyToOne|OneToOne|OneToMany|ManyToMany)"
                            r"(\([^)]*\))?", annots)
            if rel:
                if rel.group(1) in {"ManyToOne", "OneToOne"} and \
                        "mappedBy" not in (rel.group(2) or ""):
                    j = re.search(r"ORM\\JoinColumn(\([^)]*\))?", annots)
                    mo.champs.add(prop)
                    mo.cles_etrangeres[prop] = (_arg_php(j.group(1) if j else
                                                         "", "name")
                                                or serpent(prop) + "_id")
                else:
                    mo.autres.add(prop)
            elif col or re.search(r"ORM\\Id\b", annots):
                mo.champs.add(prop)
                mo.cles_etrangeres[prop] = (_arg_php(col.group(1) if col
                                                     and col.group(1) else "",
                                                     "name") or serpent(prop))
        # les annotations du membre SUIVANT sont a la fin de ce morceau
        fin = re.search(r"[;{}]\s*((?:#\[[^\]]*\]\s*|/\*\*(?:.|\n)*?\*/\s*)*)$",
                        morceau)
        annots = fin.group(1) if fin else morceau
    return mo


_ELOQUENT_COL = re.compile(
    r"\b(\w+)::(?:where|orWhere|whereIn|whereNotIn|whereNull|whereNotNull|"
    r"whereBetween|firstWhere|orderBy|orderByDesc|pluck|latest|oldest)"
    r"\(\s*['\"](\w+)['\"]")
_ELOQUENT_CREATE = re.compile(r"\b(\w+)::(?:create|firstOrCreate|"
                              r"updateOrCreate|make|forceCreate)\(\s*\[")


def colonnes_visees_php(nom: str, texte: str, modeles: dict[str, Modele]
                        ) -> list[tuple[int, Modele, str]]:
    """Client::where('col') : a juger contre le schema SQL (Eloquent ne
    declare pas ses colonnes)."""
    out = []
    for q in _ELOQUENT_COL.finditer(texte):
        m = modeles.get(q.group(1))
        if m is not None and m.orm == "eloquent":
            out.append((_ligne(texte, q.start()), m, q.group(2)))
    return out


def hors_fillable_php(nom: str, texte: str, modeles: dict[str, Modele]
                      ) -> list[tuple[int, Modele, str]]:
    """Client::create(['cle' => ...]) avec une cle hors de $fillable :
    Laravel l'ignore en silence (sans $guarded = [])."""
    out = []
    for q in _ELOQUENT_CREATE.finditer(texte):
        m = modeles.get(q.group(1))
        if m is None or m.orm != "eloquent" or not m.remplissables \
                or m.gardes is not None or "forceCreate" in q.group(0):
            continue
        i = q.end() - 1
        corps = texte[i:_accolade(texte, i)]
        # cles de premier niveau seulement (create([...], [...]) : 1er tableau)
        for c in _cles_php(corps):
            if c not in m.remplissables:
                out.append((_ligne(texte, q.start()), m, c))
    return out


def _cles_php(tableau: str) -> list[str]:
    """Les cles de PREMIER niveau d'un tableau PHP ['a' => 1, ...]."""
    cles, prof, morceau = [], 0, ""
    for ch in tableau[1:] + ",":
        if ch in "[(":
            prof += 1
        elif ch in "])":
            prof -= 1
        if ch == "," and prof == 0:
            m = re.match(r"""\s*['"](\w+)['"]\s*=>""", morceau)
            if m:
                cles.append(m.group(1))
            morceau = ""
        else:
            morceau += ch
    return cles


# -------------------------------------------------------------- entree
EXTENSIONS = {".java", ".cs", ".go", ".php"}


def modeles(racine: Path, vus: list[str]) -> list[Modele]:
    textes = {}
    for f in vus:
        if Path(f).suffix.lower() in EXTENSIONS:
            try:
                textes[f] = sans_commentaires(
                    (Path(racine) / f).read_text(encoding="utf-8",
                                                 errors="replace"),
                    docblocks=f.lower().endswith(".php"))
            except OSError:
                pass
    out = []
    java = {f: t for f, t in textes.items() if f.lower().endswith(".java")}
    parents = {}
    for t in java.values():
        parents.update(parents_java(t))
    for f, t in java.items():
        out += modeles_java(f, t, parents)
    out += modeles_cs({f: t for f, t in textes.items()
                       if f.lower().endswith(".cs")})
    out += modeles_go({f: t for f, t in textes.items()
                       if f.lower().endswith(".go")})
    for f, t in textes.items():
        if f.lower().endswith(".php"):
            out += modeles_php(f, t)
    return out


def champs_vises(nom: str, texte: str, modeles_: dict[str, Modele]
                 ) -> list[tuple[int, Modele, str]]:
    ext = Path(nom).suffix.lower()
    if ext == ".java":
        return champs_vises_java(nom, sans_commentaires(texte), modeles_)
    if ext == ".cs":
        return champs_vises_cs(nom, sans_commentaires(texte), modeles_)
    return []
