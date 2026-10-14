"""Les TESTS d'un depot existant, executes : avant / apres le correctif.

Point 4.4 de la feuille de route « agent autonome » (12/10/2026). Les
evaluations publiques (SWE-bench) ne lisent pas le correctif : elles
EXECUTENT des tests caches. MAEL doit donc savoir, lui aussi, lancer les
tests d'un depot qu'il n'a pas ecrit, et comparer :
  - REPARES : en echec avant, reussis apres (le ticket est regle) ;
  - REGRESSIONS : reussis avant, en echec apres (le correctif casse) ;
  - TOUJOURS EN ECHEC.

Un depot reel a des DEPENDANCES (requests veut urllib3, astropy numpy...).
Les tests tournent SANS reseau (surete) : l'ENVIRONNEMENT est donc prepare
une fois, avec reseau — une image Docker par depot, nommee d'apres
l'empreinte de ses fichiers de dependances (rien ne change -> reutilisee).

Execution : conteneur jetable, --network none, memoire plafonnee ; le depot
y est COPIE (une archive sans .git, .mael, node_modules) — aucun volume de
l'hote. La lecture de la sortie pytest (statut de chaque test) est pure,
testee sans Docker.

Mode HOTE (MAEL_ESSAIS=hote, 15/10/2026) : pour les machines SANS Docker
(Kaggle). Python seulement : un environnement virtuel par depot (uv), meme
recette d'installation que l'image, range dans MAEL_ENVS ; les tests y
tournent sur une copie du depot, sans reseau si `unshare -rn` est permis
(sinon AVEC reseau). Moins etanche que Docker : reserve aux bancs d'essai
sur une machine jetable.

Etat au 12/10/2026 : Python complet ; recettes Node, Go, Maven, .NET
ecrites mais NON verifiees en vrai (dit par limites()).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .depot import ECARTES, RUNTESTS_DJANGO, Suite, est_django

MEMOIRE = "2g"
# La copie n'emporte pas .git : setuptools_scm (pytest, xarray, astropy...)
# ne trouve plus sa version et « pip install -e . » echoue (Kaggle 15/10,
# pytest-9359). Une version haute : les « >= » des dependances passent.
VERSION_SANS_GIT = "9999.0.0"
DELAI_CONSTRUCTION = 3600         # connexion lente : pip peut etre long
DELAI_TESTS = 900
PYTHONS = ("3.12", "3.11", "3.10", "3.9", "3.8", "3.7", "3.6", "3.5")
# Ce que l'INDEX ignore n'est pas tout ce que la COPIE doit ignorer : bin/,
# env/ et coverage/ sont souvent du code (sympy : bin/isympy, declare dans
# setup.py — sans lui « pip install -e . » echouait, et aucun test sympy ne
# tournait ; banc du 15/10). Le bin/ d'un projet .NET (a cote d'obj/) reste
# ecarte : des binaires compiles.
EXCLUS_COPIE = (ECARTES - {"bin", "env", "coverage"}) | {".git", ".mael"}
# recettes eprouvees EN VRAI (banc du 13/10 : un test qui passe, un qui
# echoue, par langage ; Node : node --test et jest — vitest et mocha lus
# par les tests unitaires seulement)
_VERIFIEES = {"python", "go", "maven", "dotnet", "node"}


# --------------------------------------------------------------- recettes
def sorte(suite: Suite) -> str:
    c = suite.commande[0] if suite.commande else ""
    return {"python": "python", "npm": "node", "go": "go", "mvn": "maven",
            "dotnet": "dotnet"}.get(c, "")


def version_python(lire) -> str:
    """La version de Python du depot : la plus haute que ses classifiers
    annoncent (un vieux depot ne tourne pas sur 3.12), sinon celle que
    requires-python permet, sinon 3.12."""
    texte = (lire("setup.py") or "") + (lire("setup.cfg") or "") + \
        (lire("pyproject.toml") or "")
    annoncees = set(re.findall(
        r"Programming Language :: Python :: (3\.\d+)", texte))
    for v in PYTHONS:
        if v in annoncees:
            return v
    if annoncees:
        # depot plus ancien que nos versions (requests 2016 : 2.6 a 3.5,
        # essai du 12/10 — sur 3.12 son vieux pytest plante) : la plus
        # haute annoncee, les vieilles images python:3.x-slim existent
        return max(annoncees, key=lambda v: int(v.split(".")[1]))
    m = re.search(r"(?:requires-python|python_requires)\s*=\s*['\"]([^'\"]+)",
                  texte)
    if m:
        try:
            from packaging.specifiers import SpecifierSet
            spec = SpecifierSet(m.group(1))
            for v in PYTHONS:
                if v in spec:
                    return v
        except Exception:                               # noqa: BLE001
            pass
    return PYTHONS[0]


def _fichiers_dependances(racine: Path, s: str) -> list[str]:
    noms = {"python": ["setup.py", "setup.cfg", "pyproject.toml",
                       "requirements.txt", "requirements-dev.txt",
                       "requirements_test.txt", "requirements-test.txt",
                       "test-requirements.txt", "dev-requirements.txt",
                       "tox.ini"],
            "node": ["package.json", "package-lock.json", "yarn.lock"],
            "go": ["go.mod", "go.sum"], "maven": ["pom.xml"],
            "dotnet": [p.relative_to(racine).as_posix()
                       for p in racine.rglob("*.csproj")]
            + [p.name for p in racine.glob("*.sln")]}.get(s, [])
    return [n for n in noms if (racine / n).is_file()]


def dockerfile(racine: Path, suite: Suite) -> str:
    """Le Dockerfile de l'environnement, construit avec le depot comme
    contexte (copie sans .git ni .mael)."""
    s = sorte(suite)

    def lire(n):
        try:
            return (racine / n).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    if s == "python":
        v = version_python(lire)
        exigences = [n for n in _fichiers_dependances(racine, s)
                     if n.endswith(".txt")]
        installe = ["pip install --no-cache-dir --timeout 120 --retries 10 "
                    "pytest"]
        installe += [f"pip install --no-cache-dir --timeout 120 --retries 10 "
                     f"-r {n} || true" for n in exigences]
        if (racine / "setup.py").exists() or (racine / "pyproject.toml"
                                              ).exists():
            # avec les extras de test s'ils existent, sinon sans
            installe.append(
                "(pip install --no-cache-dir --timeout 120 --retries 10 "
                "-e '.[test]' || pip install --no-cache-dir --timeout 120 "
                "--retries 10 -e '.[testing]' || pip install --no-cache-dir "
                "--timeout 120 --retries 10 -e .)")
        # les outils de compilation, SI POSSIBLE : les images des vieux
        # Python (3.5 : Debian stretch) ont des depots apt archives — apt
        # echoue (essai du 12/10). Un depot pur Python n'en a pas besoin.
        return (f"FROM python:{v}-slim\n"
                "RUN (apt-get update -qq && apt-get install -y -qq --no-install"
                "-recommends git build-essential >/dev/null && rm -rf "
                "/var/lib/apt/lists/*) || echo 'outils de compilation "
                "indisponibles'\n"
                "WORKDIR /travail\nCOPY . /travail\n"
                f"ENV SETUPTOOLS_SCM_PRETEND_VERSION={VERSION_SANS_GIT}\n"
                f"RUN {' && '.join(installe)}\n"
                "ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1\n")
    if s == "node":
        return ("FROM node:22-slim\nWORKDIR /travail\nCOPY . /travail\n"
                "RUN npm ci || npm install\n")
    if s == "go":
        return ("FROM golang:1.26\nWORKDIR /travail\nCOPY . /travail\n"
                "RUN go mod download && go build ./... || true\n")
    if s == "maven":
        # go-offline ne telecharge PAS le fournisseur de surefire (JUnit 5,
        # resolu au lancement) : on lance les tests une fois, avec le reseau,
        # echecs ignores — tout le necessaire est alors en cache (13/10).
        return ("FROM maven:3.9-eclipse-temurin-21\nWORKDIR /travail\n"
                "COPY . /travail\nRUN mvn -q -B dependency:go-offline test "
                "-Dmaven.test.failure.ignore=true || true\n")
    if s == "dotnet":
        # chaque projet restaure ; les projets de TEST construits
        return ("FROM mcr.microsoft.com/dotnet/sdk:10.0\nWORKDIR /travail\n"
                "COPY . /travail\nRUN for p in $(find . -name '*.csproj'); "
                "do dotnet restore \"$p\" || exit 1; done; for p in "
                f"{_PROJETS_TEST_DOTNET}; do dotnet build \"$p\" --no-restore "
                "|| true; done\n")
    return ""


_PROJETS_TEST_DOTNET = ("$(grep -l -i 'Microsoft.NET.Test.Sdk' "
                        "$(find . -name '*.csproj'))")


# Chaque langage rend un rapport PAR TEST, dans un format standard, entre
# deux marques (13/10/2026) : sans lui, MAEL ne savait que « tout passe » ou
# « quelque chose echoue » — impossible de dire quel test un correctif
# repare ou casse. Le code de sortie de la commande de test est garde.
MARQUE = "=====MAEL-RAPPORT====="


def _sh(commande: str, rapport: str) -> list[str]:
    return ["sh", "-c", f"{commande}; c=$?; echo '{MARQUE}'; {rapport}; "
                        "exit $c"]


def lanceur_node(racine: Path | None) -> str:
    """jest | vitest | mocha | node-test | '' d'apres package.json."""
    try:
        paquet = json.loads((racine / "package.json").read_text(
            encoding="utf-8")) if racine else {}
    except (OSError, ValueError):
        return ""
    script = str((paquet.get("scripts") or {}).get("test", ""))
    deps = {**(paquet.get("dependencies") or {}),
            **(paquet.get("devDependencies") or {})}
    for nom in ("vitest", "jest", "mocha"):
        if nom in script:
            return nom
    if "node --test" in script:
        return "node-test"
    return next((n for n in ("vitest", "jest", "mocha") if n in deps), "")


