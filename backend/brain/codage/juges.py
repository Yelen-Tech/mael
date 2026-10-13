"""Les juges du code : des regles pures, chacune rattachee a une norme nommee.

Un defaut porte TOUJOURS : le fichier, la ligne, la regle, la norme qui la
fonde, et ce qu'il faut faire. « C'est mal ecrit » n'est pas un defaut ;
« index.html:42, <img> sans alt — WCAG 2.2 critere 1.1.1 » en est un.

Gravites :
    BLOQUANT  -- le code est faux, dangereux ou hors norme : on renvoie le
                 modele corriger, et le bilan ne dit pas « conforme ».
    CONSEIL   -- bonne pratique non respectee : signale, non bloquant.

Aucun modele, aucun reseau. Les seuls outils externes appeles sont ceux qui
sont INSTALLES (node pour le JavaScript) ; absents, le bilan le dit au lieu
de pretendre avoir verifie.
"""
from __future__ import annotations

import enum
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


class GRAVITE(str, enum.Enum):
    BLOQUANT = "bloquant"
    CONSEIL = "conseil"


@dataclass(frozen=True)
class Defaut:
    fichier: str
    ligne: int
    regle: str
    gravite: GRAVITE
    message: str
    norme: str
    # Qui a vu ce defaut : « mael » (nos juges) et/ou des outils externes
    # (couche 5). Deux sources independantes = defaut CERTAIN (vote croise,
    # doc 15) ; une seule = PROBABLE.
    sources: tuple[str, ...] = ("mael",)

    @property
    def certain(self) -> bool:
        return len(set(self.sources)) >= 2

    def __str__(self) -> str:
        temoins = (f" — certain : {' + '.join(self.sources)}" if self.certain
                   else (f" — vu par {self.sources[0]}"
                         if self.sources != ("mael",) else ""))
        return (f"{self.fichier}:{self.ligne} [{self.gravite.value}] "
                f"{self.message} ({self.norme}){temoins}")


# Fichiers qu'on ne juge pas : ce n'est pas du code ecrit par l'utilisateur.
DOSSIERS_IGNORES = {".git", "node_modules", "venv", ".venv", "__pycache__",
                    "dist", "build", ".mael"}
EXTENSIONS = {".html", ".htm", ".css", ".js", ".mjs", ".jsx", ".py", ".php",
              ".java",
              # La base de donnees (09/10/2026) : schema, migrations, donnees.
              ".sql", ".prisma", ".cql"}
TAILLE_MAX = 500_000   # au-dela, ce n'est plus du code ecrit a la main


def _ligne(texte: str, position: int) -> int:
    return texte.count("\n", 0, position) + 1


# --------------------------------------------------------------- communs
# Secrets ecrits en dur : la faute la plus chere, quel que soit le langage.
_SECRETS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "cle d'acces AWS"),
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "cle d'API (format sk-)"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "jeton GitHub"),
    (re.compile(r"AIza[0-9A-Za-z_-]{35}"), "cle d'API Google"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
     "cle privee"),
    (re.compile(r"""(?ix)\b(?:password|passwd|mot_?de_?passe|secret|api_?key
                    |token)\b\s*[:=]\s*["'][^"'\s]{6,}["']"""),
     "mot de passe ou secret ecrit en dur"),
]
# Code laisse inacheve par le modele : il « resume » au lieu d'ecrire.
_INACHEVE = re.compile(
    r"(?im)^\s*(?://|#|/\*|<!--)\s*(?:\.\.\.|…|reste du code|rest of (?:the )?"
    r"code|todo: implement|a completer|à compléter|votre code ici|your code "
    r"here)")


def _juger_commun(nom: str, texte: str) -> list[Defaut]:
    defauts = []
    for motif, quoi in _SECRETS:
        for m in motif.finditer(texte):
            # Un exemple vide ou visiblement factice n'est pas un secret.
            extrait = m.group(0).lower()
            if any(f in extrait for f in ("example", "exemple", "xxxx",
                                          "changeme", "votre_", "your_")):
                continue
            defauts.append(Defaut(
                nom, _ligne(texte, m.start()), "secret-en-dur",
                GRAVITE.BLOQUANT,
                f"{quoi} dans le code : a lire depuis une variable "
                "d'environnement ou un coffre",
                "OWASP A07 / CWE-798"))
    for m in _INACHEVE.finditer(texte):
        defauts.append(Defaut(
            nom, _ligne(texte, m.start()), "code-inacheve", GRAVITE.BLOQUANT,
            "code laisse inacheve (« ... », « reste du code ») : ecrire le "
            "fichier en entier", "completude"))
    return defauts


