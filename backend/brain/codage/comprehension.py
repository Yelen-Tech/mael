"""Comprendre la demande AVANT d'agir (premiere piece du raisonnement profond).

Mesure du 08/10/2026 : MAEL ne comprenait que des mots francais bien
ecrits. « un formulere de contacte et une gallerie », une demande en
anglais, « un truc bien pour ma boutique » ou « une seule page avec trois
pages » : AUCUNE exigence retenue, en silence ; le modele devinait, et
personne ne le controlait.

Cette etape, sans appel au modele (instantanee, deterministe, testee) :
  1. LECTURE TOLERANTE : un mot proche d'un mot du vocabulaire (distance
     d'edition 1, ou 2 pour un mot long, meme premiere lettre) est lu comme
     lui ; l'anglais courant est traduit — seulement si la demande EST en
     anglais (sinon « reserver une table » deviendrait un <table>) ;
  2. NOMBRE DE PAGES : « trois pages », « 3 pages », « une seule page » ;
     deux nombres differents = CONTRADICTION signalee ;
  3. DEMANDE VAGUE : aucun element reconnu, aucun nombre de pages, peu de
     mots -> signalee ;
  4. SUPPOSITIONS : chaque correction, chaque choix fait a la place du
     developpeur est ECRIT — dans le plan et dans le bilan. Rien de cache.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Mots que les exigences reconnaissent (demande.py) : la cible des
# corrections. Formes de base, sans accents.
VOCABULAIRE = ["formulaire", "formulaires", "galerie", "galeries", "photos",
               "inscription", "connexion", "navigation", "tableau",
               "tableaux", "video", "videos", "bouton", "boutons", "menu",
               "contact", "accueil", "page", "pages", "footer"]

# Anglais -> francais, appliques seulement a une demande en anglais. Les
# expressions longues d'abord.
ANGLAIS = [
    ("contact form", "formulaire de contact"), ("photo gallery", "galerie"),
    ("image gallery", "galerie"), ("navigation bar", "menu"),
    ("navbar", "menu"), ("sign up", "inscription"), ("signup", "inscription"),
    ("register", "inscription"), ("registration", "inscription"),
    ("log in", "connexion"), ("login", "connexion"), ("sign in", "connexion"),
    ("gallery", "galerie"), ("form", "formulaire"), ("forms", "formulaire"),
    ("footer", "pied de page"), ("buttons", "boutons"),
    ("button", "bouton"), ("table", "tableau"), ("videos", "videos"),
    ("video", "video"), ("homepage", "accueil"), ("home page", "accueil"),
    ("pages", "pages"), ("page", "page"), ("photos", "photos"),
]
_MOTS_FR = {"le", "la", "les", "un", "une", "des", "avec", "et", "pour",
            "de", "du", "sur", "mon", "ma", "mes", "site", "fais", "moi"}
_MOTS_EN = {"the", "a", "an", "with", "and", "for", "of", "my", "website",
            "make", "me", "build", "create", "site", "please"}

NOMBRES = {"une": 1, "un": 1, "deux": 2, "trois": 3, "quatre": 4,
           "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
           "two": 2, "three": 3, "four": 4, "five": 5}


@dataclass
class Comprehension:
    demande: str                     # telle que le developpeur l'a ecrite
    texte: str                       # corrigee, normalisee, en francais
    corrections: list[str] = field(default_factory=list)
    langue: str = "fr"
    nb_pages: int | None = None
    contradictions: list[str] = field(default_factory=list)
    vague: bool = False

    @property
    def suppositions(self) -> list[str]:
        """Ce que MAEL a decide ou corrige a la place du developpeur."""
        s = list(self.corrections)
        if self.langue == "en":
            s.append("demande en anglais : comprise et traduite pour les "
                     "verifications (le site reste dans la langue demandee)")
        if self.vague:
            s.append("demande VAGUE : aucun element precis reconnu ; le plan "
                     "sera un choix de MAEL, a confirmer")
        s += [f"CONTRADICTION : {c}" for c in self.contradictions]
        return s


def _sans_accents(texte: str) -> str:
    t = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def distance(a: str, b: str) -> int:
    """Distance d'edition (insertion, suppression, substitution,
    transposition de deux lettres voisines)."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cout = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1,
                          d[i - 1][j - 1] + cout)
            if (i > 1 and j > 1 and a[i - 1] == b[j - 2]
                    and a[i - 2] == b[j - 1]):
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len(a)][len(b)]


def _proche(mot: str) -> str | None:
    """Le mot du vocabulaire que `mot` voulait ecrire, ou None. Prudent :
    mots d'au moins 5 lettres, meme premiere lettre, distance 1 (2 au-dela
    de 7 lettres), et un seul candidat le plus proche."""
    if len(mot) < 5 or mot in VOCABULAIRE:
        return None
    seuil = 2 if len(mot) >= 8 else 1
    # Seulement vers des mots d'au moins 7 lettres : un mot court a trop de
    # vrais voisins (le banc l'a vu : « pagnes », le tissu, devenait
    # « pages »). formulaire, galerie, contact, accueil, inscription...
    candidats = sorted((distance(mot, v), v) for v in VOCABULAIRE
                       if len(v) >= 7 and v[0] == mot[0]
                       and abs(len(v) - len(mot)) <= seuil)
    if not candidats or candidats[0][0] > seuil:
        return None
    if len(candidats) > 1 and candidats[1][0] == candidats[0][0] \
            and candidats[1][1].rstrip("sx") != candidats[0][1].rstrip("sx"):
        return None                      # deux lectures possibles : on ne choisit pas
    return candidats[0][1]


def _langue(mots: list[str]) -> str:
    en = sum(m in _MOTS_EN for m in mots)
    fr = sum(m in _MOTS_FR for m in mots)
    return "en" if en > fr else "fr"


def _nombres_de_pages(texte: str) -> set[int]:
    """Les nombres de pages annonces. « une page de contact » DECRIT une
    page, il ne compte pas le site : seuls comptent un nombre suivi de
    « pages » (pluriel) et les formes explicites d'une page unique."""
    vus = set()
    for m in re.finditer(r"\b(\d{1,2}|[a-z]+)\s+pages\b", texte):
        mot = m.group(1)
        n = int(mot) if mot.isdigit() else NOMBRES.get(mot)
        if n and n >= 2:
            vus.add(n)
    if re.search(r"\b(?:page unique|une seule page|un site d une page|"
                 r"1 page|one page|single page|one-page)\b", texte):
        vus.add(1)
    return vus


def comprendre(demande: str) -> Comprehension:
    brut = _sans_accents(demande)
    mots = re.findall(r"[a-z0-9]+", brut)
    c = Comprehension(demande=demande, texte=brut, langue=_langue(mots))

    texte = brut
    if c.langue == "en":
        for en, fr in ANGLAIS:
            texte = re.sub(rf"\b{re.escape(en)}\b", fr, texte)

    def corriger(m: re.Match) -> str:
        mot = m.group(0)
        juste = _proche(mot)
        if juste:
            c.corrections.append(f"« {mot} » lu comme « {juste} »")
            return juste
        return mot
    texte = re.sub(r"[a-z]+", corriger, texte)
    c.texte = texte

    nombres = _nombres_de_pages(texte)
    if len(nombres) == 1:
        c.nb_pages = nombres.pop()
    elif len(nombres) > 1:
        c.contradictions.append(
            "nombres de pages differents dans la demande : "
            + ", ".join(str(n) for n in sorted(nombres)))

    from .demande import exigences
    c.vague = (not exigences(texte) and c.nb_pages is None
               and len(mots) <= 12)
    return c
