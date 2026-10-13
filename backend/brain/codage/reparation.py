"""Reparation automatique : quand le juge connait la correction EXACTE,
MAEL l'applique lui-meme, sans rappeler le modele.

Un tour de modele coute ~4 minutes sur une machine de 8 Go sans carte
graphique (essais reels du 07/10/2026). Remplacer une couleur par celle que
le juge a calculee, ou un chemin par le fichier qui existe, ne demande
aucune intelligence : le faire a la main du modele, c'est payer 4 minutes
pour un rechercher-remplacer.

Regles :
  - seulement des corrections SURES et SANS CHOIX : la couleur calculee,
    le chemin d'un fichier homonyme qui existe, une ligne obligatoire et
    toujours identique (doctype, charset, viewport), rel="noopener" ;
  - jamais de contenu invente (un alt, un texte, une langue : au modele) ;
  - on ne remplace que si le texte attendu est EXACTEMENT a la ligne dite ;
    sinon on ne touche a rien (le modele s'en chargera) ;
  - chaque reparation passe par l'espace (sauvegarde de l'original) et est
    DITE dans le bilan et au modele (pour qu'il ne la defasse pas).
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path

from .espace import CheminRefuse, Espace
from .juges import Defaut


@dataclass(frozen=True)
class Reparation:
    fichier: str
    ligne: int
    quoi: str
    provisoire: bool = False      # image de remplacement, a remplacer

    def __str__(self) -> str:
        return f"{self.fichier}:{self.ligne} {self.quoi}"


def _image_provisoire(espace: Espace, d: Defaut, ligne: str | None
                      ) -> tuple[Reparation | None, str]:
    """Photo appelee mais absente -> image neutre au bon chemin (option A,
    decision du responsable). (reparation, raison si impossible)."""
    from .images import EXTENSIONS, fabriquer, taille_dans_la_balise
    m = re.search(r'(\w+)="([^"]+)" : ce fichier', d.message)
    if not m:
        return None, ""
    lien = m.group(2).split("#")[0].split("?")[0]
    if Path(lien).suffix.lower() not in EXTENSIONS:
        return None, ""
    cible = posixpath.normpath(posixpath.join(posixpath.dirname(d.fichier),
                                              lien))
    largeur, hauteur = taille_dans_la_balise(ligne or "", m.group(2))
    octets, raison = fabriquer(cible, largeur, hauteur)
    if octets is None:
        return None, raison
    try:
        espace.creer_octets(cible, octets)
    except (CheminRefuse, FileExistsError, OSError):
        return None, ""
    return Reparation(cible, 1, f"image provisoire {largeur}x{hauteur} "
                      "creee (a remplacer par la vraie)", provisoire=True), ""


# Images qu'on n'a pas pu fabriquer (format sans Pillow...) : dit au bilan.
formats_impossibles: list[str] = []
# Les couleurs posees par MAEL dans CE chantier, et celles qu'une autre
# correction voulait lui faire defaire (videes au debut de chaque chantier).
COULEURS_POSEES: set[str] = set()
CONFLITS: list[str] = []


def nouveau_chantier() -> None:
    formats_impossibles.clear()
    COULEURS_POSEES.clear()
    CONFLITS.clear()


def limites() -> list[str]:
    return ([f"image provisoire non creee — {r}" for r in formats_impossibles]
            + [f"conflit de palette : {c} est une couleur posee par MAEL, une "
               "autre correction voulait la defaire — laissee, a trancher "
               "(OUTIL MANQUANT : palette d'ensemble)" for c in CONFLITS])


def homonyme(d: Defaut, fichiers: list[str]) -> tuple[str, str, str] | None:
    """Lien casse vers un fichier qui existe sous le meme nom ailleurs :
    (attribut, lien ecrit, lien juste). None si aucun ou si ambigu."""
    m = re.search(r'(\w+)="([^"]+)" : ce fichier', d.message)
    if not m:
        return None
    attr, lien = m.group(1), m.group(2)
    propre = lien.split("#")[0].split("?")[0]
    dossier = posixpath.dirname(d.fichier)
    cible = posixpath.normpath(posixpath.join(dossier, propre))
    memes = [f for f in fichiers
             if posixpath.basename(f) == posixpath.basename(cible)]
    if not memes and lien.startswith("/") and not Path(propre).suffix:
        # Lien « de serveur » sans extension (/gallery, /contact, /) vers une
        # page statique : la page du projet DE MEME NOM (septieme essai :
        # liens recopies d'un gabarit, /gallery pour gallery.html).
        nom = propre.strip("/") or "index"
        memes = [f for f in fichiers if Path(f).suffix.lower()
                 in {".html", ".htm"} and Path(f).stem == nom]
    if not memes:
        # Meme ROLE, et un seul fichier de ce role : une feuille de style
        # absente ne peut viser que l'UNIQUE feuille du projet (troisieme
        # essai du chantier : css/style.css pour styles.css, js/app.js pour
        # script.js — des habitudes du modele, pas des choix). Jamais pour
        # une page : deux pages ne sont pas interchangeables.
        role = _ROLES.get(Path(cible).suffix.lower())
        if role:
            memes = [f for f in fichiers
                     if _ROLES.get(Path(f).suffix.lower()) == role]
    if len(memes) != 1:
        return None                      # aucun, ou plusieurs : on ne choisit pas
    return attr, lien, posixpath.relpath(memes[0], dossier or ".")


_ROLES = {".css": "style", ".js": "script", ".mjs": "script"}


# ----------------------------------------------------------- chaque regle
def _contraste(d: Defaut, lignes_de) -> list[tuple[str, int, str, str]]:
    m = re.search(r"dans (\S+) \(ligne\(s\) ([\d, ]+)\) : remplace (#[0-9a-f]{6})"
                  r" \(\w+\) par (#[0-9a-f]{6})", d.message)
    if not m:
        return []
    from .bac_a_sable import motif_couleur
    fichier, ancienne, nouvelle = m.group(1), m.group(3), m.group(4)
    if ancienne.lower() in COULEURS_POSEES:
        # MAEL ne redefait jamais SA couleur (anti-oscillation, mission 003
        # du 08/10) : deux corrections qui se contredisent = conflit de
        # palette, dit par la memoire de travail, pas un va-et-vient.
        if ancienne.lower() not in CONFLITS:
            CONFLITS.append(ancienne.lower())
        return []
    COULEURS_POSEES.add(nouvelle.lower())
    motif = motif_couleur(ancienne)
    remplacements = []
    for n in (int(x) for x in m.group(2).split(",")):
        ligne = lignes_de(fichier, n)
        if ligne is None:
            continue
        code, separateur, commentaire = ligne.partition("/*")
        nouveau_code = motif.sub(nouvelle, code)   # jamais dans le commentaire
        if nouveau_code != code:
            remplacements.append((fichier, n, ligne,
                                  nouveau_code + separateur + commentaire))
    return remplacements


def _lien(d: Defaut, lignes_de, fichiers) -> list[tuple[str, int, str, str]]:
    h = homonyme(d, fichiers)
    if not h:
        return []
    attr, lien, juste = h
    ligne = lignes_de(d.fichier, d.ligne)
    ancien = f'{attr}="{lien}"'
    if ligne is None or ligne.count(ancien) != 1:
        return []
    return [(d.fichier, d.ligne, ligne,
             ligne.replace(ancien, f'{attr}="{juste}"'))]


_INSERTIONS = {
    # regle -> (balise apres laquelle inserer, ligne a inserer)
    "charset": ("<head>", '<meta charset="utf-8">'),
    "viewport": ("<head>", '<meta name="viewport" '
                 'content="width=device-width, initial-scale=1">'),
}
# Deja present -> rien a faire. Une reparation appliquee deux fois ne doit
# rien doubler (le banc l'a vu : deux <!DOCTYPE html>).
_DEJA = {
    "doctype": re.compile(r"<!doctype\s+html", re.I),
    "charset": re.compile(r"<meta[^>]*\bcharset\s*=", re.I),
    "viewport": re.compile(r"<meta[^>]*name\s*=\s*[\"']?viewport", re.I),
}


def _insertion(d: Defaut, texte: str | None) -> list[tuple[str, int, str, str]]:
    if texte is None or _DEJA[d.regle].search(texte):
        return []
    lignes = texte.split("\n")
    if d.regle == "doctype":
        for i, l in enumerate(lignes, 1):
            if re.match(r"\s*<html[\s>]", l, re.I):
                return [(d.fichier, i, l, "<!DOCTYPE html>\n" + l)]
        return []
    balise, ajout = _INSERTIONS[d.regle]
    trouvees = [i for i, l in enumerate(lignes, 1)
                if re.search(re.escape(balise) + r"(?![\w-])", l, re.I)]
    if len(trouvees) != 1:
        return []
    i = trouvees[0]
    l = lignes[i - 1]
    pos = l.lower().index(balise) + len(balise)
    return [(d.fichier, i, l, l[:pos] + "\n" + ajout + l[pos:])]


def _retirer_import(d: Defaut, lignes_de) -> list[tuple[str, int, str, str]]:
    """@import d'un fichier qui n'existe pas : la ligne est retiree — mais
    SEULEMENT si elle ne contient rien d'autre que cet @import."""
    ligne = lignes_de(d.fichier, d.ligne)
    if ligne is None or not re.fullmatch(
            r"\s*@import[^;{}]*;\s*(?:/\*.*?\*/\s*)?", ligne):
        return []
    return [(d.fichier, d.ligne, ligne, "")]


