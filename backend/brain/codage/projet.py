"""Juges du PROJET ENTIER : ce qu'aucun fichier ne montre a lui seul.

Premier juge : le selecteur mort. Un script qui cherche un element
(getElementById, querySelector...) que AUCUNE page du projet ne contient
ne fera jamais rien — ou plantera s'il ne verifie pas le resultat
(cinquieme essai reel, 07/10/2026 : `querySelector('form#contact')` alors
que l'id « contact » etait porte par la <section>).

Contre-juge (zero faux positif, doc 15) :
  - les elements que le script CREE lui-meme comptent comme existants :
    createElement('x'), id = "x", setAttribute('id', 'x'), classList.add,
    et tout id="..." / class="..." ecrit dans une chaine du script ;
  - un selecteur construit (template `${...}`, concatenation) n'est pas
    juge : on ne devine pas ;
  - pseudo-classes et attributs ([type=email], :hover) ne sont pas juges,
    seuls la balise, l'id et les classes le sont ;
  - seuls les scripts du NAVIGATEUR sont lus (pas un serveur Node), et
    seulement s'il y a des pages HTML dans le projet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from .juges import GRAVITE, Defaut

B = GRAVITE.BLOQUANT
NORME = "DOM Living Standard — selecteur sans cible (code mort)"


@dataclass(frozen=True)
class Element:
    fichier: str
    ligne: int
    balise: str
    ident: str
    classes: frozenset


class _Inventaire(HTMLParser):
    def __init__(self, fichier: str):
        super().__init__(convert_charrefs=True)
        self.fichier = fichier
        self.elements: list[Element] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        self.elements.append(Element(
            self.fichier, self.getpos()[0], tag.lower(), a.get("id", ""),
            frozenset(a.get("class", "").split())))

    handle_startendtag = handle_starttag


def inventaire(racine: Path, pages: list[str]) -> list[Element]:
    elements = []
    for p in pages:
        inv = _Inventaire(p)
        try:
            inv.feed((Path(racine) / p).read_text(encoding="utf-8",
                                                  errors="replace"))
            inv.close()
        except Exception:      # page illisible : ses juges le disent deja
            pass
        elements += inv.elements
    return elements


# ------------------------------------------------------- lecture du script
_APPELS = re.compile(
    r"\b(getElementById|querySelector|querySelectorAll|closest|matches)"
    r"\s*\(\s*(['\"])((?:(?!\2).)*)\2\s*\)")
_CLASSES_NOM = re.compile(r"\bgetElementsByClassName\s*\(\s*(['\"])([\w\s-]+)\1")
_CREES = {
    "ids": [re.compile(r"""\.id\s*=\s*(['"`])([\w-]+)\1"""),
            re.compile(r"""setAttribute\s*\(\s*(['"])id\1\s*,\s*(['"`])([\w-]+)\2"""),
            re.compile(r"""\bid\s*=\s*\\?(['"])([\w-]+)\\?\1""")],
    "classes": [re.compile(r"""classList\s*\.\s*(?:add|toggle|replace)\s*\(([^)]*)\)"""),
                re.compile(r"""className\s*[+]?=\s*(['"`])([^'"`]+)\1"""),
                re.compile(r"""\bclass\s*=\s*\\?(['"])([^'"\\]+)\\?\1""")],
    "balises": [re.compile(r"""createElement\s*\(\s*(['"])([\w-]+)\1""")],
}


def _sans_commentaires(js: str) -> str:
    from .contamination_php_java import _sans_commentaires as sc
    return sc(js, diese=False)


def crees_par_les_scripts(scripts: dict[str, str]) -> tuple[set, set, set]:
    ids, classes, balises = set(), set(), set()
    for js in scripts.values():
        code = _sans_commentaires(js)
        for m in _CREES["ids"][0].finditer(code):
            ids.add(m.group(2))
        for m in _CREES["ids"][1].finditer(code):
            ids.add(m.group(3))
        for m in _CREES["ids"][2].finditer(code):
            ids.add(m.group(2))
        for m in _CREES["classes"][0].finditer(code):
            classes.update(re.findall(r"['\"`]([\w-]+)['\"`]", m.group(1)))
        for motif in _CREES["classes"][1:]:
            for m in motif.finditer(code):
                classes.update(m.group(2).split())
        for m in _CREES["balises"][0].finditer(code):
            balises.add(m.group(2).lower())
    return ids, classes, balises


