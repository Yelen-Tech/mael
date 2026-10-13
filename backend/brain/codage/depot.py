"""L'INDEX d'un depot existant : ce que MAEL sait d'un projet avant d'y toucher.

Point 4 de la feuille de route « agent autonome » (12/10/2026) : reprendre
un depot existant (type SWE-bench). Jusque-la, le mode « assister » montrait
TOUT le projet au modele, sous 12 000 caracteres : impossible au-dela de
quelques fichiers. Un depot reel en a des milliers (exigence du responsable :
10 000 et plus).

L'index, sans modele (deterministe, teste) :
  - INVENTAIRE : `git ls-files` quand le depot est sous git (il respecte le
    .gitignore), sinon un parcours qui ecarte les dossiers de dependances et
    de construction ; les binaires et les fichiers trop gros sont ecartes ;
  - SYMBOLES : fonctions, classes, methodes, avec leurs lignes de debut et
    de fin — par l'AST pour Python, par motifs pour JS/TS, Java, Go, C#, PHP ;
  - TESTS : les fichiers de test, reconnus a leur nom et a leur dossier ;
  - COMMANDE DE TEST du depot (pytest, npm test, go test, mvn, gradle,
    dotnet, phpunit, cargo) : c'est elle qui dira s'il y a regression ;
  - CACHE dans .mael/index.json : un fichier dont la taille et la date n'ont
    pas change n'est pas relu.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

VERSION = 1                      # change -> le cache est refait
TAILLE_MAX = 1_000_000           # au-dela : fichier genere ou donnees
ECARTES = {".git", ".mael", ".hg", ".svn", "node_modules", "venv", ".venv",
           "env", "__pycache__", ".mypy_cache", ".pytest_cache", ".tox",
           "dist", "build", "target", "bin", "obj", "vendor", ".idea",
           ".vscode", "coverage", ".next", ".gradle", "site-packages"}
LANGAGES = {".py": "python", ".js": "javascript", ".mjs": "javascript",
            ".cjs": "javascript", ".jsx": "javascript", ".ts": "typescript",
            ".tsx": "typescript", ".java": "java", ".go": "go", ".cs": "csharp",
            ".php": "php", ".rb": "ruby", ".rs": "rust", ".kt": "kotlin",
            ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
            ".html": "html", ".css": "css", ".sql": "sql", ".md": "texte",
            ".rst": "texte", ".txt": "texte", ".toml": "config",
            ".yaml": "config", ".yml": "config", ".json": "config",
            ".cfg": "config", ".ini": "config", ".xml": "config"}


@dataclass
class Symbole:
    nom: str                     # « Classe.methode » pour une methode
    sorte: str                   # fonction | classe | methode | type
    debut: int
    fin: int


@dataclass
class Fichier:
    chemin: str                  # relatif, avec des /
    langage: str
    taille: int
    date: int                    # mtime en ns
    lignes: int
    test: bool
    symboles: list[Symbole] = field(default_factory=list)


@dataclass
class Index:
    racine: str
    fichiers: dict[str, Fichier]
    suites: list  # list[Suite] : les tests du depot, par (sous-)projet
    ecartes: int = 0             # binaires, trop gros
    secondes: float = 0.0

    def symboles(self):
        for f in self.fichiers.values():
            for s in f.symboles:
                yield f, s


# ---------------------------------------------------------------- inventaire
def _git_ls(racine: Path) -> list[str] | None:
    if not (racine / ".git").exists():
        return None
    try:
        r = subprocess.run(["git", "-C", str(racine), "ls-files", "-z",
                            "--cached", "--others", "--exclude-standard"],
                           capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode:
        return None
    return [p for p in r.stdout.decode("utf-8", "replace").split("\0") if p]


def _parcours(racine: Path) -> list[str]:
    out = []
    base = len(str(racine)) + 1
    for dossier, sous, noms in os.walk(racine):
        sous[:] = [s for s in sous if s not in ECARTES
                   and not s.endswith(".egg-info")]
        rel = dossier[base:].replace("\\", "/")   # relative_to : 30 % du temps
        out.extend(f"{rel}/{n}" if rel else n for n in noms)
    return out


def inventaire(racine: Path) -> list[str]:
    """Les fichiers du depot (chemins relatifs), sans dependances ni
    constructions — meme si le depot les a commites par erreur."""
    chemins = _git_ls(racine)
    if chemins is None:
        chemins = _parcours(racine)
    return sorted(p for p in chemins
                  if not set(PurePosixPath(p).parts[:-1]) & ECARTES)


def _binaire(octets: bytes) -> bool:
    return b"\0" in octets[:8192]


# ------------------------------------------------------------------- tests
_TEST = re.compile(
    r"(^|/)(tests?|__tests__|spec|testing)/"
    r"|(^|/)test_[^/]+\.py$|_test\.(py|go)$|\.(test|spec)\.[cm]?[jt]sx?$"
    r"|(^|/)src/test/|Tests?\.(java|cs|kt)$|Test\.php$|(^|/)conftest\.py$")


def est_test(chemin: str) -> bool:
    return bool(_TEST.search(chemin))


# ---------------------------------------------------------------- symboles
def symboles_python(texte: str) -> list[Symbole]:
    import warnings
    try:
        with warnings.catch_warnings():
            # « invalid escape sequence » du code LU : pas un avis de MAEL
            warnings.simplefilter("ignore", SyntaxWarning)
            arbre = ast.parse(texte)
    except (SyntaxError, ValueError):
        return []
    out = []

    def visiter(noeuds, prefixe=""):
        for n in noeuds:
            if isinstance(n, ast.ClassDef):
                out.append(Symbole(prefixe + n.name, "classe", n.lineno,
                                   n.end_lineno or n.lineno))
                visiter(n.body, prefixe + n.name + ".")
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # les decorateurs font partie de la fonction a montrer
                debut = min([d.lineno for d in n.decorator_list] + [n.lineno])
                out.append(Symbole(prefixe + n.name,
                                   "methode" if prefixe else "fonction",
                                   debut, n.end_lineno or n.lineno))
    visiter(arbre.body)
    return out


# Langages a accolades : le motif trouve la DECLARATION, la fin est l'accolade
# fermante correspondante (chaines et commentaires sautes).
_MOTIFS = {
    "javascript": [
        ("classe", r"^\s*(?:export\s+)?(?:default\s+)?class\s+(\w+)"),
        ("fonction", r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
                     r"function\s*\*?\s*(\w+)\s*\("),
        ("fonction", r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*"
                     r"(?:async\s+)?(?:function\b|\([^)]*\)\s*=>|\w+\s*=>)"),
        ("methode", r"^\s+(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?"
                    r"(?!if\b|for\b|while\b|switch\b|catch\b|return\b)"
                    r"(\w+)\s*\([^)]*\)\s*\{"),
    ],
    "java": [
        ("classe", r"^\s*(?:@\w+\s+)*(?:(?:public|private|protected|abstract|"
                   r"final|static|sealed)\s+)*(?:class|interface|enum|record)"
                   r"\s+(\w+)"),
        ("methode", r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:public|private|"
                    r"protected|static|final|abstract|synchronized|default)\s+)"
                    r"*(?:<[^>]+>\s+)?[\w.<>\[\], ?]+\s+(\w+)\s*\([^;{]*\)"
                    r"\s*(?:throws\s+[\w., ]+)?\s*\{"),
    ],
    "csharp": [
        ("classe", r"^\s*(?:\[[^\]]*\]\s*)*(?:(?:public|private|protected|"
                   r"internal|abstract|sealed|static|partial)\s+)*"
                   r"(?:class|interface|struct|record|enum)\s+(\w+)"),
        ("methode", r"^\s*(?:(?:public|private|protected|internal|static|"
                    r"virtual|override|async|abstract|sealed)\s+)+"
                    r"[\w.<>\[\], ?]+\s+(\w+)\s*\([^;{]*\)\s*\{?\s*$"),
    ],
    "go": [
        ("fonction", r"^func\s+(?:\([^)]*\)\s*)?(\w+)\s*[\[(]"),
        ("type", r"^type\s+(\w+)\s+(?:struct|interface)\b"),
    ],
    "php": [
        ("classe", r"^\s*(?:(?:abstract|final|readonly)\s+)*"
                   r"(?:class|interface|trait|enum)\s+(\w+)"),
        ("fonction", r"^\s*(?:(?:public|private|protected|static|abstract|"
                     r"final)\s+)*function\s+&?(\w+)\s*\("),
    ],
}
_MOTIFS["typescript"] = _MOTIFS["javascript"] + [
    ("type", r"^\s*(?:export\s+)?(?:interface|type|enum)\s+(\w+)")]
_MOTIFS["kotlin"] = [("classe", r"^\s*(?:\w+\s+)*class\s+(\w+)"),
                     ("fonction", r"^\s*(?:\w+\s+)*fun\s+(?:<[^>]+>\s*)?"
                                  r"(?:\w+\.)?(\w+)\s*\(")]
_MOTIFS["rust"] = [("fonction", r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?"
                                r"fn\s+(\w+)"),
                   ("type", r"^\s*(?:pub\s+)?(?:struct|enum|trait|impl)\s+"
                            r"(?:<[^>]+>\s*)?(\w+)")]
_COMPILES = {k: [(s, re.compile(m)) for s, m in v] for k, v in _MOTIFS.items()}


def _fin_accolade(lignes: list[str], i: int) -> int:
    """Ligne (1-indexee) de l'accolade qui ferme le bloc ouvert a partir de
    la ligne i (0-indexee). Sans accolade : la declaration seule."""
    profondeur, ouvert = 0, False
    for j in range(i, min(len(lignes), i + 5000)):
        l = re.sub(r"//.*$|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`[^`]*`",
                   "", lignes[j])
        for c in l:
            if c == "{":
                profondeur += 1
                ouvert = True
            elif c == "}":
                profondeur -= 1
                if ouvert and profondeur <= 0:
                    return j + 1
        if not ouvert and j > i + 2:         # declaration sans corps
            return i + 1
        if not ouvert and l.rstrip().endswith(";"):
            return j + 1
    return i + 1


def symboles_motifs(texte: str, langage: str) -> list[Symbole]:
    motifs = _COMPILES.get(langage)
    if not motifs:
        return []
    lignes = texte.splitlines()
    out: list[Symbole] = []
    classes: list[Symbole] = []
    for i, l in enumerate(lignes):
        for sorte, m in motifs:
            t = m.match(l)
            if not t:
                continue
            nom = t.group(1)
            fin = _fin_accolade(lignes, i)
            parent = next((c for c in reversed(classes)
                           if c.debut < i + 1 <= c.fin), None)
            if parent and sorte in {"fonction", "methode"}:
                s = Symbole(f"{parent.nom}.{nom}", "methode", i + 1, fin)
            else:
                s = Symbole(nom, sorte, i + 1, fin)
            out.append(s)
            if sorte == "classe":
                classes.append(s)
            break
    return out


def symboles(texte: str, langage: str) -> list[Symbole]:
    if langage == "python":
        return symboles_python(texte)
    return symboles_motifs(texte, langage)


# -------------------------------------------------------- commande de test
@dataclass
class Suite:
    """Les tests d'un (sous-)projet : un depot reel en a souvent plusieurs
    (backend/ en Python, frontend/ en JS). Mesure du 12/10 sur MAEL lui-meme :
    pytest est configure dans backend/, pas a la racine."""
    dossier: str                 # "" = racine du depot
    commande: list[str]
    motifs_py: list[str] = field(default_factory=list)   # python_files


_MARQUES = {"package.json", "go.mod", "Cargo.toml", "pom.xml", "build.gradle",
            "build.gradle.kts", "phpunit.xml", "phpunit.xml.dist",
            "pyproject.toml", "setup.cfg", "setup.py", "pytest.ini", "tox.ini",
            "conftest.py"}
PROFONDEUR_PROJETS = 3


def motifs_pytest(lire) -> list[str]:
    """Les motifs `python_files` de la configuration pytest du projet (par
    defaut test_*.py et *_test.py) : MAEL nomme ses tests tests_*.py."""
    import configparser
    import tomllib
    try:
        conf = tomllib.loads(lire("pyproject.toml") or "")
        v = conf.get("tool", {}).get("pytest", {}).get(
            "ini_options", {}).get("python_files")
        if v:
            return [v] if isinstance(v, str) else list(v)
    except (tomllib.TOMLDecodeError, AttributeError):
        pass
    for nom, section in (("pytest.ini", "pytest"), ("setup.cfg", "tool:pytest"),
                         ("tox.ini", "pytest")):
        p = configparser.ConfigParser(interpolation=None)
        try:
            p.read_string(lire(nom) or "")
        except configparser.Error:
            continue
        if p.has_option(section, "python_files"):
            return p.get(section, "python_files").split()
    return []


def _suite(racine: Path, dossier: str, noms: set[str],
           chemins_py: list[str]) -> Suite | None:
    """La commande qui lance les tests d'un projet, telle que ses auteurs la
    lancent (ce qui est ecrit dans le depot, jamais devine au hasard)."""
    def lire(p):
        try:
            return (racine / dossier / p).read_text(encoding="utf-8",
                                                    errors="replace")
        except OSError:
            return ""
    if "package.json" in noms:
        try:
            scripts = json.loads(lire("package.json")).get("scripts", {})
        except ValueError:
            scripts = {}
        test = scripts.get("test", "")
        if test and "no test specified" not in test:
            return Suite(dossier, ["npm", "test"])
    if "go.mod" in noms:
        return Suite(dossier, ["go", "test", "./..."])
    if "Cargo.toml" in noms:
        return Suite(dossier, ["cargo", "test"])
    if "pom.xml" in noms:
        return Suite(dossier, ["mvn", "-q", "test"])
    if {"build.gradle", "build.gradle.kts"} & noms:
        return Suite(dossier, ["./gradlew", "test"] if "gradlew" in noms
                     else ["gradle", "test"])
    if any(n.endswith((".sln", ".csproj")) for n in noms):
        return Suite(dossier, ["dotnet", "test"])
    if {"phpunit.xml", "phpunit.xml.dist"} & noms:
        return Suite(dossier, ["vendor/bin/phpunit"])
    motifs = motifs_pytest(lire)
    pytest_ecrit = (motifs or "pytest.ini" in noms or "conftest.py" in noms
                    or "[tool.pytest" in lire("pyproject.toml")
                    or "[tool:pytest]" in lire("setup.cfg")
                    or "pytest" in lire("tox.ini"))
    if pytest_ecrit or any(est_test(p) for p in chemins_py):
        return Suite(dossier, ["python", "-m", "pytest"], motifs)
    return None


def suites_de_test(racine: Path, chemins: list[str]) -> list[Suite]:
    """Une suite par (sous-)projet portant une marque (package.json, go.mod,
    pyproject.toml...), jusqu'a PROFONDEUR_PROJETS dossiers ; la racine
    d'abord. Un sous-projet inclus dans un autre garde sa propre suite."""
    enfants: dict[str, set[str]] = {}          # dossier -> noms directs
    for c in chemins:
        d, _, nom = c.rpartition("/")
        enfants.setdefault(d, set()).add(nom)
    projets = [d for d, noms in enfants.items()
               if (not d or d.count("/") < PROFONDEUR_PROJETS)
               and any(n in _MARQUES or n.endswith(".sln") for n in noms)]
    # .NET : un .csproj seul n'est pas une suite — Calc/ (le code) et
    # Calc.Tests/ (les tests, qui referencent ../Calc) se testent ENSEMBLE,
    # depuis leur solution ou leur dossier commun (banc reel du 13/10 : la
    # suite « Calc/ » ne lancait aucun test et rendait « tout passe »).
    dotnet = _racines_dotnet(enfants)
    out = []
    for d in sorted(set(projets) | dotnet,
                    key=lambda d: (d.count("/") if d else -1, d)):
        py = [c for c in chemins if c.endswith(".py")
              and (not d or c.startswith(d + "/"))]
        s = _suite(racine, d, enfants.get(d, set()), py)
        if s is None and d in dotnet:
            s = Suite(d, ["dotnet", "test"])
        if s:
            out.append(s)
    return out


