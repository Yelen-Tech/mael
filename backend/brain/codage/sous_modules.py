"""Les SOUS-MODULES git, absents des archives GitHub — 15/10/2026.

L'archive codeload d'un depot laisse les sous-modules VIDES : astropy-6938
(2017) ne peut pas se construire sans astropy_helpers (controle Kaggle du
15/10 : « ENVIRONNEMENT IMPOSSIBLE »). Le clonage git --recurse-submodules
reste exclu (il bloquait sur la connexion du responsable, 12/10). On fait
donc a la main ce que git ferait : le .gitmodules donne les chemins, l'API
GitHub donne le commit exact du gitlink a ce commit du depot, et l'archive
du sous-module se telecharge comme celle du depot.

    completer("astropy/astropy", commit, dossier, archives)
    -> [] si tout est la, sinon les chemins manquants (jamais d'exception :
    un sous-module introuvable ne doit pas perdre le ticket, la note le dit).
"""
from __future__ import annotations

import json
import posixpath
import re
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

_SECTION = re.compile(r'\[submodule "([^"]+)"\]\s*([^[]*)')
_CLE = re.compile(r"^\s*(path|url)\s*=\s*(\S+)\s*$", re.M)
_GITHUB = re.compile(r"(?:github\.com[:/])([\w.-]+/[\w.-]+?)(?:\.git)?$")


def lire_gitmodules(dossier: Path) -> list[tuple[str, str]]:
    """Les (chemin, url) declares par le .gitmodules du depot ; [] s'il n'y
    en a pas (le cas de presque tous les depots : cout nul)."""
    try:
        texte = (dossier / ".gitmodules").read_text(encoding="utf-8",
                                                    errors="replace")
    except OSError:
        return []
    couples = []
    for _, corps in _SECTION.findall(texte):
        cles = dict(_CLE.findall(corps))
        if "path" in cles and "url" in cles:
            couples.append((cles["path"], cles["url"]))
    return couples


def _depot_de(url: str, repo: str) -> str | None:
    """L'« owner/depot » GitHub du sous-module : absolue (https, ssh, git) ou
    relative au depot parent (« ../astropy_helpers.git », astropy 2017)."""
    m = _GITHUB.search(url)
    if m:
        return m.group(1)
    if url.startswith(("./", "../")):
        resolu = posixpath.normpath(posixpath.join(repo, url))
        parties = resolu.split("/")
        if len(parties) == 2 and all(parties):
            return "/".join(p.removesuffix(".git") for p in parties)
    return None


def _gitlink(repo: str, commit: str, chemin: str) -> str | None:
    """Le commit exact du sous-module a ce commit du depot (l'archive ne le
    contient pas : il est dans l'arbre git, visible par l'API)."""
    url = (f"https://api.github.com/repos/{repo}/contents/{chemin}"
           f"?ref={commit}")
    for essai in range(3):
        r = subprocess.run(["curl", "-sfL", "--max-time", "60",
                            "-H", "Accept: application/vnd.github+json",
                            "-H", "User-Agent: mael", url],
                           capture_output=True, text=True)
        if r.returncode == 0:
            try:
                d = json.loads(r.stdout)
            except json.JSONDecodeError:
                return None
            return d.get("sha") if isinstance(d, dict) else None
        time.sleep(10 * (essai + 1))
    return None


def _telecharger(depot: str, sha: str, archives: Path) -> Path | None:
    """L'archive du sous-module, gardee en cache comme celles des depots
    (banc_depot.telecharger) : .part puis renommage, 5 essais."""
    cible = archives / depot.replace("/", "__") / f"{sha}.tar.gz"
    if cible.exists() and cible.stat().st_size > 0:
        return cible
    cible.parent.mkdir(parents=True, exist_ok=True)
    tmp = cible.with_suffix(".part")
    url = f"https://codeload.github.com/{depot}/tar.gz/{sha}"
    for essai in range(5):
        r = subprocess.run(["curl", "-sfL", "--max-time", "900", "-o",
                            str(tmp), url], capture_output=True)
        if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            tmp.replace(cible)
            return cible
        time.sleep(20 * (essai + 1))
    return None


def _extraire_dans(archive: Path, cible: Path) -> None:
    """Extrait l'archive du sous-module dans son chemin (filtre « data »,
    dossier de tete retire), sans toucher au reste du depot."""
    if cible.exists():
        shutil.rmtree(cible)
    cible.mkdir(parents=True)
    with tarfile.open(archive) as t:
        membres = []
        for m in t.getmembers():
            parties = m.name.split("/", 1)
            if len(parties) < 2 or not parties[1]:
                continue
            m.name = parties[1]
            membres.append(m)
        t.extractall(cible, members=membres, filter="data")


def completer(repo: str, commit: str, dossier: Path,
              archives: Path) -> list[str]:
    """Telecharge les sous-modules declares, au commit exact du gitlink, dans
    leur chemin. Renvoie les chemins MANQUANTS ([] si tout est la) — jamais
    d'exception : un sous-module introuvable est dit, le ticket continue."""
    manquants = []
    for chemin, url in lire_gitmodules(dossier):
        cible = dossier / chemin
        if cible.exists() and any(cible.iterdir()):
            continue                            # deja complete (reprise)
        depot = _depot_de(url, repo)
        sha = _gitlink(repo, commit, chemin) if depot else None
        archive = _telecharger(depot, sha, archives) if sha else None
        if archive is None:
            manquants.append(chemin)
            continue
        try:
            _extraire_dans(archive, cible)
        except (OSError, tarfile.TarError):
            manquants.append(chemin)
    return manquants
