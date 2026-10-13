"""`mael installer` : MAEL et son MOTEUR en une commande (13/10/2026).

Demande du responsable : sur la machine qui fera tourner MAEL (un PC, un
serveur, une machine a cartes graphiques), une seule commande doit poser le
moteur llama.cpp ET le modele — sans qu'on ait a savoir ce qu'est un .gguf.

Le modele s'appelle MAEL-Coder : c'est Qwen3-Coder-30B-A3B-Instruct (Alibaba
Qwen, Apache-2.0), en version COMPRESSEE (Q4_K_M, ~18,6 Go) — ni entraine,
ni modifie par Yelen Tech. La licence exige qu'on le dise : la carte du
modele est posee a cote du fichier, et la commande l'annonce AVANT de
telecharger. Rien ne se telecharge sans accord (ou --oui, ecrit par celui
qui lance).

Surete :
  - sources FIGEES : depot et revision exacte sur Hugging Face, version
    exacte de llama.cpp sur GitHub ; empreinte sha256 relevee le 13/10/2026 ;
    un fichier dont l'empreinte differe est DETRUIT, jamais utilise ;
  - HTTPS seulement ; reprise apres coupure (en-tete Range) ;
  - espace disque verifie avant ; memoire verifiee (on previent) ;
  - archive du moteur extraite sans sortir de son dossier.
"""
from __future__ import annotations

import hashlib
import json
import platform
import shutil
import tarfile
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx

from brain.backends.llamacpp import _racine_mael

Go = 10 ** 9                   # Go decimaux, comme Hugging Face (18,6 Go)


@dataclass(frozen=True)
class Fichier:
    url: str
    nom: str
    taille: int
    sha256: str


@dataclass(frozen=True)
class ModeleCatalogue:
    nom: str                      # ce que l'utilisateur voit
    fichier_local: str
    base: str                     # le modele d'origine (licence : le dire)
    licence: str
    compression: str
    source: Fichier
    milliards: float
    actifs: float                 # parametres actifs par jeton (MoE)
    memoire_min: int              # octets pour tourner (modele + contexte)


# Releves du 13/10/2026 (API Hugging Face, champ lfs.oid = sha256).
_REV_QWEN = "b17cb02dd882d5b6ab62fc777ad2995f19668350"
CATALOGUE = {
    "mael-coder": ModeleCatalogue(
        nom="MAEL-Coder",
        fichier_local="mael-coder.gguf",
        base="Qwen/Qwen3-Coder-30B-A3B-Instruct",
        licence="Apache-2.0",
        compression="Q4_K_M (GGUF, unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF)",
        source=Fichier(
            url=("https://huggingface.co/unsloth/Qwen3-Coder-30B-A3B-"
                 f"Instruct-GGUF/resolve/{_REV_QWEN}/Qwen3-Coder-30B-A3B-"
                 "Instruct-Q4_K_M.gguf"),
            nom="Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf",
            taille=18_556_689_568,
            sha256=("fadc3e5f8d42bf7e894a785b05082e47daee4df26680389817e2093"
                    "056f088ad")),
        milliards=30.5, actifs=3.3, memoire_min=22 * Go),
}
DEFAUT = "mael-coder"

# llama.cpp b11122 (23/09/2026) : le moteur deja eprouve par MAEL sur le
# portable du responsable. Empreintes : champ « digest » de l'API GitHub.
VERSION_MOTEUR = "b11122"
_GH = (f"https://github.com/ggml-org/llama.cpp/releases/download/"
       f"{VERSION_MOTEUR}/")
MOTEURS = {
    ("Windows", "cpu"): [Fichier(
        _GH + "llama-b11122-bin-win-cpu-x64.zip",
        "llama-b11122-bin-win-cpu-x64.zip", 18_558_409,
        "025c69d8f974852457d20460273ce927cf6c219c6f5ba4720a8d46d4d42c9a3a")],
    ("Windows", "cuda"): [
        Fichier(_GH + "llama-b11122-bin-win-cuda-12.4-x64.zip",
                "llama-b11122-bin-win-cuda-12.4-x64.zip", 253_782_395,
                "c4904021c2314542d717093bf645abbde6a31f8424d39dd365536d32"
                "1138f1d9"),
        Fichier(_GH + "cudart-llama-bin-win-cuda-12.4-x64.zip",
                "cudart-llama-bin-win-cuda-12.4-x64.zip", 391_443_627,
                "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7"
                "e32ae1d6")],
    ("Linux", "cpu"): [Fichier(
        _GH + "llama-b11122-bin-ubuntu-x64.tar.gz",
        "llama-b11122-bin-ubuntu-x64.tar.gz", 16_998_046,
        "103ecf52ebc8720358384f17c379f64f2b88f7b24c3791537016ae92a269d6f6")],
    ("Linux", "cuda"): [
        Fichier(_GH + "llama-b11122-bin-ubuntu-cuda-12.8-x64.tar.gz",
                "llama-b11122-bin-ubuntu-cuda-12.8-x64.tar.gz", 168_870_879,
                "c194a0704987c5e0878b3acaaed3913619328f48db8ab3c2c81ed99f"
                "3be9a400"),
        Fichier(_GH + "cudart-llama-b11122-bin-ubuntu-cuda-12.8-x64.tar.gz",
                "cudart-llama-b11122-bin-ubuntu-cuda-12.8-x64.tar.gz",
                594_373_573,
                "f9f30f1c8b7254a7ffde088fa1ff0713a612a6bebebb4771f7e54fda"
                "46ca5b45")],
}


