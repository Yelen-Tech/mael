"""Mesure de la recuperation des fiches sur le jeu de questions de reference.

    python -m brain.bibliotheque.evaluation [--controle] [--details]

--controle : jeu de controle (questions jamais utilisees pour regler la
recherche) -- la mesure honnete de la generalisation.

Indicateurs (sur les fiches applicables au systeme du jeu de questions) :
  - top1   : une fiche attendue arrive en premier ;
  - top2   : une fiche attendue est dans les 2 premieres (ce qui est injecte) ;
  - MRR    : moyenne de 1/rang de la premiere fiche attendue (rang > 10 = 0) ;
  - theme  : la premiere fiche est du theme attendu (prepare l'aiguillage).

Sert de garde-fou de progression : toute modification de la recherche se
juge ici, pas sur un exemple isole.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from brain import bibliotheque as bib
from brain import contexte as cx

FICHIER = Path(__file__).with_name("questions_reference.yaml")
FICHIER_CONTROLE = Path(__file__).with_name("questions_controle.yaml")


@dataclass
class Resultat:
    question: str
    theme: str
    attendues: list[str]
    classement: list[str]              # ids des 10 premieres fiches
    rang: int | None                   # rang (1..10) de la 1re attendue
    theme_obtenu: str | None
    invalide: bool = False             # aucune attendue ne s'applique au systeme


@dataclass
class Mesure:
    resultats: list[Resultat] = field(default_factory=list)
    duree_ms: float = 0.0

    def _part(self, predicat) -> float:
        return sum(1 for r in self.resultats if predicat(r)) / len(self.resultats)

    @property
    def top1(self) -> float:
        return self._part(lambda r: r.rang == 1)

    @property
    def top2(self) -> float:
        return self._part(lambda r: r.rang is not None and r.rang <= 2)

    @property
    def mrr(self) -> float:
        return sum(1 / r.rang for r in self.resultats if r.rang) / len(self.resultats)

    @property
    def theme(self) -> float:
        return self._part(lambda r: r.theme_obtenu == r.theme)

    def par_domaine(self) -> dict[str, tuple[int, int]]:
        from brain.bibliotheque.taxonomie import THEMES
        bilan: dict[str, list[int]] = {}
        for r in self.resultats:
            ok = int(r.rang is not None and r.rang <= 2)
            domaine = THEMES[r.theme][1]
            bilan.setdefault(domaine, [0, 0])
            bilan[domaine][0] += ok
            bilan[domaine][1] += 1
        return {d: (v[0], v[1]) for d, v in sorted(bilan.items())}


def charger(fichier: Path = FICHIER) -> dict:
    return yaml.safe_load(fichier.read_text(encoding="utf-8"))


def contexte_du_jeu(jeu: dict) -> cx.Contexte:
    ctx = cx.depuis_declaration(jeu["systeme"])
    ctx.services = list(jeu.get("services", []))
    ctx.services_connus = True
    return ctx


def fiches_inconnues(jeu: dict) -> list[str]:
    ids = {f.id for f in bib.toutes()}
    return sorted({a for q in jeu["questions"] for a in q["attendues"]} - ids)


def classement(question: str, ctx: cx.Contexte, n: int = 10) -> list[bib.Fiche]:
    """Classement complet utilise par la recuperation (hors continuite)."""
    from brain.bibliotheque import recherche
    trouvailles, _, _ = recherche.chercher(question, contexte=ctx, n=n)
    return [t.fiche for t in trouvailles]


def mesurer(jeu: dict | None = None) -> Mesure:
    jeu = jeu or charger()
    ctx_defaut = contexte_du_jeu(jeu)
    mesure = Mesure()
    t0 = time.perf_counter()
    for q in jeu["questions"]:
        # Une question peut viser un autre systeme (fiche propre a Debian 12).
        ctx = (contexte_du_jeu({**jeu, "systeme": q["systeme"]})
               if q.get("systeme") else ctx_defaut)
        top = classement(q["question"], ctx)
        ids = [f.id for f in top]
        par_id = {f.id: f for f in bib.toutes()}
        invalide = not any(cx.applicable(par_id[a], ctx)[0]
                           for a in q["attendues"] if a in par_id)
        rang = next((i for i, fid in enumerate(ids, 1)
                     if fid in q["attendues"]), None)
        mesure.resultats.append(Resultat(
            question=q["question"], theme=q["theme"],
            attendues=q["attendues"], classement=ids, rang=rang,
            theme_obtenu=top[0].taxonomie.get("theme") if top else None,
            invalide=invalide))
    mesure.duree_ms = (time.perf_counter() - t0) * 1000 / len(jeu["questions"])
    return mesure


def rapport(mesure: Mesure, details: bool = False) -> str:
    n = len(mesure.resultats)
    lignes = [
        f"{n} questions — top1 {mesure.top1:.0%} | top2 {mesure.top2:.0%} | "
        f"MRR {mesure.mrr:.2f} | theme {mesure.theme:.0%} | "
        f"{mesure.duree_ms:.0f} ms/question",
        "par domaine (top2) : " + ", ".join(
            f"{d} {ok}/{tot}" for d, (ok, tot) in mesure.par_domaine().items()),
    ]
    echecs = [r for r in mesure.resultats if not (r.rang and r.rang <= 2)]
    if echecs:
        lignes.append(f"\nEchecs top2 ({len(echecs)}) :")
        for r in echecs:
            rang = f"rang {r.rang}" if r.rang else "absente du top 10"
            if r.invalide:
                rang += ", QUESTION INVALIDE : aucune attendue applicable"
            obtenu = ", ".join(r.classement[:2]) or "rien"
            lignes.append(f"  - « {r.question} » ({r.theme}, {rang}) -> {obtenu}")
    if details:
        lignes.append("\nDetail :")
        for r in mesure.resultats:
            lignes.append(f"  [{r.rang or '-'}] {r.question} -> {r.classement[:3]}")
    return "\n".join(lignes)


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    argv = sys.argv[1:] if argv is None else argv
    jeu = charger(FICHIER_CONTROLE if "--controle" in argv else FICHIER)
    inconnues = fiches_inconnues(jeu)
    if inconnues:
        print("Fiches attendues introuvables :", ", ".join(inconnues))
        return 2
    print(rapport(mesurer(jeu), details="--details" in argv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