def _noopener(d: Defaut, lignes_de) -> list[tuple[str, int, str, str]]:
    ligne = lignes_de(d.fichier, d.ligne)
    if ligne is None or ligne.count('target="_blank"') != 1 \
            or re.search(r"\brel\s*=", ligne):
        return []
    return [(d.fichier, d.ligne, ligne, ligne.replace(
        'target="_blank"', 'target="_blank" rel="noopener noreferrer"'))]


# ------------------------------------- leviers « programme » (09/10/2026)
# L'examen des 100 missions l'a montre : le conseil des professeurs donnait
# la solution (« ajouter moi-meme le <script> du plan qui manque », « retirer
# moi-meme un lien qui ne vise aucun fichier »), avec une confiance haute —
# et le defaut restait, parce que personne ne l'appliquait. Ces leviers sont
# maintenant PROGRAMMES : une solution connue et sans choix ne se laisse pas.
_PAGES = {".html", ".htm"}


def _ressource_du_head(d: Defaut, texte: str | None
                       ) -> list[tuple[str, int, str, str]]:
    """Levier reparer-ressources-du-head : le critere « charge X : <balise> »
    dit EXACTEMENT la ligne a ecrire ; on la pose juste avant </head>."""
    m = re.search(r"non tenu : charge (\S+) : (<(?:link|script)\b[^\n]*>)\s*$",
                  d.message)
    if texte is None or not m:
        return []
    balise = m.group(2)
    cible = re.search(r'(?:href|src)="([^"]+)"', balise)
    if cible and re.search(r'(?:href|src)\s*=\s*["\']' + re.escape(
            cible.group(1)) + r'["\']', texte):
        return []                                    # deja la
    lignes = texte.split("\n")
    trouvees = [i for i, l in enumerate(lignes, 1)
                if re.search(r"</head\s*>", l, re.I)]
    if len(trouvees) != 1:
        return []
    i = trouvees[0]
    l = lignes[i - 1]
    pos = re.search(r"</head\s*>", l, re.I).start()
    return [(d.fichier, i, l, l[:pos] + balise + "\n" + l[pos:])]