class InstallationImpossible(RuntimeError):
    """Une phrase claire, et ce qu'il faut faire."""


# ------------------------------------------------------------------ plan
@dataclass
class Plan:
    modele: ModeleCatalogue | None
    moteur: list[Fichier]
    acceleration: str                     # "cpu" | "cuda"
    dossier: Path
    deja: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)

    @property
    def a_telecharger(self) -> int:
        n = sum(f.taille for f in self.moteur)
        if self.modele and self.modele.nom not in self.deja:
            n += self.modele.source.taille
        return n

    def lignes(self) -> list[str]:
        l = [f"Dossier : {self.dossier}"]
        if self.moteur:
            l.append(f"Moteur  : llama.cpp {VERSION_MOTEUR} "
                     f"({self.acceleration}) — {_go(sum(f.taille for f in self.moteur))}")
        if self.modele:
            m = self.modele
            etat = ("deja installe" if m.nom in self.deja
                    else _go(m.source.taille))
            l += [f"Modele  : {m.nom} — {etat}",
                  f"          = {m.base} ({m.licence}), compresse "
                  f"{m.compression.split(' ')[0]}",
                  f"          {m.milliards:g} milliards de parametres, "
                  f"{m.actifs:g} actifs par jeton ; memoire conseillee "
                  f"{_go(m.memoire_min)}",
                  f"          source : {m.source.url.split('/resolve/')[0]}"]
        l.append(f"A telecharger : {_go(self.a_telecharger)} "
                 "(empreinte sha256 verifiee)")
        return l + [f"Attention : {a}" for a in self.avertissements]


def _go(octets: int) -> str:
    return f"{octets / Go:.1f} Go" if octets >= Go / 10 else \
        f"{octets / 10 ** 6:.0f} Mo"


