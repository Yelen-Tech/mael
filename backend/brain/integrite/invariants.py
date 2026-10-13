"""Module 3 du noyau d'integrite : invariants.

Un invariant est une propriete qui doit tenir EN PERMANENCE, pas seulement
quand on pense a lancer les tests : chacun est une fonction nommee qui rend
la liste de ses violations (vide = tenu). Le code verifie, jamais le modele.

    python -m brain.integrite --invariants
"""
from __future__ import annotations

import re
from datetime import date

from brain import bibliotheque as bib
from brain.garde import NIVEAU, classer

_MARQUEURS = re.compile(r"SENTINELLE:[A-Z_]+")
_RE_REF_ANSSI_CIS = re.compile(r"^(R\d+|[\d.]+)")


def observations_en_lecture() -> list[str]:
    """Toute commande observer est classee LECTURE par le garde-fou, y
    compris apres une evolution du garde-fou lui-meme."""
    violations = []
    for f in bib.toutes():
        for obs in f.observer:
            for cmd in obs.toutes_les_commandes():
                v = classer(cmd)
                if v.niveau is not NIVEAU.LECTURE:
                    violations.append(
                        f"{f.id} : « {cmd[:60]} » classe {v.niveau.value}")
    return violations


def relectures_datees() -> list[str]:
    """Une fiche « verifie » porte une date de relecture, jamais future."""
    violations = []
    aujourd_hui = date.today().isoformat()
    for f in bib.toutes():
        if f.etat == "verifie" and not f.verifie_le:
            violations.append(f"{f.id} : verifie sans verifie_le")
        elif f.verifie_le and str(f.verifie_le) > aujourd_hui:
            violations.append(f"{f.id} : verifie_le dans le futur")
    return violations


def sceau_playbooks_intact() -> list[str]:
    """Le sceau des playbooks est intact (un script modifie n'est jamais
    execute : cet invariant est ce qui le prouve en continu)."""
    from brain import playbooks

    violations = []
    for pid in playbooks.tous():
        violations += [f"{pid} : {a}" for a in playbooks.controler_sceau(pid)]
    return violations


def sceau_bibliotheque_intact() -> list[str]:
    """Le sceau de Merkle de la bibliotheque est intact, s'il existe
    (absent = pas encore scelle : signale, pas une violation)."""
    from . import merkle

    if not merkle.SCEAU.exists():
        return []
    return merkle.controler()


def identifiants_uniques() -> list[str]:
    """ids de fiches uniques, egaux au nom de fichier."""
    vus: dict[str, int] = {}
    violations = []
    for chemin, donnees, exc in bib.lire_fiches():
        if exc is not None or not donnees:
            continue
        fid = donnees.get("id")
        vus[fid] = vus.get(fid, 0) + 1
        if fid and chemin.stem != fid:
            violations.append(f"{chemin.name} : id « {fid} » ≠ nom de fichier")
    violations += [f"id « {fid} » en double ({n} fichiers)"
                   for fid, n in vus.items() if n > 1]
    return violations


def pas_de_reference_inventee() -> list[str]:
    """Une fiche MANUELLE encore brouillon ne doit pas porter de numero de
    regle ANSSI/CIS (regle du projet : jamais de numero ecrit de memoire ;
    les fiches importees citent leur source, c'est leur tracabilite)."""
    violations = []
    for f in bib.toutes():
        if f.etat != "brouillon" or f.source.origine != "manuel":
            continue
        for r in [*f.referentiels,
                  *(r for c in f.controles for r in c.referentiels)]:
            if r.nom in {"ANSSI", "CIS"} and r.ref \
                    and _RE_REF_ANSSI_CIS.match(str(r.ref)):
                violations.append(
                    f"{f.id} : ref « {r.ref} » ({r.nom}) sur une fiche "
                    f"manuelle non relue")
    return violations


def marqueurs_hors_du_prompt() -> list[str]:
    """Les marqueurs SENTINELLE:* n'appartiennent qu'aux commandes observer
    (detection interne) — jamais dans un texte montre au modele ou a
    l'utilisateur (titre, resume, pieges, risque, action...)."""
    violations = []
    for f in bib.toutes():
        textes = [f.titre, f.resume, *f.pieges]
        for c in f.controles:
            textes += [c.controle, c.bon, c.mauvais, c.risque, c.action,
                       c.sans_playbook]
        for t in textes:
            if _MARQUEURS.search(t or ""):
                violations.append(f"{f.id} : marqueur SENTINELLE dans un "
                                  f"texte affiche")
                break
    return violations


# nom -> fonction. L'ordre est celui de l'affichage.
INVARIANTS = {
    "observations en lecture": observations_en_lecture,
    "relectures datees": relectures_datees,
    "sceau des playbooks intact": sceau_playbooks_intact,
    "sceau de la bibliotheque intact": sceau_bibliotheque_intact,
    "identifiants uniques": identifiants_uniques,
    "pas de reference inventee": pas_de_reference_inventee,
    "marqueurs hors du prompt": marqueurs_hors_du_prompt,
}


def verifier() -> dict[str, list[str]]:
    """nom de l'invariant -> violations (vide = tenu)."""
    return {nom: f() for nom, f in INVARIANTS.items()}