@dataclass(frozen=True)
class Morceau:
    balise: str
    ident: str
    classes: frozenset
    texte: str


def morceaux(selecteur: str) -> list[Morceau] | None:
    """Les parties simples d'un selecteur (« nav a.actif, #menu > li »).
    None si on ne sait pas le lire sans deviner."""
    if "${" in selecteur:
        return None
    l = []
    for groupe in selecteur.split(","):
        for partie in re.split(r"\s*[>+~]\s*|\s+", groupe.strip()):
            if not partie or partie == "*":
                continue
            propre = re.sub(r"\[[^\]]*\]|::?[\w-]+(?:\([^)]*\))?", "", partie)
            if not propre:
                continue
            m = re.fullmatch(r"([a-zA-Z][\w-]*)?((?:[#.][\w-]+)*)", propre)
            if not m:
                return None            # forme inconnue : on ne juge pas
            ident = re.findall(r"#([\w-]+)", m.group(2))
            l.append(Morceau(
                (m.group(1) or "").lower(), ident[0] if ident else "",
                frozenset(re.findall(r"\.([\w-]+)", m.group(2))), partie))
    return l


def _existe(m: Morceau, elements: list[Element]) -> bool:
    return any((not m.balise or e.balise == m.balise)
               and (not m.ident or e.ident == m.ident)
               and m.classes <= e.classes for e in elements)


def _conseil(m: Morceau, elements: list[Element]) -> str:
    """La correction exacte, quand on la connait."""
    if m.ident:
        porteur = next((e for e in elements if e.ident == m.ident), None)
        if porteur:
            return (f" — l'id « {m.ident} » est porte par <{porteur.balise}> "
                    f"({porteur.fichier} ligne {porteur.ligne}), pas par "
                    f"<{m.balise or '?'}> : ecris '#{m.ident}', ou donne un "
                    f"id a l'element vise")
        connus = sorted({e.ident for e in elements if e.ident})[:8]
        return (" — ids existants : " + ", ".join(connus) if connus
                else " — aucune page n'a d'id")
    if m.classes:
        connues = sorted({c for e in elements for c in e.classes})[:8]
        return (" — classes existantes : " + ", ".join(connues) if connues
                else "")
    return ""


def _ligne(texte: str, pos: int) -> int:
    return texte.count("\n", 0, pos) + 1


def selecteurs_morts(scripts: dict[str, str], elements: list[Element]
                     ) -> list[Defaut]:
    ids, classes, balises = crees_par_les_scripts(scripts)
    d = []
    for nom, js in scripts.items():
        code = _sans_commentaires(js)
        trouves = [(m.start(), m.group(1), m.group(3))
                   for m in _APPELS.finditer(code)]
        trouves += [(m.start(), "getElementsByClassName",
                     "." + ".".join(m.group(2).split()))
                    for m in _CLASSES_NOM.finditer(code)]
        for pos, fonction, sel in trouves:
            if fonction == "getElementById":
                parties = [Morceau("", sel, frozenset(), "#" + sel)]
            else:
                parties = morceaux(sel)
            if not parties:
                continue
            for m in parties:
                if (m.ident in ids or (m.classes and m.classes <= classes)
                        or (m.balise and m.balise in balises)):
                    continue               # cree par le script lui-meme
                if not _existe(m, elements):
                    d.append(Defaut(
                        nom, _ligne(code, pos), "selecteur-mort", B,
                        f"{fonction}('{sel}') : aucun element « {m.texte} » "
                        "dans les pages du projet, ce code ne fera jamais "
                        "rien" + _conseil(m, elements), NORME))
                    break
    return d


_NODE = re.compile(r"""\brequire\s*\(|^\s*import\s.+\sfrom\s+['"](?!\.)""",
                   re.M)