def commande_hors_ligne(suite: Suite, cibles: list[str],
                        racine: Path | None = None) -> list[str]:
    """La commande de test, sans reseau, limitee aux cibles si possible."""
    s = sorte(suite)
    if s == "python" and est_django(suite):
        # comme SWE-bench : sqlite, un seul processus, un test par ligne
        return ["python", RUNTESTS_DJANGO, "--verbosity", "2",
                "--settings=test_sqlite", "--parallel", "1",
                *dict.fromkeys(libelle_django(c) for c in cibles)]
    if s == "python":
        return ["python", "-m", "pytest", "-v", "-rA", "--tb=short",
                "-p", "no:cacheprovider", *cibles]
    if s == "node":
        c = " ".join(shlex.quote(x) for x in cibles)
        lanceur = lanceur_node(racine)
        if lanceur == "jest":
            return _sh(f"npx jest --ci --json --outputFile=/tmp/mael.json {c}",
                       "cat /tmp/mael.json")
        if lanceur == "vitest":
            return _sh(f"npx vitest run --reporter=json "
                       f"--outputFile=/tmp/mael.json {c}", "cat /tmp/mael.json")
        if lanceur == "mocha":
            return _sh(f"npx mocha --reporter json {c} > /tmp/mael.json",
                       "cat /tmp/mael.json")
        if lanceur == "node-test":
            return _sh(f"node --test --test-reporter=junit "
                       f"--test-reporter-destination=/tmp/mael.xml {c}",
                       "cat /tmp/mael.xml")
        return ["npm", "test", "--", *cibles]
    if s == "go":
        return ["go", "test", "-json", *(cibles or ["./..."])]
    if s == "maven":
        return _sh("mvn -o -B test", "find . -path '*surefire-reports/TEST-*"
                   ".xml' -exec cat {} +")
    if s == "dotnet":
        # chaque projet de TEST (reference a Microsoft.NET.Test.Sdk) ; le
        # code de sortie est le pire des projets
        return _sh(f"e=0; for p in {_PROJETS_TEST_DOTNET}; do dotnet test "
                   "\"$p\" --no-restore --logger 'trx;LogFileName=mael.trx' "
                   "|| e=1; done; (exit $e)",
                   "find . -name mael.trx -exec cat {} +")
    return list(suite.commande)