def _racines_dotnet(enfants: dict[str, set[str]]) -> set[str]:
    """Les dossiers d'ou tester les projets .NET : la solution qui les
    contient, sinon le dossier commun des projets sans solution."""
    import posixpath
    slns = {d for d, noms in enfants.items()
            if any(n.endswith(".sln") for n in noms)}
    seuls = []
    for d, noms in enfants.items():
        if not any(n.endswith(".csproj") for n in noms):
            continue
        if not any(s == "" or d == s or d.startswith(s + "/") for s in slns):
            seuls.append(d)
    out = set(slns)
    if seuls:
        commun = posixpath.commonpath(seuls) if all(seuls) else ""
        out.add(commun if len(seuls) > 1 else seuls[0])
    return out


def _glob_re(motif: str) -> re.Pattern:
    import fnmatch
    return re.compile(fnmatch.translate(motif))


def est_test_suite(chemin: str, suites: list[Suite]) -> bool:
    """Test selon son nom (conventions communes) OU selon les motifs
    python_files de la suite qui le contient."""
    if est_test(chemin):
        return True
    if not chemin.endswith(".py"):
        return False
    nom = chemin.rsplit("/", 1)[-1]
    for s in suites:
        if s.motifs_py and (not s.dossier or chemin.startswith(s.dossier
                                                               + "/")):
            if any(_glob_re(m).match(nom) for m in s.motifs_py):
                return True
    return False


