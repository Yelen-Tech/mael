"""La FRAICHEUR du savoir-faire : un savoir perime est un PROBLEME.

Consigne du responsable (08/10/2026) : « il faut que le savoir-faire soit
recent, sinon il y a un probleme ». Le jour meme, la verification en ligne
l'a montre : pytest etait en 9.1.1 alors que le conteneur de tests de MAEL
l'enfermait en version 8 ; PHP en 8.5.11 pour un 8.4.26 installe le matin.

Donc : aucun numero de version ecrit en dur dans les fiches. MAEL verifie :

  - EN LIGNE (mael code --rafraichir-savoir) : chaque source citee repond ;
    la derniere version de chaque dependance suivie (PyPI, npm, php.net),
    comparee a ce que MAEL utilise vraiment (plages du Dockerfile de tests,
    outils installes) ; le resultat va dans savoir_faire/fraicheur.json ;
  - HORS LIGNE, a chaque usage : la date de revue de chaque fiche, l'age de
    la derniere verification en ligne, et les problemes qu'elle a notes.

Une fiche dont la date de revue est passee, ou dont la source a disparu,
n'est PLUS donnee au modele (elle enseignerait du perime) : elle est
signalee comme probleme (bilan, BESOINS-DE-MAEL.md).
"""
from __future__ import annotations

import json
import re
import ssl
import subprocess
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .emplacements import trouver

DOSSIER = Path(__file__).parent / "savoir_faire"
FICHIER = DOSSIER / "fraicheur.json"
DOCKERFILE = Path(__file__).parent / "conteneur" / "Dockerfile.python"
JOURS_MAX = 30          # au-dela, le savoir n'a pas ete reverifie : probleme
DELAI = 60              # s par requete (connexion lente)

# Les dependances suivies : ou lire leur derniere version.
SUIVIES = {
    "flask": "pypi", "pytest": "pypi", "sqlalchemy": "pypi",
    "fastapi": "pypi", "httpx": "pypi",
    "eslint": "npm", "stylelint": "npm", "html-validate": "npm",
    "php": "php.net",
}


@dataclass
class Releve:
    date: str = ""
    versions: dict = field(default_factory=dict)     # nom -> derniere
    utilisees: dict = field(default_factory=dict)    # nom -> ce que MAEL a
    problemes: list = field(default_factory=list)    # textes
    sources_mortes: list = field(default_factory=list)


def charger(chemin: Path | None = None) -> Releve:
    try:
        d = json.loads(Path(chemin or FICHIER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Releve()
    return Releve(**{k: d.get(k, v) for k, v in Releve().__dict__.items()})


def age_jours(r: Releve, aujourd_hui: date | None = None) -> int | None:
    if not r.date:
        return None
    return ((aujourd_hui or date.today()) - date.fromisoformat(r.date)).days


# ------------------------------------------------ ce que MAEL utilise
def plages_du_conteneur(texte: str | None = None) -> dict[str, str]:
    """« pytest>=9,<10 » dans le Dockerfile de tests -> {"pytest": ">=9,<10"}."""
    if texte is None:
        try:
            texte = DOCKERFILE.read_text(encoding="utf-8")
        except OSError:
            return {}
    return {m.group(1).lower(): m.group(2)
            for m in re.finditer(r'"([A-Za-z0-9_-]+)((?:[<>=!]=?[0-9.]+,?)+)"',
                                 texte)}


def _version_outil(nom: str) -> str:
    exe = trouver(nom)
    if not exe:
        return ""
    try:
        r = subprocess.run([exe, "-v" if nom == "php" else "--version"],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"(\d+\.\d+\.\d+)", r.stdout + r.stderr)
    return m.group(1) if m else ""


def _tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def dans_la_plage(version: str, plage: str) -> bool:
    v = _tuple(version)
    for borne in plage.split(","):
        m = re.match(r"(>=|<=|==|<|>)([0-9.]+)", borne.strip())
        if not m:
            continue
        op, b = m.group(1), _tuple(m.group(2))
        ok = {">=": v >= b, "<=": v <= b, "==": v[:len(b)] == b,
              "<": v < b, ">": v > b}[op]
        if not ok:
            return False
    return True


def comparer(nom: str, derniere: str, utilisee: str) -> str:
    """Le probleme, ou "" si MAEL est a jour."""
    if not derniere:
        return ""
    if SUIVIES[nom] == "pypi":
        if utilisee and not dans_la_plage(derniere, utilisee):
            return (f"{nom} {derniere} est sorti, le conteneur de tests "
                    f"l'enferme en {utilisee} (Dockerfile.python a mettre a "
                    "jour, puis reconstruire l'image)")
        return ""
    if not utilisee:
        return f"{nom} {derniere} n'est pas installe"
    a, b = _tuple(derniere), _tuple(utilisee)
    profondeur = 2 if SUIVIES[nom] == "php.net" else 1   # php : 8.4 -> 8.5
    if a[:profondeur] > b[:profondeur]:
        return f"{nom} {derniere} est sorti, MAEL utilise {utilisee}"
    return ""


# ---------------------------------------------------- la verification
def _lire_url(url: str) -> bytes:
    # Le magasin de certificats du systeme : la connexion passe par un
    # filtre TLS que Windows connait (memoire du chantier Android).
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "MAEL"})
    with urllib.request.urlopen(req, timeout=DELAI, context=ctx) as r:
        return r.read()


