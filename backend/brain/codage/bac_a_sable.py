"""Couche 6 : executer pour de vrai, dans un bac a sable (doc 15).

Ce qui marche « sur le papier » doit marcher EN VRAI. Chaque page HTML du
projet est ouverte dans un navigateur sans ecran (Playwright, Apache 2.0,
Chromium) et l'on releve :
  - les erreurs a l'execution (exception non rattrapee, console.error) ;
  - les fichiers demandes par la page et introuvables (404) ;
  - l'accessibilite par axe-core (MPL-2.0, le moteur de reference), dont
    le CONTRASTE MESURE sur le rendu reel (WCAG 1.4.3) ;
  - le rendu sur telephone (375 px) : debordement horizontal (WCAG 1.4.10).

Regles du bac a sable :
  - HORS LIGNE : la page est servie depuis le dossier du projet par un petit
    serveur sur 127.0.0.1 ; toute requete vers l'exterieur est COUPEE (et
    notee). Rien ne sort de la machine ;
  - pas de service worker, pas de telechargement, boites de dialogue
    refusees ; un delai par page et un budget total (machine de 8 Go) ;
  - axe-core est embarque (vendor/axe-core) et son empreinte verifiee :
    un fichier modifie n'est pas injecte ;
  - absent (Playwright, Chromium) ou en panne = DIT dans le bilan, jamais
    « rien a signaler » ;
  - contre-juge : on ne releve que les « violations » d'axe-core, jamais ses
    cas « a verifier » (un juge qui crie au loup perd la confiance).

Comme en couche 5, la lecture des resultats (`lire_axe`, `ligne_de`,
`lieu_erreur`) est faite de fonctions pures : elles se testent sans
navigateur, sur des resultats enregistres.

Le code SERVEUR (Flask, FastAPI, Express, Django, PHP, Java) n'est PAS
execute (decision du 07/10/2026) : il est lu par les couches 1 a 5, dont le
suivi de contamination. Le bilan nomme les fichiers serveur concernes.
"""
from __future__ import annotations

import functools
import hashlib
import http.server
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from .juges import GRAVITE, Defaut

B, C = GRAVITE.BLOQUANT, GRAVITE.CONSEIL
SOURCE_AXE, SOURCE_NAV = "axe-core", "navigateur"

AXE = Path(__file__).parent / "vendor" / "axe-core" / "axe.min.js"
AXE_SHA256 = "b511cd9dec01c76f4b2ad1723b66b6db37d4c2eb4ed199076e1829d9ee7b75e3"
AXE_VERSION = "4.10.2"
# Normes demandees a axe-core : WCAG 2.0 / 2.1 / 2.2, niveaux A et AA.
AXE_NORMES = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]

DELAI_PAGE = 15_000     # ms pour charger une page
ATTENTE_SCRIPTS = 600   # ms apres le chargement : laisser les scripts agir
BUDGET = 120            # secondes pour tout le projet
PAGES_MAX = 20
NOEUDS_MAX = 5          # par regle axe : au-dela, c'est la meme faute
ORDINATEUR = {"width": 1280, "height": 800}
TELEPHONE = {"width": 375, "height": 667}


