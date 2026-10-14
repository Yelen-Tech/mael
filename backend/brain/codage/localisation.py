"""La LOCALISATION : d'un ticket aux fichiers et fonctions a lire.

Point 4 (reprise d'un depot existant), 12/10/2026. Sur un depot de milliers
de fichiers, le modele ne peut pas tout lire : il faut lui montrer LES BONS
endroits. Cette etape se fait sans modele (deterministe, mesurable sur
SWE-bench : on connait le fichier corrige de chaque ticket).

Les indices d'un ticket, du plus sur au plus vague :
  1. TRACE D'ERREUR : « File ".../sympy/geometry/point.py", line 153 » —
     le fichier ET la ligne ; le cadre le plus profond (la ou l'erreur est
     levee) compte le plus ;
  2. CHEMIN cite : « requests/models.py », ou seulement « models.py » ;
  3. IMPORT dans un exemple : « from astropy.modeling.separable import ... »
     designe astropy/modeling/separable.py ;
  4. MESSAGE d'erreur cite, retrouve TEL QUEL dans le code (la ou il est
     leve) ;
  5. IDENTIFIANTS (`separability_matrix`, Point2D, version_info) : le
     fichier qui les DEFINIT, puis ceux qui les emploient ;
  6. MOTS du texte, en dernier (BM25), pour departager.
Chaque fichier propose dit POURQUOI (les raisons sont gardees) : le modele
et le developpeur voient d'ou vient le choix.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .depot import Index

# Poids des indices (calibres sur SWE-bench Lite, voir banc_depot.py)
P_TRACE, P_TRACE_PROFOND = 6.0, 4.0
P_CHEMIN, P_NOM_FICHIER = 8.0, 3.0
P_IMPORT = 6.0
P_MESSAGE = 6.0
P_DEFINIT, P_EMPLOIE = 4.0, 1.0
P_MOT = 0.6
# Un correctif va dans le code, rarement dans un test ou la documentation.
FACTEUR = {"test": 0.3, "texte": 0.3, "config": 0.4, "tiers": 0.1}
# Code d'AUTRUI range dans le depot (jquery de sphinx, traductions) : on ne
# le corrige jamais dans un ticket (13/10/2026, sphinx-8273).
_TIERS = re.compile(r"(^|/)(static|vendor|vendored|_vendor|third_party|"
                    r"node_modules|locale|dist)/|\.min\.[cm]?js$|"
                    r"(^|/)jquery[\w.-]*\.js$")
# Leviers du 13/10 (reglage seulement) : deux mots colles = nom de fichier
P_COLLE = 3.0
P_NORMAL = True

_COMMUNS = set("""self cls none true false print return import from class def
lambda assert raise yield async await with pass else elif while break
continue global try except finally str int float bool list dict set tuple len
range type object super isinstance open args kwargs main init test tests
error value result data name file path the and for not this that true false
array index key keys items values get put post new null undefined var let
const function console log string number this foo bar baz""".split())
_VIDES = set("""the and for not this that with have has was were are been
from into when what which while will would should could there their then than
also just like only some such does doesn here more most other same very about
after before because between both each even every however instead itself
using used use make made need needs want wants seems seem way get gets got
expected actual following example issue problem bug code version case cases
work works working return returns returned call calls called output input
les des une pour dans avec sans sur par que qui est sont pas plus mais ou
donc car""".split())
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


@dataclass
class Indices:
    trace: list[tuple[str, int, str]] = field(default_factory=list)  # chemin, ligne, fonction
    chemins: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)                 # a.b.c
    messages: list[str] = field(default_factory=list)
    identifiants: list[str] = field(default_factory=list)
    mots: list[str] = field(default_factory=list)
    noms_possibles: set[str] = field(default_factory=set)   # noms de fichier
    noms_colles: set[str] = field(default_factory=set)      # « man page »
    # cadres de trace repetes (chemin, ligne) -> fois : la BOUCLE d'une
    # RecursionError (agent_depot.trace_de les marque « (xN) »)
    repetes: dict[tuple[str, int], int] = field(default_factory=dict)
    recursion: bool = False


@dataclass
class SymboleVise:
    nom: str
    debut: int
    fin: int
    score: float


@dataclass
class Lieu:
    fichier: str
    score: float
    raisons: list[str] = field(default_factory=list)
    lignes: list[int] = field(default_factory=list)       # lignes de trace
    symboles: list[SymboleVise] = field(default_factory=list)


# ------------------------------------------------------------- les indices
_TRACES = [
    # Python : File "x/y.py", line 12, in f
    re.compile(r'File "([^"]+)", line (\d+)(?:, in (\S+))?(?:  \(x(\d+)\))?'),
    # IPython / Jupyter : File ~/x/y.py:12, in f(a, b) — tres courant dans
    # les tickets des bibliotheques scientifiques (seaborn, banc du 12/10)
    re.compile(r"File ((?:[A-Za-z]:)?~?[^\s\"':]+\.pyx?):(\d+)"
               r"(?:, in ([\w.<>]+))?"),
    # JS : at f (x/y.js:12:5)  /  at x/y.js:12:5
    re.compile(r"at (?:([\w.$<>]+) \()?((?:[A-Za-z]:)?[^\s():]+\.[cm]?[jt]sx?)"
               r":(\d+)(?::\d+)?\)?"),
    # Java : at a.b.C.m(C.java:12)
    re.compile(r"at ([\w.$]+)\.([\w$<>]+)\((\w+\.(?:java|kt)):(\d+)\)"),
    # Go, Rust, C# et le reste : chemin/fichier.ext:12
    re.compile(r"((?:[\w.-]+/)*[\w.-]+\.(?:go|rs|cs|php|rb)):(\d+)"),
]


def _blocs_de_code(texte: str) -> tuple[str, str]:
    """(prose, code) : ce qui est entre ``` ou indente de 4, et le reste."""
    code, prose = [], []
    dedans = False
    for l in texte.splitlines():
        if l.strip().startswith("```"):
            dedans = not dedans
            continue
        (code if dedans or l.startswith(("    ", "\t", ">>> ")) else
         prose).append(l)
    return "\n".join(prose), "\n".join(code)


