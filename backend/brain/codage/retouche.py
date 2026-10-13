"""La retouche : corriger LES LIGNES fautives, pas tout le fichier.

Idee du responsable (07/10/2026) : en correction, le modele reecrivait le
fichier entier pour changer deux lignes. Sur une machine sans carte
graphique (~2,5 jetons/s), c'est l'essentiel du temps perdu. Les juges
donnent deja le fichier et la ligne de chaque defaut : on ne montre au
modele que des EXTRAITS NUMEROTES autour des defauts, et il renvoie
seulement les lignes qui les remplacent.

Surete (rien n'est applique a l'aveugle) :
  - un extrait = une plage de lignes [debut, fin] proposee par MAEL ; une
    retouche n'est appliquee que si son fichier ET sa plage sont exactement
    ceux d'un extrait propose (le modele ne choisit pas ou ecrire) ;
  - les numeros de ligne recopies par megarde (« 12| ») sont retires ;
  - plusieurs retouches dans un meme fichier sont appliquees du bas vers le
    haut (les numeros des plages du dessus restent justes) ;
  - un defaut sans ligne precise (critere de structure, <main> manquant,
    demande non tenue) ne se retouche pas : reecriture complete, comme
    avant. Si rien n'est applicable, la tache repasse a la reecriture.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .espace import CheminRefuse, Espace
from .juges import GRAVITE, Defaut

MARGE = 3                # lignes de contexte de chaque cote du defaut
PART_MAX = 0.6           # au-dela de 60 % du fichier, autant tout reecrire
LIGNES_MIN = 15          # petit fichier : la reecriture coute peu

# Defauts qui ne tiennent pas a une ligne : il faut AJOUTER de la structure.
NON_LOCALISES = {"critere-non-tenu", "demande-non-tenue", "contenu-perdu",
                 "main", "h1", "title", "doctype", "charset", "viewport",
                 "lang", "code-inacheve", "syntaxe-equilibre",
                 "balise-non-fermee"}

SYSTEME_RETOUCHE = """Tu es MAEL. Tu corriges des EXTRAITS de code, pas des
fichiers entiers. Pour chaque extrait recu, renvoie un bloc qui REMPLACE
exactement ses lignes, avec la meme en-tete :
```retouche fichier=index.html lignes=12-18
...les lignes corrigees, sans numeros...
```
Garde tout ce qui n'est pas fautif. N'ecris RIEN d'autre que ces blocs."""

_BLOC = re.compile(
    r"(?ms)^```[ \t]*retouche[ \t]+fichier=([\w./-]+)[ \t]+lignes=(\d+)-(\d+)"
    r"[ \t]*\n(.*?)^```[ \t]*$")
_NUMERO = re.compile(r"^\s*\d+\s*\|\s?")


@dataclass(frozen=True)
class Extrait:
    fichier: str
    debut: int
    fin: int


def eligible(defauts: list[Defaut], fichier: str, nb_lignes: int) -> bool:
    """Retoucher plutot que reecrire ? Seulement si TOUS les defauts
    bloquants du fichier tiennent a une ligne, et que ca vaut le coup."""
    bloquants = [d for d in defauts
                 if d.fichier == fichier and d.gravite is GRAVITE.BLOQUANT]
    if not bloquants or nb_lignes < LIGNES_MIN:
        return False
    if any(d.ligne <= 1 or d.regle in NON_LOCALISES for d in bloquants):
        return False
    couvertes = sum(e.fin - e.debut + 1
                    for e in plages(bloquants, fichier, nb_lignes))
    return couvertes <= PART_MAX * nb_lignes


def plages(defauts: list[Defaut], fichier: str, nb_lignes: int
           ) -> list[Extrait]:
    """Les extraits autour des defauts, fusionnes s'ils se touchent."""
    lignes = sorted({d.ligne for d in defauts
                     if d.fichier == fichier and d.ligne >= 1})
    extraits: list[list[int]] = []
    for n in lignes:
        debut, fin = max(1, n - MARGE), min(nb_lignes, n + MARGE)
        if extraits and debut <= extraits[-1][1] + 1:
            extraits[-1][1] = max(extraits[-1][1], fin)
        else:
            extraits.append([debut, fin])
    return [Extrait(fichier, a, b) for a, b in extraits]


def montrer(texte: str, extraits: list[Extrait], langage: str) -> str:
    """Les extraits numerotes, prets pour le modele."""
    lignes = texte.split("\n")
    morceaux = []
    for e in extraits:
        corps = "\n".join(f"{n}| {lignes[n - 1]}"
                          for n in range(e.debut, e.fin + 1))
        morceaux.append(f"```{langage} fichier={e.fichier} "
                        f"lignes={e.debut}-{e.fin}\n{corps}\n```")
    return "\n\n".join(morceaux)


def appliquer(espace: Espace, reponse: str, proposes: list[Extrait]
              ) -> tuple[list[Extrait], list[str]]:
    """Applique les retouches dont la plage est EXACTEMENT un extrait
    propose. Rend (appliquees, refus)."""
    permis = set(proposes)
    par_fichier: dict[str, list[tuple[Extrait, str]]] = {}
    refus = []
    for m in _BLOC.finditer(reponse):
        e = Extrait(m.group(1), int(m.group(2)), int(m.group(3)))
        if e not in permis:
            refus.append(f"retouche {e.fichier} lignes {e.debut}-{e.fin} "
                         "refusee : plage non proposee")
            continue
        corps = "\n".join(_NUMERO.sub("", l)
                          for l in m.group(4).rstrip("\n").split("\n"))
        par_fichier.setdefault(e.fichier, []).append((e, corps))
    appliquees = []
    for fichier, liste in par_fichier.items():
        try:
            lignes = espace.lire(fichier).split("\n")
        except (OSError, CheminRefuse):
            continue
        vues = set()
        for e, corps in sorted(liste, key=lambda x: x[0].debut, reverse=True):
            if e in vues:                      # meme plage deux fois
                continue
            vues.add(e)
            lignes[e.debut - 1:e.fin] = corps.split("\n")
            appliquees.append(e)
        try:
            espace.ecrire(fichier, "\n".join(lignes).rstrip("\n") + "\n")
        except CheminRefuse:
            appliquees = [x for x in appliquees if x.fichier != fichier]
    if not _BLOC.search(reponse):
        refus.append("aucune retouche lisible dans la reponse")
    return appliquees, refus
