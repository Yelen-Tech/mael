"""Les criteres de chaque tache : la liste que le modele recoit, et que MAEL
verifie LUI-MEME (decision du responsable, 07/10/2026).

Un petit modele a qui l'on demande « as-tu tout fait ? » repond oui. Ici
le modele voit la liste au moment d'ecrire ; la verification est faite par
lecture du fichier, comme pour la demande tenue. Une tache n'est validee
(puis verrouillee) que si tous ses criteres verifiables passent.

Criteres deduits du plan, sans deviner :
  - balise   : ce que le BUT de la tache nomme (formulaire -> <form>,
               menu -> <nav>, galerie -> <img>...) ;
  - lien     : dans un site de plusieurs pages, chaque page mene aux autres
               (sinon une page est introuvable : sixieme essai reel) ;
  - charge   : chaque page charge le CSS et le JavaScript prevus au plan ;
  - libre    : une consigne qu'on ne sait pas verifier — montree au modele,
               marquee « non verifie » dans le bilan, jamais bloquante.
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from .demande import exigences
from .juges import GRAVITE, Defaut

B = GRAVITE.BLOQUANT
NORME = "critere de la tache (plan du chantier)"
_PAGES = {".html", ".htm"}


@dataclass
class Critere:
    type: str                       # balise | lien | charge | libre
    texte: str                      # ce que le modele lit
    balises: list[str] = field(default_factory=list)
    cible: str = ""

    def vers_dict(self) -> dict:
        return asdict(self)


class _Lecture(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.balises: set[str] = set()
        self.liens: set[str] = set()
        self.charges: set[str] = set()

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        self.balises.add(tag)
        if tag == "a" and a.get("href"):
            self.liens.add(a["href"].split("#")[0].split("?")[0])
        if tag == "link" and a.get("href"):
            self.charges.add(a["href"])
        if tag == "script" and a.get("src"):
            self.charges.add(a["src"])

    handle_startendtag = handle_starttag


def _relatif(depuis: str, vers: str) -> str:
    return posixpath.relpath(vers, posixpath.dirname(depuis) or ".")


def deduire(fichier: str, but: str, plan: list[str]) -> list[Critere]:
    """Les criteres d'une tache, a partir de son but et du plan entier."""
    ext = Path(fichier).suffix.lower()
    c: list[Critere] = []
    from .arborescence import est_fragment
    if est_fragment(fichier):
        # Levier fragments-sans-criteres-de-page : un footer.html n'a ni
        # <main> ni <h1> ni le menu complet (mission 004 du 08/10).
        return [Critere("libre", but)]
    if ext in _PAGES:
        # Toute page complete : un contenu principal et un titre (WCAG
        # 1.3.1 / 2.4.1). photos.html en manquait (premier essai du
        # chantier) : ce n'etait qu'un conseil, c'est maintenant un critere.
        c.append(Critere("balise", "a un <main> (le contenu principal)",
                         balises=["main"]))
        c.append(Critere("balise", "a un <h1> (le titre de la page)",
                         balises=["h1"]))
        for mot, balises in exigences(but):
            c.append(Critere("balise", f"contient {mot} ("
                             + " ou ".join(f"<{b}>" for b in balises) + ")",
                             balises=list(balises)))
        autres = [p for p in plan if Path(p).suffix.lower() in _PAGES
                  and p != fichier]
        for p in autres:
            lien = _relatif(fichier, p)
            c.append(Critere("lien", f'mene a {p} : <a href="{lien}">',
                             cible=p))
        for p in plan:
            e = Path(p).suffix.lower()
            if e == ".css":
                c.append(Critere("charge", f'charge {p} : <link '
                                 f'rel="stylesheet" href="{_relatif(fichier, p)}">',
                                 cible=p))
            elif e in {".js", ".mjs"}:
                c.append(Critere("charge", f'charge {p} : <script src="'
                                 f'{_relatif(fichier, p)}" defer></script>',
                                 cible=p))
    if not c:
        c.append(Critere("libre", but))
    return c