# La SORTIE d'un outil collee dans le ticket (pylint-7080 : « src/x.py:2:0:
# R2044: Line with empty comment », « ***** Module about ») : ses mots sont
# ceux de l'outil, pas du bug — ils noyaient les vrais indices (13/10/2026).
# Les traces d'erreur, elles, sont lues a part (_TRACES) et restent.
_SORTIE = re.compile(
    r"^\s*(?:\S+:\d+(?::\d+)?:\s|\*{5,}|[-=_]{5,}|Your code has been rated"
    r"|[A-Z]\d{4}:|collected \d+ items?|=+ .* in [\d.]+s)")
# PAS les lignes « E   assert b'' == b'42' » ni « FAILED » de pytest : elles
# portent l'explication du bug (pytest-5495 reculait de 2 a 8, banc 13/10).


_LIGNE_ERREUR = re.compile(
    r"^(\s*[\w.]*(?:Error|Exception|Warning)\w*):\s.*$", re.M)


def sans_messages(code: str) -> str:
    """« RecursionError: maximum recursion depth exceeded » -> la classe
    d'erreur seule : le message est de la prose (il est lu a part, comme
    MESSAGE, et cherche tel quel dans le code)."""
    return _LIGNE_ERREUR.sub(r"\1", code)


def _forme_code(t: str) -> bool:
    """Un mot qui a la forme du code : snake_case, camelCase, CamelCase
    compose, ou pointe."""
    return bool("_" in t.strip("_") or re.search(r"[a-z][A-Z]", t)
                or "." in t or re.match(r"[A-Z][a-z]+[A-Z]", t))


def _phrase(texte: str) -> bool:
    """De la prose : au moins 4 mots, sans ponctuation de code."""
    return (len(re.findall(r"[A-Za-z]+", texte)) >= 4
            and not re.search(r"[()\[\]{}=<>]", texte))


def sans_sortie(code: str) -> str:
    return "\n".join(l for l in code.splitlines() if not _SORTIE.match(l))


