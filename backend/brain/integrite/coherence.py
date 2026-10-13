"""Module 9 du noyau d'integrite : solveur de coherence fiches <-> playbooks.

Un verificateur de contraintes deterministe — regles ecrites et relisibles,
pas de solveur externe. Quatre regles :

  1. CONTRADICTION entre fiches : deux controles juges sur la meme cle
     (lecteur, champ) avec des « attendu » differents et des systemes
     applicables qui se recoupent.
  2. LIAISON fiche -> playbook : les parametres du playbook doivent porter
     la valeur que la fiche juge conforme (sinon la correction ne corrige
     pas vers l'attendu).
  3. COUVERTURE : tout controle a un playbook OU une raison ecrite
     (sans_playbook) — remontee en continu, pas seulement en test.
  4. REFERENCES croisees : une fiche citee dans un texte (« fiche
     crypto-cles-hotes-ssh », « fiches cac-sshd-* ») doit exister.

    python -m brain.integrite --coherence
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from brain import bibliotheque as bib

_RE_OS = re.compile(r"^(?P<nom>[a-z]+)(\s*(>=|<=|==|>|<)\s*[\d.]+)?$")
_RE_CITATION = re.compile(r"fiches?\s+`?([a-z0-9*]+(?:-[a-z0-9*]+)+)`?")


@dataclass
class Violation:
    regle: str                   # contradiction | liaison | couverture | reference
    detail: str

    def __str__(self) -> str:
        return f"[{self.regle}] {self.detail}"


def _systemes(fiche) -> set[str]:
    """Noms de systemes applicables, sans les contraintes de version."""
    noms = set()
    for s in (fiche.applicable or {}).get("os") or []:
        m = _RE_OS.match(str(s))
        if m:
            noms.add(m.group("nom"))
    return noms


def _se_recoupent(a, b) -> bool:
    sa, sb = _systemes(a), _systemes(b)
    return bool(sa & sb) or "linux" in sa or "linux" in sb


def _attendu_simple(spec) -> str | None:
    """L'attendu quand c'est une valeur unique comparable, sinon None."""
    if spec.get("comparateur") not in {"egal", "toutes_egales"}:
        return None
    a = spec.get("attendu")
    if isinstance(a, list):
        return None
    return str(a)


def _intervalle(spec) -> tuple[float, float] | None:
    """Intervalle numerique admis par une evaluation, sinon None.
    Relecture 19/09/2026 (Claude) : les bornes (au_moins, au_plus, entre)
    n'etaient pas comparees ; « minlen >= 14 » et « minlen <= 8 » passaient."""
    comp, a = spec.get("comparateur"), spec.get("attendu")
    try:
        if comp in {"egal", "toutes_egales"} and not isinstance(a, list):
            v = float(a)
            return (v, v)
        if comp == "au_moins":
            return (float(a), float("inf"))
        if comp in {"au_plus", "max"}:
            return (float("-inf"), float(a))
        if comp == "entre" and isinstance(a, list) and len(a) == 2:
            return (float(a[0]), float(a[1]))
    except (TypeError, ValueError):
        return None
    return None


def _contradictions_intervalles(fiches) -> list[Violation]:
    """Meme (lecteur, champ), intervalles admis disjoints, systemes
    recoupes : aucune valeur ne peut satisfaire les deux controles."""
    par_cle: dict[tuple, list] = {}
    for f in fiches:
        for c in f.controles:
            for spec in c.evaluation:
                iv = _intervalle(spec)
                cle = (spec.get("lecteur"), spec.get("champ"))
                if iv is not None and cle[1] and \
                        spec.get("comparateur") not in {"egal", "toutes_egales"}:
                    par_cle.setdefault(cle, []).append((f, c, iv))
                elif iv is not None and cle[1]:
                    par_cle.setdefault(cle, []).append((f, c, iv))
    violations = []
    for (lecteur, champ), occ in sorted(par_cle.items()):
        for i in range(len(occ)):
            for j in range(i + 1, len(occ)):
                (f1, c1, (b1, h1)), (f2, c2, (b2, h2)) = occ[i], occ[j]
                if f1.id == f2.id or not _se_recoupent(f1, f2):
                    continue
                # egal/egal deja traite par _contradictions
                if b1 == h1 and b2 == h2:
                    continue
                if max(b1, b2) > min(h1, h2):
                    violations.append(Violation(
                        "contradiction",
                        f"{f1.id}#« {c1.controle} » [{b1}, {h1}] et "
                        f"{f2.id}#« {c2.controle} » [{b2}, {h2}] : aucune "
                        f"valeur commune ({lecteur} {champ})"))
    return violations