def _apres_marque(sortie: str) -> str:
    return sortie.split(MARQUE, 1)[1] if MARQUE in sortie else ""


def statuts_go(sortie: str) -> dict[str, str]:
    out: dict[str, str] = {}
    echecs_paquet: set[str] = set()
    for ligne in sortie.splitlines():
        try:
            e = json.loads(ligne)
        except ValueError:
            continue
        action, paquet, test = e.get("Action"), e.get("Package", ""), \
            e.get("Test")
        statut = {"pass": "PASSED", "fail": "FAILED", "skip": "SKIPPED"
                  }.get(action)
        if statut and test:
            out[f"{paquet}::{test}"] = statut
        elif action == "fail" and not test:
            echecs_paquet.add(paquet)
    # un paquet en echec SANS aucun test rendu : il ne compile pas (un
    # paquet dont un test echoue est aussi « fail » : pas une erreur de plus)
    for paquet in echecs_paquet:
        if not any(t.startswith(paquet + "::") for t in out):
            out[paquet] = "ERROR"
    return out


def statuts_junit(xml: str) -> dict[str, str]:
    """JUnit XML (surefire, node --test, ...), un ou plusieurs documents."""
    import xml.etree.ElementTree as ET
    out = {}
    for doc in re.findall(r"<testsuites?\b.*?</testsuites?>", xml, re.S):
        try:
            racine = ET.fromstring(doc)
        except ET.ParseError:
            continue
        for cas in racine.iter("testcase"):
            nom = f"{cas.get('classname', '')}::{cas.get('name', '')}"
            if cas.find("failure") is not None:
                out[nom] = "FAILED"
            elif cas.find("error") is not None:
                out[nom] = "ERROR"
            elif cas.find("skipped") is not None:
                out[nom] = "SKIPPED"
            else:
                out[nom] = "PASSED"
    return out


def statuts_trx(xml: str) -> dict[str, str]:
    out = {}
    for m in re.finditer(r"<UnitTestResult\b[^>]*>", xml):
        balise = m.group(0)
        nom = re.search(r'testName="([^"]*)"', balise)
        issue = re.search(r'outcome="([^"]*)"', balise)
        if nom and issue:
            out[nom.group(1)] = {"Passed": "PASSED", "Failed": "FAILED",
                                 "NotExecuted": "SKIPPED"}.get(
                issue.group(1), "ERROR")
    return out


