"""Couche 7 : la JUSTESSE, verifiee en EXECUTANT des tests (option A du
responsable : dans un conteneur Docker sans reseau).

Pourquoi : nos juges lisent le code ; les evaluations publiques
l'EXECUTENT sur des tests caches (exigence du responsable, 07/10/2026 : « ils
ne jouent pas »). Un code conforme a toutes les normes peut calculer faux.

Schema valide par le responsable (08/10/2026), dicte par la memoire d'une
machine de 8 Go (modele ~3,5 Go + Docker ~1 Go = trop) :
  - les tests tournent en UN passage, a la finition, pas a chaque tache ;
  - le modele est DECHARGE de la memoire avant (Ollama keep_alive=0), et ne
    se recharge que s'il reste des corrections ;
  - la memoire libre est MESUREE avant : si elle manque, rien n'est lance
    et le bilan le dit (jamais « teste » sans l'avoir ete).

Le conteneur : image mael-tests-python (conteneur/Dockerfile.python),
jetable, --network none, --memory, --cpus, --pids-limit, utilisateur sans
droits (65534), aucun volume monte : les fichiers y sont COPIES.

Ce qui est execute :
  - les TESTS DE FUMEE ecrits par MAEL (ils ne dependent pas du modele) :
    chaque module Python s'importe ; chaque route sans parametre d'une
    application Flask repond sans erreur 500 ;
  - les tests du projet (test_*.py), ecrits par le modele.
Chaque echec devient un defaut bloquant, avec fichier et ligne.

Les fonctions de lecture (fumee, lire_pytest) sont pures : testees sans
Docker.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .juges import GRAVITE, Defaut

B = GRAVITE.BLOQUANT
IMAGE = "mael-tests-python"
DOCKERFILE = Path(__file__).parent / "conteneur" / "Dockerfile.python"
MEMOIRE_CONTENEUR = "512m"
MEMOIRE_LIBRE_MIN_GO = 1.5     # en dessous : on ne lance pas (machine 8 Go)
DELAI_TESTS = 180              # secondes pour toute la suite
FUMEE = "test_mael_fumee.py"
TRAVAIL = "/travail"
NORME = "execution reelle (pytest, conteneur sans reseau)"


@dataclass
class Rapport:
    lance: bool = False
    raison: str = ""                 # pourquoi rien n'a ete lance
    passes: int = 0
    echoues: int = 0
    erreurs: int = 0
    secondes: float = 0.0
    modele_decharge: bool = False


dernier_rapport = Rapport()


# ----------------------------------------------------------- la machine
def memoire_libre_go() -> float | None:
    """Memoire vive libre, en Go (None si on ne sait pas la lire)."""
    try:
        if sys.platform.startswith("win"):
            import ctypes

            class _Etat(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            e = _Etat()
            e.dwLength = ctypes.sizeof(_Etat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(e))
            return e.ullAvailPhys / 1024 ** 3
        with open("/proc/meminfo", encoding="ascii") as f:
            for ligne in f:
                if ligne.startswith("MemAvailable:"):
                    return int(ligne.split()[1]) / 1024 ** 2
    except (OSError, AttributeError, ValueError):
        return None
    return None


def _docker(args: list[str], delai: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          timeout=delai, check=False)


def docker_pret() -> str:
    """"" si Docker repond et que l'image existe ; sinon la raison."""
    try:
        # « docker version » (0,7 s) et non « docker info » (65 s sur le
        # portable vise, mesure du 09/10 : il interroge tous les greffons).
        if _docker(["version", "--format", "{{.Server.Version}}"]).returncode:
            return "Docker ne repond pas (Docker Desktop arrete ?)"
        if _docker(["image", "inspect", IMAGE]).returncode:
            return (f"image {IMAGE} absente (la construire, sans contexte : "
                    f"docker build -t {IMAGE} - < {DOCKERFILE.as_posix()})")
    except FileNotFoundError:
        return "Docker n'est pas installe"
    except subprocess.TimeoutExpired:
        return "Docker ne repond pas (delai depasse)"
    return ""


def decharger_modele(base: str, modele: str) -> bool:
    """Demande a Ollama de liberer la memoire du modele (keep_alive=0)."""
    try:
        import httpx
        r = httpx.post(f"{base}/api/generate",
                       json={"model": modele, "keep_alive": 0}, timeout=30)
        return r.status_code == 200
    except Exception:          # Ollama absent : rien a decharger
        return False