def indices(ticket: str) -> Indices:
    i = Indices()
    cadres = []                               # (position, chemin, ligne, f)
    for m in _TRACES[0].finditer(ticket):
        c = (m.group(1).replace("\\", "/"), int(m.group(2)))
        cadres.append((m.start(), *c, m.group(3) or ""))
        i.repetes[c] = i.repetes.get(c, 0) + int(m.group(4) or 1)
    i.recursion = "RecursionError" in ticket
    for m in _TRACES[1].finditer(ticket):
        cadres.append((m.start(), m.group(1).replace("\\", "/"),
                       int(m.group(2)), (m.group(3) or "").rsplit(".", 1)[-1]))
    for m in _TRACES[2].finditer(ticket):
        cadres.append((m.start(), m.group(2).replace("\\", "/"),
                       int(m.group(3)), m.group(1) or ""))
    for m in _TRACES[3].finditer(ticket):
        paquet = m.group(1).rsplit(".", 1)[0].replace(".", "/")
        cadres.append((m.start(), f"{paquet}/{m.group(3)}", int(m.group(4)),
                       m.group(2)))
    for m in _TRACES[4].finditer(ticket):
        cadres.append((m.start(), m.group(1), int(m.group(2)), ""))
    # dans l'ordre du ticket : le dernier cadre est le plus profond
    vus_cadres = set()
    for _, c, l, f in sorted(cadres):
        if (c, l) not in vus_cadres:
            vus_cadres.add((c, l))
            i.trace.append((c, l, f))
    vus = {t[0] for t in i.trace}
    for m in re.finditer(r"(?<![\w/.-])((?:[\w.-]+/)*[\w-]+\.(?:py|pyx|js|mjs|"
                         r"ts|tsx|jsx|java|go|cs|php|rb|rs|kt|c|h|cpp|html|"
                         r"css|rst|md|cfg|toml|ini|txt|json|ya?ml))\b", ticket):
        c = m.group(1)
        if c not in vus and not c.startswith("www."):
            vus.add(c)
            i.chemins.append(c)
    for m in re.finditer(r"(?m)^\s*(?:>>>\s*|\.\.\.\s*)?(?:from\s+([\w.]+)\s+"
                         r"import\s+([\w, ()]+)|import\s+([\w.]+))", ticket):
        if m.group(1):
            i.modules.append(m.group(1))
            for nom in re.findall(r"\w+", m.group(2)):
                i.modules.append(f"{m.group(1)}.{nom}")
        else:
            i.modules.append(m.group(3))
    # messages : texte entre guillemets, et la ligne finale « XError: msg »
    for m in re.finditer(r"(?m)^\s*\w*(?:Error|Exception|Warning)\w*:\s*(.+)$",
                         ticket):
        i.messages.append(m.group(1).strip())
    for m in re.finditer(r"[\"'`]([^\"'`\n]{12,120})[\"'`]", ticket):
        if " " in m.group(1):
            i.messages.append(m.group(1).strip())
    i.messages = list(dict.fromkeys(x.rstrip(".") for x in i.messages
                                    if len(x) >= 12))[:12]
    prose, code = _blocs_de_code(ticket)
    candidats = Counter()
    for m in re.finditer(r"`([^`\n]+)`", ticket):        # entre accents graves
        # une PHRASE entre accents graves (« `RecursionError: maximum
        # recursion depth exceeded` », sympy-21627) n'est pas du code :
        # seuls ses mots qui ONT la forme du code comptent — sinon
        # « depth » designait polys/agca/ideals.py (Kaggle, 15/10)
        phrase = _phrase(m.group(1))
        for t in _IDENT.findall(m.group(1)):
            if not phrase or _forme_code(t):
                candidats[t] += 3
    for t in _IDENT.findall(sans_messages(sans_sortie(code))):
        candidats[t] += 1
    for t in _IDENT.findall(prose):
        if ("_" in t.strip("_") or re.search(r"[a-z][A-Z]", t)
                or "." in t or re.match(r"[A-Z][a-z]+[A-Z]", t)):
            candidats[t] += 2
    for m in re.finditer(r"\b([A-Za-z_]\w*)\(", prose):
        candidats[m.group(1)] += 2
    # options a tirets : « --import-mode », `ignore-paths`, « foo-bar = »
    # s'ecrivent import_mode / ignore_paths dans le code (pylint, pytest,
    # banc du 12/10). Seulement quand c'est clairement une option : apres
    # --, entre accents graves, ou suivie de « = ».
    for m in re.finditer(r"(?:--|`)([a-z][a-z0-9]*(?:-[a-z0-9]+)+)"
                         r"|\b([a-z][a-z0-9]*(?:-[a-z0-9]+)+)\s*=", ticket):
        candidats[(m.group(1) or m.group(2)).replace("-", "_")] += 2
    ids = []
    for t, _ in candidats.most_common():
        for partie in [t] + t.split(".")[1:]:
            der = partie.rsplit(".", 1)[-1]
            if len(der) < 3 or der.lower() in _COMMUNS or der.isdigit():
                continue
            ids.append(partie)
    i.identifiants = list(dict.fromkeys(ids))[:40]
    mots = Counter(w.lower() for w in re.findall(r"[A-Za-z]{4,}", prose))
    i.mots = [w for w, _ in mots.most_common()
              if w not in _VIDES and w not in _COMMUNS][:25]
    # les noms de fichiers que le texte peut designer : un mot, ou deux mots
    # colles (« man page » -> manpage.py, sphinx, banc du 12/10)
    suite = [w.lower() for w in re.findall(r"[A-Za-z]+", prose)]
    seuls = {w for w in suite if len(w) >= 5}
    i.noms_colles = {a + b for a, b in zip(suite, suite[1:])
                     if len(a + b) >= 6 and min(len(a), len(b)) >= 3} - seuls
    i.noms_possibles = seuls | i.noms_colles
    return i


