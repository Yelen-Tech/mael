"""Le savoir donne AVANT d'ecrire (terme k de la loi, doc 15).

Les gabarits (gabarits/, decrits par gabarits/index.yaml) sont des FORMES
JUSTES : chacun a passe tous les juges sans defaut bloquant (verifie par les
tests). Un savoir faux enseignerait la faute a chaque usage.

Deux usages :
    pour_prompt(demande) -- avant d'ecrire : les 1 ou 2 gabarits les plus
                            proches de la demande, sous un budget ;
    pour_regle(regle)    -- pendant la correction : la forme juste complete
                            qui montre comment eviter CE defaut.

Le choix est volontairement simple et previsible : on compte les mots de la
demande qui touchent les mots d'un gabarit, par leur racine (« inscrire »
touche « inscription »). On prefere ne rien injecter qu'injecter le mauvais
gabarit : un score nul n'injecte rien.
"""
from __future__ import annotations

import functools
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml

DOSSIER_GABARITS = Path(__file__).parent / "gabarits"
INDEX = DOSSIER_GABARITS / "index.yaml"
BUDGET_CARACTERES = 1_000   # ~250 jetons : le budget d'une machine de 8 Go
BUDGET_CORRECTION = 800     # gabarit joint a une correction (~200 jetons)
MAX_GABARITS = 2
RACINE = 5                  # lettres comparees pour rapprocher deux mots


@dataclass(frozen=True)
class Gabarit:
    fichier: str
    titre: str
    mots: tuple[str, ...]
    regles: tuple[str, ...]

    @property
    def chemin(self) -> Path:
        return DOSSIER_GABARITS / self.fichier

    def texte(self) -> str:
        return self.chemin.read_text(encoding="utf-8").strip()


def _normaliser(texte: str) -> str:
    sans_accents = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in sans_accents
                   if not unicodedata.combining(c)).lower()


def _mots(texte: str) -> set[str]:
    return {m for m in re.findall(r"[a-z0-9]+", _normaliser(texte))
            if len(m) >= 2}


def _touche(mot_demande: str, mot_gabarit: str) -> bool:
    if mot_demande == mot_gabarit:
        return True
    if mot_demande.rstrip("sx") == mot_gabarit.rstrip("sx"):
        return True             # pluriel : pages / page, reseaux / reseau
    # Racine commune, seulement pour des mots assez longs : « inscr- »
    # rapproche inscrire / inscription, mais « api » ne touche pas « apiculteur ».
    return (len(mot_demande) >= RACINE and len(mot_gabarit) >= RACINE
            and mot_demande[:RACINE] == mot_gabarit[:RACINE])


@functools.lru_cache(maxsize=1)
def tous() -> tuple[Gabarit, ...]:
    donnees = yaml.safe_load(INDEX.read_text(encoding="utf-8")) or {}
    return tuple(
        Gabarit(fichier=g["fichier"], titre=g.get("titre", ""),
                mots=tuple(_normaliser(m) for m in g.get("mots", [])),
                regles=tuple(g.get("regles", [])))
        for g in donnees.get("gabarits", []))


# ------------------------------------------------------ choix par le sens
# Meme methode que la recherche des fiches d'audit (bibliotheque/recherche) :
#   1. la PILE demandee (django, php, java...) : filtre strict pour le code
#      serveur — une demande en PHP ne recoit jamais un gabarit Flask ;
#   2. les THEMES (connexion, fichier, sql...) : intention, via le lexique ;
#   3. les SYNONYMES (« envoyer des photos » -> televersement, upload) ;
#   4. la pertinence BM25 sur le titre, les mots et le code du gabarit ;
#   5. la DIVERSITE : deux gabarits couvrent deux besoins differents.
# Aucun modele : deterministe, explicable, rapide. Limite assumee : une
# demande sans aucun mot connu du lexique ni des gabarits ne trouve rien —
# et alors on n'injecte rien plutot que n'importe quoi.
LEXIQUE = Path(__file__).with_name("lexique_gabarits.yaml")
BONUS_THEME = 3.0
BONUS_PILE = 2.0
SEUIL = 1.5                 # en dessous : rapprochement trop faible, ignore
K1, B_LONGUEUR = 1.2, 0.75  # parametres BM25 classiques
POIDS = {"titre": 3.0, "mots": 3.0, "code": 1.0}
MOTS_VIDES = {
    "le", "la", "les", "un", "une", "des", "de", "du", "d", "l", "en", "et",
    "ou", "a", "au", "aux", "pour", "avec", "sur", "dans", "par", "mon", "ma",
    "mes", "sa", "son", "ses", "ton", "ta", "qui", "que", "qu", "je", "j",
    "tu", "il", "on", "nous", "vous", "me", "m", "moi", "veux", "voudrais",
    "besoin", "faire", "fais", "fait", "peux", "peut", "comment", "svp",
    "stp", "merci", "aide", "aider", "voir", "est", "sont", "ce", "cet",
    "cette", "ces", "y", "s", "t", "ne", "pas", "plus", "tres", "bien",
    "simple", "petit", "petite", "the", "a", "an", "of", "to", "with", "my",
}
# Pile d'un gabarit, d'apres son nom : rien a maintenir a la main.
_PREFIXES_PILE = [("django-", "django"), ("flask-", "flask"),
                  ("fastapi-", "fastapi"), ("express-", "node"),
                  ("php-", "php"), ("java-", "java"), ("spring-", "java")]
