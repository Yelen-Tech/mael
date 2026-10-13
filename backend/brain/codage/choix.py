"""Le CHOIX par le modele parmi les candidats de la localisation (levier 3).

Point 4, 12/10/2026. La localisation calculee (localisation.py) met le bon
fichier dans les 5 premiers environ 4 fois sur 5, mais en PREMIER seulement
une fois sur 2 (banc SWE-bench Lite, 63 tickets). Departager des candidats
demande de COMPRENDRE le ticket : c'est le travail du modele — mais sur un
resume court (chemins, raisons, signatures des fonctions designees), pas sur
le code : quelques centaines de jetons, a la portee d'un petit modele.

Surete :
  - la reponse est imposee (JSON, grammaire) ;
  - un chemin hors des candidats (invente) est ignore ;
  - si le modele echoue ou ne dit rien d'utilisable, l'ordre calcule reste :
    le choix ne peut qu'AVANCER des candidats, jamais en faire disparaitre.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CANDIDATS = 8
SIGNATURES = 3                  # fonctions montrees par candidat

SCHEMA_CHOIX = {
    "type": "object",
    "properties": {
        "fichiers": {"type": "array", "items": {"type": "string"},
                     "minItems": 1, "maxItems": 3},
        "raison": {"type": "string"}},
    "required": ["fichiers", "raison"]}

SYSTEME = """Tu aides a corriger un ticket dans un depot de code. On te montre
le ticket et une liste de fichiers CANDIDATS, avec pourquoi chacun a ete
retenu et la signature de ses fonctions concernees. Dis quels fichiers (1 a
3, du plus probable au moins probable) contiennent le code A MODIFIER pour
corriger le ticket — pas celui qui l'utilise seulement.
Reponds en JSON : {"fichiers": ["chemin", ...], "raison": "une phrase"}.
Recopie les chemins EXACTEMENT comme dans la liste."""


@dataclass
class Choix:
    fichiers: list[str]          # retenus par le modele, valides
    raison: str
    applique: bool               # l'ordre a-t-il change ?


def resume(lieux, textes: dict[str, str], n: int = CANDIDATS) -> str:
    """La liste des candidats pour le modele : chemin, raisons, signatures."""
    l = []
    for k, lieu in enumerate(lieux[:n], 1):
        l.append(f"{k}. {lieu.fichier} — "
                 + (", ".join(lieu.raisons[:3]) or "mots du ticket"))
        lignes = textes.get(lieu.fichier, "").split("\n")
        for s in lieu.symboles[:SIGNATURES]:
            sig = lignes[s.debut - 1].strip() if 0 < s.debut <= len(
                lignes) else s.nom
            # decorateur en tete : la ligne suivante porte la signature
            if sig.startswith("@") and s.debut < len(lignes):
                sig = lignes[s.debut].strip()
            l.append(f"     {s.nom} (ligne {s.debut}) : {sig[:120]}")
    return "\n".join(l)


def lire(donnees, texte: str, candidats: list[str]) -> tuple[list[str], str]:
    if not isinstance(donnees, dict):
        try:
            donnees = json.loads(texte)
        except (ValueError, TypeError):
            return [], ""
    brut = donnees.get("fichiers") if isinstance(donnees, dict) else None
    if not isinstance(brut, list):
        return [], ""
    valides = []
    for f in brut:
        f = str(f).strip().strip("`").removeprefix("./")
        if f in candidats and f not in valides:
            valides.append(f)
        elif f not in candidats:
            # un numero de la liste, ou un nom de fichier sans dossier
            if f.isdigit() and 1 <= int(f) <= len(candidats):
                f = candidats[int(f) - 1]
            else:
                proches = [c for c in candidats if Path(c).name == Path(f).name]
                f = proches[0] if len(proches) == 1 else ""
            if f and f not in valides:
                valides.append(f)
    return valides[:3], str(donnees.get("raison", ""))[:300]


def choisir(backend, ticket: str, lieux, textes: dict[str, str],
            limite_ticket: int = 3000):
    """Rend (lieux reordonnes, Choix). Les fichiers choisis passent devant,
    dans l'ordre du modele ; les autres gardent l'ordre calcule."""
    candidats = [l.fichier for l in lieux[:CANDIDATS]]
    if len(candidats) < 2:
        return lieux, Choix([], "un seul candidat", False)
    t = ticket.strip()
    if len(t) > limite_ticket:
        t = t[:limite_ticket] + "\n[... ticket coupe ...]"
    message = (f"TICKET :\n{t}\n\nCANDIDATS (ordre calcule par MAEL) :\n"
               + resume(lieux, textes))
    try:
        rep = backend.completer(systeme=SYSTEME, messages=[
            {"role": "user", "content": message}], role_modele="codeur",
            schema=SCHEMA_CHOIX)
    except Exception:                                   # noqa: BLE001
        return lieux, Choix([], "le modele n'a pas repondu", False)
    choisis, raison = lire(rep.donnees, rep.texte, candidats)
    if not choisis:
        return lieux, Choix([], raison or "reponse inutilisable", False)
    par_nom = {l.fichier: l for l in lieux}
    nouveaux = [par_nom[f] for f in choisis] + [
        l for l in lieux if l.fichier not in choisis]
    for f in choisis:
        r = f"choisi par le modele : {raison}" if raison else \
            "choisi par le modele"
        if r not in par_nom[f].raisons:
            par_nom[f].raisons.insert(0, r[:160])
    return nouveaux, Choix(choisis, raison,
                           [l.fichier for l in nouveaux] != [
                               l.fichier for l in lieux])