def _generique(fonction: str) -> bool:
    """Un cadre de mecanique (constructeur, operateur, decorateur), pas de
    logique propre au bug."""
    return (fonction.startswith("__") or fonction.startswith("<")
            or fonction in {"wrapper", "wrapped", "inner", "_func",
                            "decorator", "binary_op_wrapper"})


def normal(nom: str) -> str:
    """import_mode, import-mode, ImportMode -> importmode (13/10/2026 :
    « --import-mode » du ticket, classe ImportMode du code, pytest-11148)."""
    return re.sub(r"[_-]", "", nom).lower()


def compose(nom: str) -> bool:
    """Un nom fait de plusieurs mots : import_mode, ImportMode, ignore-paths."""
    n = nom.strip("_")
    return len(normal(n)) >= 6 and bool(re.search(r"[a-z0-9][_-][a-z]|"
                                                  r"[a-z][A-Z]", n))


# ---------------------------------------------------------- correspondances
def _par_suffixe(index: Index, chemin: str) -> list[str]:
    """Les fichiers du depot dont le chemin est le plus long suffixe du chemin
    cite (« /home/x/site-packages/sympy/core/basic.py » -> sympy/core/basic.py)."""
    parties = PurePosixPath(chemin.replace("\\", "/")).parts
    for k in range(len(parties), 0, -1):
        suffixe = "/".join(parties[-k:])
        trouves = [f for f in index.fichiers
                   if f == suffixe or f.endswith("/" + suffixe)]
        if trouves:
            return trouves if k > 1 or len(trouves) <= 3 else []
    return []


def _module(index: Index, module: str) -> list[str]:
    base = module.replace(".", "/")
    cibles = (base + ".py", base + "/__init__.py", base + ".pyx")
    return [f for f in index.fichiers
            if f in cibles or any(f.endswith("/" + c) for c in cibles)]


# ------------------------------------------------------------- localiser
P_COUVERTURE = 12.0
COUVERTURE_FICHIERS = 8
# une seule instruction : rien a comparer, tout ce qu'elle traverse compte
COUVERTURE_UNE_INSTRUCTION = True


def fonctions_fautives(couverture) -> dict[str, list[tuple[str, int]]]:
    """{fichier: [(fonction, premiere ligne)]} traversees par la DERNIERE
    instruction de l'exemple qui touche au depot, et par AUCUNE avant elle :
    les premieres preparent ou montrent le cas qui marche, la derniere
    montre le bug (sympy-12236 : 652 fonctions executees -> 136, dont
    from_FractionField, la fonction du correctif officiel). Une seule
    instruction : tout ce qu'elle traverse."""
    par: dict[int, set] = {}
    for f, appels in (couverture or {}).items():
        for nom, ligne, i in appels:
            par.setdefault(i, set()).add((f, nom, ligne))
    if not par or (len(par) == 1 and not COUVERTURE_UNE_INSTRUCTION):
        return {}
    derniere = max(par)
    avant = set().union(*(s for i, s in par.items() if i != derniere))
    out: dict[str, list[tuple[str, int]]] = {}
    for f, nom, ligne in sorted(par[derniere] - avant):
        out.setdefault(f, []).append((nom, ligne))
    return out


def _nommee(nom: str) -> bool:
    """Une vraie fonction du depot : ni <listcomp>/<lambda>, ni __dunder__."""
    return not nom.startswith("<") and not (nom.startswith("__")
                                            and nom.endswith("__"))