# ----------------------------------------------------------- familles
# Regle axe-core -> famille MAEL. Sert au vote croise avec les couches 1-5 :
# un img sans alt vu par nos juges ET par axe-core devient « certain ».
FAMILLES_AXE = {
    "image-alt": "img-alt", "input-image-alt": "img-alt",
    "role-img-alt": "img-alt", "svg-img-alt": "img-alt",
    "area-alt": "img-alt", "object-alt": "img-alt",
    "label": "champ-sans-label", "select-name": "champ-sans-label",
    "input-button-name": "nom-accessible", "button-name": "nom-accessible",
    "link-name": "nom-accessible", "frame-title": "nom-accessible",
    "html-has-lang": "lang", "html-lang-valid": "lang",
    "valid-lang": "lang",
    "document-title": "title",
    "duplicate-id": "id-duplique", "duplicate-id-aria": "id-duplique",
    "duplicate-id-active": "id-duplique",
    "meta-viewport": "zoom-bloque", "meta-viewport-large": "zoom-bloque",
    "heading-order": "titres-sautes",
    "landmark-one-main": "main",
    "color-contrast": "contraste", "color-contrast-enhanced": "contraste",
    "link-in-text-block": "contraste",
    "target-size": "cible-trop-petite",
    "aria-allowed-attr": "aria-invalide", "aria-required-attr": "aria-invalide",
    "aria-valid-attr": "aria-invalide", "aria-valid-attr-value": "aria-invalide",
    "aria-roles": "aria-invalide", "aria-hidden-focus": "aria-invalide",
    "list": "structure-liste", "listitem": "structure-liste",
    "nested-interactive": "nom-accessible",
    "autocomplete-valid": "autocomplete",
}
# Seules ces familles bloquent quand axe-core les juge graves (« serious »
# ou « critical ») : chacune a son remede (regle d'entree de remedes.py).
# Une regle axe inconnue de MAEL reste un CONSEIL : bloquer sans savoir
# corriger ferait tourner l'atelier a vide.
FAMILLES_BLOQUANTES = {
    "img-alt", "champ-sans-label", "nom-accessible", "lang", "title",
    "id-duplique", "zoom-bloque", "contraste", "aria-invalide",
    # WCAG 2.2 niveau AA (2.5.8) : bloquant depuis le 07/10/2026 (rigueur).
    "cible-trop-petite",
}


@dataclass
class Rapport:
    """Ce que la couche 6 a fait, pour le bilan : rien n'est cache."""
    pages: list[str] = field(default_factory=list)
    non_ouvertes: list[str] = field(default_factory=list)
    absent: str = ""          # raison si le navigateur n'a pas ete lance
    en_panne: list[str] = field(default_factory=list)
    axe: bool = False
    hors_budget: int = 0
    serveur: list[str] = field(default_factory=list)   # lu, pas execute
    reessais: list[str] = field(default_factory=list)  # ouvertes au 2e coup
    budget: float = 0.0                                # s, pour ce projet


dernier_rapport = Rapport()


# --------------------------------------------------- fonctions pures
_ATTRS_REPERES = ("id", "name", "for", "src", "href", "action", "alt",
                  "aria-label", "class")


def ligne_de(texte: str, extrait: str) -> int:
    """Ligne du source ou se trouve l'element `extrait` (HTML rendu par le
    navigateur). Le rendu n'est pas le source a l'identique : on cherche
    d'abord la balise ouvrante exacte, puis un attribut reperant (id, name,
    src...), puis une balise unique. 1 si on ne sait pas (jamais au hasard).
    """
    if not texte or not extrait:
        return 1

    def ligne(pos: int) -> int:
        return texte.count("\n", 0, pos) + 1

    ouvrante = extrait.split(">", 1)[0] + ">" if extrait.startswith("<") \
        else extrait
    pos = texte.find(ouvrante)
    # Seulement si la balise est UNIQUE : deux <p> nus, et le premier n'est
    # pas forcement le bon (quatrieme essai reel : le <p> du pied de page
    # etait attribue a celui d'une section).
    if pos >= 0 and texte.find(ouvrante, pos + 1) < 0:
        return ligne(pos)
    for attr in _ATTRS_REPERES:
        m = re.search(rf'\s{attr}\s*=\s*"([^"]+)"', ouvrante)
        if not m:
            continue
        valeur = re.escape(m.group(1))
        trouves = [x.start() for x in re.finditer(
            rf'\s{attr}\s*=\s*["\']?{valeur}["\'\s>/]', texte)]
        if len(trouves) == 1 or (trouves and attr in {"id", "for"}):
            return ligne(trouves[0])
    m = re.match(r"<([a-zA-Z][\w-]*)", extrait)
    if m:
        trouves = [x.start() for x in re.finditer(
            rf"<{m.group(1)}[\s>/]", texte, re.I)]
        if len(trouves) == 1:
            return ligne(trouves[0])
    return 1