# ------------------------------------------------------------------ HTML
_VIDES = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
          "meta", "source", "track", "wbr"}
# Balises qu'HTML ferme implicitement : leur fermeture manquante n'est pas
# une faute de structure.
_FERMETURE_OPTIONNELLE = {"p", "li", "dt", "dd", "option", "tr", "td", "th",
                          "thead", "tbody", "tfoot", "colgroup", "optgroup",
                          "rt", "rp", "html", "head", "body"}
_CHAMPS = {"input", "select", "textarea"}
_SANS_ETIQUETTE = {"hidden", "submit", "button", "reset", "image"}
_EVENEMENTS = re.compile(r"^on[a-z]+$")


class _AnalyseHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pile: list[tuple[str, int]] = []
        self.balises: list[tuple[str, dict, int]] = []
        self.structure: list[tuple[int, str]] = []
        self.doctype = False
        self.textes_label: dict[str, int] = {}
        self.dans_label = 0
        self.champs_dans_label: set[int] = set()
        self.titre = ""
        self._dans_titre = False
        self.dans_bouton_ou_lien: list[list[str]] = []

    def handle_decl(self, decl):
        if decl.lower().startswith("doctype html"):
            self.doctype = True

    def handle_starttag(self, tag, attrs):
        ligne = self.getpos()[0]
        a = {k.lower(): (v if v is not None else "") for k, v in attrs}
        self.balises.append((tag, a, ligne))
        if tag == "label":
            self.dans_label += 1
            if a.get("for"):
                self.textes_label[a["for"]] = ligne
        if tag in _CHAMPS and self.dans_label:
            self.champs_dans_label.add(len(self.balises) - 1)
        if tag == "title":
            self._dans_titre = True
        if tag in {"a", "button"}:
            self.dans_bouton_ou_lien.append([])
        if tag not in _VIDES:
            self.pile.append((tag, ligne))

    def handle_startendtag(self, tag, attrs):
        # <img ... /> : meme traitement, sans empiler.
        ligne = self.getpos()[0]
        a = {k.lower(): (v if v is not None else "") for k, v in attrs}
        self.balises.append((tag, a, ligne))
        if tag in _CHAMPS and self.dans_label:
            self.champs_dans_label.add(len(self.balises) - 1)

    def handle_endtag(self, tag):
        ligne = self.getpos()[0]
        if tag == "label":
            self.dans_label = max(0, self.dans_label - 1)
        if tag == "title":
            self._dans_titre = False
        if tag in {"a", "button"} and self.dans_bouton_ou_lien:
            contenu = "".join(self.dans_bouton_ou_lien.pop()).strip()
            ouvrante = next((b for b in reversed(self.balises)
                             if b[0] == tag), None)
            if ouvrante is not None and not contenu:
                self.structure.append((ligne, f"vide:{tag}:{ouvrante[2]}"))
        if tag in _VIDES:
            return
        # Remonter la pile : tout ce qui est saute sans fermeture optionnelle
        # est une balise mal fermee.
        for i in range(len(self.pile) - 1, -1, -1):
            if self.pile[i][0] == tag:
                for nom, l in self.pile[i + 1:]:
                    if nom not in _FERMETURE_OPTIONNELLE:
                        self.structure.append((l, f"non-fermee:{nom}"))
                del self.pile[i:]
                return
        self.structure.append((ligne, f"fermeture-orpheline:{tag}"))

    def handle_data(self, data):
        if self._dans_titre:
            self.titre += data
        for pile in self.dans_bouton_ou_lien:
            pile.append(data)