def derniere_version(nom: str) -> str:
    registre = SUIVIES[nom]
    if registre == "pypi":
        return json.loads(_lire_url(f"https://pypi.org/pypi/{nom}/json"))[
            "info"]["version"]
    if registre == "npm":
        return json.loads(_lire_url(
            f"https://registry.npmjs.org/{nom}/latest"))["version"]
    rel = json.loads(_lire_url(
        "https://windows.php.net/downloads/releases/releases.json"))
    return max((v["version"] for v in rel.values()), key=_tuple)


def rafraichir(sources: list[str], annoncer=lambda _m: None,
               chemin: Path | None = None) -> Releve:
    r = Releve(date=date.today().isoformat())
    plages = plages_du_conteneur()
    for nom, registre in SUIVIES.items():
        r.utilisees[nom] = (plages.get(nom, "") if registre == "pypi"
                            else _version_outil(nom))
        try:
            r.versions[nom] = derniere_version(nom)
        except Exception as exc:                       # noqa: BLE001
            r.problemes.append(f"{nom} : derniere version illisible "
                               f"({type(exc).__name__})")
            continue
        probleme = comparer(nom, r.versions[nom], r.utilisees[nom])
        annoncer(f"{nom} : derniere {r.versions[nom]}, MAEL "
                 f"{r.utilisees[nom] or '—'}"
                 + (f" — PROBLEME : {probleme}" if probleme else ""))
        if probleme:
            r.problemes.append(probleme)
    for url in sources:
        try:
            _lire_url(url)
        except Exception as exc:                       # noqa: BLE001
            r.sources_mortes.append(url)
            annoncer(f"source introuvable : {url} ({type(exc).__name__})")
    Path(chemin or FICHIER).write_text(json.dumps(
        r.__dict__, ensure_ascii=False, indent=1), encoding="utf-8")
    return r


def problemes_hors_ligne(r: Releve, aujourd_hui: date | None = None
                         ) -> list[str]:
    """Ce qui ne va pas, sans Internet : verification trop vieille, ou
    problemes notes par la derniere verification."""
    age = age_jours(r, aujourd_hui)
    out = []
    if age is None:
        out.append("savoir-faire JAMAIS verifie en ligne (mael code "
                   "--rafraichir-savoir)")
    elif age > JOURS_MAX:
        out.append(f"savoir-faire verifie il y a {age} jours (plus de "
                   f"{JOURS_MAX}) : a reverifier en ligne")
    out += r.problemes
    out += [f"source introuvable : {u}" for u in r.sources_mortes]
    return out