def statuts_node_json(texte: str) -> dict[str, str]:
    """jest / vitest (testResults[].assertionResults[]) et mocha (passes,
    failures, pending)."""
    debut = texte.find("{")
    try:
        r = json.loads(texte[debut:texte.rfind("}") + 1]) if debut >= 0 else {}
    except ValueError:
        return {}
    out = {}
    for fichier in r.get("testResults") or []:
        nom_f = Path(str(fichier.get("name") or fichier.get("testFilePath")
                         or "")).name
        for a in fichier.get("assertionResults") or []:
            out[f"{nom_f}::{a.get('fullName') or a.get('title')}"] = {
                "passed": "PASSED", "failed": "FAILED", "pending": "SKIPPED",
                "skipped": "SKIPPED", "todo": "SKIPPED"}.get(
                a.get("status"), "ERROR")
    for cle, statut in (("passes", "PASSED"), ("failures", "FAILED"),
                        ("pending", "SKIPPED")):
        for t in r.get(cle) or []:
            out[f"{Path(str(t.get('file', ''))).name}::{t.get('fullTitle')}"] \
                = statut
    return out


def statuts_langage(s: str, sortie: str) -> dict[str, str]:
    """Le rapport par test d'un langage autre que Python."""
    if s == "go":
        return statuts_go(sortie)
    rapport = _apres_marque(sortie)
    if s == "maven":
        return statuts_junit(rapport)
    if s == "dotnet":
        return statuts_trx(rapport)
    if s == "node":
        return (statuts_junit(rapport) if "<testsuite" in rapport
                else statuts_node_json(rapport))
    return {}


def empreinte(racine: Path, suite: Suite) -> str:
    h = hashlib.sha256(dockerfile(racine, suite).encode())
    for n in _fichiers_dependances(racine, sorte(suite)):
        h.update(n.encode() + b"\0" + (racine / n).read_bytes())
    return h.hexdigest()[:12]


def nom_image(racine: Path, suite: Suite) -> str:
    nom = re.sub(r"[^a-z0-9]+", "-", racine.name.lower()).strip("-")[:30]
    return f"mael-depot-{nom or 'depot'}-{empreinte(racine, suite)}"


# ------------------------------------------------------------- la copie
def archive(racine: Path) -> bytes:
    """Le depot en archive tar, sans .git, .mael, dependances, constructions
    — ce qui entre dans le conteneur (ni volume, ni lien vers l'hote)."""
    tampon = io.BytesIO()
    with tarfile.open(fileobj=tampon, mode="w") as t:
        def filtre(info):
            parties = Path(info.name).parts
            if set(parties) & EXCLUS_COPIE:
                return None
            if "bin" in parties and (racine.joinpath(
                    *parties[:parties.index("bin")]) / "obj").is_dir():
                return None                       # sortie de build .NET
            if info.isdir() and (racine / info.name / "pyvenv.cfg").exists():
                return None                       # un environnement virtuel
            if info.issym() or info.islnk():
                return None                       # aucun lien vers l'hote
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            return info
        for p in sorted(racine.iterdir()):
            if p.name in EXCLUS_COPIE:
                continue
            t.add(p, arcname=p.name, filter=filtre)
    return tampon.getvalue()


# ------------------------------------------------------- la sortie pytest
_STATUTS = "PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS|xfail"
_RESUME = re.compile(rf"^({_STATUTS}) (\S+?)(?: - .*)?$", re.M)
# la ligne detaillee (-v), comprise par TOUS les pytest : un vieux pytest
# (requests 2016, essai du 12/10) ne liste pas les reussis dans son resume
_DETAIL = re.compile(rf"^(\S+::\S+) ({_STATUTS})\b", re.M)


def libelle_django(cible: str) -> str:
    """« tests/validators/tests.py[::Classe[::test]] » -> le libelle du
    lanceur de Django : « validators.tests[.Classe[.test]] »."""
    chemin, _, reste = cible.partition("::")
    module = chemin.removeprefix("tests/").removesuffix(".py").replace(
        "/", ".")
    return ".".join([module, *[x for x in reste.split("::") if x]])


_LIGNE_DJANGO = re.compile(r"^([\w.]+) \(([\w.]+)\)(.*)$")
_FIN_DJANGO = re.compile(r"\.\.\. (ok|FAIL|ERROR|skipped|expected failure|"
                         r"unexpected success)\b")
_STATUT_DJANGO = {"ok": "PASSED", "FAIL": "FAILED", "ERROR": "ERROR",
                  "skipped": "SKIPPED", "expected failure": "XFAIL",
                  "unexpected success": "FAILED"}