FRONT = {"html", "css", "js"}


def _racine(mot: str) -> str:
    m = mot
    if len(m) > 3:
        sans = m.rstrip("sx")
        m = sans if len(sans) >= 3 else m
    return m[:RACINE] if len(m) >= RACINE else m


def _jetons(texte: str) -> list[str]:
    return [_racine(m) for m in re.findall(r"[a-z0-9]+", _normaliser(texte))
            if m not in MOTS_VIDES and len(m) >= 2]


@functools.lru_cache(maxsize=1)
def lexique() -> dict:
    return yaml.safe_load(LEXIQUE.read_text(encoding="utf-8")) or {}


def _contient(texte_norm: str, expression: str, exact: bool = False) -> bool:
    """Une expression de plusieurs mots se cherche telle quelle ; un mot seul
    se compare par sa racine (sauf `exact` : « react » ne doit pas
    reconnaitre « reactif »)."""
    expr = _normaliser(str(expression))
    if " " in expr or "'" in expr or "-" in expr or "." in expr:
        def plat(t):
            return " " + re.sub(r"[^a-z0-9.'-]+", " ", t) + " "
        return plat(expr).strip() in plat(texte_norm)
    mots = re.findall(r"[a-z0-9]+", texte_norm)
    if exact:
        return expr in mots
    return _racine(expr) in {_racine(m) for m in mots}


def piles_de(demande: str) -> set[str]:
    t = _normaliser(demande)
    return {p for p, exprs in (lexique().get("piles") or {}).items()
            if any(_contient(t, e, exact=True) for e in exprs)}


def themes_de(texte: str) -> set[str]:
    t = _normaliser(texte)
    return {th for th, exprs in (lexique().get("themes") or {}).items()
            if any(_contient(t, e) for e in exprs)}


def _etendre(demande: str) -> str:
    """La demande + les mots des synonymes qu'elle contient."""
    t = _normaliser(demande)
    ajouts = [m for expr, cibles in (lexique().get("synonymes") or {}).items()
              if _contient(t, expr) for m in cibles]
    return " ".join([demande, *ajouts])


def pile_du_gabarit(g: Gabarit) -> str:
    for prefixe, pile in _PREFIXES_PILE:
        if g.fichier.startswith(prefixe):
            return pile
    ext = g.fichier.rsplit(".", 1)[-1]
    return {"py": "python", "jsx": "react", "html": "html", "css": "css",
            "js": "js", "php": "php", "java": "java"}.get(ext, ext)


def _sert(g: Gabarit, piles: set[str]) -> bool | None:
    """True : le gabarit est de la pile demandee ; None : neutre (front, ou
    aucune pile demandee) ; False : autre pile serveur -> exclu."""
    pile = pile_du_gabarit(g)
    if not piles or pile in FRONT:
        return None
    sert = set((lexique().get("compatibles") or {}).get(pile, [pile]))
    return bool(sert & piles)


@dataclass(frozen=True)
class _Doc:
    g: Gabarit
    tf: dict
    longueur: float
    themes: frozenset
    # Les jetons du titre et des mots d'appel. Le CODE du gabarit peut
    # renforcer un choix, jamais le declencher seul : « bonjour » ne doit pas
    # appeler un gabarit parce que son exemple affiche « Bonjour ».
    appel: frozenset = frozenset()


@functools.lru_cache(maxsize=1)
def _corpus() -> tuple[tuple[_Doc, ...], dict, float]:
    docs = []
    for g in tous():
        champs = {"titre": g.titre, "mots": " ".join(g.mots),
                  "code": g.texte() if g.chemin.exists() else ""}
        tf: dict[str, float] = {}
        for champ, texte in champs.items():
            for j in _jetons(texte):
                tf[j] = tf.get(j, 0.0) + POIDS[champ]
        docs.append(_Doc(g, tf, sum(tf.values()),
                         frozenset(themes_de(g.titre + " " + " ".join(g.mots))),
                         frozenset(_jetons(champs["titre"] + " "
                                           + champs["mots"]))))
    df: dict[str, int] = {}
    for d in docs:
        for j in d.tf:
            df[j] = df.get(j, 0) + 1
    moyenne = sum(d.longueur for d in docs) / max(1, len(docs))
    return tuple(docs), df, moyenne


