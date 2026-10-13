"""Le SAVOIR-FAIRE des specialistes : le COMMENT, le POURQUOI, des savoirs
RECENTS, et les DEPENDANCES de chaque tache (feuille de route, etape 3).

Les gabarits (savoir.py) montrent une forme juste — le « quoi ». Le
savoir-faire (savoir_faire/<specialiste>.yaml) dit comment s'y prendre,
pourquoi (la norme), d'ou vient ce savoir (source), quand il a ete verifie,
et ce qu'il faut pour realiser la tache (dependances).

  - pour_tache(fichier, texte) : les 1 ou 2 fiches du SEUL specialiste de la
    tache qui touchent la demande, sous un budget (memoire de 4 096 jetons) ;
  - une fiche PERIMEE (date de revue passee, source disparue) n'est pas
    donnee : elle est signalee (fraicheur.py) ;
  - les dependances verifiables sur la machine (extension PHP...) le sont :
    une absence est un besoin, dit au bilan.
"""
from __future__ import annotations

import functools
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from . import fraicheur
from .emplacements import trouver
from .specialistes import pour as specialiste_de

BUDGET = 1_200             # caracteres (~300 jetons)
FICHES_MAX = 2


@dataclass(frozen=True)
class Fiche:
    id: str
    specialiste: str
    titre: str
    mots: tuple[str, ...]
    comment: tuple[str, ...]
    pourquoi: str
    source: str
    verifie_le: str
    revoir_apres: str
    dependances: tuple[dict, ...] = ()
    juges: tuple[str, ...] = ()
    gabarit: str = ""          # la forme juste qui va avec (gabarits/)
    contexte: str = ""         # js : navigateur | serveur | react
    pour: tuple[str, ...] = ()  # projet : langages que la fiche suppose
    hypotheses: tuple[str, ...] = ()  # conseil : causes connues a departager
    verifier: tuple[str, ...] = ()    # conseil : comment prouver la solution

    @property
    def url(self) -> str:
        m = re.search(r"https://\S+", self.source)
        return m.group(0) if m else ""


@functools.lru_cache(maxsize=1)
def toutes() -> tuple[Fiche, ...]:
    out = []
    for chemin in sorted(fraicheur.DOSSIER.glob("*.yaml")):
        d = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
        for f in d.get("fiches", []):
            out.append(Fiche(
                id=f["id"], specialiste=d["specialiste"], titre=f["titre"],
                mots=tuple(f.get("mots", [])),
                comment=tuple(f.get("comment", [])), pourquoi=f["pourquoi"],
                source=f["source"], verifie_le=str(f["verifie_le"]),
                revoir_apres=str(f["revoir_apres"]),
                dependances=tuple(f.get("dependances", []) or []),
                juges=tuple(f.get("juges", []) or []),
                gabarit=f.get("gabarit", ""),
                pour=tuple(f.get("pour", []) or []),
                hypotheses=tuple(f.get("hypotheses", []) or []),
                verifier=tuple(f.get("verifier", []) or []),
                contexte=f.get("contexte", d.get("contexte", ""))))
    return tuple(out)


_SERVEUR = re.compile(r"(?i)\b(express|serveur|server|node|nodejs|backend)\b")


def contexte_js(fichier: str, texte: str) -> str:
    """Un script de PAGE, un SERVEUR Node, ou un composant REACT : trois
    savoir-faire differents pour le meme specialiste."""
    if Path(fichier).suffix.lower() == ".jsx" or re.search(r"(?i)\breact\b",
                                                           texte):
        return "react"
    dossier = Path(fichier).parent.as_posix()
    if _SERVEUR.search(f"{texte} {Path(fichier).name}") and dossier not in {
            "js", "scripts", "public/js"}:
        return "serveur"
    return "navigateur"


def _mots(texte: str) -> set[str]:
    from .savoir import _mots as mots_normalises
    return mots_normalises(texte)


def _touche(mot_demande: str, mot_fiche: str) -> bool:
    from .savoir import _touche as touche
    return touche(mot_demande, mot_fiche)


