"""Moteur de recherche du catalogue (etape 3 du pipeline).

    question
      -> normalisation (minuscules, sans accents, mots vides retires)
      -> AIGUILLAGE d'intention : themes detectes (lexique_recherche.yaml)
      -> expansion par SYNONYMES (francais -> termes techniques)
      -> INDEX SQLite FTS5 construit une fois (bm25 par colonnes ponderees)
      -> FILTRES STRICTS : systeme et services (contexte), etat, niveau client
      -> classement : pertinence + bonus du theme detecte

Aucun modele. Deterministe. L'aiguillage est SOUPLE : il favorise un theme
sans exclure les autres (un aiguillage rate ne fait pas disparaitre la bonne
fiche).
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

LEXIQUE = Path(__file__).with_name("lexique_recherche.yaml")

# Poids des colonnes pour bm25 (ordre des colonnes de la table `docs`).
COLONNES = ["titre", "mots_cles", "techniques", "theme", "controles", "resume"]
POIDS = [4.0, 4.0, 3.0, 3.0, 1.5, 1.0]
BONUS_THEME = 8.0          # a ajouter a la pertinence si le theme est detecte
PERTINENCE_MIN = 2.0       # en dessous : correspondance trop faible, ignoree

# Mots sans valeur pour distinguer une fiche (formulation de la question).
MOTS_VIDES = {
    "est", "sont", "il", "ils", "elle", "elles", "les", "des", "la", "le", "du",
    "de", "d", "l", "un", "une", "sur", "dans", "avec", "pour", "par", "au", "aux",
    "et", "ou", "ce", "cet", "cette", "ces", "y", "a", "t", "en", "que", "qui",
    "quel", "quelle", "quels", "quelles", "qu", "se", "ne", "pas", "plus",
    "mon", "ma", "mes", "ton", "son", "sa", "ses", "notre", "votre",
    "machine", "serveur", "systeme", "configuration", "configure", "configuree",
    "correct", "correcte", "corrects", "correctes", "actif", "active", "activee",
    "actifs", "desactive", "desactivee", "desactives", "installe", "installee",
    "installes", "marche", "tourne", "verifie", "verifier", "peut", "peuvent",
    "doit", "doivent", "etre", "est-ce", "combien", "comment", "niveau",
    "fichier", "quoi", "bien", "tout", "tous", "court", "bloquees", "bloque",
    "refuse", "refuses", "refusee", "autorise", "autorisee", "autorisees",
    "restreint", "manque", "manquent", "utilisateurs", "lire",
    "options", "option", "securite",
}


def normaliser(texte: str) -> str:
    texte = unicodedata.normalize("NFD", (texte or "").lower())
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return texte.replace("’", "'")


def _mots(texte: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9_./-]*", normaliser(texte))


def _racine(mot: str) -> str:
    """Racine francaise grossiere pour une recherche par prefixe :
    redirections -> redirection, journalises -> journalis, compile -> compil."""
    for fin in ("ees", "es", "ee", "s", "x", "e"):
        if len(mot) > len(fin) + 3 and mot.endswith(fin):
            return mot[: -len(fin)]
    return mot


@lru_cache(maxsize=1)
def lexique() -> dict:
    return yaml.safe_load(LEXIQUE.read_text(encoding="utf-8")) or {}


def _contient(question_norm: str, terme: str) -> bool:
    terme = normaliser(terme)
    if " " in terme or "/" in terme or "'" in terme or "-" in terme:
        return terme in question_norm
    return re.search(rf"(?<![a-z0-9_]){re.escape(terme)}(?![a-z0-9_])",
                     question_norm) is not None


def preparer(question: str) -> str:
    """Question normalisee, avec les remplacements du lexique appliques
    (« groupe proprietaire » -> « groupe »)."""
    q = normaliser(question)
    for avant, apres in (lexique().get("remplacements") or {}).items():
        q = q.replace(normaliser(str(avant)), normaliser(str(apres)))
    return q


def aiguiller(question: str) -> dict[str, int]:
    """Themes detectes dans la question -> nombre de declencheurs trouves."""
    q = preparer(question)
    trouves: dict[str, int] = {}
    for theme, termes in (lexique().get("themes") or {}).items():
        n = sum(1 for t in termes if _contient(q, str(t)))
        if n:
            trouves[theme] = n
    return trouves


def expansions(question: str) -> list[str]:
    """Synonymes des termes de la question. L'expression la plus longue
    l'emporte : « routage par la source » n'active pas aussi « routage »."""
    q = preparer(question)
    synonymes = lexique().get("synonymes") or {}
    trouves = [normaliser(str(t)) for t in synonymes if _contient(q, str(t))]
    retenus = [t for t in trouves
               if not any(t != autre and t in autre for autre in trouves)]
    ajouts: list[str] = []
    for terme, cibles in synonymes.items():
        if normaliser(str(terme)) in retenus:
            ajouts += [str(c) for c in cibles]
    return ajouts


# --------------------------------------------------------------------------- #
# Index
# --------------------------------------------------------------------------- #
def _texte_technique(fiche) -> str:
    """Identifiants techniques (id, regle source) coupes en mots :
    sysctl_net_ipv4_conf_all_log_martians -> ... log martians."""
    brut = f"{fiche.id} {fiche.source.regle or ''}"
    return re.sub(r"[_\-.]", " ", brut)


def _texte_theme(fiche) -> str:
    from .taxonomie import THEMES
    theme = (fiche.taxonomie or {}).get("theme")
    return f"{theme or ''} {THEMES.get(theme, ('', ''))[0]}"


class Index:
    def __init__(self, fiches):
        self.fiches = {f.id: f for f in fiches}
        self.db = sqlite3.connect(":memory:")
        self.db.execute(
            "CREATE VIRTUAL TABLE docs USING fts5(id UNINDEXED, "
            + ", ".join(COLONNES)
            + ", tokenize = 'unicode61 remove_diacritics 2')")
        lignes = []
        for f in fiches:
            controles = " ".join(f"{c.controle} {c.bon}" for c in f.controles)
            lignes.append((
                f.id, f.titre, " ".join(f.mots_cles), _texte_technique(f),
                _texte_theme(f), controles, f.resume))
        self.db.executemany(
            f"INSERT INTO docs VALUES (?, {', '.join('?' * len(COLONNES))})",
            lignes)

    @staticmethod
    def _requete(question: str) -> str | None:
        termes: list[str] = []
        for mot in _mots(preparer(question)) + [m for e in expansions(question)
                                                for m in _mots(e)]:
            morceaux = [m for m in re.split(r"[_./-]", mot) if m]
            if ("/" in mot or "." in mot) and len(morceaux) >= 2:
                # Chemin ou nom pointe (/etc/cron.d) : ses morceaux doivent se
                # suivre. Sans cette phrase, « cron.d » se reduit a « cron »
                # (le « d » est trop court) et rejoint /etc/crontab.
                phrase = '"' + " ".join(morceaux) + '"'
                if phrase not in termes:
                    termes.append(phrase)
            for morceau in morceaux:
                morceau = morceau.strip("-")
                if len(morceau) < 2 or morceau in MOTS_VIDES:
                    continue
                racine = _racine(morceau)
                terme = f'"{racine}"*' if len(racine) >= 4 else f'"{morceau}"'
                if terme not in termes:
                    termes.append(terme)
        return " OR ".join(termes) if termes else None

    def pertinences(self, question: str) -> dict[str, float]:
        requete = self._requete(question)
        if requete is None:
            return {}
        poids = ", ".join(str(p) for p in POIDS)
        try:
            lignes = self.db.execute(
                f"SELECT id, bm25(docs, 0, {poids}) FROM docs WHERE docs MATCH ?",
                (requete,)).fetchall()
        except sqlite3.OperationalError:
            return {}
        # bm25 est negatif (plus petit = meilleur) : on inverse.
        return {fid: -score for fid, score in lignes}


@dataclass
class Trouvaille:
    fiche: object
    score: float
    pertinence: float
    themes: list[str] = field(default_factory=list)


@lru_cache(maxsize=2)
def _index_pour(ids: tuple[int, ...]) -> Index:
    from . import actives
    return Index(actives())


def index() -> Index:
    from . import actives
    return _index_pour(tuple(id(f) for f in actives()))


def chercher(question: str, contexte=None, niveau: tuple | None = None,
             n: int = 10) -> tuple[list[Trouvaille], dict[str, int], list[str]]:
    """Rend (trouvailles classees, themes detectes, fiches ecartees par les
    filtres stricts avec raison)."""
    from brain.contexte import applicable

    from .taxonomie import dans_le_niveau

    themes = aiguiller(question)
    pertinences = index().pertinences(question)
    trouvailles, ecartees = [], []
    for fid, pertinence in pertinences.items():
        fiche = index().fiches[fid]
        theme = (fiche.taxonomie or {}).get("theme")
        bonus = BONUS_THEME if theme in themes else 0.0
        if pertinence < PERTINENCE_MIN and not bonus:
            continue
        score = pertinence + bonus
        ok, raison = applicable(fiche, contexte)
        if not ok:
            ecartees.append((score, f"{fiche.titre} : {raison}"))
            continue
        if niveau is not None and not dans_le_niveau(fiche.taxonomie, *niveau):
            ecartees.append((score, f"{fiche.titre} : hors niveau de conformite retenu"))
            continue
        trouvailles.append(Trouvaille(fiche, score, pertinence, sorted(themes)))
    trouvailles.sort(key=lambda t: (-t.score, len(t.fiche.mots_cles), t.fiche.id))
    ecartees.sort(key=lambda e: -e[0])
    return trouvailles[:n], themes, [e[1] for e in ecartees[:3]]
