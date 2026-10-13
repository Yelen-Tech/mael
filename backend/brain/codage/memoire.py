"""La MEMOIRE DE TRAVAIL du chantier : aucun probleme n'est laisse en route.

Examen des 100 missions (09/10/2026), remarque du responsable : « MAEL a
identifie le probleme et ne l'a pas corrige ; il ne peut pas laisser un
probleme non resolu et passer a d'autres — ou bien il lui manque du savoir
ou des outils ». Jusque-la, une tache gardait ses defauts apres deux tours
et le chantier passait a la suivante ; la finition n'en reprenait que trois
fichiers ; le reste tombait dans « ce qui reste a corriger » sans un mot.

Ici chaque defaut bloquant vu pendant le chantier est RETENU : combien de
fois il a ete montre au modele, s'il a disparu. La finition repart de cette
memoire (tous les problemes ouverts, pas seulement les premiers). Et ce qui
reste a la fin n'est jamais muet : chaque probleme dit POURQUOI il reste —
- OUTIL MANQUANT : MAEL sait le reparer seul, mais ce cas lui echappe ;
- SOLUTION CONNUE non appliquee par le modele (avec le nombre d'essais) ;
- SAVOIR MANQUANT : aucune solution connue pour cette regle ;
- VERROU : fichier valide puis verrouille, seules les reparations sures.
Les deux premieres et la troisieme sont des BESOINS pour la relecture.
"""
from __future__ import annotations

from dataclasses import dataclass

from .juges import GRAVITE, Defaut
from .remedes import remede

# Les regles que reparation.py traite seul (sans modele) dans les cas surs.
REPARABLES = {"contraste", "fichier-absent", "doctype", "charset", "viewport",
              "import-absent", "blank-noopener", "critere-non-tenu",
              "cible-trop-petite", "focus-invisible"}


def cle(d: Defaut) -> tuple[str, str, str]:
    return d.fichier, d.regle, d.message


@dataclass
class Probleme:
    fichier: str
    regle: str
    message: str
    essais: int = 0             # combien de fois montre au modele
    resolu: bool = False


class Memoire:
    def __init__(self):
        self.problemes: dict[tuple[str, str, str], Probleme] = {}

    def retenir(self, defauts: list[Defaut]) -> None:
        for d in defauts:
            if d.gravite is GRAVITE.BLOQUANT:
                p = self.problemes.setdefault(
                    cle(d), Probleme(d.fichier, d.regle, d.message))
                p.resolu = False

    def montres(self, defauts: list[Defaut]) -> None:
        """Ces defauts viennent d'etre donnes au modele a corriger."""
        self.retenir(defauts)
        for d in defauts:
            if d.gravite is GRAVITE.BLOQUANT:
                self.problemes[cle(d)].essais += 1

    def constater(self, fichier: str | None, defauts: list[Defaut]) -> None:
        """Apres un jugement : ce qui n'est plus la est RESOLU (pour ce
        fichier, ou pour tout le projet si fichier est None)."""
        presents = {cle(d) for d in defauts if d.gravite is GRAVITE.BLOQUANT}
        for k, p in self.problemes.items():
            if (fichier is None or p.fichier == fichier) and k not in presents:
                p.resolu = True
        self.retenir(defauts)

    def ouverts(self) -> list[Probleme]:
        return [p for p in self.problemes.values() if not p.resolu]

    def resolus(self) -> int:
        return sum(p.resolu for p in self.problemes.values())


def pourquoi(p: Probleme, verrouilles: set[str]) -> str:
    """La raison pour laquelle ce probleme reste, en une ligne."""
    if p.fichier in verrouilles:
        return ("VERROU : fichier valide puis verrouille, seules les "
                "reparations sures y touchent")
    if p.regle in REPARABLES:
        return ("OUTIL MANQUANT : je repare seul cette regle, mais pas ce "
                "cas-ci (texte inattendu) — a ajouter a reparation.py")
    sol = remede(p.regle)
    if sol:
        return (f"SOLUTION CONNUE non appliquee par le modele en {p.essais} "
                f"essai(s) : {sol}")
    return f"SAVOIR MANQUANT : aucune solution connue pour « {p.regle} »"


def rapport(m: Memoire, restes: list[Defaut], verrouilles: set[str]
            ) -> list[str]:
    """Les lignes du journal : chaque probleme restant et sa raison."""
    m.constater(None, restes)
    lignes = []
    for d in restes:
        if d.gravite is not GRAVITE.BLOQUANT:
            continue
        p = m.problemes[cle(d)]
        lignes.append(f"`{d.fichier}:{d.ligne}` {d.message[:160]} — "
                      f"{pourquoi(p, verrouilles)}")
    return lignes
