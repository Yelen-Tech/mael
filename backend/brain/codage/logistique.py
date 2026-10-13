"""La LOGISTIQUE : un maillon de la chaine, apres chaque ecriture.

Idee du responsable (09/10/2026) : « ce n'est pas au chantier ; c'est une
logistique qui s'en charge apres chaque ecriture, au lieu de bourrer les
autres — un systeme plus fluide, comme une chaine ». La chaine devient :

    plan -> [logistique : adresses] -> ecriture -> [logistique : rangement]
         -> juges -> reparation -> ... -> finition -> [logistique : annexes]

Le chantier ne fait que l'appeler a ces trois moments. Elle ne juge rien
et n'appelle jamais le modele ; elle range, d'apres le SAVOIR de
l'arborescence standard (arborescence.py) :
  - AU PLAN : chaque fichier recoit son adresse standard (assets/css/...,
    app/..., tests/...) ; un morceau de page (header.html, footer.html) est
    retire du plan — il s'ecrit dans chaque page ;
  - APRES CHAQUE ECRITURE : les chemins que le modele a ecrits par
    habitude (href="styles.css", src="script.js", images/x.jpg) sont
    portes a l'adresse standard ; un paquet Python recoit son __init__.py ;
  - EN FIN : README.md, .gitignore, requirements.txt, package.json,
    .env.example — ecrits a partir des faits du projet, jamais ecrases.
Chaque geste est DIT (notes du tour, bilan) : rien en silence.
"""
from __future__ import annotations

import posixpath
import re
from pathlib import Path

from . import arborescence as arbo
from .espace import CheminRefuse, Espace

_REF = re.compile(r"""(\b(?:href|src|action)\s*=\s*["'])([^"'#?]+)""", re.I)
_IMAGES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif"}


