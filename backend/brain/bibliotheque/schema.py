"""Schema v2 des fiches et validation (etape 2.4.1).

Quand la bibliotheque passera de 6 a des milliers de fiches (import depuis
ComplianceAsCode, STIG...), aucune ne sera relue ligne a ligne a chaque mise a
jour. C'est donc le CODE qui refuse une fiche douteuse avant qu'elle
n'atteigne le modele.

    valider(donnees, chemin) -> (erreurs, avertissements)

- ERREUR : la fiche est ecartee au chargement. En particulier, toute commande
  d'observation (ou variante) que le garde-fou ne classe pas en LECTURE.
- AVERTISSEMENT : la fiche est chargee mais incomplete (pas de renvoi ANSSI /
  CIS, jamais testee en conteneur...). Sert de liste de travail.

Rapport de toute la bibliotheque :
    python -m brain.bibliotheque.schema
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

SCHEMA_ACTUEL = 2

DOMAINES = {
    "acces", "comptes", "systeme", "noyau", "fichiers", "services", "reseau",
    "tls", "web", "dns", "journaux", "paquets", "conteneurs",
}
ETATS = {"brouillon", "verifie", "obsolete"}
GRAVITES = {"critique", "elevee", "moyenne", "faible", "info"}
REFERENTIELS = {"ANSSI", "CIS", "STIG", "RFC", "OWASP", "NIST", "autre"}
ORIGINES = {"manuel", "complianceascode", "stig", "tldr", "sigma", "autre"}

# Familles de systemes pour les variantes de commandes.
FAMILLES = {"debian", "rhel", "suse", "alpine", "arch", "generique"}
# Systemes reconnus dans `applicable.os` (« linux » = toute distribution).
SYSTEMES = {
    "linux", "debian", "ubuntu", "rhel", "centos", "rocky", "almalinux",
    "fedora", "oracle", "amzn", "suse", "opensuse", "sles", "alpine", "arch",
}
# Domaines « systeme Linux » : un renvoi ANSSI et CIS y est attendu.
DOMAINES_ANSSI_CIS = {"acces", "comptes", "systeme", "noyau", "fichiers",
                      "services", "reseau", "journaux", "paquets"}

_CONTRAINTE = r"(\s*(>=|<=|==|>|<)\s*\d+(\.\d+)*)?"
_RE_OS = re.compile(rf"^(?P<nom>[a-z]+){_CONTRAINTE}$")
_RE_SERVICE = re.compile(rf"^[a-z0-9][a-z0-9_.+-]*{_CONTRAINTE}$")
_RE_TESTE_SUR = re.compile(r"^[a-z]+:[0-9][0-9.]*$")        # ubuntu:22.04
_RE_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _ids_playbooks() -> set[str]:
    """Identifiants declares par les manifestes de playbooks."""
    import yaml

    racine = Path(__file__).resolve().parents[2] / "playbooks"
    ids = set()
    for manifeste in racine.glob("*/*/manifest.yaml"):
        try:
            ids.add(yaml.safe_load(manifeste.read_text(encoding="utf-8"))["id"])
        except Exception:  # noqa: BLE001  (un manifeste casse = id absent)
            continue
    return ids


def _texte(d: dict, cle: str, erreurs: list[str], requis: bool = True) -> None:
    v = d.get(cle)
    if v is None or (isinstance(v, str) and not v.strip()):
        if requis:
            erreurs.append(f"champ « {cle} » manquant")
    elif not isinstance(v, str):
        erreurs.append(f"champ « {cle} » doit etre du texte")


def _liste_de_textes(d: dict, cle: str, erreurs: list[str]) -> list:
    v = d.get(cle, [])
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        erreurs.append(f"« {cle} » doit etre une liste de textes")
        return []
    return v


def _valider_referentiels(liste, ou: str, erreurs: list[str]) -> set[str]:
    noms = set()
    if liste is None:
        return noms
    if not isinstance(liste, list):
        erreurs.append(f"{ou} : « referentiels » doit etre une liste")
        return noms
    for r in liste:
        if not isinstance(r, dict) or not r.get("nom") or not r.get("document"):
            erreurs.append(f"{ou} : referentiel incomplet (nom + document)")
            continue
        if r["nom"] not in REFERENTIELS:
            erreurs.append(f"{ou} : referentiel inconnu « {r['nom']} »")
        inconnus = set(r) - {"nom", "document", "ref"}
        if inconnus:
            erreurs.append(f"{ou} : champs inconnus {sorted(inconnus)}")
        noms.add(r["nom"])
    return noms


def valider(donnees, chemin: Path | None = None,
            playbooks: set[str] | None = None) -> tuple[list[str], list[str]]:
    """Rend (erreurs, avertissements). Aucune erreur = fiche chargeable."""
    from brain.garde import NIVEAU, classer

    erreurs: list[str] = []
    avert: list[str] = []
    if not isinstance(donnees, dict):
        return ["la fiche n'est pas un objet YAML"], []

    # --- identite ---------------------------------------------------------
    fid = donnees.get("id")
    if not isinstance(fid, str) or not _RE_ID.match(fid or ""):
        erreurs.append("« id » manquant ou invalide (minuscules-et-tirets)")
    elif chemin is not None and chemin.stem != fid:
        erreurs.append(f"l'id « {fid} » ne correspond pas au fichier "
                       f"« {chemin.name} »")
    _texte(donnees, "titre", erreurs)
    _texte(donnees, "resume", erreurs)
    if donnees.get("domaine") not in DOMAINES:
        erreurs.append(f"domaine « {donnees.get('domaine')} » inconnu "
                       f"(attendu : {', '.join(sorted(DOMAINES))})")
    if not _liste_de_textes(donnees, "mots_cles", erreurs):
        erreurs.append("« mots_cles » vide : la fiche serait introuvable")

    schema = donnees.get("schema", 1)
    if schema != SCHEMA_ACTUEL:
        erreurs.append(f"schema {schema} : migrer vers le schema "
                       f"{SCHEMA_ACTUEL}")
        return erreurs, avert     # le reste suppose le schema v2

    # --- cycle de vie -----------------------------------------------------
    if not isinstance(donnees.get("version"), int) or donnees["version"] < 1:
        erreurs.append("« version » doit etre un entier >= 1")
    etat = donnees.get("etat")
    if etat not in ETATS:
        erreurs.append(f"etat « {etat} » inconnu ({', '.join(sorted(ETATS))})")
    verifie_le = donnees.get("verifie_le")
    if verifie_le is not None:
        try:
            jour = (verifie_le if isinstance(verifie_le, date)
                    else date.fromisoformat(str(verifie_le)))
            if jour > date.today():
                erreurs.append("« verifie_le » est dans le futur")
        except ValueError:
            erreurs.append("« verifie_le » doit etre une date AAAA-MM-JJ")
    elif etat == "verifie":
        erreurs.append("une fiche « verifie » doit dater sa relecture "
                       "(verifie_le)")
    if etat == "verifie" and not donnees.get("relu_par"):
        avert.append("relecture sans auteur (relu_par)")
    if donnees.get("relu_par") is not None and not isinstance(
            donnees["relu_par"], str):
        erreurs.append("« relu_par » doit etre du texte")
    teste_sur = _liste_de_textes(donnees, "teste_sur", erreurs)
    for t in teste_sur:
        if not _RE_TESTE_SUR.match(t):
            erreurs.append(f"teste_sur « {t} » invalide (ex. ubuntu:22.04)")
    if etat == "verifie" and not teste_sur:
        avert.append("jamais executee en conteneur (etape 2.5)")

    # --- contexte d'application ------------------------------------------
    applicable = donnees.get("applicable")
    if not isinstance(applicable, dict) or not applicable.get("os"):
        erreurs.append("« applicable.os » requis (ex. [linux] ou "
                       "[ubuntu>=20.04, rhel>=8])")
    else:
        inconnus = set(applicable) - {"os", "services"}
        if inconnus:
            erreurs.append(f"applicable : champs inconnus {sorted(inconnus)}")
        for s in applicable.get("os") or []:
            m = _RE_OS.match(str(s))
            if not m or m.group("nom") not in SYSTEMES:
                erreurs.append(f"applicable.os « {s} » invalide")
        for s in applicable.get("services") or []:
            if not _RE_SERVICE.match(str(s)):
                erreurs.append(f"applicable.services « {s} » invalide")

    # --- taxonomie (domaine / theme / type / niveaux) ----------------------
    from .taxonomie import valider as valider_taxonomie
    erreurs += valider_taxonomie(donnees.get("taxonomie"), donnees.get("domaine"))

    # --- source -----------------------------------------------------------
    source = donnees.get("source")
    if not isinstance(source, dict) or source.get("origine") not in ORIGINES:
        erreurs.append(f"« source.origine » requis ({', '.join(sorted(ORIGINES))})")
    else:
        inconnus = set(source) - {"origine", "regle", "version", "url"}
        if inconnus:
            erreurs.append(f"source : champs inconnus {sorted(inconnus)}")
        if source["origine"] != "manuel" and not (source.get("regle")
                                                  and source.get("version")):
            erreurs.append("une fiche importee doit citer source.regle et "
                           "source.version (tracabilite des mises a jour)")

    # --- commandes d'observation : LECTURE obligatoire --------------------
    observer = donnees.get("observer")
    if not isinstance(observer, list) or not observer:
        erreurs.append("« observer » : au moins une commande de lecture")
        observer = []
    for i, obs in enumerate(observer, 1):
        if not isinstance(obs, dict) or not obs.get("commande"):
            erreurs.append(f"observer #{i} : « commande » manquante")
            continue
        inconnus = set(obs) - {"commande", "but", "lecture", "variantes"}
        if inconnus:
            erreurs.append(f"observer #{i} : champs inconnus {sorted(inconnus)}")
        if not obs.get("lecture"):
            avert.append(f"observer #{i} : « lecture » vide (comment "
                         f"interpreter la sortie ?)")
        commandes = [("defaut", obs["commande"])]
        variantes = obs.get("variantes") or {}
        if not isinstance(variantes, dict):
            erreurs.append(f"observer #{i} : « variantes » doit etre un "
                           f"dictionnaire famille -> commande")
            variantes = {}
        for famille, cmd in variantes.items():
            if famille not in FAMILLES:
                erreurs.append(f"observer #{i} : famille « {famille} » "
                               f"inconnue ({', '.join(sorted(FAMILLES))})")
            commandes.append((famille, cmd))
        for famille, cmd in commandes:
            if not isinstance(cmd, str) or not cmd.strip():
                erreurs.append(f"observer #{i} ({famille}) : commande vide")
                continue
            v = classer(cmd)
            if v.niveau is not NIVEAU.LECTURE:
                erreurs.append(f"observer #{i} ({famille}) : le garde-fou "
                               f"classe « {cmd} » en {v.niveau.value} "
                               f"({v.motif}) ; une observation doit etre une "
                               f"LECTURE")

    # --- points de controle ----------------------------------------------
    controles = donnees.get("controles")
    if not isinstance(controles, list) or not controles:
        erreurs.append("« controles » : au moins un point de controle")
        controles = []
    connus = playbooks if playbooks is not None else _ids_playbooks()
    noms_fiche = _valider_referentiels(donnees.get("referentiels"), "fiche",
                                       erreurs)
    for i, c in enumerate(controles, 1):
        ou = f"controle #{i}"
        if not isinstance(c, dict) or not c.get("controle"):
            erreurs.append(f"{ou} : « controle » manquant")
            continue
        inconnus = set(c) - {"controle", "bon", "mauvais", "gravite", "risque",
                             "action", "playbook", "referentiels",
                             "evaluation", "parametres", "sans_playbook"}
        if inconnus:
            erreurs.append(f"{ou} : champs inconnus {sorted(inconnus)}")
        if c.get("gravite") not in GRAVITES:
            erreurs.append(f"{ou} : gravite « {c.get('gravite')} » inconnue")
        for champ in ("risque", "action"):
            if not c.get(champ):
                erreurs.append(f"{ou} : « {champ} » manquant")
        evaluation = c.get("evaluation")
        if evaluation is not None:
            from .ecarts import valider_spec
            if not isinstance(evaluation, list):
                erreurs.append(f"{ou} : « evaluation » doit etre une liste")
            else:
                nb = len(donnees.get("observer") or [])
                for j, spec in enumerate(evaluation, 1):
                    erreurs += [f"{ou} evaluation #{j} : {e}"
                                for e in valider_spec(spec, nb)]
        if c.get("playbook") and c["playbook"] not in connus:
            erreurs.append(f"{ou} : playbook « {c['playbook']} » introuvable")
        elif c.get("playbook"):
            from brain.playbooks import valider_parametres
            erreurs += [f"{ou} : {e}" for e in
                        valider_parametres(c["playbook"], c.get("parametres") or {},
                                           complet=False)]
        elif c.get("parametres"):
            erreurs.append(f"{ou} : « parametres » sans playbook")
        noms = noms_fiche | _valider_referentiels(c.get("referentiels"), ou,
                                                  erreurs)
        if donnees.get("domaine") in DOMAINES_ANSSI_CIS:
            for attendu in ("ANSSI", "CIS"):
                if attendu not in noms:
                    avert.append(f"{ou} : pas de renvoi {attendu}")

    if "references" in donnees:
        erreurs.append("« references » (texte libre, v1) remplace par "
                       "« referentiels » en v2")
    return erreurs, avert


def rapport() -> tuple[int, int, str]:
    """Valide toute la bibliotheque : (nb erreurs, nb avertissements, texte)."""
    from . import lire_fiches

    lignes, nb_err, nb_av, ids = [], 0, 0, {}
    playbooks = _ids_playbooks()
    for chemin, donnees, exc in lire_fiches():
        if exc is not None:
            erreurs, avert = [f"YAML illisible : {exc}"], []
        else:
            erreurs, avert = valider(donnees, chemin, playbooks)
            fid = (donnees or {}).get("id")
            if fid in ids:
                erreurs.append(f"id en double avec {ids[fid]}")
            ids[fid] = chemin.name
        nb_err += len(erreurs)
        nb_av += len(avert)
        etat = "ECARTEE" if erreurs else "ok"
        lignes.append(f"{chemin.name} : {etat}")
        lignes += [f"   ERREUR  {e}" for e in erreurs]
        lignes += [f"   a faire {a}" for a in avert]
    lignes.append(f"\n{len(ids)} fiche(s), {nb_err} erreur(s), "
                  f"{nb_av} avertissement(s)")
    return nb_err, nb_av, "\n".join(lignes)


if __name__ == "__main__":
    import sys

    for flux in (sys.stdout,):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    nb_err, _, texte = rapport()
    print(texte)
    sys.exit(1 if nb_err else 0)