def _nom_de_page(page: str) -> str:
    stem = Path(page).stem
    if stem.lower() in {"index", "accueil", "home"}:
        return "Accueil"
    return stem.replace("-", " ").replace("_", " ").strip().capitalize()


def _lien_du_menu(d: Defaut, texte: str | None
                  ) -> list[tuple[str, int, str, str]]:
    """Levier reparer-liens-du-menu : le critere « mene a X : <a href=..> »
    manque -> une entree de plus dans la liste du <nav> (une seule liste)."""
    m = re.search(r'non tenu : mene a (\S+) : <a href="([^"]+)">', d.message)
    if texte is None or not m:
        return []
    nav = re.search(r"<nav\b.*?</nav\s*>", texte, re.I | re.S)
    if not nav or len(re.findall(r"</ul\s*>", nav.group(0), re.I)) != 1:
        return []
    debut_nav = texte[:nav.start()].count("\n") + 1
    lignes = texte.split("\n")
    for i in range(debut_nav, debut_nav + nav.group(0).count("\n") + 1):
        l = lignes[i - 1]
        f = re.search(r"</ul\s*>", l, re.I)
        if f:
            ajout = f'<li><a href="{m.group(2)}">{_nom_de_page(m.group(1))}</a></li>'
            return [(d.fichier, i, l, l[:f.start()] + ajout + "\n"
                     + l[f.start():])]
    return []