def perimee(f: Fiche, releve: fraicheur.Releve,
            aujourd_hui: date | None = None) -> str:
    """La raison pour laquelle cette fiche ne doit plus servir, ou ""."""
    jour = aujourd_hui or date.today()
    if jour > date.fromisoformat(f.revoir_apres):
        return f"date de revue passee ({f.revoir_apres})"
    if f.url and f.url in releve.sources_mortes:
        return f"source introuvable ({f.url})"
    return ""


@dataclass
class Choix:
    fiches: list[Fiche] = field(default_factory=list)
    ecartees: list[tuple[Fiche, str]] = field(default_factory=list)


def choisir(fichier: str, texte: str, releve: fraicheur.Releve | None = None,
            aujourd_hui: date | None = None) -> Choix:
    s = specialiste_de(fichier)
    choix = Choix()
    if s is None:
        return choix
    return _choisir_parmi(s.nom, _mots(f"{texte} {Path(fichier).stem}"),
                          releve, aujourd_hui,
                          contexte_js(fichier, texte) if s.nom == "js"
                          else "")


def _choisir_parmi(specialiste: str, demande: set[str],
                   releve: fraicheur.Releve | None, aujourd_hui: date | None,
                   contexte: str = "", groupes: set[str] | None = None
                   ) -> Choix:
    choix = Choix()
    releve = releve if releve is not None else fraicheur.charger()
    notes = []
    for f in toutes():
        if f.specialiste != specialiste:
            continue
        if contexte and f.contexte and f.contexte != contexte:
            continue
        if groupes is not None and not set(f.pour) <= groupes:
            continue                       # suppose un langage non demande
        # Par racine, comme les gabarits : « lisibles » touche « lisible ».
        score = sum(1 for m in f.mots if any(_touche(d, m) for d in demande))
        if score == 0:
            continue
        raison = perimee(f, releve, aujourd_hui)
        if raison:
            choix.ecartees.append((f, raison))
            continue
        notes.append((score, f))
    notes.sort(key=lambda x: (-x[0], x[1].id))
    choix.fiches = [f for _s, f in notes[:FICHES_MAX]]
    return choix


def _versions(fiches: list[Fiche], releve: fraicheur.Releve) -> str:
    noms = {d["nom"].lower() for f in fiches for d in f.dependances
            if d.get("type") == "python"} & set(releve.versions)
    if not noms or not releve.date:
        return ""
    return (f"versions actuelles (verifiees le {releve.date}) : "
            + ", ".join(f"{n} {releve.versions[n]}" for n in sorted(noms)))


def pour_tache(fichier: str, texte: str, releve: fraicheur.Releve | None = None,
               budget: int = BUDGET, aujourd_hui: date | None = None
               ) -> tuple[str, Choix]:
    """Le bloc de savoir-faire de la consigne, et ce qui a ete choisi /
    ecarte (pour le bilan)."""
    releve = releve if releve is not None else fraicheur.charger()
    choix = choisir(fichier, texte, releve, aujourd_hui)
    if not choix.fiches:
        return "", choix
    s = specialiste_de(fichier)
    return _rendre(f"[savoir-faire {s.nom} — comment et pourquoi]", choix,
                   releve, budget), choix


def pour_plan(demande: str, releve: fraicheur.Releve | None = None,
              budget: int = BUDGET, aujourd_hui: date | None = None
              ) -> tuple[str, Choix]:
    """Le savoir-faire du CHEF DE CHANTIER (conduire un long projet) : il va
    au plan, la ou se decident l'ordre, la structure et les dependances."""
    releve = releve if releve is not None else fraicheur.charger()
    # Seulement les fiches des langages DEMANDES (banc des plans du
    # 08/10/2026 : les exemples d'API recopies dans des sites vitrines).
    from .professeurs import etablir
    langages = etablir(demande).langages
    groupes = set(langages) | ({"serveur"} if langages - {"html"} else set())
    choix = _choisir_parmi("projet", _mots(demande), releve, aujourd_hui,
                           groupes=groupes)
    if not choix.fiches:
        return "", choix
    return _rendre("[savoir-faire du chef de chantier — conduire le projet]",
                   choix, releve, budget), choix


# Des mots trop courants pour designer un savoir (phase de test des
# problemes inedits du 08/10/2026 : « site » + « telephone » donnaient la
# fiche du menu commun a « mon site met 10 secondes a s'ouvrir »).
BANALS = {"site", "sites", "page", "pages", "telephone", "bouton", "boutons",
          "application", "applications", "projet", "web", "faire", "complet",
          "complete", "mon", "ma", "mes", "tout", "veux", "avec"}