def installe(racine: Path | None = None) -> dict:
    """Ce que `mael installer` a pose : {} si rien."""
    try:
        return json.loads(((racine or _racine_mael()) / "installe.json"
                           ).read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def preparer(nom: str = DEFAUT, acceleration: str = "", moteur: bool = True,
             modele: bool = True, systeme: str = "",
             dossier: Path | None = None) -> Plan:
    from brain import machine
    systeme = systeme or platform.system()
    if nom not in CATALOGUE:
        raise InstallationImpossible(
            f"modele « {nom} » inconnu (catalogue : {', '.join(CATALOGUE)})")
    if not acceleration:
        acceleration = "cuda" if machine.carte_graphique() else "cpu"
    if moteur and (systeme, acceleration) not in MOTEURS:
        raise InstallationImpossible(
            f"pas de moteur llama.cpp prevu pour {systeme}/{acceleration} : "
            "installer llama-server a la main et le designer par "
            "BRAIN_LLAMA_SERVEUR")
    racine = dossier or _racine_mael()
    plan = Plan(CATALOGUE[nom] if modele else None,
                MOTEURS[(systeme, acceleration)] if moteur else [],
                acceleration, racine)
    deja = installe(racine)
    if plan.modele and deja.get("modele") == plan.modele.nom and (
            racine / "modeles" / plan.modele.fichier_local).exists():
        plan.deja.append(plan.modele.nom)
    if plan.moteur and deja.get("moteur") == f"{VERSION_MOTEUR}-{acceleration}" \
            and (racine / "moteur" / f"llama-{VERSION_MOTEUR}").exists():
        plan.moteur = []
    if plan.modele:
        totale, _ = machine.memoire()
        vram = (machine.carte_graphique() or ("", 0))[1]
        if totale and max(totale, vram) < plan.modele.memoire_min:
            plan.avertissements.append(
                f"cette machine a {_go(totale)} de memoire : {plan.modele.nom} "
                f"en demande {_go(plan.modele.memoire_min)}. Il tournera "
                "tres lentement, ou pas du tout.")
    return plan


# ----------------------------------------------------------- telechargement
def telecharger(f: Fichier, destination: Path, client: httpx.Client,
                progression=None) -> Path:
    """Telecharge `f` vers `destination`, en reprenant un .partiel ; verifie
    l'empreinte ; detruit un fichier faux."""
    if not f.url.startswith("https://"):
        raise InstallationImpossible(f"{f.url} : HTTPS exige")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partiel = destination.with_name(destination.name + ".partiel")
    deja = partiel.stat().st_size if partiel.exists() else 0
    if deja > f.taille:
        partiel.unlink()
        deja = 0
    if deja < f.taille:
        entetes = {"Range": f"bytes={deja}-"} if deja else {}
        with client.stream("GET", f.url, headers=entetes,
                           follow_redirects=True) as r:
            if r.status_code == 200 and deja:
                deja = 0                      # le serveur ignore Range
            elif r.status_code not in (200, 206):
                raise InstallationImpossible(
                    f"{f.nom} : le serveur repond {r.status_code}")
            with open(partiel, "ab" if deja else "wb") as sortie:
                for bloc in r.iter_bytes(1024 * 1024):
                    sortie.write(bloc)
                    deja += len(bloc)
                    if progression:
                        progression(f.nom, deja, f.taille)
    if empreinte(partiel) != f.sha256:
        partiel.unlink(missing_ok=True)
        raise InstallationImpossible(
            f"{f.nom} : empreinte FAUSSE — fichier detruit. Relancer ; si "
            "cela se repete, la source a change : ne pas forcer.")
    partiel.replace(destination)
    return destination


def empreinte(chemin: Path) -> str:
    h = hashlib.sha256()
    with open(chemin, "rb") as e:
        for bloc in iter(lambda: e.read(4 * 1024 * 1024), b""):
            h.update(bloc)
    return h.hexdigest()


def extraire(archive: Path, cible: Path) -> None:
    """Archive du moteur -> cible, sans qu'un chemin n'en sorte."""
    cible.mkdir(parents=True, exist_ok=True)
    racine = cible.resolve()
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for membre in z.namelist():
                if not (cible / membre).resolve().is_relative_to(racine):
                    raise InstallationImpossible(
                        f"{archive.name} : chemin hors du dossier ({membre})")
            z.extractall(cible)
    else:
        with tarfile.open(archive) as t:
            t.extractall(cible, filter="data")     # refuse les evasions
    # les archives Linux rangent tout dans un sous-dossier : on l'aplatit
    serveurs = list(cible.rglob("llama-server*"))
    if serveurs and serveurs[0].parent != cible:
        for p in list(serveurs[0].parent.iterdir()):
            if not (cible / p.name).exists():
                shutil.move(str(p), cible / p.name)
    for s in cible.glob("llama-server*"):
        s.chmod(s.stat().st_mode | 0o111)


def carte(m: ModeleCatalogue) -> str:
    """La carte du modele : ce qu'il est vraiment, et sa licence."""
    return "\n".join([
        f"# {m.nom}", "",
        f"{m.nom} est le moteur conseille de MAEL. Ce n'est PAS un modele "
        "entraine par Yelen Tech :",
        f"c'est **{m.base}** (Alibaba Qwen, licence {m.licence}), utilise "
        "tel quel,",
        f"en version compressee {m.compression}.", "",
        "Ce que MAEL ajoute est autour du modele : juges, reparation, "
        "verification, outils.", "",
        f"- Modele d'origine : https://huggingface.co/{m.base}",
        f"- Licence : {m.licence} — https://www.apache.org/licenses/"
        "LICENSE-2.0",
        f"- Fichier : {m.source.nom}",
        f"- Empreinte sha256 : {m.source.sha256}",
        f"- Source : {m.source.url}", ""])


def installer(plan: Plan, client: httpx.Client | None = None,
              progression=None) -> dict:
    libre = shutil.disk_usage(plan.dossier if plan.dossier.exists()
                              else plan.dossier.anchor or "/").free
    if plan.a_telecharger * 1.1 > libre:
        raise InstallationImpossible(
            f"espace disque insuffisant : {_go(plan.a_telecharger)} a "
            f"telecharger, {_go(libre)} libres")
    propre = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(60, connect=20))
    etat = installe(plan.dossier)
    try:
        if plan.moteur:
            dossier_moteur = plan.dossier / "moteur" / f"llama-{VERSION_MOTEUR}"
            for f in plan.moteur:
                archive = telecharger(f, plan.dossier / "telechargements" /
                                      f.nom, client, progression)
                extraire(archive, dossier_moteur)
                archive.unlink(missing_ok=True)
            etat["moteur"] = f"{VERSION_MOTEUR}-{plan.acceleration}"
        if plan.modele and plan.modele.nom not in plan.deja:
            m = plan.modele
            telecharger(m.source, plan.dossier / "modeles" / m.fichier_local,
                        client, progression)
            (plan.dossier / "modeles" / "MAEL-Coder.md").write_text(
                carte(m), encoding="utf-8")
            etat.update({"modele": m.nom, "fichier": m.fichier_local,
                         "base": m.base, "licence": m.licence,
                         "sha256": m.source.sha256,
                         "milliards": m.milliards})
    finally:
        if propre:
            client.close()
    etat["date"] = date.today().isoformat()
    plan.dossier.mkdir(parents=True, exist_ok=True)
    (plan.dossier / "installe.json").write_text(
        json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
    return etat