def statuts_django(sortie: str) -> dict[str, str]:
    """La sortie de `runtests.py --verbosity 2` (unittest) -> les MEMES
    identifiants que pytest : « tests/validators/tests.py::Classe::test ».
    Une ligne de docstring peut s'intercaler avant « ... ok ». Un module
    qui ne s'importe pas (_FailedTest) donne ERROR sur son fichier."""
    out: dict[str, str] = {}
    lignes = sortie.splitlines()
    for k, l in enumerate(lignes):
        m = _LIGNE_DJANGO.match(l)
        if not m:
            continue
        fin = _FIN_DJANGO.search(m.group(3)) or (
            _FIN_DJANGO.search(lignes[k + 1]) if k + 1 < len(lignes)
            else None)
        if not fin:
            continue
        nom, chemin = m.group(1), m.group(2)
        if "_FailedTest" in chemin:
            out[f"tests/{nom.replace('.', '/')}.py"] = "ERROR"
            continue
        parties = chemin.split(".")
        if parties[-1] == nom:                  # Python 3.11+ : Classe.test
            parties = parties[:-1]
        if len(parties) < 2:
            continue
        fichier = "tests/" + "/".join(parties[:-1]) + ".py"
        out[f"{fichier}::{parties[-1]}::{nom}"] = _STATUT_DJANGO[fin.group(1)]
    # le RESUME l'emporte : un sous-test en echec n'apparait que la (essai
    # reel du 15/10, validators : la ligne disait « skipped », le resume
    # « ERROR: test_validators (...) [URLValidator] »)
    for m in _RESUME_DJANGO.finditer(sortie):
        parties = m.group(3).split(".")
        if parties[-1] == m.group(2):
            parties = parties[:-1]
        if len(parties) >= 2 and "_FailedTest" not in m.group(3):
            fichier = "tests/" + "/".join(parties[:-1]) + ".py"
            out[f"{fichier}::{parties[-1]}::{m.group(2)}"] = (
                "FAILED" if m.group(1) == "FAIL" else "ERROR")
    return out


_RESUME_DJANGO = re.compile(r"^(FAIL|ERROR): (\w+) \(([\w.]+)\)", re.M)


def lire_statuts(sortie: str) -> dict[str, str]:
    """Sortie de `pytest -v -rA` -> {identifiant du test : PASSED|FAILED|
    ERROR|...}. Une erreur de COLLECTE (le module ne s'importe pas) donne
    ERROR sur le fichier. Le resume fait foi s'il existe. La sortie du
    lanceur de Django est lue aussi (memes identifiants)."""
    out: dict[str, str] = statuts_django(sortie)
    for test, statut in _DETAIL.findall(sortie):
        out[test] = statut.upper()
    for statut, test in _RESUME.findall(sortie):
        if test.startswith("[") and "]" in test:          # SKIPPED [1] x:12
            continue
        out[test] = statut.upper()
    return out


# ------------------------------------------------------------- resultats
@dataclass
class Environnement:
    image: str = ""
    suite: Suite | None = None
    pret: bool = False
    raison: str = ""
    secondes: float = 0.0
    journal: str = ""
    hote: str = ""            # mode hote : le dossier de l'environnement


@dataclass
class Execution:
    lance: bool = False
    raison: str = ""
    statuts: dict[str, str] = field(default_factory=dict)
    code: int = 0
    sortie: str = ""
    secondes: float = 0.0

    def reussi(self, test: str) -> bool:
        return self.statuts.get(test) in {"PASSED", "XFAIL"}


@dataclass
class Comparaison:
    repares: list[str] = field(default_factory=list)
    regressions: list[str] = field(default_factory=list)
    toujours_en_echec: list[str] = field(default_factory=list)
    nouveaux_en_echec: list[str] = field(default_factory=list)  # absents avant

    @property
    def sans_regression(self) -> bool:
        return not self.regressions


def comparer(avant: Execution, apres: Execution) -> Comparaison:
    c = Comparaison()
    for t, s in sorted(apres.statuts.items()):
        ok_apres = apres.reussi(t)
        if t not in avant.statuts:
            if not ok_apres and s != "SKIPPED":
                c.nouveaux_en_echec.append(t)
            continue
        ok_avant = avant.reussi(t)
        if ok_avant and not ok_apres and s != "SKIPPED":
            c.regressions.append(t)
        elif not ok_avant and ok_apres:
            c.repares.append(t)
        elif not ok_avant and not ok_apres and s != "SKIPPED" \
                and avant.statuts[t] != "SKIPPED":
            c.toujours_en_echec.append(t)
    # un test qui disparait (le module ne s'importe plus) : regression
    for t in avant.statuts:
        if t not in apres.statuts and avant.reussi(t) and apres.lance:
            fichier = t.split("::")[0]
            if apres.statuts.get(fichier) == "ERROR" or not any(
                    x.startswith(fichier) for x in apres.statuts):
                c.regressions.append(t)
    return c


# ---------------------------------------------------------------- Docker
def _docker(args, delai=60, entree: bytes | None = None):
    return subprocess.run(["docker", *args], capture_output=True,
                          timeout=delai, input=entree)


def _texte(octets: bytes) -> str:
    return (octets or b"").decode("utf-8", "replace")


