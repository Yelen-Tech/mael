"""Connaissances generales (etape 2 du plan : les langages de programmation).

Bibliotheque de connaissances GENERALES, separee des fiches de controle de
`brain.bibliotheque`, qui restent le savoir d'audit (commandes de lecture,
points de controle, evaluation). Ici : du savoir de fond — comment un
langage gere la memoire, quels sont ses pieges de securite classiques —
sans commandes ni evaluation.

Une connaissance est un fichier YAML dans `langages/`, valide par
`schema.valider` (le code decide, jamais le modele) et sourcée (chaque
fiche cite sa documentation officielle). Ce module : le modele de donnees,
le chargement (une fois par processus) et une recherche par mots-cles
deterministe — aucun appel modele, aucune dependance externe (stdlib +
PyYAML uniquement).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml


@dataclass
class Connaissance:
    """Une fiche de savoir general (ex. un langage de programmation)."""
    id: str
    nom: str
    resume: str
    famille: str                      # cf. schema.FAMILLES (« langage »)
    version: int = 1
    etat: str = "brouillon"           # brouillon | verifie | obsolete
    mots_cles: list[str] = field(default_factory=list)
    caracteristiques: dict = field(default_factory=dict)
    securite: list[dict] = field(default_factory=list)   # titre, risque,
    #                                                        conseil, gravite
    sources: list[dict] = field(default_factory=list)    # titre, url
    chemin: Path | None = None


# --------------------------------------------------------------------------- #
# Chargement
# --------------------------------------------------------------------------- #
def _dossier() -> Path:
    """Racine des connaissances ; un sous-dossier par famille."""
    return Path(__file__).resolve().parent


def _depuis_yaml(donnees: dict, chemin: Path) -> Connaissance:
    return Connaissance(
        id=donnees["id"],
        nom=donnees.get("nom", donnees["id"]),
        resume=donnees.get("resume", ""),
        famille=donnees.get("famille", ""),
        version=int(donnees.get("version", 1)),
        etat=donnees.get("etat", "brouillon"),
        mots_cles=[str(m) for m in donnees.get("mots_cles", [])],
        caracteristiques=dict(donnees.get("caracteristiques") or {}),
        securite=[dict(p) for p in donnees.get("securite", [])],
        sources=[dict(s) for s in donnees.get("sources", [])],
        chemin=chemin,
    )


@lru_cache(maxsize=1)
def toutes() -> list[Connaissance]:
    """Charge les connaissances VALIDES une fois. Une fiche qui echoue a la
    validation (schema.valider) est ecartee et signalee par un avertissement
    imprime, jamais silencieuse. Un id en double est refuse (ValueError)."""
    from .schema import valider

    connaissances: list[Connaissance] = []
    ids: set[str] = set()
    for chemin in sorted(_dossier().rglob("*.yaml")):
        try:
            donnees = yaml.safe_load(chemin.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"[connaissances] fiche illisible {chemin.name} : {exc}")
            continue
        erreurs, _ = valider(donnees, chemin)
        if erreurs:
            print(f"[connaissances] fiche invalide {chemin.name} ecartee : "
                  f"{' | '.join(erreurs)}")
            continue
        c = _depuis_yaml(donnees, chemin)
        if c.id in ids:
            raise ValueError(f"id de connaissance en double : {c.id}")
        ids.add(c.id)
        connaissances.append(c)
    return connaissances


# --------------------------------------------------------------------------- #
# Recherche par mots-cles : deterministe, sans modele.
#
# La requete et les champs sont normalises (minuscules, accents retires) puis
# decoupes en jetons. Score = correspondances de jetons ponderees par champ :
# nom 3, mots-cles 2, resume + titres des points de securite 1. Seuil 1.
# --------------------------------------------------------------------------- #
SEUIL = 1          # score minimal pour retenir une fiche
_POIDS_NOM = 3
_POIDS_CLES = 2
_POIDS_TEXTE = 1   # resume + titres des points de securite


def _normaliser(texte: str) -> str:
    texte = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


def _jetons(texte: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _normaliser(texte)))


def _score(c: Connaissance, mots: set[str]) -> int:
    nom = _jetons(c.nom)
    cles: set[str] = set()
    for mc in c.mots_cles:
        cles |= _jetons(mc)
    texte = _jetons(c.resume)
    for point in c.securite:
        texte |= _jetons(str(point.get("titre", "")))
    score = 0
    for m in mots:
        if m in nom:
            score += _POIDS_NOM
        if m in cles:
            score += _POIDS_CLES
        if m in texte:
            score += _POIDS_TEXTE
    return score


def recuperer(requete: str, n: int = 3) -> list[Connaissance]:
    """Les n connaissances les mieux notees pour la requete (score >= SEUIL,
    tri par score decroissant puis id pour un ordre stable)."""
    mots = _jetons(requete)
    if not mots:
        return []
    scores = [(s, c) for c in toutes() if (s := _score(c, mots)) >= SEUIL]
    scores.sort(key=lambda sc: (-sc[0], sc[1].id))
    return [c for _, c in scores[:n]]


# --------------------------------------------------------------------------- #
# Injection dans le prompt : savoir de fond, jamais un verdict.
# --------------------------------------------------------------------------- #
BUDGET_JETONS = 250        # une connaissance ne doit pas couter cher
CARACTERES_PAR_JETON = 3.0  # meme estimation prudente que bibliotheque.injection


def pour_prompt(requete: str, budget_jetons: int = BUDGET_JETONS) -> str:
    """Bloc compact de savoir general pour le prompt, "" si rien d'utile.

    Une seule connaissance, la mieux notee : nom, resume, puis ses points de
    securite (titre + conseil) tant que le budget tient — les derniers points
    sont sacrifies en premier. C'est du SAVOIR DE FOND : le bloc le dit, et
    rien ici ne produit ni ne modifie un verdict d'audit."""
    trouvees = recuperer(requete, n=1)
    if not trouvees:
        return ""
    c = trouvees[0]
    lignes = [f"CONNAISSANCE « {c.nom} » — savoir general, PAS un constat "
              "d'audit :", c.resume]
    for p in c.securite:
        candidat = lignes + [f"  - [{p.get('gravite', '?')}] {p.get('titre', '')}"
                             f" : {p.get('conseil', '')}"]
        if sum(len(l) for l in candidat) / CARACTERES_PAR_JETON > budget_jetons:
            break
        lignes = candidat
    return "\n".join(lignes)