def _bm25(requete: list[str], d: _Doc, df: dict, n: int, moyenne: float
          ) -> float:
    import math
    s = 0.0
    for j in set(requete):
        f = d.tf.get(j)
        if not f:
            continue
        idf = math.log(1 + (n - df[j] + 0.5) / (df[j] + 0.5))
        s += idf * f * (K1 + 1) / (f + K1 * (1 - B_LONGUEUR + B_LONGUEUR
                                               * d.longueur / moyenne))
    return s


def classer(demande: str) -> list[tuple[float, Gabarit, frozenset]]:
    """Tous les gabarits pertinents, du meilleur au moins bon, avec leur
    score et leurs themes. Sert au choix ET a expliquer le choix."""
    docs, df, moyenne = _corpus()
    etendue = _etendre(demande)
    piles, themes = piles_de(demande), themes_de(etendue)
    requete = _jetons(etendue)
    resultats = []
    for i, d in enumerate(docs):
        sert = _sert(d.g, piles)
        if sert is False:
            continue                     # autre pile serveur : jamais
        if not (sert or d.themes & themes or d.appel.intersection(requete)):
            continue                     # touche seulement le code : non
        s = _bm25(requete, d, df, len(docs), moyenne)
        s += BONUS_THEME * len(d.themes & themes)
        if sert:
            s += BONUS_PILE
        if s >= SEUIL:
            resultats.append((s, -i, d.g, d.themes & themes))
    resultats.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return [(s, g, th) for s, _, g, th in resultats]


def score(demande: str, g: Gabarit) -> float:
    return next((s for s, x, _ in classer(demande) if x == g), 0.0)


# Familles de types : un gabarit .htm sert une page .html, un .mjs un .js.
_FAMILLE_EXT = {".htm": ".html", ".mjs": ".js"}


def _famille(nom: str) -> str:
    ext = Path(nom).suffix.lower()
    return _FAMILLE_EXT.get(ext, ext)


def choisir(demande: str, n: int = MAX_GABARITS,
            fichier: str | None = None) -> list[Gabarit]:
    """Les n meilleurs, en cherchant a couvrir des besoins DIFFERENTS : pour
    « un site avec formulaire de contact », une page ET un formulaire — pas
    deux formulaires.

    `fichier` : le fichier a ecrire (chantier). Seuls les gabarits du MEME
    type sont proposes : montrer une page complete pendant la tache d'un
    script pousse un petit modele a ecrire des pages (quatrieme essai :
    menu.html donne pour js/app.js, et le modele a reecrit les 4 autres
    fichiers, 542 s perdues)."""
    classes = classer(demande)
    if fichier:
        voulu = _famille(fichier)
        classes = [c for c in classes if _famille(c[1].fichier) == voulu]
    choisis, couverts = [], set()
    for _, g, th in classes:                 # 1er passage : diversite
        if len(choisis) >= n:
            break
        if not choisis or (th - couverts):
            choisis.append(g)
            couverts |= th
    for _, g, _ in classes:                  # 2e passage : completer
        if len(choisis) >= n:
            break
        if g not in choisis:
            choisis.append(g)
    return choisis


def pour_prompt(demande: str, budget: int = BUDGET_CARACTERES,
                fichier: str | None = None) -> str:
    morceaux, total = [], 0
    for g in choisir(demande, fichier=fichier):
        texte = g.texte()
        if total + len(texte) > budget:
            continue
        total += len(texte)
        morceaux.append(f"--- {g.fichier} ({g.titre}) ---\n{texte}")
    if not morceaux:
        return ""
    return ("[savoir] Formes justes deja verifiees par les juges. Reprends "
            "leur structure (pas forcement leur texte) :\n"
            + "\n".join(morceaux))


def pour_regle(regle: str, budget: int = BUDGET_CORRECTION) -> str:
    """La forme juste complete qui evite ce defaut, ou "" s'il n'y en a pas
    (ou si elle depasse le budget)."""
    for g in tous():
        if regle in g.regles:
            texte = g.texte()
            if len(texte) <= budget:
                langage = g.fichier.rsplit(".", 1)[-1]
                return (f"[savoir] forme juste complete ({g.titre}) :\n"
                        f"```{langage}\n{texte}\n```")
    return ""