# --------------------------------------------------- le contrat d'API
# Banc de la chaine du 08/10/2026 : le script appelait /api/products, la
# route Flask etait /api/produits ; aucun juge ne le voyait, la page restait
# vide sans erreur. Un appel du navigateur doit viser une route du serveur.
_ROUTE_PY = re.compile(r"""@\w+\.(?:get|post|put|patch|delete|route|"""
                       r"""api_route)\(\s*['"](/[^'"]*)['"]""")
_ROUTE_JS = re.compile(r"""\b\w+\.(?:get|post|put|patch|delete|all|use)\(\s*"""
                       r"""['"`](/[^'"`]*)['"`]""")
_APPEL = re.compile(r"""\bfetch\(\s*['"`](/[^'"`?#$]*)""")


def _motif_route(route: str) -> re.Pattern:
    """/api/produits/<int:id>, /api/produits/{id}, /api/produits/:id ->
    une expression ; un segment variable accepte tout segment."""
    morceaux = []
    for seg in route.rstrip("/").split("/"):
        if re.fullmatch(r"<[^>]+>|\{[^}]+\}|:\w+", seg):
            morceaux.append(r"[^/]+")
        else:
            morceaux.append(re.escape(seg))
    return re.compile("^" + "/".join(morceaux) + "/?$")


def contrats_api(racine: Path, vus: list[str]) -> list[Defaut]:
    racine = Path(racine)
    routes: list[str] = []
    appels: list[tuple[str, int, str]] = []
    for f in vus:
        ext = Path(f).suffix.lower()
        if ext not in {".py", ".js", ".mjs", ".html", ".htm"}:
            continue
        texte = (racine / f).read_text(encoding="utf-8", errors="replace")
        if ext == ".py":
            routes += _ROUTE_PY.findall(texte)
        elif ext in {".js", ".mjs"} and _NODE.search(texte):
            routes += _ROUTE_JS.findall(texte)
        else:
            for m in _APPEL.finditer(texte):
                appels.append((f, texte.count("\n", 0, m.start()) + 1,
                               m.group(1)))
    if not routes:
        return []                     # pas de serveur au projet : rien a lier
    motifs = [_motif_route(r) for r in routes]
    d = []
    for f, ligne, chemin in appels:
        if not any(m.match(chemin.rstrip("/") or "/") for m in motifs):
            d.append(Defaut(
                f, ligne, "contrat-api", GRAVITE.BLOQUANT,
                f'fetch("{chemin}") : aucune route du serveur ne repond a ce '
                f"chemin (routes : {', '.join(sorted(set(routes))[:5])})",
                "contrat entre fichiers (plan du chantier)"))
    return d


def juger(racine: Path, vus: list[str]) -> list[Defaut]:
    """Les juges entre fichiers. Rien sans page HTML."""
    racine = Path(racine)
    pages = [f for f in vus if Path(f).suffix.lower() in {".html", ".htm"}]
    if not pages:
        return []
    contrats = contrats_api(racine, vus)
    scripts = {}
    for f in vus:
        if Path(f).suffix.lower() in {".js", ".mjs"}:
            texte = (racine / f).read_text(encoding="utf-8", errors="replace")
            if not _NODE.search(texte):        # un serveur Node : pas ici
                scripts[f] = texte
    # Les scripts ecrits dans les pages comptent aussi.
    for p in pages:
        texte = (racine / p).read_text(encoding="utf-8", errors="replace")
        for i, m in enumerate(re.finditer(
                r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", texte,
                re.S | re.I)):
            # On garde les lignes : le script commence la ou il est.
            scripts[f"{p}#script{i + 1}"] = "\n" * texte.count(
                "\n", 0, m.start(1)) + m.group(1)
    if not scripts:
        return contrats
    d = selecteurs_morts(scripts, inventaire(racine, pages))
    # Un script ecrit dans une page se rapporte a la page elle-meme.
    return contrats + [Defaut(x.fichier.split("#script")[0], x.ligne,
                              x.regle, x.gravite, x.message, x.norme,
                              x.sources) for x in d]
