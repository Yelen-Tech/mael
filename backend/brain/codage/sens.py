"""Le juge du SENS : ce que les normes ne voient pas (sans modele).

Examen des 100 missions (09/10/2026) : des pages CONFORMES aux normes, mais
pas livrables a un client —
  - un pied de page qui affiche « Pied de page », un « Lorem ipsum », un
    « Votre texte ici », un numero « 00 00 00 00 » : du TEXTE PROVISOIRE ;
  - trois boutons « Ajouter au panier » qu'aucun script ne fait marcher
    (mission 001) : un BOUTON SANS EFFET.
Les deux se voient par lecture, sans deviner. Ce juge ne dit RIEN du fond
(une boulangerie qui vend du « Ravioli croustille ») : juger le sujet
demande le modele ou un lexique du metier — c'est un SAVOIR MANQUANT, dit
dans limites().
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from .juges import GRAVITE, Defaut

B = GRAVITE.BLOQUANT
NORME = "contenu livrable (juge du sens de MAEL)"

# Textes provisoires : en ENTIER (« Pied de page ») ou en morceau (lorem).
_PROVISOIRE_ENTIER = re.compile(
    r"^\s*(pied de page|en-tete|en tete|header|footer|titre|titre de la "
    r"page|sous-titre|texte|contenu|description|paragraphe|lien|image|"
    r"nom du produit|nom prenom|votre nom|mon site|site web)\s*\.?\s*$", re.I)
_PROVISOIRE_MORCEAU = re.compile(
    r"lorem ipsum|dolor sit amet|votre texte ici|texte ici|a completer|"
    r"à compléter|\bTODO\b|\bFIXME\b|\bXXX\b|insert(?:ez|er)? (?:ici|votre)|"
    r"votre (?:contenu|description|adresse) ici|exemple\.com|example\.com|"
    r"(?<!\d)(?:00[ .]?){4,}(?!\d)|123[- .]?456[- .]?789", re.I)


class _Lecture(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.textes: list[tuple[int, str]] = []        # (ligne, texte)
        self.boutons: list[dict] = []
        self._pile: list[str] = []
        self._bouton: dict | None = None
        self._dans_form = 0

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag in {"script", "style"}:
            self._pile.append(tag)
        if tag == "form":
            self._dans_form += 1
        if tag == "button":
            self._bouton = {"ligne": self.getpos()[0], "attrs": a,
                            "texte": "", "form": self._dans_form > 0}

    def handle_endtag(self, tag):
        if self._pile and tag == self._pile[-1]:
            self._pile.pop()
        if tag == "form":
            self._dans_form = max(0, self._dans_form - 1)
        if tag == "button" and self._bouton is not None:
            self.boutons.append(self._bouton)
            self._bouton = None

    def handle_data(self, data):
        if self._pile:
            return
        if self._bouton is not None:
            self._bouton["texte"] += data
        if data.strip():
            self.textes.append((self.getpos()[0], data.strip()))


def _lire(texte: str) -> _Lecture:
    lu = _Lecture()
    try:
        lu.feed(texte)
        lu.close()
    except Exception:                                   # noqa: BLE001
        pass
    return lu


def provisoires(nom: str, texte: str) -> list[Defaut]:
    d, vus = [], set()
    for ligne, t in _lire(texte).textes:
        m = _PROVISOIRE_ENTIER.match(t) or _PROVISOIRE_MORCEAU.search(t)
        if not m:
            continue
        cle = (ligne, m.group(0).lower())
        if cle in vus:
            continue
        vus.add(cle)
        d.append(Defaut(nom, ligne, "texte-provisoire", B,
                        f"texte provisoire « {t[:60]} » : ecris le vrai "
                        "contenu (ou retire l'element)", NORME))
    return d


def _vise(js: str, bouton: dict) -> bool:
    a = bouton["attrs"]
    if a.get("onclick") or a.get("aria-controls") or a.get("popovertarget") \
            or a.get("form") or a.get("formaction"):
        return True
    cibles = []
    if a.get("id"):
        i = re.escape(a["id"])
        cibles.append(rf"getElementById\(\s*['\"]{i}['\"]|#{i}(?![\w-])")
    for c in a.get("class", "").split():
        cibles.append(rf"\.{re.escape(c)}(?![\w-])|classList|"
                      rf"getElementsByClassName\(\s*['\"]{re.escape(c)}")
    for k in a:
        if k.startswith("data-"):
            cibles.append(rf"\[{re.escape(k)}|dataset\.")
    cibles.append(r"querySelectorAll\(\s*['\"]button|getElementsByTagName"
                  r"\(\s*['\"]button")
    return any(re.search(c, js) for c in cibles)


def boutons_sans_effet(pages: dict[str, str], scripts: str) -> list[Defaut]:
    d = []
    for nom, texte in pages.items():
        js = scripts + "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>",
                                            texte, re.S | re.I))
        for b in _lire(texte).boutons:
            genre = b["attrs"].get("type", "").lower()
            if genre in {"submit", "reset"} or (b["form"] and genre != "button"):
                continue                      # un bouton de formulaire agit
            if _vise(js, b):
                continue
            libelle = re.sub(r"\s+", " ", b["texte"]).strip() or "(sans texte)"
            d.append(Defaut(nom, b["ligne"], "bouton-sans-effet", B,
                            f"bouton « {libelle[:40]} » sans effet : aucun "
                            "script ne le vise (id, classe, data-...) — "
                            "ecris son comportement dans le script, ou "
                            "retire-le", NORME))
    return d


def juger(racine: Path, vus: list[str]) -> list[Defaut]:
    racine = Path(racine)
    pages, scripts = {}, []
    for f in vus:
        ext = Path(f).suffix.lower()
        try:
            texte = (racine / f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if ext in {".html", ".htm", ".php"}:
            pages[f] = texte
        elif ext in {".js", ".mjs", ".jsx"}:
            scripts.append(texte)
    d = []
    for nom, texte in pages.items():
        d += provisoires(nom, texte)
    d += boutons_sans_effet(pages, "\n".join(scripts))
    return d


def limites() -> list[str]:
    return ["sens du contenu non juge (produit hors du metier demande, "
            "texte incoherent) : demande le modele ou un lexique du metier "
            "— SAVOIR MANQUANT"]