def localiser(index: Index, ticket: str, n: int = 10,
              textes: dict[str, str] | None = None,
              couverture=None) -> list[Lieu]:
    """Les n fichiers les plus probables, avec leurs raisons et, dans chacun,
    les fonctions a lire. `textes` : contenus deja lus (sinon lus ici).
    `couverture` : ce que l'exemple du ticket a execute (couverture.lire)."""
    racine = Path(index.racine)
    ind = indices(ticket)
    lieux: dict[str, Lieu] = {}

    def ajouter(f, points, raison):
        l = lieux.setdefault(f, Lieu(f, 0.0))
        l.score += points
        if raison not in l.raisons:
            l.raisons.append(raison)
        return l

    # 0. l'exemple du ticket, EXECUTE : les fichiers que seule l'instruction
    # fautive traverse, d'autant plus qu'elle y appelle de vraies fonctions
    fautives = {f: [x for x in fs if _nommee(x[0])]
                for f, fs in fonctions_fautives(couverture).items()
                if f in index.fichiers and not index.fichiers[f].test}
    fautives = {f: fs for f, fs in fautives.items() if fs}
    if fautives:
        # la DENSITE (part des fonctions du fichier traversees), pas leur
        # nombre : sinon un gros fichier utilitaire (rings.py, 150
        # fonctions) ecrase le petit fichier fautif (polynomialring.py)
        def densite(f):
            total = sum(1 for s in index.fichiers[f].symboles
                        if s.sorte != "classe")
            return len(fautives[f]) / max(total, len(fautives[f]), 1)
        plus = max(densite(f) for f in fautives)
        for f in sorted(fautives, key=densite,
                        reverse=True)[:COUVERTURE_FICHIERS]:
            fs = fautives[f]
            l = ajouter(f, P_COUVERTURE * (0.5 + 0.5 * densite(f) / plus),
                        "execute par l'exemple : "
                        + ", ".join(nom for nom, _ in fs[:4]))
            # co_firstlineno est le decorateur ou le def : +1 tombe dedans
            l.lignes += [ligne + 1 for _, ligne in fs[:6]]

    # 1. traces : le cadre le plus profond (le dernier) compte le plus —
    # sauf dans une RecursionError, ou le fond de la pile est n'importe ou
    # dans la boucle : la, ce sont les cadres REPETES qui comptent, hors
    # mecanique generique (__new__, wrapper de cache). sympy-21627 : le
    # correctif est dans complexes.py (eval, x97), le fond est basic.py.
    # Chaque fichier n'y compte que son MEILLEUR cadre : basic.py, 4 cadres
    # de parcours hors boucle, passait devant.
    boucle = ({k for k, n in ind.repetes.items() if n >= 3}
              if ind.recursion else set())
    meilleur: dict[str, float] = {}
    for rang, (c, ligne, fonction) in enumerate(ind.trace):
        trouves = _par_suffixe(index, c)
        if boucle:
            poids = (P_TRACE + P_TRACE_PROFOND if (c, ligne) in boucle
                     and not _generique(fonction) else P_TRACE / 2)
        else:
            profond = rang == len(ind.trace) - 1 or rang >= len(ind.trace) - 2
            poids = P_TRACE + (P_TRACE_PROFOND if profond else 0)
        for f in trouves:
            raison = f"trace : ligne {ligne}" + (f" ({fonction})" if fonction
                                                 else "")
            if boucle:
                part = max(0.0, poids / len(trouves) - meilleur.get(f, 0.0))
                meilleur[f] = max(meilleur.get(f, 0.0), poids / len(trouves))
                l = ajouter(f, part, raison)
            else:
                l = ajouter(f, poids / len(trouves), raison)
            l.lignes.append(ligne)
    # 2. chemins cites
    for c in ind.chemins:
        trouves = _par_suffixe(index, c)
        exact = "/" in c
        for f in trouves:
            ajouter(f, (P_CHEMIN if exact else P_NOM_FICHIER) / len(trouves),
                    f"chemin cite : {c}")
    # 2 bis. un nom de fichier designe par les mots (« man page » -> manpage)
    if ind.noms_possibles:
        par_nom: dict[str, list[str]] = {}
        for f in index.fichiers:
            nom = PurePosixPath(f).stem.lower().replace("_", "")
            if nom in ind.noms_possibles:
                par_nom.setdefault(nom, []).append(f)
        for nom, fs in par_nom.items():
            if len(fs) <= 3:
                # deux mots colles qui font un nom de fichier : indice PRECIS
                # (manpage) ; un mot seul (generate, build) : bruit frequent
                poids = P_COLLE if nom in ind.noms_colles else P_NOM_FICHIER / 2
                for f in fs:
                    ajouter(f, poids / len(fs), f"nom de fichier : {nom}")
    # 3. imports
    for mod in ind.modules:
        trouves = _module(index, mod)
        for f in trouves:
            ajouter(f, P_IMPORT / len(trouves), f"import : {mod}")
    # 4-6 : lire les contenus (une fois)
    if textes is None:
        textes = {}
    def texte(f):
        if f not in textes:
            try:
                textes[f] = (racine / f).read_text(encoding="utf-8",
                                                   errors="replace")
            except OSError:
                textes[f] = ""
        return textes[f]
    # definitions : nom du symbole (dernier morceau, ou « Classe.methode »)
    definitions: dict[str, set[str]] = {}
    normales: dict[str, set[str]] = {}
    for f, s in index.symboles():
        definitions.setdefault(s.nom, set()).add(f.chemin)
        der = s.nom.rsplit(".", 1)[-1]
        definitions.setdefault(der, set()).add(f.chemin)
        normales.setdefault(normal(der), set()).add(f.chemin)
    nb = max(1, len(index.fichiers))
    for ident in ind.identifiants:
        der = ident.rsplit(".", 1)[-1]
        defs = definitions.get(ident) or definitions.get(der) or set()
        if not defs and P_NORMAL and compose(der):
            # import_mode ~ ImportMode ; jamais un mot simple (autosummary
            # ~ Autosummary, pytest ~ _pytest : faux rapprochements, 13/10)
            defs = normales.get(normal(der), set())
        if defs and len(defs) <= 25:
            poids = P_DEFINIT / math.sqrt(len(defs))
            for f in defs:
                ajouter(f, poids, f"definit {der}")
    usages: dict[str, list[str]] = {}
    termes = [i.rsplit(".", 1)[-1] for i in ind.identifiants]
    mots = ind.mots
    tf_mots: dict[str, Counter] = {}
    longueur: dict[str, int] = {}
    for f, fi in index.fichiers.items():
        t = texte(f)
        if not t:
            continue
        for m in ind.messages:
            if m in t:
                usages.setdefault("\0" + m, []).append(f)
        for terme in termes:
            if terme in t:
                usages.setdefault(terme, []).append(f)
        if mots:
            bas = t.lower()
            c = Counter({w: bas.count(w) for w in mots})
            c = +c
            if c:
                tf_mots[f] = c
                longueur[f] = max(1, fi.lignes)
    for m in ind.messages:
        fs = usages.get("\0" + m, [])
        if fs and len(fs) <= 10:
            for f in fs:
                ajouter(f, P_MESSAGE / len(fs), f"message « {m[:40]} »")
    for terme in dict.fromkeys(termes):
        fs = usages.get(terme, [])
        # trop courant (> 20 % des fichiers) : n'apprend rien — sauf sur un
        # petit depot, ou tout nom est « courant »
        if fs and len(fs) <= max(5, nb * 0.2):
            idf = math.log(1 + nb / len(fs))
            for f in fs:
                if f in lieux or len(fs) <= 50:
                    ajouter(f, P_EMPLOIE * idf / math.log(1 + nb),
                            f"emploie {terme}")
    # 6. BM25 sur les mots du texte
    if tf_mots:
        moyenne = sum(longueur.values()) / len(longueur)
        df = Counter(w for c in tf_mots.values() for w in c)
        for f, c in tf_mots.items():
            s = 0.0
            for w, tf in c.items():
                idf = math.log(1 + (nb - df[w] + 0.5) / (df[w] + 0.5))
                s += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * longueur[f]
                                                   / moyenne))
            if s > 0 and (f in lieux or s > 4):
                l = lieux.setdefault(f, Lieu(f, 0.0))
                l.score += P_MOT * s / max(1, len(mots)) * 4
    # les tests et la documentation passent apres le code
    for f, l in lieux.items():
        fi = index.fichiers.get(f)
        sorte = "test" if fi and fi.test else (fi.langage if fi else "")
        if _TIERS.search(f):
            sorte = "tiers"
        l.score *= FACTEUR.get(sorte, 1.0)
    _suivre_les_appels(index, ind, lieux, definitions, texte, ajouter)
    classes = sorted(lieux.values(), key=lambda l: (-l.score, l.fichier))[:n]
    for l in classes:
        l.symboles = _symboles_vises(index, l, ind, texte(l.fichier))
    return classes