class Logistique:
    def __init__(self, espace: Espace, demande: str = ""):
        self.espace = espace
        self.demande = demande
        self.sorte = ""
        self.adresses: dict[str, str] = {}      # chemin du modele -> standard
        self.fragments: list[str] = []
        self.gestes: list[str] = []

    # ------------------------------------------------------------ au plan
    def adresser(self, fichiers: list[str], deja: list[str] = ()
                 ) -> list[str]:
        """Le plan aux adresses standard (meme ordre, fragments retires).
        `deja` : les fichiers des etapes precedentes — le TYPE du projet se
        decide sur le projet entier, pas sur une etape (une etape « base »
        n'a que des .sql)."""
        deja = list(deja)
        if not deja:
            self.sorte, self.adresses, self.fragments = arbo.ranger_plan(
                fichiers, self.demande)
        else:
            self.sorte = arbo.type_de_projet(self.demande, deja + fichiers)
            self.fragments = [f for f in fichiers if arbo.est_fragment(f)]
            cibles = {f: arbo.ranger(f, self.sorte) for f in fichiers
                      if f not in self.fragments}
            compte: dict[str, int] = {}
            for c in cibles.values():
                compte[c] = compte.get(c, 0) + 1
            # Une cible DEJA faite est le meme fichier (le plan de l'etape
            # le retirera) ; deux nouveaux au meme endroit gardent leur nom.
            self.adresses = {f: (c if c in deja or compte[c] == 1 else f)
                             for f, c in cibles.items()}
        for f in self.fragments:
            self.gestes.append(f"{f} retire du plan : un morceau de page "
                               "s'ecrit dans chaque page")
        for ancien, nouveau in self.adresses.items():
            if ancien != nouveau:
                self.gestes.append(f"{ancien} -> {nouveau} (arborescence "
                                   f"standard « {self.sorte} »)")
        return [self.adresses[f] for f in fichiers if f in self.adresses]

    def adresse(self, chemin: str) -> str:
        """L'adresse standard d'un fichier ajoute en cours de route."""
        nouveau = arbo.ranger(chemin, self.sorte or "site")
        self.adresses[chemin] = nouveau
        if nouveau != chemin:
            self.gestes.append(f"{chemin} -> {nouveau} (ajoute en cours de "
                               "route, arborescence standard)")
        return nouveau

    def connaitre(self, fichiers: list[str]) -> None:
        """Reprise d'un chantier : le type se retrouve d'apres le plan."""
        self.sorte = arbo.type_de_projet(self.demande, fichiers)
        self.adresses = {f: f for f in fichiers}

    # ------------------------------------------- apres chaque ecriture
    def _vise(self, depuis: str, lien: str, plan: list[str]) -> str | None:
        """L'adresse standard que vise un lien ecrit par habitude, ou None."""
        if re.match(r"(?i)^([a-z]+:|//|/)", lien) or not lien.strip():
            return None
        ici = posixpath.dirname(depuis)
        cible = posixpath.normpath(posixpath.join(ici, lien))
        if cible in plan or (Path(self.espace.racine) / cible).exists():
            return None                              # deja juste
        nom = posixpath.basename(lien)
        # 1) un fichier du plan de meme nom (styles.css -> assets/css/styles.css)
        memes = [f for f in plan if posixpath.basename(f) == nom]
        if len(memes) == 1:
            return memes[0]
        # 2) l'ancien chemin du modele, devenu standard
        for ancien, nouveau in self.adresses.items():
            if posixpath.normpath(ancien) == cible:
                return nouveau
        # 3) une image hors de son dossier standard
        ext = Path(nom).suffix.lower()
        if ext in _IMAGES and self.sorte in {"site", "php"}:
            return f"assets/images/{nom}"
        if ext in _IMAGES and self.sorte == "python":
            return f"app/static/images/{nom}"
        return None

    def apres_ecriture(self, fichier: str, plan: list[str]) -> list[str]:
        """Ranger ce qui vient d'etre ecrit. Rend les gestes faits."""
        gestes: list[str] = []
        try:
            texte = self.espace.lire(fichier)
        except (OSError, CheminRefuse):
            return gestes
        ext = Path(fichier).suffix.lower()
        if ext in arbo.PAGES | {".php", ".jsx"} or (
                ext == ".css" and "url(" in texte):
            def porter(m):
                juste = self._vise(fichier, m.group(2), plan)
                if juste is None:
                    return m.group(0)
                rel = posixpath.relpath(juste, posixpath.dirname(fichier)
                                        or ".")
                gestes.append(f"{fichier} : {m.group(2)} -> {rel}")
                return m.group(1) + rel
            nouveau = _REF.sub(porter, texte)
            if nouveau != texte:
                try:
                    self.espace.ecrire(fichier, nouveau)
                except CheminRefuse:
                    gestes.clear()
        if ext == ".py" and fichier.startswith("app/"):
            init = "app/__init__.py"
            if not (Path(self.espace.racine) / init).exists():
                try:
                    self.espace.ecrire(init, "")
                    gestes.append(f"{init} cree (paquet app)")
                except CheminRefuse:
                    pass
        gestes = [f"logistique : {g}" for g in gestes]
        self.gestes += gestes
        return gestes

    # ------------------------------------------------------------- en fin
    def finir(self, provisoires: list[str] = ()) -> list[str]:
        """Les fichiers simples, ecrits par MAEL (README en dernier : il
        montre l'arborescence finale). Jamais un fichier existant ecrase."""
        racine = Path(self.espace.racine)
        if not self.sorte:
            self.connaitre([p.relative_to(racine).as_posix()
                            for p in racine.rglob("*") if p.is_file()])
        ecrits = []
        for passe in ("autres", "readme"):
            for chemin, contenu in arbo.annexes(
                    racine, self.sorte, self.demande, list(provisoires)
                    ).items():
                if (chemin == "README.md") != (passe == "readme"):
                    continue
                try:
                    self.espace.ecrire(chemin, contenu)
                    ecrits.append(chemin)
                except CheminRefuse:
                    pass
        if ecrits:
            self.gestes.append("logistique : ecrits par MAEL — "
                               + ", ".join(ecrits))
        return ecrits

    def consigne(self, fichier: str) -> str:
        forme = arbo.consigne(self.sorte, fichier)
        base = arbo.consigne_base(
            self.espace.racine,
            arbo.bases_du_projet(self.espace.racine, self.demande), fichier)
        return " ; ".join(x for x in (forme, base) if x)