def _juger_html(nom: str, texte: str, dossier: Path | None) -> list[Defaut]:
    d: list[Defaut] = []

    def ajouter(ligne, regle, gravite, message, norme):
        d.append(Defaut(nom, ligne, regle, gravite, message, norme))

    p = _AnalyseHTML()
    try:
        p.feed(texte)
        p.close()
    except Exception as exc:  # noqa: BLE001 — html.parser est tolerant ;
        ajouter(1, "html-illisible", GRAVITE.BLOQUANT,  # s'il casse, on le dit
                f"HTML illisible : {exc}", "HTML Living Standard")
        return d

    page_complete = bool(re.search(r"(?i)<html", texte))
    balises = p.balises

    def premieres(tag):
        return [b for b in balises if b[0] == tag]

    if page_complete:
        if not p.doctype:
            ajouter(1, "doctype", GRAVITE.BLOQUANT,
                    "<!DOCTYPE html> manquant (le navigateur passe en mode "
                    "quirks)", "HTML Living Standard §13.1.1")
        html = premieres("html")
        if html and not html[0][1].get("lang"):
            ajouter(html[0][2], "lang", GRAVITE.BLOQUANT,
                    "<html> sans attribut lang (ex. lang=\"fr\")",
                    "WCAG 2.2 — 3.1.1")
        metas = premieres("meta")
        if not any("charset" in m[1] for m in metas):
            ajouter(1, "charset", GRAVITE.BLOQUANT,
                    "<meta charset=\"utf-8\"> manquant", "HTML §4.2.5.4")
        if not any(m[1].get("name", "").lower() == "viewport" for m in metas):
            ajouter(1, "viewport", GRAVITE.BLOQUANT,
                    "<meta name=\"viewport\" ...> manquant : page illisible "
                    "sur telephone", "WCAG 2.2 — 1.4.10 (reflow)")
        for m in metas:
            if (m[1].get("name", "").lower() == "viewport" and re.search(
                    r"user-scalable\s*=\s*(no|0)|maximum-scale\s*=\s*1(\.0)?\b",
                    m[1].get("content", ""))):
                ajouter(m[2], "zoom-bloque", GRAVITE.BLOQUANT,
                        "le viewport interdit le zoom", "WCAG 2.2 — 1.4.4")
        if not p.titre.strip():
            ajouter(1, "title", GRAVITE.BLOQUANT,
                    "<title> absent ou vide", "WCAG 2.2 — 2.4.2")
        h1 = premieres("h1")
        if not h1:
            ajouter(1, "h1", GRAVITE.CONSEIL,
                    "aucun titre <h1> dans la page", "WCAG 2.2 — 1.3.1")
        elif len(h1) > 1:
            ajouter(h1[1][2], "h1-multiple", GRAVITE.CONSEIL,
                    f"{len(h1)} titres <h1> : un seul par page est plus clair",
                    "WCAG 2.2 — 1.3.1")
        if not premieres("main"):
            ajouter(1, "main", GRAVITE.CONSEIL,
                    "pas de <main> : les lecteurs d'ecran ne trouvent pas le "
                    "contenu principal", "WCAG 2.2 — 1.3.1 / 2.4.1")

    # Ordre des titres : on ne saute pas de h2 a h4.
    niveau_prec = 0
    for tag, _, ligne in balises:
        if re.fullmatch(r"h[1-6]", tag):
            n = int(tag[1])
            if niveau_prec and n > niveau_prec + 1:
                ajouter(ligne, "titres-sautes", GRAVITE.CONSEIL,
                        f"titre <{tag}> apres <h{niveau_prec}> : niveau saute",
                        "WCAG 2.2 — 1.3.1")
            niveau_prec = n

    # Ancre interne sans cible : href="#contact" sans id="contact" ne mene
    # nulle part (premier essai reel, 07/10/2026). Seulement sur une page
    # complete : un fragment de page peut viser un id pose ailleurs.
    # « # » seul et « #top » sont definis par la norme (haut de page).
    if page_complete:
        cibles = {a["id"] for _, a, _ in balises if a.get("id")} | {
            a["name"] for t, a, _ in balises if t == "a" and a.get("name")}
        for tag, a, ligne in balises:
            href = a.get("href", "")
            if tag == "a" and href.startswith("#"):
                ancre = href[1:]
                if ancre and ancre.lower() != "top" and ancre not in cibles:
                    ajouter(ligne, "ancre-absente", GRAVITE.BLOQUANT,
                            f"href=\"{href}\" : aucun element id=\"{ancre}\" "
                            "dans la page (lien mort)",
                            "HTML §7.4.6.4 — lien casse")

    ids: dict[str, int] = {}
    for i, (tag, a, ligne) in enumerate(balises):
        if "id" in a:
            if a["id"] in ids:
                ajouter(ligne, "id-duplique", GRAVITE.BLOQUANT,
                        f"id « {a['id']} » deja utilise ligne {ids[a['id']]}",
                        "HTML §3.2.6.1")
            ids.setdefault(a["id"], ligne)
        if tag == "img" and "alt" not in a:
            ajouter(ligne, "img-alt", GRAVITE.BLOQUANT,
                    "<img> sans alt (alt=\"\" si l'image est decorative)",
                    "WCAG 2.2 — 1.1.1")
        if tag in _CHAMPS and a.get("type", "text").lower() not in _SANS_ETIQUETTE:
            etiquete = (a.get("id") in p.textes_label
                        or i in p.champs_dans_label
                        or a.get("aria-label") or a.get("aria-labelledby")
                        or a.get("title"))
            if not etiquete:
                ajouter(ligne, "champ-sans-label", GRAVITE.BLOQUANT,
                        f"<{tag}> sans etiquette (<label for> ou aria-label) ; "
                        "un placeholder ne suffit pas", "WCAG 2.2 — 1.3.1 / 4.1.2")
        if tag == "a" and a.get("target") == "_blank":
            rel = a.get("rel", "").lower()
            if "noopener" not in rel and "noreferrer" not in rel:
                ajouter(ligne, "blank-noopener", GRAVITE.CONSEIL,
                        "lien target=\"_blank\" sans rel=\"noopener\"",
                        "OWASP — reverse tabnabbing")
        if tag == "a" and "href" in a and a["href"].strip().lower().startswith(
                "javascript:"):
            ajouter(ligne, "href-javascript", GRAVITE.BLOQUANT,
                    "href=\"javascript:...\" : utiliser un <button> et un "
                    "ecouteur d'evenement", "OWASP A03 / CSP")
        if tag == "button" and "type" not in a:
            ajouter(ligne, "button-type", GRAVITE.CONSEIL,
                    "<button> sans type : il soumet le formulaire par defaut",
                    "HTML §4.10.6")
        for attr in a:
            if _EVENEMENTS.match(attr):
                # Bloquant depuis le 07/10/2026 (rigueur demandee par le
                # responsable) : notre propre consigne l'interdit, et une
                # page sous CSP stricte ne l'executerait pas.
                ajouter(ligne, "evenement-en-ligne", GRAVITE.BLOQUANT,
                        f"gestionnaire en ligne {attr}=... : incompatible avec "
                        "une politique CSP stricte", "OWASP — CSP")
                break
        for attr in ("src", "href", "action"):
            v = a.get(attr, "")
            if v.lower().startswith("http://") and tag in {
                    "script", "link", "img", "iframe", "form", "source"}:
                ajouter(ligne, "contenu-mixte", GRAVITE.BLOQUANT,
                        f"{attr} en http:// : bloque ou intercepte sous HTTPS",
                        "OWASP A02 / contenu mixte")
        if tag == "script" and a.get("src", "").startswith("https://") and \
                "integrity" not in a:
            ajouter(ligne, "sri", GRAVITE.CONSEIL,
                    "script externe sans integrity= (SRI)",
                    "OWASP A08 — integrite")
        if tag == "form":
            methode = a.get("method", "get").lower()
            mots = [b for b in balises[i:] if b[0] == "input"
                    and b[1].get("type", "").lower() == "password"]
            if mots and methode != "post":
                ajouter(ligne, "mdp-en-get", GRAVITE.BLOQUANT,
                        "formulaire avec mot de passe envoye en GET (le mot de "
                        "passe finit dans l'URL et les journaux)",
                        "OWASP A04")
        # Fichiers locaux references mais absents : le site est casse.
        if dossier is not None:
            for attr in ("src", "href"):
                v = a.get(attr, "")
                if (v and not re.match(r"(?i)^([a-z]+:|//|#|\?|data:|mailto:)", v)
                        and tag in {"img", "script", "link", "source", "a",
                                    "video", "audio"}):
                    cible = (dossier / v.split("#")[0].split("?")[0])
                    if v.split("#")[0] and not cible.exists():
                        ajouter(ligne, "fichier-absent", GRAVITE.BLOQUANT,
                                f"{attr}=\"{v}\" : ce fichier n'existe pas",
                                "lien casse")

    for ligne, quoi in p.structure:
        genre, _, rest = quoi.partition(":")
        if genre == "non-fermee":
            ajouter(ligne, "balise-non-fermee", GRAVITE.BLOQUANT,
                    f"<{rest}> jamais fermee", "HTML Living Standard")
        elif genre == "fermeture-orpheline":
            ajouter(ligne, "fermeture-orpheline", GRAVITE.BLOQUANT,
                    f"</{rest}> sans balise ouvrante", "HTML Living Standard")
        elif genre == "vide":
            tag, _, l_ouv = rest.partition(":")
            ouv = next((b for b in balises if b[0] == tag and str(b[2]) == l_ouv),
                       None)
            if ouv and not (ouv[1].get("aria-label")
                            or ouv[1].get("aria-labelledby")
                            or ouv[1].get("title")):
                # Un <a><img alt="..."></a> a un nom : on ne crie pas.
                interieur = [b for b in balises if b[2] >= ouv[2] and b[2] <= ligne
                             and b[0] in {"img", "svg"}
                             and (b[1].get("alt") or b[1].get("aria-label"))]
                if not interieur:
                    ajouter(int(l_ouv), "nom-accessible", GRAVITE.BLOQUANT,
                            f"<{tag}> sans texte ni aria-label : nom vide pour "
                            "un lecteur d'ecran", "WCAG 2.2 — 2.4.4 / 4.1.2")
    for nom_balise, ligne in p.pile:
        if nom_balise not in _FERMETURE_OPTIONNELLE:
            ajouter(ligne, "balise-non-fermee", GRAVITE.BLOQUANT,
                    f"<{nom_balise}> jamais fermee", "HTML Living Standard")

    # Le CSS et le JS en ligne passent aussi devant leurs juges.
    for m in re.finditer(r"(?is)<style[^>]*>(.*?)</style>", texte):
        decalage = _ligne(texte, m.start(1)) - 1
        d += [_decaler(x, decalage) for x in _juger_css(nom, m.group(1))]
    for m in re.finditer(r"(?is)<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", texte):
        decalage = _ligne(texte, m.start(1)) - 1
        d += [_decaler(x, decalage) for x in _juger_js(nom, m.group(1),
                                                         syntaxe=True)]
    return d