def preparer(racine: Path | str, suite: Suite, *, reseau: bool = True
             ) -> Environnement:
    """Construit (une fois) l'image de l'environnement du depot. Sans
    reseau, seule une image deja construite peut servir."""
    racine = Path(racine)
    if suite.dossier:
        racine = racine / suite.dossier
    env = Environnement(suite=suite)
    if mode_hote():
        return _preparer_hote(racine, suite, env, reseau)
    if not dockerfile(racine, suite):
        env.raison = f"aucune recette pour « {' '.join(suite.commande)} »"
        return env
    env.image = nom_image(racine, suite)
    try:
        if _docker(["version", "--format", "{{.Server.Version}}"],
                   30).returncode:
            env.raison = "Docker ne repond pas (Docker Desktop arrete ?)"
            return env
        if _docker(["image", "inspect", env.image], 30).returncode == 0:
            env.pret = True
            return env
    except (FileNotFoundError, subprocess.TimeoutExpired):
        env.raison = "Docker n'est pas installe ou ne repond pas"
        return env
    if not reseau:
        env.raison = (f"environnement {env.image} absent, et pas de reseau "
                      "pour le construire")
        return env
    debut = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        # le contexte : la copie du depot (sans .git ni .mael) dans un
        # dossier a part, avec le Dockerfile. (Contexte tar par l'entree
        # standard + -f : refuse par Docker, « ambiguous Dockerfile source »,
        # essai du 12/10.)
        contexte = Path(tmp) / "contexte"
        contexte.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive(racine))) as t:
            t.extractall(contexte, filter="data")
        (contexte / "Dockerfile.mael").write_text(dockerfile(racine, suite),
                                                  encoding="utf-8")
        try:
            r = subprocess.run(
                ["docker", "build", "-q", "-t", env.image, "-f",
                 str(contexte / "Dockerfile.mael"), str(contexte)],
                capture_output=True, timeout=DELAI_CONSTRUCTION)
        except subprocess.TimeoutExpired:
            env.raison = f"construction trop longue (> {DELAI_CONSTRUCTION} s)"
            return env
    env.secondes = time.monotonic() - debut
    env.journal = _texte(r.stdout)[-2000:] + _texte(r.stderr)[-3000:]
    if r.returncode:
        env.raison = "la construction de l'environnement a echoue"
        return env
    env.pret = True
    return env


def executer_tests(env: Environnement, racine: Path | str,
                   cibles: list[str] | None = None, *,
                   delai: int = DELAI_TESTS) -> Execution:
    """Lance les tests (les cibles, ou toute la suite) sur l'etat ACTUEL du
    depot, dans un conteneur sans reseau. Les cibles sont relatives au
    dossier de la suite."""
    ex = Execution()
    if not env.pret:
        ex.raison = env.raison or "environnement non prepare"
        return ex
    racine = Path(racine)
    if env.suite and env.suite.dossier:
        racine = racine / env.suite.dossier
    if env.hote:
        return _executer_hote(env, racine, cibles or [], delai, ex)
    nom = f"mael-essai-{hashlib.sha1(str(time.time()).encode()).hexdigest()[:10]}"
    debut = time.monotonic()
    try:
        if _docker(["run", "-d", "--name", nom, "--network", "none",
                    "--memory", MEMOIRE, "--cpus", "2", "--pids-limit", "512",
                    env.image, "sleep", "infinity"], 120).returncode:
            ex.raison = "le conteneur n'a pas demarre"
            return ex
        # l'etat actuel du depot remplace celui de l'image (les fichiers
        # supprimes depuis restent : rare pour un correctif)
        r = _docker(["cp", "-", f"{nom}:/travail"], 600, archive(racine))
        if r.returncode:
            ex.raison = f"copie impossible : {_texte(r.stderr)[:200]}"
            return ex
        commande = commande_hors_ligne(env.suite, cibles or [], racine)
        try:
            r = _docker(["exec", "-w", "/travail", nom, *commande], delai)
            ex.code = r.returncode
            ex.sortie = _texte(r.stdout) + _texte(r.stderr)
        except subprocess.TimeoutExpired:
            ex.code = 124
            ex.raison = f"tests trop longs (> {delai} s)"
        ex.lance = ex.code != 124
        s = sorte(env.suite)
        ex.statuts = lire_statuts(ex.sortie) if s == "python" \
            else statuts_langage(s, ex.sortie)
        if ex.lance and not ex.statuts and MARQUE in ex.sortie:
            # rapport par test VIDE : aucun test n'a tourne. Ce n'est PAS
            # « tout passe » (dotnet sur un projet sans tests rendait 0).
            ex.raison = "aucun test execute (rapport vide)"
        elif ex.lance and not ex.statuts and s != "python":
            # aucun rapport par test lisible : le verdict global, DIT comme tel
            ex.statuts = {" ".join(commande): "PASSED" if ex.code == 0
                          else "FAILED"}
    finally:
        try:
            _docker(["rm", "-f", nom], 60)
        except Exception:                               # noqa: BLE001
            pass
        ex.secondes = time.monotonic() - debut
    return ex


# ------------------------------------------------------------ mode hote
def mode_hote() -> bool:
    return os.environ.get("MAEL_ESSAIS", "").strip().lower() == "hote"


def _racine_envs() -> Path:
    return Path(os.environ.get("MAEL_ENVS") or
                Path(tempfile.gettempdir()) / "mael-envs")


def _python_de(dossier: Path) -> Path:
    return dossier / ("Scripts/python.exe" if os.name == "nt"
                      else "bin/python")