def pour_conseil(texte: str, n: int = 3, releve: fraicheur.Releve | None = None
                 ) -> list[Fiche]:
    return [f for _s, f in pour_conseil_note(texte, n, releve)]


def pour_conseil_note(texte: str, n: int = 3,
                      releve: fraicheur.Releve | None = None
                      ) -> list[tuple[int, Fiche]]:
    """Les fiches que le professeur CONNAISSANCE consulte pour un probleme,
    avec leur score (mots SPECIFIQUES communs) : la famille « conseil »
    (corriger, diagnostiquer, migrer, services externes...) puis les fiches
    des specialistes ; les perimees sont ecartees."""
    releve = releve if releve is not None else fraicheur.charger()
    mots = _mots(texte) - BANALS
    # Une fiche d'un LANGAGE non demande ne s'applique pas (la meteo
    # tombait sur « afficher une valeur en PHP » a cause du mot affiche).
    from .professeurs import etablir
    langages = etablir(texte).langages
    notes = []
    for f in toutes():
        if f.specialiste == "projet" or perimee(f, releve):
            continue
        if (f.specialiste in {"php", "python", "java"}
                and f.specialiste not in langages):
            continue
        score = sum(1 for m in f.mots if m not in BANALS
                    and any(_touche(d, m) for d in mots))
        # Deux mots communs au moins, pour TOUTES les fiches : un seul mot
        # (« robot ») faisait repondre la fiche anti-spam a un robot d'echecs
        # sur Arduino. La famille du conseil passe ensuite en premier.
        if score >= 2:
            notes.append((score, f))
    notes.sort(key=lambda x: (-(x[0] + (1 if x[1].specialiste == "conseil"
                                        else 0)), x[1].id))
    return notes[:n]


def _rendre(entete: str, choix: Choix, releve: fraicheur.Releve,
            budget: int) -> str:
    l = [entete]
    for f in choix.fiches:
        fin = [f"  POURQUOI : {f.pourquoi}",
               f"  (source : {f.source.split(' — ')[0]} ; verifie le "
               f"{f.verifie_le})"]
        if f.dependances:
            fin.append("  IL FAUT : " + " ; ".join(
                f"{d['nom']} ({d['pourquoi']})" for d in f.dependances))
        # Trop long pour le budget : moins d'etapes, jamais sans le pourquoi.
        for n in range(len(f.comment), 0, -1):
            bloc = ([f"* {f.titre} :", "  COMMENT :"]
                    + [f"  - {c}" for c in f.comment[:n]] + fin)
            if len("\n".join(l + bloc)) <= budget:
                l += bloc
                break
    v = _versions(choix.fiches, releve)
    if v:
        l.append(v)
    return "\n".join(l) if len(l) > 1 else ""


# --------------------------------- dependances verifiables sur la machine
@functools.lru_cache(maxsize=1)
def _extensions_php() -> frozenset[str] | None:
    if os.environ.get("MAEL_SANS_OUTILS"):    # tests : pas d'outil machine
        return None
    php = trouver("php")
    if not php:
        return None
    try:
        r = subprocess.run([php, "-m"], capture_output=True, text=True,
                           timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return frozenset(l.strip().lower() for l in r.stdout.splitlines()
                     if l.strip() and not l.startswith("["))


def dependances_absentes(fiches: list[Fiche]) -> list[str]:
    """Les dependances des fiches choisies qui MANQUENT sur la machine,
    quand MAEL sait le verifier (extensions PHP)."""
    out = []
    exts = None
    for f in fiches:
        for d in f.dependances:
            if d.get("type") != "php-ext":
                continue
            if exts is None:
                exts = _extensions_php()
            if exts is None:
                # Pas de php : rien a affirmer ici (l'absence de php est
                # deja un angle mort, angles_morts.py).
                return out
            if d["nom"].lower() not in exts:
                out.append(f"dependance absente sur la machine : extension "
                           f"PHP {d['nom']} — {d['pourquoi']}")
    return list(dict.fromkeys(out))