def _decaler(x: Defaut, n: int) -> Defaut:
    return Defaut(x.fichier, x.ligne + n, x.regle, x.gravite, x.message,
                  x.norme)


# ------------------------------------------------------------------- CSS
def _juger_css(nom: str, texte: str, dossier: Path | None = None
               ) -> list[Defaut]:
    d = []
    sans_commentaires = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ",
                               m.group(0)), texte, flags=re.S)
    profondeur = 0
    for i, c in enumerate(sans_commentaires):
        if c == "{":
            profondeur += 1
        elif c == "}":
            profondeur -= 1
            if profondeur < 0:
                d.append(Defaut(nom, _ligne(texte, i), "css-accolade",
                                GRAVITE.BLOQUANT, "accolade fermante en trop",
                                "CSS Syntax Level 3"))
                profondeur = 0
    if profondeur > 0:
        d.append(Defaut(nom, _ligne(texte, len(texte)), "css-accolade",
                        GRAVITE.BLOQUANT,
                        f"{profondeur} accolade(s) jamais fermee(s)",
                        "CSS Syntax Level 3"))
    for m in re.finditer(r"outline\s*:\s*(none|0)\b", sans_commentaires):
        # Supprimer le contour de focus sans le remplacer : clavier aveugle.
        bloc = sans_commentaires[max(0, m.start() - 200):m.start()]
        if ":focus" in bloc and "focus-visible" not in sans_commentaires:
            d.append(Defaut(nom, _ligne(texte, m.start()), "focus-invisible",
                            GRAVITE.BLOQUANT,
                            "contour de focus supprime sans remplacement",
                            "WCAG 2.2 — 2.4.7"))
    n = len(re.findall(r"!important", sans_commentaires))
    if n > 5:
        d.append(Defaut(nom, 1, "important", GRAVITE.CONSEIL,
                        f"{n} !important : la cascade n'est plus maitrisee",
                        "maintenabilite"))
    # Fichiers appeles par la feuille et absents (cinquieme essai reel :
    # « @import url('mise-en-page.css') », le nom d'un de nos gabarits, 404
    # sur toutes les pages). Chemins relatifs au DOSSIER DE LA FEUILLE.
    if dossier is not None:
        for m in re.finditer(
                r"""(@import\s+(?:url\(\s*)?|url\(\s*)['"]?([^'")\s]+)['"]?""",
                sans_commentaires):
            v = m.group(2)
            if re.match(r"(?i)^([a-z]+:|//|#|data:)", v):
                continue
            if (dossier / v.split("#")[0].split("?")[0]).exists():
                continue
            if m.group(1).startswith("@import"):
                d.append(Defaut(nom, _ligne(texte, m.start()), "import-absent",
                                GRAVITE.BLOQUANT,
                                f'@import "{v}" : ce fichier n\'existe pas',
                                "lien casse"))
            else:
                d.append(Defaut(nom, _ligne(texte, m.start()), "fichier-absent",
                                GRAVITE.BLOQUANT,
                                f'url="{v}" : ce fichier n\'existe pas',
                                "lien casse"))
    return d