# Banc v3 du 12/10 (63 tickets) : a 2.0, et en ouvrant la liste a tout
# fichier qui definit une fonction appelee, le levier faisait PLUS DE MAL
# (17 tickets moins bien classes, 5 mieux) — les fonctions appelees sont
# souvent des utilitaires partages. Version prudente (departager seulement
# des candidats, poids 0.8) mesuree sur la moitie « reglage » : top 1
# 17 -> 15, top 5 25 -> 26 — pas mieux que sans. Poids NUL : le lien reste
# une RAISON affichee (le modele, au levier 3, verra qui appelle qui), il ne
# change plus le classement.
P_APPEL = 0.0
_RANGS_SUIVIS = (1.0, 0.6, 0.4)        # poids des 3 premiers lieux
_APPEL = re.compile(r"(?<![\w])([A-Za-z_]\w{3,})\s*\(")


def _suivre_les_appels(index: Index, ind: Indices, lieux: dict,
                       definitions: dict, texte, ajouter) -> None:
    """Levier 2 (12/10/2026) : le ticket nomme ce que l'utilisateur APPELLE
    (iter_content), le bug est souvent dans ce que cette fonction appelle a
    son tour (stream_decode_response_unicode, dans un autre fichier :
    requests-3362). Dans les fonctions designees des 3 premiers lieux, on
    releve les fonctions appelees ; le fichier qui les DEFINIT gagne des
    points (d'autant plus que le lieu est haut, d'autant moins que le nom est
    defini en beaucoup d'endroits)."""
    premiers = sorted(lieux.values(), key=lambda l: (-l.score, l.fichier))[:3]
    for poids, l in zip(_RANGS_SUIVIS, premiers):
        fi = index.fichiers.get(l.fichier)
        if not fi or fi.test:
            continue
        t = texte(l.fichier)
        lignes = t.split("\n")
        appels: set[str] = set()
        for s in _symboles_vises(index, l, ind, t)[:3]:
            corps = "\n".join(lignes[s.debut:s.fin])          # sans la def
            appels |= set(_APPEL.findall(corps))
            appels.discard(s.nom.rsplit(".", 1)[-1])
        for nom in appels - _COMMUNS:
            defs = {f for f in definitions.get(nom, set())
                    if f != l.fichier and not index.fichiers[f].test
                    and f in lieux}               # departager, pas ouvrir
            if defs and len(defs) <= 5:
                for f in defs:
                    ajouter(f, P_APPEL * poids / math.sqrt(len(defs)),
                            f"appele depuis {l.fichier} : {nom}")