def _retirer_lien_hors_plan(d: Defaut, lignes_de, fichiers
                            ) -> list[tuple[str, int, str, str]]:
    """Levier reparer-lien-hors-plan : un <a> vers une PAGE qui n'est ni au
    plan ni au projet (et sans homonyme : _lien l'aurait corrige). Une
    entree de liste qui ne contient que ce lien est retiree ; sinon le lien
    devient du texte (le mot reste, la page fantome disparait). Jamais la
    page n'est inventee (a ne PAS faire, dit le conseil)."""
    m = re.search(r'href="([^"]+)" : ce fichier', d.message)
    if not m:
        return []
    lien = m.group(1)
    propre = lien.split("#")[0].split("?")[0]
    if re.match(r"(?i)^([a-z]+:|//)", lien) or (
            Path(propre).suffix.lower() not in _PAGES
            and Path(propre).suffix):
        return []
    cible = posixpath.normpath(posixpath.join(posixpath.dirname(d.fichier),
                                              propre.lstrip("/")))
    if cible in fichiers:
        return []
    ligne = lignes_de(d.fichier, d.ligne)
    if ligne is None:
        return []
    a = re.compile(r'<a\b[^>]*\bhref="' + re.escape(lien)
                   + r'"[^>]*>(.*?)</a\s*>', re.I)
    if len(a.findall(ligne)) != 1:
        return []
    if re.fullmatch(r"\s*<li\b[^>]*>\s*" + a.pattern + r"\s*</li\s*>\s*",
                    ligne, re.I):
        return [(d.fichier, d.ligne, ligne, None)]          # ligne retiree
    return [(d.fichier, d.ligne, ligne, a.sub(r"\1", ligne))]


CIBLES_24PX = ("/* MAEL : zones cliquables d'au moins 24 x 24 px "
               "(WCAG 2.2 - 2.5.8) */\n"
               "button, input:not([type=\"hidden\"]):not([type=\"checkbox\"])"
               ":not([type=\"radio\"]), select, textarea "
               "{ min-height: 24px; min-width: 24px; }\n"
               "nav a, a.btn, a.bouton, header a, footer a "
               "{ display: inline-block; min-height: 24px; min-width: 24px; "
               "line-height: 24px; }\n")


def _cibles_24px(espace: Espace, fichiers: list[str]) -> Reparation | None:
    """Levier reparer-cibles-24px : la regle va a l'UNIQUE feuille de style
    du projet, une seule fois (marque MAEL)."""
    css = [f for f in fichiers if Path(f).suffix.lower() == ".css"]
    if len(css) != 1:
        return None
    try:
        texte = espace.lire(css[0])
    except (OSError, CheminRefuse):
        return None
    if "MAEL : zones cliquables" in texte:
        return None
    try:
        espace.ecrire(css[0], texte.rstrip("\n") + "\n\n" + CIBLES_24PX)
    except CheminRefuse:
        return None
    return Reparation(css[0], texte.count("\n") + 2,
                      "zones cliquables portees a 24 px (lecon : "
                      "reparer-cibles-24px)")


FOCUS_VISIBLE = ("/* MAEL : contour de focus visible (WCAG 2.2 - 2.4.7) */\n"
                 ":focus-visible { outline: 3px solid #1a5fb4; "
                 "outline-offset: 2px; }\n")
LIENS_SOULIGNES = ("/* MAEL : liens du texte reconnaissables sans la couleur "
                   "(WCAG 2.2 - 1.4.1) */\n"
                   "p a, li a, td a, dd a { text-decoration: underline; }\n"
                   "nav li a { text-decoration: none; }\n")


def _ajouter_regle(espace: Espace, css: str, marque: str, regle: str,
                   quoi: str) -> Reparation | None:
    """Ajouter UNE fois une regle sure en fin de feuille (marque MAEL)."""
    try:
        texte = espace.lire(css)
    except (OSError, CheminRefuse):
        return None
    if marque in texte:
        return None
    try:
        espace.ecrire(css, texte.rstrip("\n") + "\n\n" + regle)
    except CheminRefuse:
        return None
    return Reparation(css, texte.count("\n") + 2, quoi)


def _unique_css(fichiers: list[str]) -> str | None:
    css = [f for f in fichiers if Path(f).suffix.lower() == ".css"]
    return css[0] if len(css) == 1 else None