# ------------------------------------------------------------ JavaScript
_JS_DANGERS = [
    (re.compile(r"\beval\s*\("), "eval() execute du texte comme du code",
     "OWASP A03 / CWE-95"),
    (re.compile(r"\bnew\s+Function\s*\("), "new Function() = eval deguise",
     "OWASP A03 / CWE-95"),
    (re.compile(r"\bdocument\.write\s*\("), "document.write()",
     "OWASP A03 — XSS"),
    (re.compile(r"\bset(?:Timeout|Interval)\s*\(\s*[\"'`]"),
     "setTimeout/setInterval avec une chaine = eval", "OWASP A03 / CWE-95"),
]
# innerHTML recoit autre chose qu'un litteral : porte ouverte au XSS.
_INNERHTML = re.compile(
    r"\.(?:innerHTML|outerHTML)\s*\+?=\s*(?![\"'][^\"'`$]*[\"']\s*;?\s*$)(.+)$",
    re.M)


def _juger_js(nom: str, texte: str, syntaxe: bool = True) -> list[Defaut]:
    # Couches 3 et 4 (acorn : arbre + contamination) d'abord ; les motifs
    # ci-dessous ne servent qu'en secours, si node ou l'analyseur manquent.
    from .analyse_js import analyser
    arbre = analyser(nom, texte)
    if arbre is not None:
        return arbre
    d = []
    for motif, quoi, norme in _JS_DANGERS:
        for m in motif.finditer(texte):
            d.append(Defaut(nom, _ligne(texte, m.start()), "js-dangereux",
                            GRAVITE.BLOQUANT, quoi, norme))
    for m in _INNERHTML.finditer(texte):
        valeur = m.group(1).strip()
        if re.fullmatch(r"[\"'`][^\"'`$]*[\"'`];?", valeur):
            continue  # litteral pur, sans interpolation
        d.append(Defaut(nom, _ligne(texte, m.start()), "innerhtml",
                        GRAVITE.BLOQUANT,
                        "innerHTML recoit une valeur construite : utiliser "
                        "textContent ou createElement", "OWASP A03 — XSS (CWE-79)"))
    if re.search(r"(?m)^\s*var\s", texte):
        d.append(Defaut(nom, _ligne(texte, re.search(r"(?m)^\s*var\s",
                        texte).start()), "js-var", GRAVITE.CONSEIL,
                        "var : preferer const / let", "ECMAScript 2015+"))
    # node --check ne lit pas le JSX : sans l'analyseur, la syntaxe d'un
    # .jsx n'est pas verifiee (et limites() le dit).
    if syntaxe and not nom.lower().endswith(".jsx"):
        d += _syntaxe_js(nom, texte)
    return d