def _symboles_vises(index: Index, lieu: Lieu, ind: Indices, texte: str
                    ) -> list[SymboleVise]:
    """Dans un fichier, les fonctions a montrer : celles de la trace, celles
    que le ticket nomme, celles qui emploient ses identifiants."""
    fi = index.fichiers.get(lieu.fichier)
    if not fi:
        return []
    lignes = texte.splitlines()
    noms = {i.rsplit(".", 1)[-1] for i in ind.identifiants}
    out = []
    for s in fi.symboles:
        score = 0.0
        if s.sorte == "classe":
            # une classe ne compte que si le ticket la NOMME : ce qu'elle
            # contient (ligne de trace, message) designe ses METHODES
            if s.nom.rsplit(".", 1)[-1] in noms and s.fin - s.debut <= 60:
                out.append(SymboleVise(s.nom, s.debut, s.fin, 2.0))
            continue
        if any(s.debut <= l <= s.fin for l in lieu.lignes):
            score += 5
        if s.nom.rsplit(".", 1)[-1] in noms or s.nom in ind.identifiants:
            score += 3
        corps = "\n".join(lignes[s.debut - 1:s.fin])
        score += sum(1 for n in noms if n in corps) * 0.5
        score += sum(1 for m in ind.messages if m in corps) * 3
        if score:
            out.append(SymboleVise(s.nom, s.debut, s.fin, score))
    out.sort(key=lambda s: (-s.score, s.debut))
    return out[:8]