# ------------------------------------------------------- tests de fumee
_FLASK = re.compile(r"^(\w+)\s*=\s*Flask\s*\(", re.M)
_ROUTE = re.compile(
    r"""@(\w+)\.(?:route|get)\s*\(\s*['"]([^'"<{]*)['"]"""
    r"""(?:[^)]*methods\s*=\s*\[([^\]]*)\])?""")


def fumee(fichiers: dict[str, str]) -> str:
    """Les tests de fumee de MAEL, pour les fichiers Python du projet :
    chaque module s'importe ; chaque route GET sans parametre d'une
    application Flask repond sans erreur 500. Rend le code du fichier de
    test ("" s'il n'y a rien a tester)."""
    modules, routes = [], []
    for nom, texte in sorted(fichiers.items()):
        if not nom.endswith(".py") or Path(nom).name.startswith("test_"):
            continue
        module = nom[:-3].replace("/", ".")
        if not re.fullmatch(r"[A-Za-z_][\w.]*", module):
            continue
        modules.append(module)
        app = _FLASK.search(texte)
        if app:
            for m in _ROUTE.finditer(texte):
                methodes = (m.group(3) or "'GET'").upper()
                if m.group(1) == app.group(1) and "GET" in methodes:
                    routes.append((module, app.group(1), m.group(2) or "/"))
    if not modules:
        return ""
    l = ['"""Tests de fumee ecrits par MAEL (pas par le modele)."""',
         "import importlib", "import pytest", ""]
    l.append(f"MODULES = {modules!r}")
    l += ["", "",
          "@pytest.mark.parametrize('module', MODULES)",
          "def test_le_module_s_importe(module):",
          "    importlib.import_module(module)", ""]
    if routes:
        l += [f"ROUTES = {routes!r}", "", "",
              "@pytest.mark.parametrize('module,app,chemin', ROUTES)",
              "def test_la_route_repond_sans_erreur_500(module, app, chemin):",
              "    application = getattr(importlib.import_module(module), app)",
              "    application.config['TESTING'] = True",
              "    reponse = application.test_client().get(chemin)",
              "    assert reponse.status_code < 500, (",
              "        f'{chemin} : erreur {reponse.status_code}')", ""]
    return "\n".join(l)


# ------------------------------------------------------ lire pytest
_ECHEC = re.compile(r"^(FAILED|ERROR) (\S+?)(?:::(\S+))?(?: - (.*))?$", re.M)
_LIEU = re.compile(r"^([\w./-]+\.py):(\d+): ", re.M)
_TOTAL = re.compile(r"(\d+) (passed|failed|error|errors)")


def lire_pytest(sortie: str, fichiers_projet: set[str]) -> tuple[
        list[Defaut], dict[str, int]]:
    """Sortie de `pytest -q -rfE --tb=short` -> (defauts, comptes). Le
    defaut vise la ligne du PROJET la plus profonde de la trace (le code
    fautif), sinon le fichier de test."""
    comptes = {"passed": 0, "failed": 0, "error": 0}
    for n, mot in _TOTAL.findall(sortie):
        comptes["error" if mot.startswith("error") else mot] += int(n)
    defauts = []
    for m in _ECHEC.finditer(sortie):
        genre, fichier_test, test, raison = m.groups()
        # La trace de CE test : du titre « ___ test ___ » au titre suivant.
        # (« ERROR collecting x.py » quand le module ne s'importe meme pas)
        titre = re.search(rf"_{{3,}} (?:ERROR collecting )?"
                          rf"{re.escape(test or fichier_test)}"
                          rf"(?:\[[^\]]*\])? _{{3,}}", sortie)
        trace = ""
        if titre:
            suite = re.search(r"\n_{3,} ", sortie[titre.end():])
            trace = sortie[titre.end():titre.end() + (suite.start() if suite
                                                      else len(sortie))]
        fichier, ligne = fichier_test, 1
        for f, n in _LIEU.findall(trace):
            if f in fichiers_projet and f != FUMEE:
                fichier, ligne = f, int(n)       # la plus profonde gagne
        message = (f"{'test echoue' if genre == 'FAILED' else 'erreur'} : "
                   f"{test or fichier_test}"
                   + (f" — {raison.strip()[:200]}" if raison else ""))
        defauts.append(Defaut(fichier, ligne, "test-echoue", B, message,
                              NORME, sources=("execution",)))
    return defauts, comptes