def verifier(racine: Path, fichier: str, criteres: list[Critere]
             ) -> list[tuple[Critere, bool | None]]:
    """(critere, True / False / None = non verifiable) pour chaque critere."""
    try:
        texte = (Path(racine) / fichier).read_text(encoding="utf-8",
                                                   errors="replace")
    except OSError:
        return [(c, False if c.type != "libre" else None) for c in criteres]
    lu = _Lecture()
    if Path(fichier).suffix.lower() in _PAGES:
        try:
            lu.feed(texte)
            lu.close()
        except Exception:
            pass
    resultats = []
    for c in criteres:
        if c.type == "balise":
            ok = any(b in lu.balises for b in c.balises)
        elif c.type in {"lien", "charge"}:
            attendus = lu.liens if c.type == "lien" else lu.charges
            ok = any(posixpath.normpath(posixpath.join(
                posixpath.dirname(fichier), x)) == c.cible for x in attendus
                if not re.match(r"(?i)^([a-z]+:|//)", x))
        elif c.type == "vise":
            # Le script vise cet id : getElementById('x'), querySelector('#x')
            # ou le selecteur d'attribut [aria-controls="x"].
            i = re.escape(c.cible)
            ok = bool(re.search(
                rf"""getElementById\s*\(\s*['"]{i}['"]\s*\)"""
                rf"""|querySelector(?:All)?\s*\(\s*['"][^'"]*#{i}(?![\w-])"""
                rf"""|aria-controls\s*=\s*\\?['"]?{i}(?![\w-])""",
                _sans_commentaires_js(texte)))
        else:
            ok = None
        resultats.append((c, ok))
    return resultats


def _sans_commentaires_js(texte: str) -> str:
    from .contamination_php_java import _sans_commentaires
    return _sans_commentaires(texte, diese=False)


class _Commandes(HTMLParser):
    """Les elements qui en commandent un autre (aria-controls) : un bouton
    de menu, d'onglet, d'accordeon. Sans script, ils ne font rien."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paires: list[tuple[str, str, str]] = []   # (balise, id, cible)
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if a.get("id"):
            self.ids.add(a["id"])
        if a.get("aria-controls"):
            self.paires.append((tag, a.get("id", ""), a["aria-controls"]))

    handle_startendtag = handle_starttag


def pour_un_script(racine: Path, pages: list[str]) -> tuple[str, list[Critere]]:
    """Ce qu'un script doit faire, DEDUIT DES PAGES (quatrieme essai : avec
    pour seul but « le script des pages », le modele visait #galerie et
    #contact, qui n'existaient pas). Rend (but precis, criteres « vise »)."""
    lu = _Commandes()
    for p in pages:
        try:
            lu.feed((Path(racine) / p).read_text(encoding="utf-8",
                                                 errors="replace"))
        except (OSError, Exception):
            continue
    consignes, criteres, vus = [], [], set()
    for tag, ident, cible in lu.paires:
        if cible not in lu.ids or (ident, cible) in vus:
            continue
        vus.add((ident, cible))
        bouton = f"#{ident}" if ident else f'[aria-controls="{cible}"]'
        consignes.append(f"le {tag} {bouton} ouvre et ferme #{cible} "
                         "(bascule l'attribut hidden de la cible et "
                         "aria-expanded du bouton)")
        if ident:
            criteres.append(Critere("vise", f"vise #{ident} (le {tag})",
                                    cible=ident))
        criteres.append(Critere("vise", f"vise #{cible} (l'element commande)",
                                cible=cible))
    if not consignes:
        return ("aucun comportement n'est demande par les pages : un script "
                "minimal, qui ne vise AUCUN element absent des pages"), []
    return "; ".join(consignes), criteres


def manques(racine: Path, fichier: str, criteres: list[Critere]
            ) -> list[Defaut]:
    """Les criteres verifiables non tenus, en defauts bloquants — avec, dans
    le message, ce qu'il faut ecrire."""
    return [Defaut(fichier, 1, "critere-non-tenu", B,
                   f"critere de la tache non tenu : {c.texte}", NORME)
            for c, ok in verifier(racine, fichier, criteres) if ok is False]
