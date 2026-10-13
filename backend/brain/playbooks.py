"""Playbooks de correction (etape 2.6) : chargement, scellement, execution.

Un playbook = backend/playbooks/<couche>/<nom>/ : manifest.yaml + detecter.sh,
appliquer.sh (--simulation), verifier.sh, revenir.sh. Le modele CHOISIT un
playbook et ses parametres viennent de la fiche ; il n'ecrit jamais de script.

Validation securisee :
  - SCEAU : l'empreinte SHA-256 de chaque script (et de la bibliotheque
    commune) est figee dans playbooks/sceau.json. Un script modifie sans
    re-scellement explicite n'est JAMAIS execute ;
  - PARAMETRES : verifies contre le motif du manifeste (fullmatch), puis
    passes en arguments (liste argv, sans shell) : aucune interpretation ;
  - la simulation est obligatoire avant l'application (cf. terminal
    /corriger), la confirmation se fait par un code a retaper.

    python -m brain.playbooks            # etat du sceau
    python -m brain.playbooks --sceller  # (re)sceller apres relecture
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parents[1] / "playbooks"
SCEAU = RACINE / "sceau.json"
COMMUN = RACINE / "_commun" / "mael.sh"
ETAPES = ("detecter", "appliquer", "verifier", "revenir")


@dataclass
class Playbook:
    id: str
    dossier: Path
    manifeste: dict = field(default_factory=dict)

    @property
    def parametres(self) -> list[dict]:
        return list(self.manifeste.get("parametres") or [])

    def script(self, etape: str) -> Path:
        return self.dossier / f"{etape}.sh"

    def fichiers(self) -> list[Path]:
        return [self.dossier / "manifest.yaml", *(self.script(e) for e in ETAPES)]


@lru_cache(maxsize=1)
def tous() -> dict[str, Playbook]:
    pbs = {}
    for manifeste in sorted(RACINE.glob("*/*/manifest.yaml")):
        donnees = yaml.safe_load(manifeste.read_text(encoding="utf-8")) or {}
        pbs[donnees["id"]] = Playbook(donnees["id"], manifeste.parent, donnees)
    return pbs


def obtenir(pid: str) -> Playbook | None:
    return tous().get(pid)


# --------------------------------------------------------------------------- #
# Sceau
# --------------------------------------------------------------------------- #
def _empreinte(chemin: Path) -> str:
    # Fin de ligne neutralisee : le meme script extrait sous Windows (CRLF) ou
    # Linux (LF) a la meme empreinte.
    return hashlib.sha256(chemin.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def calculer_sceau() -> dict[str, dict[str, str]]:
    sceau = {"_commun": {"mael.sh": _empreinte(COMMUN)}}
    for pid, pb in tous().items():
        sceau[pid] = {f.name: _empreinte(f) for f in pb.fichiers() if f.exists()}
    return sceau


def sceller() -> dict:
    sceau = calculer_sceau()
    SCEAU.write_text(json.dumps(sceau, indent=1, sort_keys=True) + "\n",
                     encoding="utf-8")
    return sceau


def controler_sceau(pid: str) -> list[str]:
    """Fichiers modifies, ajoutes ou manquants par rapport au sceau (vide =
    intact). Sans sceau : tout est refuse."""
    if not SCEAU.exists():
        return ["sceau.json absent : playbooks non scelles"]
    sceau = json.loads(SCEAU.read_text(encoding="utf-8"))
    pb = obtenir(pid)
    if pb is None:
        return [f"playbook {pid} inconnu"]
    attendu = sceau.get(pid)
    if attendu is None:
        return [f"{pid} absent du sceau"]
    alteres = []
    for f in pb.fichiers():
        if not f.exists():
            alteres.append(f"{f.name} manquant")
        elif attendu.get(f.name) != _empreinte(f):
            alteres.append(f"{f.name} modifie")
    if sceau.get("_commun", {}).get("mael.sh") != _empreinte(COMMUN):
        alteres.append("_commun/mael.sh modifie")
    return alteres


# --------------------------------------------------------------------------- #
# Parametres et execution
# --------------------------------------------------------------------------- #
def valider_parametres(pid: str, parametres: dict,
                       complet: bool = True) -> list[str]:
    """complet=False (schema des fiches) : seuls les parametres fournis sont
    controles ; un parametre de contexte (ex. domaine du site) est donne a
    l'execution. complet=True (execution) : les requis doivent y etre."""
    pb = obtenir(pid)
    if pb is None:
        return [f"playbook « {pid} » introuvable"]
    erreurs = []
    connus = {p["nom"] for p in pb.parametres}
    for inconnu in sorted(set(parametres or {}) - connus):
        erreurs.append(f"parametre inconnu « {inconnu} »")
    for p in pb.parametres:
        valeur = (parametres or {}).get(p["nom"], p.get("defaut"))
        if valeur is None:
            if p.get("requis") and complet:
                erreurs.append(f"parametre « {p['nom']} » requis")
            continue
        motif = p.get("motif")
        if motif and not re.fullmatch(motif, str(valeur)):
            erreurs.append(f"parametre « {p['nom']} » invalide : {valeur!r}")
    return erreurs