def _contradictions(fiches) -> list[Violation]:
    """Meme (lecteur, champ), attendus differents, systemes recoupes."""
    par_cle: dict[tuple, list] = {}
    for f in fiches:
        for c in f.controles:
            for spec in c.evaluation:
                attendu = _attendu_simple(spec)
                cle = (spec.get("lecteur"), spec.get("champ"))
                if attendu is not None and cle[1]:
                    par_cle.setdefault(cle, []).append((f, c, attendu))
    violations = []
    for (lecteur, champ), occurrences in sorted(par_cle.items()):
        for i in range(len(occurrences)):
            for j in range(i + 1, len(occurrences)):
                f1, c1, a1 = occurrences[i]
                f2, c2, a2 = occurrences[j]
                if a1 != a2 and _se_recoupent(f1, f2):
                    violations.append(Violation(
                        "contradiction",
                        f"{f1.id}#« {c1.controle} » attend « {a1} » mais "
                        f"{f2.id}#« {c2.controle} » attend « {a2} » "
                        f"({lecteur} {champ})"))
    return violations


def _liaisons(fiches) -> list[Violation]:
    """Le playbook doit porter la valeur que la fiche juge conforme."""
    violations = []
    for f in fiches:
        for c in f.controles:
            if not c.playbook or not c.parametres:
                continue
            attendus = {_attendu_simple(s) for s in c.evaluation} - {None}
            if len(attendus) != 1:
                continue                       # 0 ou plusieurs : pas tranchable
            attendu = attendus.pop()
            valeurs = {str(v) for v in c.parametres.values()}
            admises = set(attendu.split("|"))  # valeurs admises du referentiel
            # Un parametre peut porter la forme « cle=valeur » (grub-argument) :
            # la coherence se juge sur la partie valeur.
            valeurs |= {v.split("=", 1)[1] for v in valeurs if "=" in v}
            if not valeurs & admises:
                violations.append(Violation(
                    "liaison",
                    f"{f.id}#« {c.controle} » : playbook {c.playbook} "
                    f"parametre {c.parametres} sans la valeur attendue "
                    f"« {attendu} »"))
    return violations


def _couverture(fiches) -> list[Violation]:
    violations = []
    for f in fiches:
        for c in f.controles:
            if not c.playbook and not c.sans_playbook:
                violations.append(Violation(
                    "couverture",
                    f"{f.id}#« {c.controle} » : ni playbook ni raison ecrite"))
    return violations


def _references(fiches) -> list[Violation]:
    ids = {f.id for f in fiches}
    violations = []
    for f in fiches:
        textes = list(f.pieges) + [f.resume]
        for c in f.controles:
            textes += [c.action, c.risque, c.sans_playbook]
        for texte in textes:
            for m in _RE_CITATION.finditer(texte or ""):
                cite = m.group(1)
                if cite.endswith("*"):
                    if not any(i.startswith(cite[:-1]) for i in ids):
                        violations.append(Violation(
                            "reference", f"{f.id} : aucune fiche ne commence "
                            f"par « {cite[:-1]} »"))
                elif cite not in ids:
                    violations.append(Violation(
                        "reference", f"{f.id} : fiche citee « {cite} » "
                        f"introuvable"))
    return violations


def resoudre(fiches=None) -> list[Violation]:
    """Toutes les violations de coherence (vide = bibliotheque coherente)."""
    if fiches is None:
        fiches = bib.toutes()
    return (_contradictions(fiches) + _contradictions_intervalles(fiches)
            + _liaisons(fiches) + _couverture(fiches) + _references(fiches))