def _critere(tags: list[str]) -> str:
    """['wcag2aa', 'wcag143'] -> '1.4.3'."""
    for t in tags or []:
        m = re.fullmatch(r"wcag(\d)(\d)(\d+)", t)
        if m:
            return ".".join(m.groups())
    return ""


# ------------------------------------------------ contraste : la correction
# Le juge ne dit pas seulement « trop pale » : il CALCULE la couleur juste et
# dit ou la changer (quatrieme essai reel, 07/10/2026 : phi4-mini savait que
# le bleu #007bff etait en cause, pas par quoi le remplacer ni ou).
_HEX = re.compile(r"^#([0-9a-f]{6})$")
_NOMMEES = {"#ffffff": ("white", "#fff"), "#000000": ("black", "#000")}


def _rgb(hexa: str) -> tuple[int, int, int] | None:
    m = _HEX.match((hexa or "").strip().lower())
    if not m:
        return None
    h = m.group(1)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luminance(hexa: str) -> float:
    """Luminance relative WCAG 2.x (definition de la norme)."""
    def canal(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(hexa)
    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


def contraste(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def ajuster(couleur: str, autre: str, exige: float) -> str:
    """La couleur la plus proche de `couleur` (meme teinte, plus sombre ou
    plus claire selon `autre`) dont le contraste avec `autre` atteint
    `exige` (+ une petite marge : les arrondis du navigateur)."""
    import colorsys
    r, g, b = (x / 255 for x in _rgb(couleur))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    sens = -1 if luminance(autre) > 0.18 else 1   # fond clair : on fonce
    for pas in range(1, 101):
        l2 = min(1.0, max(0.0, l + sens * pas / 100))
        r2, g2, b2 = colorsys.hls_to_rgb(h, l2, s)
        essai = "#" + "".join(f"{round(x * 255):02x}" for x in (r2, g2, b2))
        if contraste(essai, autre) >= exige + 0.1:
            return essai
    return "#000000" if sens < 0 else "#ffffff"


def motif_couleur(couleur: str) -> re.Pattern | None:
    """Les formes courantes d'une couleur dans un CSS (#007bff, #07f si
    possible, white, rgb(...)), sous forme d'expression reguliere."""
    rgb = _rgb(couleur)
    if not rgb:
        return None
    formes = {couleur.lower()}
    h = couleur.lower()[1:]
    if h[0] == h[1] and h[2] == h[3] and h[4] == h[5]:
        formes.add(f"#{h[0]}{h[2]}{h[4]}")
    formes.update(_NOMMEES.get(couleur.lower(), ()))
    formes.add("rgb({}, {}, {})".format(*rgb))
    formes.add("rgb({},{},{})".format(*rgb))
    # Les formes longues d'abord : « #007bff » avant « #07f ».
    return re.compile(
        r"(?i)(?<![\w#-])(?:" + "|".join(
            re.escape(f) for f in sorted(formes, key=len, reverse=True))
        + r")(?![\w-])")


def lieux_couleur(feuilles: dict[str, str], couleur: str
                  ) -> list[tuple[str, int]]:
    """(fichier, ligne) ou `couleur` est ecrite dans les feuilles de style
    (hors commentaires)."""
    motif = motif_couleur(couleur)
    if motif is None:
        return []
    lieux = []
    for nom, texte in feuilles.items():
        for i, l in enumerate(texte.splitlines(), 1):
            if motif.search(l.split("/*")[0]):
                lieux.append((nom, i))
    return lieux


def fonds_de_page(feuilles: dict[str, str]) -> set[str]:
    """Les couleurs de fond de la PAGE (html, body, :root), variables CSS
    resolues : #d7d7d7 pour « body { background: var(--fond) } »."""
    tout = "\n".join(feuilles.values())
    # Toutes les valeurs d'une variable : le mode sombre la redefinit.
    variables: dict[str, set[str]] = {}
    for m in re.finditer(r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\b", tout):
        variables.setdefault(m.group(1), set()).add(m.group(2).lower())
    fonds = set()
    for m in re.finditer(r"(?:^|[}\s,])(html|body|:root)\b[^{]*\{([^}]*)\}",
                         tout):
        for v in re.finditer(r"background(?:-color)?\s*:\s*([^;]+)",
                             m.group(2)):
            valeur = v.group(1).strip()
            var = re.search(r"var\(\s*(--[\w-]+)", valeur)
            if var and var.group(1) in variables:
                fonds |= variables[var.group(1)]
            hexa = re.search(r"#[0-9a-fA-F]{3,8}\b", valeur)
            if hexa:
                fonds.add(hexa.group(0).lower())
    return fonds


def correction_contraste(fg: str, bg: str, exige: float,
                         feuilles: dict[str, str], cible: str = "") -> str:
    """La consigne exacte. On change de preference le FOND s'il est ecrit
    dans le CSS (le texte blanc reste blanc), sinon le texte ; si aucune des
    deux n'est ecrite (couleur par defaut du navigateur, comme le bleu des
    liens #0000ee), on donne la regle a ajouter."""
    if not (_rgb(fg) and _rgb(bg)):
        return ""
    lieux_fg = lieux_couleur(feuilles, fg)
    # Couleur de lien par defaut du navigateur, jamais ecrite dans le CSS :
    # toucher au fond la-dessus casserait le reste (texte blanc du meme
    # fond) ; on donne une couleur au lien.
    defaut_navigateur = fg.lower() in {"#0000ee", "#551a8b", "#ee0000"}
    essais = [] if (defaut_navigateur and not lieux_fg) else \
        [(bg, fg, "fond"), (fg, bg, "texte")]
    # Le fond de TOUTE LA PAGE ne se change pas pour un bouton : le reste du
    # texte en depend (mission 003 du 08/10 : --fond corrige pour le texte
    # clair des boutons, le texte fonce du corps casse, et ainsi de suite —
    # une oscillation). On change alors le texte.
    if essais and bg.lower() in fonds_de_page(feuilles):
        essais.reverse()
    for change, garde, role in essais:
        lieux = lieux_fg if change is fg else lieux_couleur(feuilles, change)
        if lieux:
            juste = ajuster(change, garde, exige)
            fichier = lieux[0][0]
            lignes = ", ".join(str(l) for f, l in lieux if f == fichier)
            return (f" -> dans {fichier} (ligne(s) {lignes}) : remplace "
                    f"{change} ({role}) par {juste} "
                    f"(contraste {contraste(juste, garde):.1f}:1)")
    juste = ajuster(fg, bg, exige)
    selecteur = cible or "l'element"
    return (f" -> couleur du texte non ecrite dans le CSS (valeur par "
            f"defaut du navigateur) : ajoute {selecteur} {{ color: {juste}; }}"
            f" (contraste {contraste(juste, bg):.1f}:1)")


def _message_contraste(noeud: dict, feuilles: dict[str, str] | None = None
                       ) -> str:
    """Le contraste MESURE, en clair, et la correction calculee : « 3.97:1
    (#ffffff sur #007bff), 4.5:1 exige -> dans style.css (ligne 9) :
    remplace #007bff (fond) par #0062cc (4.6:1) »."""
    for verif in noeud.get("any", []) or []:
        d = verif.get("data") or {}
        if isinstance(d, dict) and d.get("contrastRatio"):
            fg, bg = d.get("fgColor", "?"), d.get("bgColor", "?")
            attendu = str(d.get("expectedContrastRatio", "4.5:1"))
            texte = (f"contraste mesure {d['contrastRatio']}:1 "
                     f"({fg} sur {bg}), {attendu} exige")
            try:
                exige = float(attendu.split(":")[0])
            except ValueError:
                exige = 4.5
            cible = ", ".join(noeud.get("target") or [])[:80]
            return texte + correction_contraste(fg, bg, exige,
                                                feuilles or {}, cible)
    return ""


def lire_axe(resultat: dict, nom: str, texte: str,
             ecran: str = "ordinateur",
             feuilles: dict[str, str] | None = None) -> list[Defaut]:
    """Resultat de axe.run() -> defauts MAEL. Seules les « violations »
    comptent ; les cas « incomplete » (a verifier a la main) sont ignores.
    `feuilles` : les CSS du projet, pour dire OU corriger un contraste.
    Deux noeuds qui donnent exactement le meme message (trois boutons du
    meme bleu) ne font qu'un defaut : une seule correction a faire."""
    d, dits = [], set()
    for v in (resultat or {}).get("violations", []) or []:
        ident = v.get("id", "")
        famille = FAMILLES_AXE.get(ident, f"axe:{ident}")
        grave = v.get("impact") in {"serious", "critical"}
        gravite = B if grave and famille in FAMILLES_BLOQUANTES else C
        critere = _critere(v.get("tags", []))
        norme = (f"WCAG 2.2 — {critere}" if critere
                 else "axe-core — bonne pratique d'accessibilite")
        lieu = "" if ecran == "ordinateur" else f", {ecran}"
        for n in (v.get("nodes") or [])[:NOEUDS_MAX]:
            precis = (_message_contraste(n, feuilles)
                      if famille == "contraste" else "")
            message = precis or v.get("help") or ident
            if precis:
                if precis in dits:
                    continue
                dits.add(precis)
            d.append(Defaut(nom, ligne_de(texte, n.get("html", "")), famille,
                            gravite,
                            f"{message} [axe-core {ident}{lieu}]", norme,
                            sources=(SOURCE_AXE,)))
    return d


_PILE = re.compile(r"(https?://[^\s()]+?):(\d+):\d+")


def lieu_erreur(pile: str, base: str, page: str) -> tuple[str, int]:
    """Premier fichier DU PROJET cite dans la pile d'appels d'une erreur
    JavaScript -> (fichier relatif, ligne). Sinon la page elle-meme, ligne 1.
    Une adresse exterieure n'est jamais retenue : ce n'est pas notre code."""
    for m in _PILE.finditer(pile or ""):
        url, ligne = m.group(1), int(m.group(2))
        if url.startswith(base):
            chemin = unquote(urlparse(url).path).lstrip("/")
            return (chemin or page), ligne
    return page, 1


def origine_404(page: str, texte: str, nom: str, feuilles: dict[str, str]
                ) -> tuple[str, int, str]:
    """Qui a demande ce fichier introuvable ? La page s'il y est ecrit ;
    sinon la feuille de style qui l'appelle (@import, url()) — c'est la
    qu'il faut corriger (cinquieme essai : un @import dans style.css,
    attribue a tort aux trois pages verrouillees)."""
    if nom in texte:
        return page, ligne_de(texte, nom), "fichier-absent"
    for feuille, contenu in feuilles.items():
        for i, l in enumerate(contenu.split("\n"), 1):
            if nom in l.split("/*")[0]:
                regle = ("import-absent" if "@import" in l
                         else "fichier-absent")
                return feuille, i, regle
    return page, 1, "fichier-absent"


def _famille_requete(chemin: str) -> str:
    return chemin.rsplit("/", 1)[-1] or chemin


# --------------------------------------------------- le petit serveur
class _Silencieux(http.server.SimpleHTTPRequestHandler):
    """Sert le dossier du projet, sans journal, sans lister les dossiers,
    sans servir les fichiers caches (.mael/, .git/, .env)."""

    def log_message(self, *args):
        pass

    def list_directory(self, path):
        self.send_error(404)
        return None

    def send_head(self):
        parties = unquote(urlparse(self.path).path).split("/")
        if any(p.startswith(".") and p not in {"", "."} for p in parties):
            self.send_error(404)
            return None
        return super().send_head()


def _serveur(racine: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    gestion = functools.partial(_Silencieux, directory=str(racine))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), gestion)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


# ------------------------------------------------------- disponibilite
def _axe_source() -> str | None:
    """Le script axe-core, seulement s'il est intact (empreinte)."""
    try:
        brut = AXE.read_bytes()
    except OSError:
        return None
    if hashlib.sha256(brut).hexdigest() != AXE_SHA256:
        return None
    return brut.decode("utf-8")


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        return None


# ------------------------------------------------------- execution
_DEBORDEMENT = """() => {
  const w = window.innerWidth;
  if (document.documentElement.scrollWidth <= w + 1) return null;
  for (const el of document.body ? document.body.querySelectorAll('*') : []) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.right > w + 1) return el.outerHTML.slice(0, 300);
  }
  return '';
}"""

_AXE_LANCER = """async (normes) => {
  const r = await axe.run(document, {
    runOnly: {type: 'tag', values: normes}, resultTypes: ['violations']});
  return {violations: r.violations.map(v => ({
    id: v.id, impact: v.impact, help: v.help, tags: v.tags,
    nodes: v.nodes.map(n => ({html: n.html, any: n.any,
      target: n.target.map(String)}))}))};
}"""


def _ouvrir_page(nav, base: str, nom: str, texte: str, axe: str | None,
                 rapport: Rapport, feuilles: dict[str, str] | None = None
                 ) -> list[Defaut]:
    d: list[Defaut] = []
    externes: set[str] = set()
    hote = urlparse(base).netloc

    def contexte(ecran):
        ctx = nav.new_context(viewport=ecran, service_workers="block",
                              accept_downloads=False,
                              java_script_enabled=True)

        def router(route):
            u = urlparse(route.request.url)
            if u.scheme in {"http", "https", "ws", "wss"} and u.netloc != hote:
                externes.add(u.netloc)
                return route.abort("blockedbyclient")
            return route.continue_()
        ctx.route("**/*", router)
        return ctx

    # --- ordinateur : erreurs, fichiers manquants, axe-core
    ctx = contexte(ORDINATEUR)
    try:
        page = ctx.new_page()
        page.on("dialog", lambda dlg: dlg.dismiss())
        erreurs: list[tuple[str, str]] = []
        console: list[str] = []
        manquants: list[str] = []
        page.on("pageerror", lambda e: erreurs.append(
            (getattr(e, "message", str(e)), getattr(e, "stack", "") or "")))
        page.on("console", lambda m: console.append(m.text)
                if m.type == "error" else None)

        def reponse(r):
            u = urlparse(r.url)
            if u.netloc == hote and r.status >= 400:
                manquants.append(unquote(u.path).lstrip("/"))
        page.on("response", reponse)

        page.goto(base + nom, wait_until="load", timeout=DELAI_PAGE)
        page.wait_for_timeout(ATTENTE_SCRIPTS)

        for message, pile in erreurs:
            fichier, ligne = lieu_erreur(pile, base, nom)
            d.append(Defaut(fichier, ligne, "js-erreur-execution", B,
                            f"erreur a l'execution : {message[:200]} "
                            "[navigateur]",
                            "ECMAScript — exception non rattrapee",
                            sources=(SOURCE_NAV,)))
        for chemin in dict.fromkeys(manquants):
            fichier, ligne, regle = origine_404(
                nom, texte, _famille_requete(chemin), feuilles or {})
            d.append(Defaut(fichier, ligne, regle, B,
                            f"« {chemin} » demande par "
                            f"{'la page' if fichier == nom else fichier} : "
                            "introuvable (404) [navigateur]", "lien casse",
                            sources=(SOURCE_NAV,)))
        # console.error : seulement ce qui n'est pas deja dit (404, exception
        # ou requete coupee par le bac a sable).
        dits = ("Failed to load resource", "net::ERR_BLOCKED_BY_CLIENT",
                "Uncaught")
        for texte_console in dict.fromkeys(console):
            if not any(x in texte_console for x in dits):
                d.append(Defaut(nom, 1, "console-erreur", C,
                                f"console.error : {texte_console[:200]} "
                                "[navigateur]", "console du navigateur",
                                sources=(SOURCE_NAV,)))
        if axe:
            page.add_script_tag(content=axe)
            d += lire_axe(page.evaluate(_AXE_LANCER, AXE_NORMES), nom, texte,
                          feuilles=feuilles)
            rapport.axe = True
    finally:
        ctx.close()

    # --- telephone : la page tient-elle dans 375 px ?
    ctx = contexte(TELEPHONE)
    try:
        page = ctx.new_page()
        page.on("dialog", lambda dlg: dlg.dismiss())
        page.goto(base + nom, wait_until="load", timeout=DELAI_PAGE)
        page.wait_for_timeout(ATTENTE_SCRIPTS)
        deborde = page.evaluate(_DEBORDEMENT)
        if deborde is not None:
            d.append(Defaut(nom, ligne_de(texte, deborde),
                            "debordement-mobile", C,
                            "sur telephone (375 px), la page deborde a droite : "
                            "defilement horizontal [navigateur]",
                            "WCAG 2.2 — 1.4.10 (redimensionnement)",
                            sources=(SOURCE_NAV,)))
    finally:
        ctx.close()

    if externes:
        d.append(Defaut(nom, 1, "ressource-externe", C,
                        "la page appelle l'exterieur ("
                        + ", ".join(sorted(externes)[:4])
                        + ") : coupe dans le bac a sable ; verifier qu'elle "
                        "reste utilisable sans [navigateur]",
                        "robustesse / vie privee", sources=(SOURCE_NAV,)))
    return d


_NODE_SERVEUR = re.compile(
    r"""require\s*\(\s*['"](?:express|http|https|fastify|koa)['"]"""
    r"""|from\s+['"](?:express|fastify|koa|node:http)['"]""")


# Les lecons de MAEL qui touchent le navigateur (leviers.py) : le chantier
# les pose avant de juger.
LECONS: set[str] = set()
BUDGET_PAR_PAGE = 60     # s : 8 Go, ordinateur + telephone + axe par page
BUDGET_MAX = 600


def budget_pour(nb_pages: int) -> float:
    """Lecon de la mission 09 : 6 pages sur 8 jamais ouvertes, budget fixe
    de 120 s. Avec la lecon, le budget suit le nombre de pages."""
    if "budget-selon-les-pages" not in LECONS:
        return BUDGET
    return min(BUDGET_MAX, max(BUDGET, BUDGET_PAR_PAGE * nb_pages))


def _reessayer(nav, base, nom, texte, axe, rapport, feuilles):
    global DELAI_PAGE
    avant = DELAI_PAGE
    DELAI_PAGE = avant * 2
    try:
        return _ouvrir_page(nav, base, nom, texte, axe, rapport, feuilles)
    except Exception:                       # noqa: BLE001
        return None
    finally:
        DELAI_PAGE = avant


def code_serveur(racine: Path, vus: list[str]) -> list[str]:
    """Les fichiers de code SERVEUR du projet : ils sont lus par les
    couches 1 a 5, jamais executes ici. Le bilan les nomme."""
    l = []
    for f in vus:
        ext = Path(f).suffix.lower()
        if ext in {".py", ".php", ".java"}:
            l.append(f)
        elif ext in {".js", ".mjs"}:
            try:
                texte = (Path(racine) / f).read_text(encoding="utf-8",
                                                     errors="replace")
            except OSError:
                continue
            if _NODE_SERVEUR.search(texte):
                l.append(f)
    return l


def juger(racine: Path, vus: list[str]) -> list[Defaut]:
    """Ouvre chaque page HTML du projet dans le navigateur sans ecran."""
    global dernier_rapport
    rapport = Rapport()
    dernier_rapport = rapport
    racine = Path(racine)
    rapport.serveur = code_serveur(racine, vus)
    pages = [f for f in vus if Path(f).suffix.lower() in {".html", ".htm"}]
    if not pages:
        return []
    if os.environ.get("MAEL_SANS_NAVIGATEUR") == "1":  # tests, banc
        rapport.absent = "desactive (MAEL_SANS_NAVIGATEUR=1)"
        return []
    sync_playwright = _playwright()
    if sync_playwright is None:
        rapport.absent = "Playwright absent (pip install playwright)"
        return []
    axe = _axe_source()
    if axe is None:
        rapport.en_panne.append("axe-core absent ou modifie (empreinte)")

    feuilles = {}
    for f in vus:
        if Path(f).suffix.lower() == ".css":
            try:
                feuilles[f] = (racine / f).read_text(encoding="utf-8",
                                                     errors="replace")
            except OSError:
                pass
    defauts: list[Defaut] = []
    srv, base = _serveur(racine)
    debut = time.monotonic()
    try:
        with sync_playwright() as pw:
            try:
                nav = pw.chromium.launch(headless=True)
            except Exception as exc:     # navigateur non installe, etc.
                rapport.absent = ("Chromium introuvable (playwright install "
                                  f"chromium) — {type(exc).__name__}")
                return []
            try:
                budget = rapport.budget = budget_pour(len(pages))
                for i, nom in enumerate(pages):
                    if i >= PAGES_MAX or time.monotonic() - debut > budget:
                        rapport.hors_budget = len(pages) - i
                        break
                    texte = (racine / nom).read_text(encoding="utf-8",
                                                     errors="replace")
                    try:
                        defauts += _ouvrir_page(nav, base, nom, texte, axe,
                                                rapport, feuilles)
                        rapport.pages.append(nom)
                    except Exception as exc:    # delai, page qui plante
                        if ("reessayer-page-expiree" in LECONS
                                and "Timeout" in type(exc).__name__):
                            # Lecon de la mission 04 (index.html en
                            # TimeoutError) : une seconde chance, delai
                            # double — une machine chargee n'est pas une
                            # page cassee.
                            reessai = _reessayer(nav, base, nom, texte, axe,
                                                 rapport, feuilles)
                            if reessai is not None:
                                defauts += reessai
                                rapport.pages.append(nom)
                                rapport.reessais.append(nom)
                                continue
                        rapport.non_ouvertes.append(
                            f"{nom} ({type(exc).__name__})")
            finally:
                nav.close()
    except Exception as exc:
        rapport.en_panne.append(f"navigateur ({type(exc).__name__})")
    finally:
        srv.shutdown()
        srv.server_close()
    return defauts


def limites() -> list[str]:
    """Ce que la couche 6 a fait ou pas, pour le bilan."""
    r = dernier_rapport
    l = []
    if r.pages:
        l.append(f"pages ouvertes dans un navigateur (ordinateur + telephone, "
                 f"hors ligne) : {len(r.pages)}"
                 + (f", accessibilite par axe-core {AXE_VERSION}"
                    if r.axe else ""))
    if r.absent:
        l.append(f"navigateur non lance — {r.absent} : contraste des couleurs "
                 "non mesure (WCAG 1.4.3), pages non executees")
    if r.pages and not r.axe:
        l.append("contraste des couleurs non mesure (axe-core indisponible)")
    if r.non_ouvertes:
        l.append("pages NON ouvertes (leurs verdicts manquent) : "
                 + ", ".join(r.non_ouvertes))
    if r.reessais:
        l.append("page(s) ouverte(s) au 2e essai (delai double) : "
                 + ", ".join(r.reessais))
    if r.hors_budget:
        l.append(f"{r.hors_budget} page(s) non ouverte(s) : budget de "
                 f"{r.budget or BUDGET:.0f} s ou {PAGES_MAX} pages atteint")
    if r.en_panne:
        l.append("couche 6 EN PANNE : " + ", ".join(r.en_panne))
    if r.serveur:
        noms = ", ".join(r.serveur[:5]) + (
            f" (+{len(r.serveur) - 5})" if len(r.serveur) > 5 else "")
        l.append(f"code serveur LU mais non execute (couches 1 a 5) : {noms}")
    return l
