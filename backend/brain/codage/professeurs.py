"""Les PROFESSEURS : un conseil qui raisonne avant de decider (feuille de
route du responsable, etape 4, 08/10/2026).

« Comme une cogitation cerebrale entre des particuliers, pour donner une
reponse en se basant sur des realites, des connaissances, des calculs et
aussi sur l'humain. »

Quatre professeurs donnent chacun leur AVIS sur une decision. Ce sont des
PROGRAMMES (aucun appel au modele) : ils relevent ce qui est vrai, ce qui est
su, ce qui se calcule, et ce que veut la personne.

  - REALITE      : les faits — ce que la demande dit exactement (nombre de
                   pages, contradictions, langue), les langages demandes,
                   ce que la machine a vraiment (outils, memoire du modele) ;
  - CONNAISSANCE : le savoir de MAEL qui s'applique (specialistes concernes,
                   fiches de conduite de projet, gabarits) ;
  - CALCUL       : les nombres — fichiers a prevoir, plafond du plan, taille
                   d'un fichier, duree estimee d'apres les missions reelles ;
  - HUMAIN       : pour qui, pour quoi faire, ce que la demande ne dit pas
                   (a supposer et ECRIRE), l'accessibilite, la langue.

Puis ils DELIBERENT ENTRE EUX, par programme, sans le modele (decision du
responsable du 08/10/2026 : deliberation.py) ; le juge du plan
(juger_plan) verifie ensuite que le plan rendu respecte leurs faits. Leur
fiabilite se mesure sans modele : banc_professeurs.py.

Premier usage : le PLAN du chantier (la decision qui commande toutes les
autres : missions 04, 05, 07, 09 et 10 du 08/10/2026 ont echoue au plan).
MAEL_SANS_PROFESSEURS=1 rend le plan d'avant, pour mesurer.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .comprehension import Comprehension, comprendre
from .emplacements import trouver

PROFESSEURS = ("realite", "connaissance", "calcul", "humain")
MINUTES_PAR_APPEL = 3.5     # missions du 08/10/2026 : 304 min / 86 appels
APPELS_PAR_TACHE = 1.6      # ecriture + corrections, memes missions
LIGNES_MAX = 150            # au-dela, un fichier deborde et se coupe


def actifs() -> bool:
    return os.environ.get("MAEL_SANS_PROFESSEURS") != "1"


@dataclass
class Avis:
    professeur: str
    points: list[str] = field(default_factory=list)

    def texte(self) -> str:
        tete = (entete(self.professeur) if self.professeur in CONSEIL
                else f"[{self.professeur}]")
        return tete + "\n" + "\n".join(f"- {p}" for p in self.points)


@dataclass
class Faits:
    """Ce que les professeurs ont etabli et que le juge fera respecter."""
    nb_pages: int | None = None
    langages: set[str] = field(default_factory=set)     # html, python, php...
    base: bool = False
    interactif: bool = False
    tests: bool = False
    site: bool = False          # « site », « boutique » : plusieurs pages
    fichiers_max: int = 8


_BASE = re.compile(r"(?i)base de donn|sqlite|\bsql\b|mysql|postgres|pdo")
# Des mots ENTIERS : « script » se cachait dans « inscription ».
_INTERACTIF = re.compile(r"(?i)\b(calcul\w*|total|ouvr\w*|ferm\w*|clic\w*|"
                         r"interactif|interactive|charge|charger|filtr\w*|"
                         r"en direct|script)\b")
_TESTS = re.compile(r"(?i)\btests?\b|automatique")


def etablir(demande: str, c: Comprehension | None = None,
            fichiers_max: int = 8) -> Faits:
    from .savoir import piles_de
    c = c or comprendre(demande)
    texte = c.texte
    piles = piles_de(texte)
    # Le plafond suit l'envergure du modele (envergure.py, 09/10).
    f = Faits(nb_pages=c.nb_pages, fichiers_max=fichiers_max)
    if piles & {"flask", "fastapi", "django", "python"}:
        f.langages.add("python")
    if "php" in piles:
        f.langages.add("php")
    if "java" in piles:
        f.langages.add("java")
    if "node" in piles:
        f.langages.add("node")
    # « les produits d'une boutique » dans une demande d'API ne demande
    # aucune page (mission 07 du 08/10/2026) : « boutique » ne compte que
    # sans langage serveur.
    serveur = bool(f.langages)
    if re.search(r"(?i)\b(site|page|pages|accueil|galerie|contact|"
                 r"formulaire|portfolio)\b", texte) or "react" in piles or (
            not serveur and re.search(r"(?i)\bboutique\b", texte)):
        f.langages.add("html")
    # « une page qui calcule », « une page de connexion et une page
    # d'inscription » : des pages dites sans chiffre (banc du 08/10/2026).
    if f.nb_pages is None and not c.contradictions:
        unes = re.findall(r"\bune page\b", texte)
        if unes:
            f.nb_pages = len(unes)
    f.site = bool(re.search(r"(?i)\b(site|boutique|portfolio)\b", texte))
    f.base = bool(_BASE.search(texte))
    f.interactif = bool(_INTERACTIF.search(texte))
    f.tests = bool(_TESTS.search(texte))
    return f


# --------------------------------------------------- les quatre professeurs
# Precision du responsable (08/10/2026) : « les professeurs ont chacun leur
# identite, un fort dans chaque domaine ; le but c'est de creer des reponses
# correctes grace aux bibliotheques, et des mesures tres fondees sur des
# bases reconnues aujourd'hui : un professeur, c'est un semblant de
# cerveau. » Chacun a donc : son IDENTITE (son fort), son PRINCIPE (ce qu'il
# ne lache jamais), sa BIBLIOTHEQUE (ce qu'il consulte) ; et chaque point de
# son avis CITE sa source.
@dataclass(frozen=True)
class Professeur:
    nom: str
    fort: str
    principe: str
    bibliotheque: tuple[str, ...]


CONSEIL = {
    "realite": Professeur(
        "realite", "les FAITS : ce qui est ecrit dans la demande et ce qui "
        "est mesure sur la machine",
        "ne retient que ce qui se constate ; une supposition n'est pas un "
        "fait",
        ("la demande analysee (comprehension.py)", "les outils de la machine "
         "(emplacements.py)", "le releve des versions en ligne "
         "(fraicheur.json)")),
    "connaissance": Professeur(
        "connaissance", "le SAVOIR reconnu : normes, bonnes pratiques, "
        "pieges connus des langages",
        "ne cite qu'un savoir source et frais",
        ("savoir-faire (savoir_faire/)", "normes WCAG / OWASP / CWE "
         "(normes/fiches.yaml)", "connaissances des langages "
         "(brain/connaissances)", "gabarits verifies (gabarits/)")),
    "calcul": Professeur(
        "calcul", "les NOMBRES : tailles, plafonds, durees, marges",
        "chaque nombre vient d'une mesure ou d'une formule, et dit sa marge",
        ("mesures des missions reelles du 08/10/2026", "limites du modele "
         "et du chantier (reglages)", "statistiques (brain/connaissances)")),
    "humain": Professeur(
        "humain", "la PERSONNE : pour qui, pour quoi faire, avec quelles "
        "capacites",
        "la personne veut un resultat qui marche ; rien ne se decide a sa "
        "place sans etre ecrit",
        ("WCAG 2.2 AA (normes/fiches.yaml)", "conduite de MAEL envers les "
         "personnes (references/comportement.md)")),
}


@dataclass
class Point:
    texte: str
    source: str


def _avis(nom: str, points: list[Point]) -> Avis:
    a = Avis(nom)
    a.points = [f"{p.texte} (source : {p.source})" for p in points]
    return a


def realite(demande: str, c: Comprehension, f: Faits) -> Avis:
    p = []
    lu = "la demande, lue par MAEL"
    if f.nb_pages:
        p.append(Point(f"la demande dit EXACTEMENT {f.nb_pages} page(s) "
                       "HTML", lu))
    for x in c.contradictions:
        p.append(Point(f"CONTRADICTION : {x} — choisir et l'ecrire en "
                       "supposition", lu))
    if c.langue == "en":
        p.append(Point("la demande est en anglais : le resultat reste en "
                       "anglais", lu))
    noms = {"html": "pages HTML/CSS", "python": "code Python (serveur)",
            "php": "code PHP", "java": "code Java", "node": "serveur Node"}
    if f.langages:
        p.append(Point("langages demandes : " + ", ".join(
            noms[l] for l in sorted(f.langages)), lu))
    else:
        p.append(Point("aucun langage n'est dit : une page web est le "
                       "minimum raisonnable", lu))
    if "html" not in f.langages and f.langages:
        p.append(Point("aucune page n'est demandee : PAS de fichier HTML",
                       lu))
    if f.base:
        p.append(Point("une base de donnees est demandee", lu))
    if f.tests:
        p.append(Point("des tests automatiques sont demandes", lu))
    outils = [n for n in ("php", "javac", "docker") if trouver(n)]
    if outils:
        p.append(Point("la machine a : " + ", ".join(outils),
                       "outils trouves sur la machine"))
    from . import fraicheur
    r = fraicheur.charger()
    suivis = {"python": ("flask", "pytest"), "php": ("php",)}
    versions = [f"{n} {r.versions[n]}" for l in sorted(f.langages)
                for n in suivis.get(l, ()) if n in r.versions]
    if versions and r.date:
        p.append(Point("versions actuelles : " + ", ".join(versions),
                       f"releve en ligne du {r.date}"))
    return _avis("realite", p)


def connaissance(demande: str, f: Faits) -> Avis:
    from . import normes, savoir_faire
    p = []
    _t, choix = savoir_faire.pour_plan(demande)
    for fiche in choix.fiches:
        p.append(Point(f"{fiche.titre} : {fiche.comment[0]}",
                       fiche.source.split(" — ")[0]))
    if "python" in f.langages:
        p.append(Point("une API Python : app.py, puis ses tests "
                       "(tests/test_app.py)", "savoir-faire api-flask-sqlite, "
                       "tests-pytest"))
    for n in normes.choisir(demande, n=1):
        p.append(Point(n.texte.split(". ")[0], f"{n.source} — {n.ref}"))
    try:
        from brain import connaissances
        for k in connaissances.recuperer(demande, n=1):
            if k.famille == "langage" and getattr(k, "securite", None):
                piege = k.securite[0]
                p.append(Point(f"piege connu de {k.nom} : {piege['titre']} "
                               f"— {piege['conseil']}", f"connaissance "
                               f"{k.id} (verifiee le {k.verifie_le})"))
    except Exception:                                  # noqa: BLE001
        pass
    return _avis("connaissance", p)


def fichiers_prevus(f: Faits) -> int:
    n = 0
    if "html" in f.langages:
        # Pages non dites : 3 pour un « site », 1 sinon (un formulaire, une
        # page) — banc du 08/10/2026 : 6 fichiers pour un formulaire PHP.
        defaut = 3 if f.site else 1
        n += (f.nb_pages or defaut) + 1            # pages + feuille de style
        n += 1 if f.interactif else 0              # un script
    if "python" in f.langages:
        n += 1 + (1 if f.tests else 0)             # app.py, tests
    if "php" in f.langages:
        n += 1 + (1 if f.base else 0)
    if "java" in f.langages or "node" in f.langages:
        n += 2
    return max(n, 1)


def calcul(f: Faits) -> Avis:
    p = []
    n = fichiers_prevus(f)
    p.append(Point(f"fichiers a prevoir : environ {n} ; plafond du plan : "
                   f"{f.fichiers_max}", "une page par page demandee + une "
                   "feuille de style + un script si interactif + le code "
                   "serveur et ses tests ; plafond : chantier.TACHES_MAX"))
    if n > f.fichiers_max:
        p.append(Point(f"{n} > {f.fichiers_max} : regrouper (une feuille de "
                       "style, un script communs) plutot que couper la "
                       "demande", "comparaison des deux nombres"))
    p.append(Point(f"chaque fichier : {LIGNES_MAX} lignes au plus (environ "
                   "9 000 caracteres ecrits d'un coup)", "coupure mesuree "
                   "au-dela de 9 000 caracteres (chantier.LONGUEUR_MAX)"))
    minutes = min(n, f.fichiers_max) * APPELS_PAR_TACHE * MINUTES_PAR_APPEL
    p.append(Point(f"duree estimee : environ {minutes:.0f} min, a +/- 50 % "
                   "pres", f"moyenne de {MINUTES_PAR_APPEL} min par appel et "
                   f"{APPELS_PAR_TACHE} appel par tache sur 10 missions "
                   "(15 a 66 min chacune) : une moyenne sur 10 cas varie "
                   "fortement"))
    return _avis("calcul", p)


_PUBLICS = (("api", "des developpeurs et un script : des reponses JSON "
             "previsibles et des codes HTTP justes"),
            ("boutique", "des clients qui achetent : prix lisibles, devise "
             "ecrite"),
            ("restaurant|restorant|boulangerie|plats|pains",
             "des clients du quartier : horaires, adresse, contact"),
            ("association", "des membres et des curieux : agenda, adhesion, "
             "contact"),
            ("photographe|portfolio", "des clients potentiels : les images "
             "d'abord"))


def humain(demande: str, c: Comprehension, f: Faits) -> Avis:
    p = []
    t = c.texte
    for motif, public in _PUBLICS:
        if motif == "api" and "html" in f.langages:
            continue                    # des pages : leur public d'abord
        if re.search(rf"(?i)\b({motif})", t):
            p.append(Point(f"pour qui : {public}", "le sujet de la demande"))
            break
    if "html" in f.langages:
        p.append(Point("tout le monde doit pouvoir s'en servir : clavier, "
                       "lecteur d'ecran, telephone", "WCAG 2.2 niveau AA "
                       "(2.1.1, 1.3.1, 1.4.10)"))
        if re.search(r"(?i)boutique|prix|vente", t) and not re.search(
                r"(?i)fcfa|eur|euro|dollar|\$|€", t):
            p.append(Point("la devise n'est pas dite : la supposer et "
                           "l'ecrire", "conduite de MAEL : rien ne se decide "
                           "a la place de la personne sans etre ecrit"))
    if c.vague:
        p.append(Point("la demande est VAGUE : le minimum utile, et chaque "
                       "choix ecrit en supposition", "conduite de MAEL "
                       "(references/comportement.md : ne rien inventer)"))
    p.append(Point("la personne veut un resultat qui MARCHE, pas le plus de "
                   "fichiers possible", "principe du professeur humain"))
    return _avis("humain", p)


def entete(nom: str) -> str:
    pr = CONSEIL[nom]
    return (f"[{nom.upper()} — fort : {pr.fort} ; principe : {pr.principe}]")


def conseil(demande: str) -> tuple[list[Avis], Faits, Comprehension]:
    c = comprendre(demande)
    f = etablir(demande, c)
    return ([realite(demande, c, f), connaissance(demande, f), calcul(f),
             humain(demande, c, f)], f, c)


# ------------------------------------------------- le juge du plan
def juger_plan(fichiers: list[str], f: Faits) -> list[str]:
    """Le plan rendu respecte-t-il les faits ? (le juge du plan, sans
    modele). Missions 07 et 10 du 08/10/2026 : une API Python dont le plan
    ne prevoyait que des pages."""
    exts = {Path(x).suffix.lower() for x in fichiers}
    noms = {Path(x).name.lower() for x in fichiers}
    raisons = []
    if "python" in f.langages and ".py" not in exts:
        raisons.append("la demande est une application Python : le plan doit "
                       "prevoir le fichier .py (app.py)")
    if "python" in f.langages and f.tests and not any(
            n.startswith("test") and n.endswith(".py") for n in noms):
        raisons.append("des tests sont demandes : le plan doit prevoir "
                       "tests/test_app.py")
    # requirements.txt n'est pas exige ici : le lecteur du plan n'accepte
    # encore que les fichiers de CODE (juges.EXTENSIONS) — limite connue.
    if "php" in f.langages and ".php" not in exts:
        raisons.append("la demande est en PHP : le plan doit prevoir un "
                       "fichier .php")
    if "html" not in f.langages and f.langages and exts & {".html", ".htm"} \
            and not f.interactif:
        raisons.append("la demande ne parle d'aucune page : pas de fichier "
                       "HTML au plan")
    # Un langage serveur que la demande n'appelle pas (recul vu au banc des
    # plans du 08/10/2026 : app.py dans des sites vitrines).
    serveur = {".py": "python", ".php": "php", ".java": "java"}
    for ext in sorted(exts & set(serveur)):
        if serveur[ext] not in f.langages:
            raisons.append(f"aucun code {serveur[ext]} n'est demande : pas de "
                           f"fichier {ext} au plan")
    return raisons