# -------------------------------------------------------------------- index
def _cache(racine: Path) -> Path:
    return racine / ".mael" / "index.json"


def _charger_cache(racine: Path) -> dict[str, Fichier]:
    try:
        brut = json.loads(_cache(racine).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if brut.get("version") != VERSION:
        return {}
    out = {}
    for c, f in brut.get("fichiers", {}).items():
        f["symboles"] = [Symbole(**s) for s in f.get("symboles", [])]
        out[c] = Fichier(**f)
    return out


def indexer(racine: Path | str, *, cache: bool = True) -> Index:
    """L'index du depot. Avec le cache, seuls les fichiers changes (taille ou
    date) sont relus : un depot de 10 000 fichiers se reindexe en secondes."""
    debut = time.monotonic()
    racine = Path(racine).resolve()
    ancien = _charger_cache(racine) if cache else {}
    chemins = inventaire(racine)
    suites = suites_de_test(racine, chemins)
    fichiers: dict[str, Fichier] = {}
    ecartes = 0
    for c in chemins:
        langage = LANGAGES.get(PurePosixPath(c).suffix.lower())
        if not langage:
            continue
        p = racine / c
        try:
            st = p.stat()
        except OSError:
            continue
        a = ancien.get(c)
        if a and a.taille == st.st_size and a.date == st.st_mtime_ns:
            a.test = est_test_suite(c, suites)   # la config a pu changer
            fichiers[c] = a
            continue
        if st.st_size > TAILLE_MAX:
            ecartes += 1
            continue
        try:
            octets = p.read_bytes()
        except OSError:
            continue
        if _binaire(octets):
            ecartes += 1
            continue
        texte = octets.decode("utf-8", "replace")
        fichiers[c] = Fichier(c, langage, st.st_size, st.st_mtime_ns,
                              texte.count("\n") + 1,
                              est_test_suite(c, suites),
                              symboles(texte, langage))
    idx = Index(str(racine), fichiers, suites, ecartes,
                time.monotonic() - debut)
    if cache:
        try:
            _cache(racine).parent.mkdir(parents=True, exist_ok=True)
            _cache(racine).write_text(json.dumps(
                {"version": VERSION,
                 "fichiers": {c: asdict(f) for c, f in fichiers.items()}},
                ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass                 # depot en lecture seule : index en memoire
    return idx
