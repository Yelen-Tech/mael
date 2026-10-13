"""Les fiches de normes (pilier 2 du doc 15) : le POURQUOI de chaque regle.

normes/fiches.yaml contient des fiches courtes, redigees par nous a partir
des normes citees (OWASP, WCAG 2.2, CWE, MDN, WHATWG). Trois usages :

    pour_prompt(demande) -- avant d'ecrire : les 1 ou 2 fiches qui touchent
                            la demande (« connexion » -> mots de passe,
                            sessions), sous un budget ;
    pour_regle(regle)    -- pendant la correction : la raison de la regle,
                            jointe au remede et a la forme juste ;
    fiche_de(regle)      -- la fiche elle-meme (bilan, explications).

Meme principe que les gabarits : choix simple et previsible, par les mots
de la demande (racines, synonymes du lexique) ; un score trop faible
n'injecte rien. Mieux vaut aucune fiche qu'une fiche hors sujet.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

import yaml

FICHES = Path(__file__).parent / "normes" / "fiches.yaml"
TEXTE_MAX = 350          # caracteres par fiche (verifie par les tests)
BUDGET_PROMPT = 800      # ~200 jetons avant d'ecrire
MAX_FICHES = 2
POIDS_MOTS, POIDS_TEXTE = 2.0, 0.5
SEUIL = 2.0              # au moins un vrai mot d'appel


@dataclass(frozen=True)
class Fiche:
    id: str
    source: str
    ref: str
    regles: tuple[str, ...]
    mots: tuple[str, ...]
    texte: str

    def court(self, source: bool = True) -> str:
        return (f"{self.texte} ({self.ref}"
                + (f" ; source : {self.source})" if source else ")"))


@functools.lru_cache(maxsize=1)
def toutes() -> tuple[Fiche, ...]:
    donnees = yaml.safe_load(FICHES.read_text(encoding="utf-8")) or {}
    return tuple(
        Fiche(id=f["id"], source=f.get("source", ""), ref=str(f.get("ref", "")),
              regles=tuple(f.get("regles", [])),
              mots=tuple(f.get("mots", [])),
              texte=" ".join(str(f.get("texte", "")).split()))
        for f in donnees.get("fiches", []))


@functools.lru_cache(maxsize=1)
def _index_regles() -> dict[str, Fiche]:
    index: dict[str, Fiche] = {}
    for f in toutes():
        for r in f.regles:
            index.setdefault(r, f)       # la premiere fiche qui l'explique
    return index


def fiche_de(regle: str) -> Fiche | None:
    return _index_regles().get(regle)


def pour_regle(regle: str) -> str:
    """La raison de la regle, en une ligne, ou "" si aucune fiche."""
    f = fiche_de(regle)
    return f"[norme] pourquoi : {f.court()}" if f else ""


@functools.lru_cache(maxsize=1)
def _corpus():
    from .savoir import _jetons
    return tuple((f, frozenset(_jetons(" ".join(f.mots))),
                  frozenset(_jetons(f.texte))) for f in toutes())


def classer(demande: str) -> list[tuple[float, Fiche]]:
    from .savoir import _etendre, _jetons
    requete = set(_jetons(_etendre(demande)))
    resultats = []
    for i, (f, mots, texte) in enumerate(_corpus()):
        s = (POIDS_MOTS * len(requete & mots)
             + POIDS_TEXTE * len(requete & texte))
        if s >= SEUIL and requete & mots:
            resultats.append((s, -i, f))
    resultats.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return [(s, f) for s, _, f in resultats]


def choisir(demande: str, n: int = MAX_FICHES) -> list[Fiche]:
    return [f for _, f in classer(demande)[:n]]


def pour_prompt(demande: str, budget: int = BUDGET_PROMPT) -> str:
    morceaux, total = [], 0
    for f in choisir(demande):
        texte = f"- {f.court(source=False)}"
        if total + len(texte) > budget:
            continue
        total += len(texte)
        morceaux.append(texte)
    if not morceaux:
        return ""
    return ("[normes] Exigences qui s'appliquent a cette demande :\n"
            + "\n".join(morceaux))