# ------------------------------------------------------------- executer
def executer(racine: Path, vus: list[str], *, base_ollama: str = "",
             modele: str = "", decharger=None) -> list[Defaut]:
    """Lance la fumee et les tests du projet dans le conteneur. Rend les
    defauts ; le rapport (lance ou non, et pourquoi) est dans
    `dernier_rapport`, repris par le bilan."""
    global dernier_rapport
    import time
    r = Rapport()
    dernier_rapport = r
    racine = Path(racine)
    python = {f: (racine / f).read_text(encoding="utf-8", errors="replace")
              for f in vus if f.endswith(".py")}
    if not python:
        r.raison = "aucun fichier Python a executer"
        return []
    if os.environ.get("MAEL_SANS_EXECUTION") == "1":
        r.raison = "desactive (MAEL_SANS_EXECUTION=1)"
        return []
    pourquoi = docker_pret()
    if pourquoi:
        r.raison = pourquoi
        return []
    if decharger is not None:
        # Le moteur de MAEL (llama.cpp) s'arrete lui-meme : memoire rendue.
        r.modele_decharge = bool(decharger())
        time.sleep(2)
    elif base_ollama and modele:
        r.modele_decharge = decharger_modele(base_ollama, modele)
        time.sleep(2)                # le temps que la memoire soit rendue
    libre = memoire_libre_go()
    if libre is not None and libre < MEMOIRE_LIBRE_MIN_GO:
        r.raison = (f"memoire insuffisante ({libre:.1f} Go libres, "
                    f"{MEMOIRE_LIBRE_MIN_GO} exiges)")
        return []

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from banc.executeurs import ExecuteurDocker
    debut = time.monotonic()
    code_fumee = fumee(python)
    # Pas de --read-only : `docker cp` ne sait pas ecrire dans un tmpfs, les
    # fichiers du projet n'arriveraient jamais. L'isolement tient a : pas de
    # reseau, memoire / processeur / processus plafonnes, utilisateur sans
    # droits, aucun dossier de l'hote monte, conteneur detruit a la fin.
    options = ("--memory", MEMOIRE_CONTENEUR, "--cpus", "1",
               "--pids-limit", "128", "--tmpfs", "/tmp:size=64m",
               "--env", "PYTHONDONTWRITEBYTECODE=1")
    try:
        with ExecuteurDocker(IMAGE, reseau=False, delai=DELAI_TESTS,
                             options=options, prefixe="mael-tests") as ex:
            for f in python:
                ex.copier(racine / f, f"{TRAVAIL}/{f}")
            if code_fumee:
                with tempfile.TemporaryDirectory() as tmp:
                    chemin = Path(tmp) / FUMEE
                    chemin.write_text(code_fumee, encoding="utf-8")
                    ex.copier(chemin, f"{TRAVAIL}/{FUMEE}")
            res = ex.executer(
                ["sh", "-c", f"cd {TRAVAIL} && DATABASE_URL=sqlite:////tmp/"
                 "test.db python -m pytest -q -rfE --tb=short "
                 "-p no:cacheprovider"], racine=False, delai=DELAI_TESTS)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        r.raison = f"conteneur en panne ({type(exc).__name__})"
        return []
    r.lance = True
    r.secondes = time.monotonic() - debut
    defauts, comptes = lire_pytest(res.stdout + res.stderr, set(python))
    r.passes, r.echoues, r.erreurs = (comptes["passed"], comptes["failed"],
                                      comptes["error"])
    if res.code == 124:
        defauts.append(Defaut(next(iter(python)), 1, "test-echoue", B,
                              f"les tests depassent {DELAI_TESTS} s (boucle "
                              "infinie ?)", NORME, sources=("execution",)))
    return defauts


def limites() -> list[str]:
    r = dernier_rapport
    if r.lance:
        return [f"tests EXECUTES en conteneur sans reseau : {r.passes} "
                f"reussi(s), {r.echoues} echoue(s), {r.erreurs} erreur(s) "
                f"en {r.secondes:.0f} s"]
    if r.raison and r.raison != "aucun fichier Python a executer":
        return [f"tests NON executes — {r.raison} : la justesse du code "
                "Python n'est pas verifiee"]
    return []