# --------------------------------------------------------------- moteur
def reparer(espace: Espace, defauts: list[Defaut], fichiers: list[str]
            ) -> list[Reparation]:
    """Applique les corrections sures. Rend ce qui a ete fait."""
    textes: dict[str, str | None] = {}

    def texte_de(fichier: str) -> str | None:
        if fichier not in textes:
            try:
                textes[fichier] = espace.lire(fichier)
            except (OSError, CheminRefuse):
                textes[fichier] = None
        return textes[fichier]

    def lignes_de(fichier: str, n: int) -> str | None:
        t = texte_de(fichier)
        if t is None:
            return None
        lignes = t.split("\n")
        return lignes[n - 1] if 1 <= n <= len(lignes) else None

    # (fichier, ligne) -> (ancien texte, nouveau texte, description)
    a_faire: dict[tuple[str, int], tuple[str, str | None, str]] = {}
    images: list[Reparation] = []
    cibles = False
    focus: set[str] = set()
    souligner = False
    for d in defauts:
        if d.regle == "cible-trop-petite":
            cibles = True
            continue
        if d.regle == "focus-invisible" and d.fichier.endswith(".css"):
            focus.add(d.fichier)                 # levier : focus visible
            continue
        if d.regle == "contraste" and "link-in-text-block" in d.message:
            souligner = True                     # levier reparer-liens-soulignes
            continue
        if d.regle == "critere-non-tenu":
            r = _ressource_du_head(d, texte_de(d.fichier))
            quoi = "ressource du plan ajoutee dans le <head> (lecon : " \
                   "reparer-ressources-du-head)"
            if not r:
                r = _lien_du_menu(d, texte_de(d.fichier))
                quoi = "lien du plan ajoute au menu (lecon : " \
                       "reparer-liens-du-menu)"
        elif d.regle == "contraste":
            r = _contraste(d, lignes_de)
            quoi = "contraste : couleur calculee appliquee"
        elif d.regle == "fichier-absent":
            r = _lien(d, lignes_de, fichiers)
            quoi = "lien corrige vers le fichier existant"
            if not r:
                r = _retirer_lien_hors_plan(d, lignes_de, fichiers)
                quoi = "lien vers une page hors du plan retire (lecon : " \
                       "reparer-lien-hors-plan)"
            if not r:
                # Pas de fichier homonyme : si c'est une image, une image
                # provisoire neutre (option A).
                img, raison = _image_provisoire(espace, d,
                                                lignes_de(d.fichier, d.ligne))
                if img:
                    images.append(img)
                elif raison and raison not in formats_impossibles:
                    formats_impossibles.append(raison)
                continue
        elif d.regle in {"doctype", "charset", "viewport"}:
            r = _insertion(d, texte_de(d.fichier))
            quoi = f"{d.regle} ajoute"
        elif d.regle == "import-absent":
            r = _retirer_import(d, lignes_de)
            quoi = "@import d'un fichier absent retire"
        elif d.regle == "blank-noopener":
            r = _noopener(d, lignes_de)
            quoi = 'rel="noopener noreferrer" ajoute'
        else:
            continue
        for fichier, n, ancien, nouveau in r:
            # Deux corrections sur la meme ligne : on garde la premiere, la
            # seconde se fera au tour suivant (jamais deux recritures a
            # l'aveugle de la meme ligne).
            a_faire.setdefault((fichier, n), (ancien, nouveau, quoi))

    faites: list[Reparation] = list(images)
    par_fichier: dict[str, list] = {}
    for (fichier, n), (ancien, nouveau, quoi) in a_faire.items():
        par_fichier.setdefault(fichier, []).append((n, ancien, nouveau, quoi))
    for fichier, liste in par_fichier.items():
        lignes = (texte_de(fichier) or "").split("\n")
        ici = []
        for n, ancien, nouveau, quoi in sorted(liste, key=lambda x: x[0],
                                                reverse=True):
            if lignes[n - 1] != ancien:
                continue                    # le fichier a bouge : on ne touche pas
            if nouveau is None:
                del lignes[n - 1]           # ligne retiree (du bas vers le haut)
            else:
                lignes[n - 1] = nouveau
            ici.append(Reparation(fichier, n, quoi))
        if not ici:
            continue
        try:
            espace.ecrire(fichier, "\n".join(lignes))
            faites += ici
        except CheminRefuse:
            pass
    if cibles:
        r = _cibles_24px(espace, fichiers)
        if r:
            faites.append(r)
    for css in sorted(focus):
        r = _ajouter_regle(espace, css, "MAEL : contour de focus visible",
                           FOCUS_VISIBLE, "contour de focus rendu visible "
                           "(:focus-visible)")
        if r:
            faites.append(r)
    if souligner and _unique_css(fichiers):
        r = _ajouter_regle(espace, _unique_css(fichiers),
                           "MAEL : liens du texte", LIENS_SOULIGNES,
                           "liens du texte soulignes (lecon : "
                           "reparer-liens-soulignes)")
        if r:
            faites.append(r)
    return sorted(faites, key=lambda r: (r.fichier, r.ligne))