def arguments(pid: str, etape: str, parametres: dict,
              simulation: bool = False) -> list[str]:
    """Arguments du script, dans l'ordre du manifeste. detecter/revenir ne
    prennent que la cle de l'etat : le 1er parametre, ou ceux que le
    manifeste nomme (« parametres_revenir ») quand l'etat depend de
    plusieurs (sinon revenir.sh s'arreterait faute d'argument)."""
    pb = obtenir(pid)
    noms = [p["nom"] for p in pb.parametres]
    if etape == "revenir" and pb.manifeste.get("parametres_revenir"):
        noms = list(pb.manifeste["parametres_revenir"])
    elif etape in {"detecter", "revenir"}:
        noms = noms[:1]
    defauts = {p["nom"]: p.get("defaut", "") for p in pb.parametres}
    valeurs = [str(parametres.get(n, defauts[n])) for n in noms]
    return (["--simulation"] if simulation and etape == "appliquer" else []) \
        + valeurs


def commande_lisible(pid: str, etape: str, parametres: dict,
                     simulation: bool = False) -> str:
    import shlex
    pb = obtenir(pid)
    rel = pb.script(etape).relative_to(RACINE.parent).as_posix()
    return " ".join(["bash", rel, *(shlex.quote(a) for a in
                                    arguments(pid, etape, parametres, simulation))])


@dataclass
class Resultat:
    etape: str
    code: int
    sortie: str
    refuse: str = ""          # raison d'un refus AVANT execution

    @property
    def ok(self) -> bool:
        return not self.refuse and self.code == 0


def executer(pid: str, etape: str, parametres: dict, bash: str,
             simulation: bool = False, delai: int = 300) -> Resultat:
    """Execute une etape. Refuse si le sceau est rompu ou les parametres
    invalides. Aucune chaine de shell : argv = [bash, script, arg...]."""
    alteres = controler_sceau(pid)
    if alteres:
        return Resultat(etape, -1, "", "sceau rompu : " + ", ".join(alteres))
    erreurs = valider_parametres(pid, parametres)
    if erreurs:
        return Resultat(etape, -1, "", "; ".join(erreurs))
    pb = obtenir(pid)
    argv = [bash, str(pb.script(etape)),
            *arguments(pid, etape, parametres, simulation)]
    try:
        r = subprocess.run(argv, capture_output=True, timeout=delai)
    except subprocess.TimeoutExpired:
        return Resultat(etape, -2, f"delai depasse ({delai} s)")
    sortie = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
    return Resultat(etape, r.returncode, sortie.strip())


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    if "--sceller" in sys.argv:
        s = sceller()
        print(f"Sceau ecrit : {len(s) - 1} playbook(s) -> {SCEAU}")
    for pid in tous():
        etat = controler_sceau(pid)
        print(f"  {pid:28} {'intact' if not etat else 'ROMPU : ' + ', '.join(etat)}")