def installations_python(racine: Path) -> list[tuple[list[list[str]], bool]]:
    """La recette de l'image Python (dockerfile) en installations pip :
    (variantes essayees dans l'ordre, obligatoire). Les `-r` qui echouent
    sont tolerees comme dans l'image ; le paquet essaie [test], [testing],
    puis nu."""
    etapes: list[tuple[list[list[str]], bool]] = [([["pytest"]], True)]
    etapes += [([["-r", n]], False) for n in _fichiers_dependances(
        racine, "python") if n.endswith(".txt")]
    if (racine / "setup.py").exists() or (racine / "pyproject.toml").exists():
        etapes.append(([["-e", ".[test]"], ["-e", ".[testing]"],
                        ["-e", "."]], True))
    return etapes


_SANS_RESEAU: list[str] | None = None


def prefixe_sans_reseau() -> list[str]:
    """`unshare -rn` s'il est permis ici (Linux, espaces de noms
    utilisateur), sinon rien : les tests auront le reseau."""
    global _SANS_RESEAU
    if _SANS_RESEAU is None:
        _SANS_RESEAU = []
        if os.name != "nt" and shutil.which("unshare"):
            try:
                if subprocess.run(["unshare", "-rn", "true"],
                                  capture_output=True, timeout=10
                                  ).returncode == 0:
                    _SANS_RESEAU = ["unshare", "-rn"]
            except (OSError, subprocess.TimeoutExpired):
                pass
    return _SANS_RESEAU


def _uv() -> list[str]:
    return ["uv"] if shutil.which("uv") else [sys.executable, "-m", "uv"]


def _preparer_hote(racine: Path, suite: Suite, env: Environnement,
                   reseau: bool) -> Environnement:
    if sorte(suite) != "python":
        env.raison = ("mode hote : seul Python est pris en charge "
                      f"(« {' '.join(suite.commande)} »)")
        return env
    dossier = _racine_envs() / nom_image(racine, suite)
    env.image = dossier.name
    env.hote = str(dossier)
    if (dossier / "PRET").exists():
        env.pret = True
        return env
    if not reseau:
        env.raison = f"environnement {env.image} absent, et pas de reseau"
        return env
    shutil.rmtree(dossier, ignore_errors=True)
    travail = dossier / "travail"
    travail.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive(racine))) as t:
        t.extractall(travail, filter="data")

    def lire(n):
        try:
            return (racine / n).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    version = version_python(lire)
    debut = time.monotonic()
    journal: list[str] = []
    try:
        # uv ne fournit pas les tres vieux Python (3.5, 3.6) : la plus
        # proche au-dessus (Kaggle 15/10, sympy-12236 : « Python 3.5 »)
        proches = [version] + [v for v in reversed(PYTHONS)
                               if int(v.split(".")[1])
                               > int(version.split(".")[1])][:3]
        for version in proches:
            r = subprocess.run([*_uv(), "venv", "--seed", "--python",
                                version, str(dossier / "venv")],
                               capture_output=True, timeout=900)
            journal.append(_texte(r.stdout) + _texte(r.stderr))
            if r.returncode == 0:
                break
        if r.returncode:
            env.raison = f"environnement virtuel impossible (Python {version})"
            env.journal = "\n".join(journal)[-3000:]
            return env
        python = str(_python_de(dossier / "venv"))
        for variantes, obligatoire in installations_python(travail):
            ok = False
            for a in variantes:
                r = subprocess.run(
                    [*_uv(), "pip", "install", "--python", python, *a],
                    capture_output=True, timeout=DELAI_CONSTRUCTION,
                    cwd=travail, env={**os.environ,
                                      "SETUPTOOLS_SCM_PRETEND_VERSION":
                                      VERSION_SANS_GIT})
                journal.append(_texte(r.stdout)[-1000:] +
                               _texte(r.stderr)[-2000:])
                if r.returncode == 0:
                    ok = True
                    break
            if obligatoire and not ok:
                env.raison = ("installation echouee : pip install "
                              f"{' '.join(variantes[-1])}")
                env.journal = "\n".join(journal)[-3000:]
                return env
    except subprocess.TimeoutExpired:
        env.raison = f"construction trop longue (> {DELAI_CONSTRUCTION} s)"
        return env
    env.secondes = time.monotonic() - debut
    env.journal = "\n".join(journal)[-3000:]
    (dossier / "PRET").write_text(version, encoding="utf-8")
    env.pret = True
    return env


def _executer_hote(env: Environnement, racine: Path, cibles: list[str],
                   delai: int, ex: Execution) -> Execution:
    """Comme le conteneur : l'etat actuel du depot est copie PAR-DESSUS le
    dossier de travail de l'environnement (installe en -e), puis pytest y
    tourne."""
    dossier = Path(env.hote)
    travail = dossier / "travail"
    debut = time.monotonic()
    try:
        with tarfile.open(fileobj=io.BytesIO(archive(racine))) as t:
            t.extractall(travail, filter="data")
        commande = commande_hors_ligne(env.suite, cibles, racine)
        commande[0] = str(_python_de(dossier / "venv"))
        variables = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                     "PYTHONUNBUFFERED": "1"}
        variables.pop("PYTHONPATH", None)
        try:
            r = subprocess.run([*prefixe_sans_reseau(), *commande],
                               capture_output=True, timeout=delai,
                               cwd=travail, env=variables)
            ex.code = r.returncode
            ex.sortie = _texte(r.stdout) + _texte(r.stderr)
        except subprocess.TimeoutExpired:
            ex.code = 124
            ex.raison = f"tests trop longs (> {delai} s)"
        ex.lance = ex.code != 124
        ex.statuts = lire_statuts(ex.sortie)
    finally:
        ex.secondes = time.monotonic() - debut
    return ex


