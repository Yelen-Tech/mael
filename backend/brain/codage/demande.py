"""Fidelite a la demande : ce que les juges de NORME ne voient pas.

Premier essai reel (07/10/2026, phi4-mini) : la page finale etait
« conforme », mais le formulaire de contact demande avait DISPARU pendant
une correction. Un juge de norme ne peut pas le voir : une page sans
formulaire est parfaitement valide. Deux controles, faits par l'atelier
(qui connait la demande et l'etat d'avant chaque tour) :

  - contenu perdu : un tour de correction n'a pas le droit de « corriger »
    en supprimant. Un element cle (formulaire, champ, menu, section...)
    present avant le tour et absent apres = defaut bloquant ;
  - demande tenue : ce que la demande nomme explicitement (« formulaire »,
    « menu », « galerie »...) doit exister dans le resultat.

Volontairement simple et previsible : une liste de mots -> balises. Un mot
absent de la liste n'exige rien (on prefere ne rien exiger qu'exiger a
tort). Seules les pages HTML sont comptees.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

from .juges import GRAVITE, Defaut, fichiers_du_projet

B = GRAVITE.BLOQUANT
NORME = "ISO/IEC 25010 — adequation fonctionnelle (completude)"

# Elements dont la disparition est une perte de contenu. Les images n'y
# sont pas : retirer une image dont le fichier n'existe pas est une
# correction legitime (et l'atelier le propose lui-meme).
CLES = ("form", "input", "textarea", "select", "button", "nav", "main",
        "section", "article", "table", "ul", "ol", "header", "footer")
# Pour les champs, toute baisse compte : un formulaire qui perd un champ
# n'est plus celui qui etait demande.
CHAMPS = {"input", "textarea", "select"}

# Mot de la demande (sans accents, minuscules) -> balises dont UNE suffit.
EXIGENCES: list[tuple[str, tuple[str, ...], str]] = [
    (r"\bformulaires?\b", ("form",), "formulaire"),
    (r"\binscri(?:re|ption|s)\b", ("form",), "inscription"),
    (r"\bconnexion\b|\bse connecter\b|\blogin\b", ("form",), "connexion"),
    # « un menu de pains » est une CARTE de produits, pas une navigation
    # (second essai du chantier) : « menu de/des/du ... » ne compte que
    # s'il s'agit du site, des pages ou de la navigation.
    (r"\bmenus?\b(?!\s+(?:(?:de|des|du)\s+(?!\s)|d')"
     r"(?!navigation|site|pages?\b))"
     r"|\bnavigation\b|\bbarre de nav", ("nav",), "menu"),
    # « galerie marchande » est un lieu (un centre commercial), pas des images.
    (r"\bgaleries?\b(?!\s+marchandes?\b)|\bphotos\b",
     ("img", "picture", "figure"), "galerie"),
    (r"\btableaux?\b(?! de bord)", ("table",), "tableau"),
    (r"\bvideos?\b", ("video", "iframe"), "video"),
    (r"\bpied de page\b|\bfooter\b", ("footer",), "pied de page"),
    (r"\bboutons?\b", ("button", "a"), "bouton"),
]


def _normaliser(texte: str) -> str:
    t = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


class _Compteur(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.balises: Counter = Counter()

    def handle_starttag(self, tag, attrs):
        self.balises[tag] += 1

    handle_startendtag = handle_starttag


def compter(texte: str) -> Counter:
    p = _Compteur()
    try:
        p.feed(texte)
        p.close()
    except Exception:     # html.parser est tolerant ; au pire, rien compte
        pass
    return p.balises


def empreinte(racine: Path) -> dict[str, Counter]:
    """Les balises de chaque page HTML du projet, a un instant donne."""
    racine = Path(racine)
    e = {}
    for p in fichiers_du_projet(racine):
        if p.suffix.lower() in {".html", ".htm"}:
            e[p.relative_to(racine).as_posix()] = compter(
                p.read_text(encoding="utf-8", errors="replace"))
    return e


def perdus(avant: dict[str, Counter], apres: dict[str, Counter]
           ) -> list[Defaut]:
    """Elements cles presents AVANT le tour et disparus APRES."""
    d = []
    for fichier, compte in avant.items():
        nouveau = apres.get(fichier, Counter())
        for tag in CLES:
            n, m = compte.get(tag, 0), nouveau.get(tag, 0)
            if n and (m == 0 or (tag in CHAMPS and m < n)):
                d.append(Defaut(
                    fichier, 1, "contenu-perdu", B,
                    f"<{tag}> : {n} avant ce tour, {m} apres — une correction "
                    "ne doit rien supprimer de ce qui etait demande ; "
                    "remets-le en corrigeant seulement le defaut", NORME))
    return d


# « un bouton VERS la galerie », « un lien vers le menu » : la galerie est
# une DESTINATION, pas un contenu de cette page (premier essai du chantier :
# l'accueil se voyait exiger des images). Ces groupes sont retires avant de
# chercher les exigences.
_DESTINATION = re.compile(
    r"\b(?:vers|menant a|qui mene(?:nt)? a|pour aller (?:a|au|aux|sur)|"
    r"renvoyant (?:a|au|aux|vers)|liens? (?:a|au|aux))\s+[^,.;:]*?"
    r"(?=,|\.|;|:|\bet\b|\bavec\b|$)")


def exigences(demande: str) -> list[tuple[str, tuple[str, ...]]]:
    """(mot, balises) que la demande exige explicitement — sans les
    destinations (« vers la galerie »)."""
    t = _DESTINATION.sub(" ", _normaliser(demande))
    vus, l = set(), []
    for motif, balises, mot in EXIGENCES:
        if re.search(motif, t) and balises not in vus:
            vus.add(balises)
            l.append((mot, balises))
    return l


class _Liens(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.liens: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if href and not re.match(r"(?i)^([a-z]+:|//|#)", href):
                self.liens.append(href.split("#")[0].split("?")[0])


def atteignables(racine: Path, pages: list[str]) -> set[str] | None:
    """Les pages qu'un visiteur peut atteindre en partant de l'accueil
    (index.html a la racine), de lien en lien. None s'il n'y a pas
    d'accueil : on ne sait pas par ou le visiteur entre."""
    import posixpath
    entree = next((p for p in ("index.html", "index.htm") if p in pages),
                  None)
    if entree is None:
        return None
    vues, a_voir = {entree}, [entree]
    while a_voir:
        page = a_voir.pop()
        p = _Liens()
        try:
            p.feed((Path(racine) / page).read_text(encoding="utf-8",
                                                    errors="replace"))
        except (OSError, Exception):
            continue
        for lien in p.liens:
            cible = posixpath.normpath(posixpath.join(
                posixpath.dirname(page), lien))
            if cible.endswith("/") or cible == ".":
                cible = posixpath.join(cible, "index.html")
            if cible in pages and cible not in vues:
                vues.add(cible)
                a_voir.append(cible)
    return vues


