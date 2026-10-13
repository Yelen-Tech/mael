"""Corpus de dialogues de reference (etape 10 du plan Kimi).

Des conversations d'audit types, en YAML valide par le code, dans
`references/dialogues/`. Elles servent d'exemples de ton et de conduite
injects sobrement dans le prompt (few-shot borne en jetons) : un exemple
montre COMMENT repondre, jamais QUOI conclure — il est etiquette comme
tel, et aucun verdict ne sort d'un dialogue de reference.

Le responsable parle de « milliers de contextes » : le corpus est fait
pour grandir (une fiche YAML par contexte, validee, recherchee). Le
fine-tuning d'un modele, lui, demande le serveur GPU de production —
hors de portee de la machine de dev ; ce module livre le corpus et son
injection, l'entrainement reste une operation a part.

    python -m brain.dialogues            # rapport de validation
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

# meme normalisation que la recherche des connaissances
from brain.connaissances import _jetons

THEMES = {"salutation", "observer", "constater", "bilan", "corriger",
          "refuser_offensif", "refuser_hors_perimetre", "expliquer_ecart",
          "hypothese_vs_fonde", "requalifier", "reprise_audit",
          "priorite_critique"}

ROLES = ("humain", "mael")
MAX_ECHANGES = 6
MAX_TEXTE = 600                 # un exemple court tient dans le prompt

BUDGET_JETONS = 220
CARACTERES_PAR_JETON = 3.0      # meme estimation prudente qu'ailleurs


@dataclass(frozen=True)
class Dialogue:
    id: str
    theme: str
    mots_cles: tuple[str, ...]
    echanges: tuple[tuple[str, str], ...]   # (role, texte)
    chemin: Path | None = field(default=None, compare=False)


def valider(donnees: dict, chemin: Path | None = None) -> list[str]:
    """Rend la liste des erreurs (vide = dialogue chargeable)."""
    erreurs: list[str] = []
    if not isinstance(donnees, dict):
        return ["le dialogue n'est pas un objet YAML"]
    did = donnees.get("id")
    if not isinstance(did, str) or not did.strip():
        erreurs.append("« id » manquant ou vide")
    elif chemin is not None and chemin.stem != did:
        erreurs.append(f"l'id « {did} » ne correspond pas au fichier "
                       f"« {chemin.name} »")
    if donnees.get("theme") not in THEMES:
        erreurs.append(f"theme « {donnees.get('theme')} » inconnu "
                       f"({', '.join(sorted(THEMES))})")
    mots_cles = donnees.get("mots_cles")
    if (not isinstance(mots_cles, list)
            or not all(isinstance(m, str) and m.strip() for m in mots_cles)):
        erreurs.append("« mots_cles » doit etre une liste de textes "
                       "(vide admise)")
    echanges = donnees.get("echanges")
    if not isinstance(echanges, list) or len(echanges) < 2:
        erreurs.append("« echanges » : au moins deux tours")
        echanges = []
    if len(echanges) > MAX_ECHANGES:
        erreurs.append(f"« echanges » : au plus {MAX_ECHANGES} tours "
                       "(un exemple est court)")
    roles = [e.get("role") if isinstance(e, dict) else None for e in echanges]
    if roles and roles[0] != "humain":
        erreurs.append("un dialogue commence par l'humain")
    for i, role in enumerate(roles):
        attendu = ROLES[i % 2]
        if role != attendu:
            erreurs.append(f"echange #{i + 1} : role « {role} », "
                           f"attendu « {attendu} » (alternance humain/mael)")
    for i, e in enumerate(echanges, 1):
        if not isinstance(e, dict):
            erreurs.append(f"echange #{i} : doit etre un dictionnaire")
            continue
        texte = e.get("texte")
        if not isinstance(texte, str) or not texte.strip():
            erreurs.append(f"echange #{i} : « texte » manquant ou vide")
        elif len(texte) > MAX_TEXTE:
            erreurs.append(f"echange #{i} : depasse {MAX_TEXTE} caracteres")
    return erreurs


def _depuis_yaml(donnees: dict, chemin: Path) -> Dialogue:
    return Dialogue(
        id=donnees["id"],
        theme=donnees["theme"],
        mots_cles=tuple(str(m) for m in donnees.get("mots_cles", [])),
        echanges=tuple((e["role"], e["texte"].strip())
                       for e in donnees["echanges"]),
        chemin=chemin,
    )


def _dossier() -> Path:
    return Path(__file__).resolve().parent / "references" / "dialogues"


@lru_cache(maxsize=1)
def tous() -> list[Dialogue]:
    """Charge les dialogues VALIDES une fois ; un invalide est ecarte et
    signale, jamais silencieux. Un id en double est refuse."""
    dialogues: list[Dialogue] = []
    ids: set[str] = set()
    for chemin in sorted(_dossier().glob("*.yaml")):
        try:
            donnees = yaml.safe_load(chemin.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"[dialogues] fichier illisible {chemin.name} : {exc}")
            continue
        erreurs = valider(donnees, chemin)
        if erreurs:
            print(f"[dialogues] {chemin.name} ecarte : {' | '.join(erreurs)}")
            continue
        d = _depuis_yaml(donnees, chemin)
        if d.id in ids:
            raise ValueError(f"id de dialogue en double : {d.id}")
        ids.add(d.id)
        dialogues.append(d)
    return dialogues


def _score(d: Dialogue, mots: set[str]) -> int:
    cles: set[str] = set()
    for mc in d.mots_cles:
        cles |= _jetons(mc)
    score = 2 * len(mots & cles)
    if any(m == d.theme for m in mots):
        score += 1
    return score


def choisir(requete: str) -> Dialogue | None:
    """Le dialogue le plus pertinent pour la requete, ou None : pas
    d'exemple vaut mieux qu'un mauvais exemple."""
    mots = _jetons(requete)
    if not mots:
        return None
    scores = [(s, d) for d in tous() if (s := _score(d, mots)) >= 2]
    scores.sort(key=lambda sd: (-sd[0], sd[1].id))
    return scores[0][1] if scores else None


def pour_prompt(requete: str, budget_jetons: int = BUDGET_JETONS) -> str:
    """Un exemple de reference formate pour le prompt, "" si rien d'utile
    ou si l'exemple ne tient pas dans le budget (on ne tronque pas une
    conversation a mi-tour : on la retire)."""
    d = choisir(requete)
    if d is None:
        return ""
    lignes = ["EXEMPLE DE REFERENCE — le ton et la conduite attendus, "
              "PAS des faits de cet audit :"]
    for role, texte in d.echanges:
        lignes.append(f"{role} : {texte}")
    texte = "\n".join(lignes)
    if int(len(texte) / CARACTERES_PAR_JETON) + 1 > budget_jetons:
        return ""
    return texte


def rapport() -> tuple[int, str]:
    """Valide tout le corpus : (nb erreurs, texte du rapport)."""
    lignes, nb_err, ids = [], 0, {}
    for chemin in sorted(_dossier().glob("*.yaml")):
        try:
            donnees = yaml.safe_load(chemin.read_text(encoding="utf-8"))
            erreurs = valider(donnees, chemin)
            did = (donnees or {}).get("id") if isinstance(donnees, dict) \
                else None
            if did is not None:
                if did in ids:
                    erreurs.append(f"id en double avec {ids[did]}")
                ids[did] = chemin.name
        except Exception as exc:  # noqa: BLE001
            erreurs = [f"YAML illisible : {exc}"]
        nb_err += len(erreurs)
        lignes.append(f"{chemin.name} : {'ECARTE' if erreurs else 'ok'}")
        lignes += [f"   ERREUR  {e}" for e in erreurs]
    lignes.append(f"\n{len(list(_dossier().glob('*.yaml')))} dialogue(s), "
                  f"{nb_err} erreur(s)")
    return nb_err, "\n".join(lignes)


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    nb_err, texte = rapport()
    print(texte)
    sys.exit(1 if nb_err else 0)