def node_disponible() -> str | None:
    return shutil.which("node")


def _syntaxe_js(nom: str, texte: str) -> list[Defaut]:
    """`node --check` sur une copie temporaire : la vraie analyse du moteur,
    pas une imitation. Module (import/export) ou script, selon le texte."""
    node = node_disponible()
    if not node or not texte.strip():
        return []
    module = re.search(r"(?m)^\s*(?:import|export)\b", texte) is not None
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / ("verif.mjs" if module else "verif.js")
        f.write_text(texte, encoding="utf-8")
        try:
            r = subprocess.run([node, "--check", str(f)], capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return []
    if r.returncode == 0:
        return []
    sortie = r.stderr or r.stdout
    m = re.search(r"verif\.m?js:(\d+)", sortie)
    message = next((l.strip() for l in sortie.splitlines()
                    if re.match(r"\s*\w*Error\b", l)), "erreur de syntaxe")
    return [Defaut(nom, int(m.group(1)) if m else 1, "js-syntaxe",
                   GRAVITE.BLOQUANT, message, "ECMAScript")]


# ---------------------------------------------------------------- Python
_PY_DANGERS = [
    (re.compile(r"(?<![\w.])(?:eval|exec)\s*\("), "eval/exec",
     "OWASP A03 / CWE-95", GRAVITE.BLOQUANT),
    (re.compile(r"shell\s*=\s*True"), "subprocess avec shell=True",
     "OWASP A03 / CWE-78", GRAVITE.BLOQUANT),
    (re.compile(r"\bos\.system\s*\("), "os.system() passe par le shell",
     "OWASP A03 / CWE-78", GRAVITE.BLOQUANT),
    (re.compile(r"\bpickle\.loads?\s*\("), "pickle.load sur des donnees "
     "non sures = execution de code", "OWASP A08 / CWE-502", GRAVITE.BLOQUANT),
    (re.compile(r"\byaml\.load\s*\((?![^)]*SafeLoader)"),
     "yaml.load sans SafeLoader (utiliser yaml.safe_load)",
     "OWASP A08 / CWE-502", GRAVITE.BLOQUANT),
    (re.compile(r"verify\s*=\s*False"), "verification TLS desactivee",
     "OWASP A02 / CWE-295", GRAVITE.BLOQUANT),
    (re.compile(r"(?m)^\s*DEBUG\s*=\s*True"), "DEBUG = True ecrit en dur",
     "OWASP A05", GRAVITE.CONSEIL),
    (re.compile(r"\.run\s*\([^)]*debug\s*=\s*True"),
     "serveur lance en mode debug", "OWASP A05", GRAVITE.BLOQUANT),
    (re.compile(r"hashlib\.(?:md5|sha1)\s*\("), "md5/sha1 : trop faible pour "
     "un mot de passe ou une signature", "OWASP A02 / CWE-328",
     GRAVITE.CONSEIL),
    (re.compile(r"(?m)^\s*except\s*:"), "except: nu avale toutes les erreurs",
     "PEP 8", GRAVITE.CONSEIL),
]
# Requete SQL montee a la main avec des valeurs : injection SQL.
_SQL = re.compile(
    r"""(?ix)\.execute(?:many)?\s*\(\s*(?:f["']|["'][^"']*["']\s*(?:%|\+|\.format))"""
    r"""[^)]*?\b(?:select|insert|update|delete)\b""")
_SQL2 = re.compile(
    r"""(?ix)\.execute(?:many)?\s*\(\s*f?["'][^"']*\b(?:select|insert|update|"""
    r"""delete)\b[^"']*["']\s*(?:%|\+|\.format)""")
_SQL3 = re.compile(r"""(?ix)\.execute(?:many)?\s*\(\s*f["'][^"']*\{""")


def _juger_python(nom: str, texte: str) -> list[Defaut]:
    # Couches 3 et 4 d'abord : l'arbre du code et la contamination. Elles ne
    # se trompent pas sur un commentaire ni sur une chaine, et suivent les
    # alias d'import. Les motifs ci-dessous ne servent qu'en SECOURS, quand
    # le fichier ne se lit pas (erreur de syntaxe) : mieux vaut un juge
    # approximatif que pas de juge.
    from .analyse_py import analyser
    arbre = analyser(nom, texte)
    if arbre is not None:
        return arbre
    d = []
    try:
        compile(texte, nom, "exec")
    except SyntaxError as e:
        d.append(Defaut(nom, e.lineno or 1, "py-syntaxe", GRAVITE.BLOQUANT,
                        f"erreur de syntaxe : {e.msg}", "Python"))
    except ValueError as e:      # octet nul dans le source
        d.append(Defaut(nom, 1, "py-syntaxe", GRAVITE.BLOQUANT,
                        f"fichier illisible : {e}", "Python"))
    for motif, quoi, norme, gravite in _PY_DANGERS:
        for m in motif.finditer(texte):
            d.append(Defaut(nom, _ligne(texte, m.start()), "py-dangereux",
                            gravite, quoi, norme))
    vues = set()
    for motif in (_SQL, _SQL2, _SQL3):
        for m in motif.finditer(texte):
            l = _ligne(texte, m.start())
            if l in vues:
                continue
            vues.add(l)
            d.append(Defaut(nom, l, "injection-sql", GRAVITE.BLOQUANT,
                            "requete SQL construite avec des valeurs : passer "
                            "les valeurs en parametres (?, %s)",
                            "OWASP A03 — injection SQL (CWE-89)"))
    return d


# ------------------------------------------------------------- aiguillage
def juger_fichier(nom: str, texte: str, dossier: Path | None = None
                  ) -> list[Defaut]:
    """Juge un fichier d'apres son extension. `dossier` sert a verifier que
    les fichiers references (images, css, js) existent vraiment."""
    ext = Path(nom).suffix.lower()
    d = _juger_commun(nom, texte)
    if ext in {".html", ".htm"}:
        d += _juger_html(nom, texte, dossier)
    elif ext == ".css":
        d += _juger_css(nom, texte, dossier)
    elif ext in {".js", ".mjs", ".jsx"}:
        d += _juger_js(nom, texte)
    elif ext == ".py":
        d += _juger_python(nom, texte)
    elif ext == ".php":
        from .juges_php_java import juger_php
        d += juger_php(nom, texte)
    elif ext == ".java":
        from .juges_php_java import juger_java
        d += juger_java(nom, texte)
    # Un meme defaut vu par deux chemins (motif ET arbre, deux motifs SQL)
    # n'en fait qu'un : meme fichier, meme ligne, meme regle.
    vus, uniques = set(), []
    for x in d:
        cle = (x.fichier, x.ligne, x.regle)
        if cle not in vus:
            vus.add(cle)
            uniques.append(x)
    return sorted(uniques, key=lambda x: (x.gravite != GRAVITE.BLOQUANT,
                                          x.fichier, x.ligne))


def fichiers_du_projet(racine: Path) -> list[Path]:
    return sorted(
        p for p in racine.rglob("*")
        if p.is_file() and p.suffix.lower() in EXTENSIONS
        and not (set(p.relative_to(racine).parts) & DOSSIERS_IGNORES)
        and p.stat().st_size <= TAILLE_MAX)


def juger_projet(racine: Path, outils_externes: bool = True,
                 executer: bool = True) -> tuple[list[Defaut], list[str]]:
    """Juge tout un dossier. Rend (defauts, fichiers juges).

    Couches 1 a 4 fichier par fichier, puis la couche 5 (outils externes
    INSTALLES, voir outils.py) sur le dossier entier, puis la couche 6 (pages
    ouvertes dans un navigateur, voir bac_a_sable.py), et le vote croise."""
    racine = Path(racine)
    from .juges_php_java import echecs_contamination
    echecs_contamination.clear()      # le bilan parle de CE projet
    tous, vus = [], []
    for p in fichiers_du_projet(racine):
        rel = p.relative_to(racine).as_posix()
        texte = p.read_text(encoding="utf-8", errors="replace")
        tous += juger_fichier(rel, texte, dossier=p.parent)
        vus.append(rel)
    # Juges du projet entier (entre fichiers) : selecteurs morts...
    from . import juges_autres_bases, juges_nosql, juges_sql, projet, sens
    tous += projet.juger(racine, vus)
    # Le SENS : textes provisoires, boutons sans effet (examen du 09/10).
    tous += sens.juger(racine, vus)
    # La BASE : schema, cles, migrations, coherence code <-> schema.
    tous += (juges_sql.juger(racine, vus) + juges_nosql.juger(racine, vus)
             + juges_autres_bases.juger(racine, vus))
    if (outils_externes or executer) and vus:
        from . import outils
        if outils_externes:
            tous = outils.fusionner(tous, outils.juger(racine, vus))
        if executer:
            from . import bac_a_sable
            tous = outils.fusionner(tous, bac_a_sable.juger(racine, vus))
        tous.sort(key=lambda x: (x.gravite != GRAVITE.BLOQUANT, x.fichier,
                                 x.ligne))
    return tous, vus


def limites() -> list[str]:
    """Ce que les juges NE verifient PAS sur cette machine. Le bilan le dit."""
    from .analyse_js import disponible as analyse_js_disponible
    l = []
    if not node_disponible():
        l.append("syntaxe JavaScript non verifiee (node absent)")
    elif not analyse_js_disponible():
        l.append("JavaScript juge par motifs seulement (analyseur acorn "
                 "absent) : contamination non suivie")
    from .juges_php_java import limites as limites_php_java
    l += limites_php_java()
    from .outils import limites as limites_outils
    l += limites_outils()
    from .bac_a_sable import limites as limites_execution
    l += limites_execution()
    from .sens import limites as limites_sens
    l += limites_sens()
    from .juges_sql import limites as limites_sql
    l += limites_sql()
    from .juges_orm import limites as limites_orm
    l += limites_orm()
    return l