def non_tenues(demande: str, apres: dict[str, Counter],
               visibles: set[str] | None = None) -> list[Defaut]:
    """Ce que la demande nomme et que le visiteur ne peut pas trouver.

    `visibles` : les pages atteignables depuis l'accueil. Un formulaire
    range dans une page vers laquelle aucun lien ne mene n'existe pas pour
    le visiteur (sixieme essai reel : formulaire.html, jamais liee)."""
    if not apres:
        return []           # pas de page : rien a exiger ici
    # La demande COMPRISE (fautes corrigees, anglais traduit) : sinon
    # « un formulere » ou « a contact form » n'exigeraient rien.
    from .comprehension import comprendre
    demande = comprendre(demande).texte
    total = Counter()
    for page, compte in apres.items():
        if visibles is None or page in visibles:
            total.update(compte)
    accueil = "index.html" if "index.html" in apres else sorted(apres)[0]
    d = []
    for mot, balises in exigences(demande):
        if any(total.get(b, 0) for b in balises):
            continue
        cachee = next((p for p, c in sorted(apres.items())
                       if any(c.get(b, 0) for b in balises)), None)
        if cachee:
            d.append(Defaut(
                accueil, 1, "demande-non-tenue", B,
                f"la demande parle de « {mot} » : il est dans {cachee}, mais "
                f"aucun lien n'y mene depuis l'accueil — ajoute <a href="
                f"\"{cachee}\"> dans {accueil} (ou mets-le dans {accueil})",
                NORME))
        else:
            d.append(Defaut(
                accueil, 1, "demande-non-tenue", B,
                f"la demande parle de « {mot} » : aucun "
                + " ni ".join(f"<{b}>" for b in balises)
                + " dans le projet", NORME))
    return d