# ------------------------------------------ l'exemple du ticket, execute
DELAI_EXEMPLE = 90


def executer_script(env: Environnement, racine: Path | str, code: str, *,
                    delai: int = DELAI_EXEMPLE) -> Execution:
    """Execute un script Python (l'exemple d'un ticket) sur l'etat ACTUEL du
    depot, sans reseau, depuis le dossier de la suite ; `sortie` rend ce
    qu'il a ecrit (la trace d'erreur s'il plante). Seulement pour une suite
    Python."""
    ex = Execution()
    if not env.pret or sorte(env.suite) != "python":
        ex.raison = env.raison or "pas d'environnement Python"
        return ex
    racine = Path(racine)
    if env.suite and env.suite.dossier:
        racine = racine / env.suite.dossier
    debut = time.monotonic()
    try:
        if env.hote:
            dossier = Path(env.hote)
            travail = dossier / "travail"
            with tarfile.open(fileobj=io.BytesIO(archive(racine))) as t:
                t.extractall(travail, filter="data")
            variables = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
            variables.pop("PYTHONPATH", None)
            commande = [*prefixe_sans_reseau(),
                        str(_python_de(dossier / "venv")), "-"]
            try:
                r = subprocess.run(commande, input=code.encode("utf-8"),
                                   capture_output=True, timeout=delai,
                                   cwd=travail, env=variables)
                ex.code, ex.sortie = r.returncode, (_texte(r.stdout)
                                                    + _texte(r.stderr))
            except subprocess.TimeoutExpired:
                ex.code, ex.raison = 124, f"exemple trop long (> {delai} s)"
            ex.lance = ex.code != 124
            return ex
        nom = ("mael-exemple-"
               + hashlib.sha1(str(time.time()).encode()).hexdigest()[:10])
        try:
            if _docker(["run", "-d", "--name", nom, "--network", "none",
                        "--memory", MEMOIRE, "--cpus", "2", "--pids-limit",
                        "512", env.image, "sleep", "infinity"],
                       120).returncode:
                ex.raison = "le conteneur n'a pas demarre"
                return ex
            if _docker(["cp", "-", f"{nom}:/travail"], 600,
                       archive(racine)).returncode:
                ex.raison = "copie impossible"
                return ex
            try:
                r = _docker(["exec", "-i", "-w", "/travail", nom, "python",
                             "-"], delai, code.encode("utf-8"))
                ex.code, ex.sortie = r.returncode, (_texte(r.stdout)
                                                    + _texte(r.stderr))
            except subprocess.TimeoutExpired:
                ex.code, ex.raison = 124, f"exemple trop long (> {delai} s)"
            ex.lance = ex.code != 124
        finally:
            try:
                _docker(["rm", "-f", nom], 60)
            except Exception:                           # noqa: BLE001
                pass
    finally:
        ex.secondes = time.monotonic() - debut
    return ex


# ------------------------------------------------- les tests a relancer
def tests_lies(index, modifies: list[str], maximum: int = 8) -> list[str]:
    """Les fichiers de test qui exercent les fichiers modifies : ceux qui
    importent leur module, ou qui portent leur nom (test_<nom>.py). Un gros
    depot (Django : des milliers de tests) ne se relance pas en entier sur
    8 Go."""
    racine = Path(index.racine)
    cibles = []
    for m in modifies:
        stem = Path(m).stem
        module = m[:-3].replace("/", ".") if m.endswith(".py") else ""
        for f, fi in index.fichiers.items():
            if not fi.test or not f.endswith(".py") or f in cibles:
                continue
            nom = Path(f).stem
            ok = nom in {f"test_{stem}", f"{stem}_test", f"tests_{stem}"}
            if not ok and module:
                try:
                    t = (racine / f).read_text(encoding="utf-8",
                                               errors="replace")
                except OSError:
                    continue
                parties = module.split(".")
                # « from requests.models import » / « import requests.models »
                # / « from requests import models »
                ok = bool(re.search(
                    rf"(?m)^\s*(?:from\s+{re.escape(module)}\s+import|import\s+"
                    rf"{re.escape(module)}\b|from\s+{re.escape('.'.join(parties[:-1]))}"
                    rf"\s+import\s+[^\n]*\b{re.escape(parties[-1])}\b)",
                    t)) if len(parties) > 1 else False
            if ok:
                cibles.append(f)
            if len(cibles) >= maximum:
                return cibles
    return cibles


def limites(suite: Suite | None) -> list[str]:
    if suite and sorte(suite) and sorte(suite) not in _VERIFIEES:
        return [f"recette de test « {sorte(suite)} » ecrite mais pas encore "
                "eprouvee en vrai"]
    return []
