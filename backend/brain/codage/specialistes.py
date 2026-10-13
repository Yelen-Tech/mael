"""Les SPECIALISTES : un groupe au-dessus des juges (feuille de route du
responsable, 08/10/2026).

Avant : a CHAQUE tache, le chantier rejugeait TOUT le projet — tous les
juges sur tous les fichiers, tous les outils externes, le navigateur sur
toutes les pages. Pour ecrire contact.html, MAEL rejugeait index.html,
style.css, le script... ; et depuis l'installation des outils externes
(eslint, stylelint, html-validate, gitleaks), chaque tache les aurait tous
relances.

Un specialiste est le PREMIER FILTRE : il recoit la tache, et ne convoque
que les juges qui repondent a son besoin.

  - ses juges de fichier (couches 1 a 4) sur le SEUL fichier de la tache ;
  - les juges du projet (selecteurs morts, liens entre fichiers) : rapides,
    sans outil ; leurs defauts sont ensuite filtres sur la tache ;
  - SES outils externes, sur son fichier seulement (stylelint pour le CSS,
    eslint pour le JS...) ; les outils du dossier entier (gitleaks, trivy)
    restent pour la finition ;
  - le navigateur seulement s'il en a besoin, et seulement sur les pages
    concernees (celles qui chargent CETTE feuille de style ou CE script).

Un specialiste est du PROGRAMME, pas un appel au modele de plus : c'est
la que se gagne le temps. La FINITION garde le jury complet, une fois : le
filet de securite, pour qu'aucun defaut n'echappe au verdict final.

MAEL_SANS_SPECIALISTES=1 rend l'ancien jugement (tout le projet a chaque
tache) : pour mesurer le gain sur le meme banc.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import juges
from .juges import Defaut


@dataclass(frozen=True)
class Specialiste:
    nom: str
    extensions: frozenset[str]
    outils: frozenset[str]          # outils externes de SON domaine
    navigateur: bool                # a-t-il besoin d'ouvrir des pages ?
    domaine: str                    # ce qu'il juge, pour le bilan


SPECIALISTES = (
    Specialiste("html", frozenset({".html", ".htm"}),
                frozenset({"html-validate"}), False,
                "structure, accessibilite WCAG, liens entre pages"),
    Specialiste("css", frozenset({".css"}), frozenset({"stylelint"}), True,
                "feuille de style, contraste et tailles mesures sur les "
                "pages qui la chargent"),
    Specialiste("js", frozenset({".js", ".mjs", ".jsx"}),
                frozenset({"eslint"}), True,
                "script, erreurs a l'execution sur les pages qui le "
                "chargent"),
    Specialiste("python", frozenset({".py"}), frozenset({"ruff", "bandit"}),
                False, "code Python, contamination, OWASP, base de donnees"),
    Specialiste("php", frozenset({".php"}), frozenset(), False,
                "code PHP, contamination, requetes preparees"),
    Specialiste("java", frozenset({".java"}), frozenset(), False,
                "code Java, contamination"),
    Specialiste("sql", frozenset({".sql", ".prisma", ".cql"}), frozenset(),
                False,
                "schema de la base : syntaxe du dialecte, cles, migrations, "
                "coherence avec le code (juges_sql.py)"),
)


def actifs() -> bool:
    return os.environ.get("MAEL_SANS_SPECIALISTES") != "1"


def pour(fichier: str) -> Specialiste | None:
    ext = Path(fichier).suffix.lower()
    return next((s for s in SPECIALISTES if ext in s.extensions), None)


_CHARGE = re.compile(r'(?i)<(?:link|script)\b[^>]*?(?:href|src)="([^"]+)"')


def pages_qui_chargent(racine: Path, fichier: str, vus: list[str]
                       ) -> list[str]:
    """Les pages du projet qui chargent ce fichier (feuille de style ou
    script) : les seules ou le navigateur a quelque chose a lui apprendre."""
    cible = Path(fichier).as_posix()
    out = []
    for p in vus:
        if Path(p).suffix.lower() not in {".html", ".htm"}:
            continue
        try:
            texte = (Path(racine) / p).read_text(encoding="utf-8",
                                                 errors="replace")
        except OSError:
            continue
        base = Path(p).parent
        for ref in _CHARGE.findall(texte):
            ref = ref.split("?")[0].split("#")[0]
            vise = (base / ref).as_posix() if not ref.startswith("/") \
                else ref.lstrip("/")
            if Path(vise).as_posix().replace("./", "") == cible:
                out.append(p)
                break
    return out


def juger_tache(racine: Path, fichier: str, *, navigateur: bool = True
                ) -> tuple[list[Defaut], list[str], Specialiste | None]:
    """Le jugement d'UNE tache par son specialiste : (defauts, fichiers du
    projet, specialiste). Sans specialiste pour ce type de fichier : le
    jury complet, comme avant."""
    racine = Path(racine)
    s = pour(fichier)
    vus = [p.relative_to(racine).as_posix()
           for p in juges.fichiers_du_projet(racine)]
    if s is None or fichier not in vus:
        defauts, vus = juges.juger_projet(racine, executer=navigateur)
        return defauts, vus, None
    from .juges_php_java import echecs_contamination
    echecs_contamination.clear()
    chemin = racine / fichier
    texte = chemin.read_text(encoding="utf-8", errors="replace")
    defauts = juges.juger_fichier(fichier, texte, dossier=chemin.parent)
    from . import juges_autres_bases, juges_nosql, juges_sql, projet, sens
    defauts += projet.juger(racine, vus)
    # Le sens et la base se jugent sur tout le projet, a chaque tache : un
    # schema change casse le code qui s'en sert (et inversement).
    defauts += (sens.juger(racine, vus) + juges_sql.juger(racine, vus)
                + juges_nosql.juger(racine, vus)
                + juges_autres_bases.juger(racine, vus))
    from . import outils
    defauts = outils.fusionner(defauts, outils.juger(racine, [fichier],
                                                     seulement=s.outils))
    if s.navigateur and navigateur:
        from . import bac_a_sable
        pages = pages_qui_chargent(racine, fichier, vus)
        if pages:
            defauts = outils.fusionner(
                defauts, bac_a_sable.juger(racine, pages + [fichier]))
    defauts.sort(key=lambda x: (x.gravite != juges.GRAVITE.BLOQUANT,
                                x.fichier, x.ligne))
    return defauts, vus, s
