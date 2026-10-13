"""MAEL se relit : il lit ses propres journaux de missions, regroupe ses
echecs, les diagnostique et ecrit ses LECONS.

Cap du responsable (08/10/2026) : on ne corrige plus MAEL a sa place ; on
lui fait voir ses faiblesses, il se corrige lui-meme, et on verifie apres.
Cette etape est la premiere de la boucle : SE RELIRE.

    mael code --se-relire --dossier <racine des missions>

  1. LES FAITS, sans modele : les journaux (JOURNAL.md), l'etat des
     missions et des chantiers (.mael/chantier.json), la reponse brute du
     plan (.mael/plan-brut.txt) ; les defauts sont classes en FAMILLES
     (un meme echec qui revient d'une mission a l'autre). Une mission sans
     plan et sans trace : MAEL rejoue SON appel de plan pour avoir la preuve.
  2. LE DIAGNOSTIC, par le modele, une famille a la fois (conversation
     neuve, preuves courtes) : la cause, l'ORIGINE (consigne, code de MAEL,
     ou modele qui n'a pas suivi une consigne claire), et UNE lecon.
  3. L'ECRIT : <racine>/BILAN-DE-MAEL.md (pour le responsable) et
     <racine>/lecons.yaml (les lecons « proposees »). Une lecon ne devient
     « validee » qu'apres une relance des missions qui montre un progres :
     c'est l'etape VERIFIER, pas celle-ci.

Les faits ne viennent JAMAIS du modele : il ne peut ni inventer un echec ni
en cacher un ; il ne fait qu'interpreter des preuves que MAEL a relevees.
"""
from __future__ import annotations

import json
import posixpath
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from . import angles_morts, juges, leviers
from .chantier import _LIGNE_PLAN, ETAT, PLAN_BRUT, Chantier
from .espace import Espace
from .missions import ETAT_MISSIONS, JOURNAL

BILAN = "BILAN-DE-MAEL.md"
LECONS = "lecons.yaml"
FAMILLES_MAX = 10           # ~2 min par diagnostic sur 8 Go
EXEMPLES_MAX = 3            # preuves montrees au modele par famille
EXTRAIT_MAX = 700           # caracteres d'un extrait de fichier
ESSAIS_MAX = 2              # un diagnostic refuse est refait une fois
FAITS_MAX = 4               # faits etablis montres au modele par famille

SYSTEME_DIAGNOSTIC = """Tu es MAEL, un atelier de code. Tu relis TON PROPRE
travail : une faiblesse qui revient dans tes missions, avec ses preuves.
Les preuves sont des FAITS releves par tes juges : ne les conteste pas.

Reponds UNIQUEMENT par ces lignes, exactement ainsi :
CAUSE : pourquoi cet echec arrive (une phrase, appuyee sur les faits)
LEVIER : le numero ou le nom du levier qui corrige cette cause, ou AUCUN
LECON : seulement si LEVIER est AUCUN : le levier qui manque (une phrase)

Un LEVIER est une action que MAEL sait appliquer a lui-meme : changer une
CONSIGNE (le texte envoye au modele) ou son PROGRAMME (lecteur du plan,
criteres, reparations). On te donne la liste de ceux qui conviennent a
cette faiblesse. Choisis celui qui corrige la CAUSE, pas un autre."""

# Il n'y a plus de ligne ORIGINE (4e essai reel, 08/10/2026 : deux fois le
# BON levier, refuse pour une origine fausse ; le petit modele trebuchait
# sur cette question). L'origine est celle du levier choisi, et le juge la
# confronte aux faits. « code » (1er et 2e essais) se lisait comme le code
# des fichiers ecrits par le modele.
ORIGINES = ("consigne", "programme", "modele")


# ------------------------------------------------------------ les faits
@dataclass
class Constat:
    """Un echec releve par MAEL dans un de ses journaux."""
    mission: str
    fichier: str
    ligne: int
    message: str
    famille: str = ""


@dataclass
class Fait:
    """Un fait ETABLI par MAEL (sans modele) a partir de ses traces : le
    diagnostic doit s'y appuyer, et l'origine doit lui etre compatible."""
    texte: str
    origines: tuple[str, ...]      # les origines que ce fait autorise
    indices: str                   # motif : la CAUSE parle de ce fait
    # Ce qu'une LECON ne doit pas proposer face a ce fait (motif, raison).
    # 2e essai reel (08/10/2026) : « exclure les chemins qui commencent par
    # / » avait ete accepte, alors que c'est justement ce qui bloque.
    contresens: tuple[str, str] | None = None


@dataclass
class Famille:
    cle: str
    titre: str
    constats: list[Constat] = field(default_factory=list)
    preuves: list[str] = field(default_factory=list)   # pour le modele
    faits: list["Fait"] = field(default_factory=list)  # etablis par MAEL
    cause: str = ""
    origine: str = ""
    lecon: str = ""
    levier: str = ""        # id du catalogue (leviers.py), ou AUCUN
    brut: str = ""          # la reponse du modele, si elle est illisible
    essais: int = 0         # diagnostics demandes au modele
    refus: list[str] = field(default_factory=list)   # juge, dernier essai

    def ajouter_fait(self, fait: "Fait"):
        if fait.texte not in {f.texte for f in self.faits}:
            self.faits.append(fait)

    @property
    def missions(self) -> list[str]:
        return sorted({c.mission for c in self.constats})

    @property
    def poids(self) -> tuple[int, int]:
        return (len(self.missions), len(self.constats))


TITRES = {
    "plan-illisible": "le plan n'a donne aucune tache (rien produit)",
    "fichier-du-plan-jamais-ecrit":
        "un fichier prevu au plan n'existe pas a la fin (les pages "
        "l'appellent quand meme)",
    "lien-navigation-manquant": "une page ne mene pas aux autres pages du "
                                "plan (menu incomplet)",
    "ressource-non-chargee": "une page ne charge pas la feuille de style ou "
                             "le script du plan",
    "fragment-traite-en-page": "un morceau de page (en-tete, pied de page) "
                               "traite comme une page complete",
    "structure-de-page": "une page sans <main> ou sans <h1>",
    "lien-casse": "un lien vers un fichier qui n'existe pas",
    "script-plante": "un script qui plante dans le navigateur",
    "contraste": "un texte trop peu contraste",
    "cible-trop-petite": "un bouton ou un lien trop petit au toucher",
    "autre": "autres defauts",
    # Angles morts (angles_morts.py) : ce que MAEL n'a pas pu verifier.
    "page-expiree": "une page jamais ouverte dans le navigateur (delai "
                    "depasse)",
    "pages-hors-budget": "des pages jamais ouvertes dans le navigateur "
                         "(budget de temps epuise)",
}
_FRAGMENTS = re.compile(r"(?i)(^|/)(header|footer|nav|menu|en-?tete|"
                        r"pied(-de-page)?)\.html?$")
_CONSTAT = re.compile(r"^- `([^`:]+):(\d+)` (.+)$")


def classer(c: Constat, prevus: set[str], existants: set[str]) -> str:
    m = c.message
    if "critere de la tache non tenu" in m:
        if _FRAGMENTS.search(c.fichier) and ("<main>" in m or "<h1>" in m
                                             or "mene a" in m):
            return "fragment-traite-en-page"
        if "mene a" in m:
            return "lien-navigation-manquant"
        if "charge " in m:
            return "ressource-non-chargee"
        if "<main>" in m or "<h1>" in m:
            return "structure-de-page"
    if "n'existe pas" in m:
        cible = re.search(r'="([^"]+)"', m)
        cible = posixpath.normpath(cible.group(1).lstrip("./")) if cible \
            else ""
        if cible in prevus and cible not in existants:
            return "fichier-du-plan-jamais-ecrit"
        return "lien-casse"
    if "erreur a l'execution" in m:
        return "script-plante"
    if "contraste" in m:
        return "contraste"
    if "target-size" in m or "24px" in m:
        return "cible-trop-petite"
    return "autre"


def _lire_json(chemin: Path) -> dict:
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def constats_du_journal(texte: str, mission: str) -> list[Constat]:
    """Les lignes de « Ce qui reste a corriger » : ce que MAEL a laisse."""
    section = re.search(r"## Ce qui reste a corriger\n(.*?)(?:\n## |\Z)",
                        texte, re.S)
    out = []
    for ligne in (section.group(1) if section else "").splitlines():
        m = _CONSTAT.match(ligne.strip())
        if m:
            out.append(Constat(mission, m.group(1), int(m.group(2)),
                               m.group(3).strip()))
    return out


def expliquer_plan(texte: str) -> list[tuple[str, bool, str]]:
    """Ligne par ligne, ce que le code de MAEL a fait de la reponse du plan,
    et POURQUOI : la preuve qui permet de dire si le modele ou le code est
    en faute. Meme regle que chantier.lire_plan, mais dite a voix haute."""
    out, vus = [], set()
    lache = re.compile(r"^\s*(?:[-*•]|\d+[.)])?\s*\**`?(\S+?\.[A-Za-z0-9]"
                       r"{1,6})`?\**\s*[:—–-]")
    for ligne in texte.splitlines():
        if not ligne.strip():
            continue
        m = _LIGNE_PLAN.match(ligne)
        if not m:
            l = lache.match(ligne)
            if l and l.group(1).startswith(("/", "\\")):
                raison = ("ecartee : le chemin commence par « / » et le "
                          "lecteur du plan exige un premier caractere "
                          "lettre ou chiffre")
            elif l:
                raison = "ecartee : chemin non reconnu par le lecteur du plan"
            else:
                raison = "ecartee : pas au format « - fichier.ext : but »"
            out.append((ligne.strip(), False, raison))
            continue
        chemin = m.group(1).strip()
        while chemin.startswith("./"):
            chemin = chemin[2:]
        propre = posixpath.normpath(chemin)
        ext = Path(propre).suffix.lower()
        if propre.startswith(".."):
            raison, ok = "ecartee : le chemin sort du projet", False
        elif ext not in juges.EXTENSIONS:
            raison, ok = f"ecartee : extension {ext} inconnue des juges", False
        elif propre in vus:
            raison, ok = "ecartee : doublon", False
        else:
            raison, ok = "retenue", True
            vus.add(propre)
        out.append((ligne.strip(), ok, raison))
    return out


def _extrait(dossier: Path, fichier: str, ligne: int) -> str:
    try:
        lignes = (dossier / fichier).read_text(
            encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return f"(le fichier {fichier} n'existe pas)"
    debut = max(0, ligne - 4) if ligne > 1 else 0
    morceau = "\n".join(f"{i + 1:>3} {l}" for i, l in
                        enumerate(lignes[debut:debut + 14], debut))
    return morceau[:EXTRAIT_MAX]


def _tours_du_journal(texte: str, fichier: str) -> str:
    """Les lignes du tableau « Deroule » qui concernent ce fichier."""
    lignes = [l for l in texte.splitlines()
              if l.startswith("|") and f"| {fichier} |" in l
              or l.startswith("|") and f"| finition {fichier} |" in l]
    return "\n".join(lignes) or "(aucun appel note)"


_LIEN = re.compile(r'(?i)<(?:a|link|script)\b[^>]*?(?:href|src)="([^"]+)"')


def _preuve_tache(dossier: Path, t: dict) -> str:
    """Ce que la CONSIGNE disait (les criteres lui sont montres tels quels)
    et ce que le fichier contient vraiment : de quoi dire si la consigne
    manquait ou si le modele ne l'a pas suivie."""
    try:
        contenu = (dossier / t["fichier"]).read_text(encoding="utf-8",
                                                     errors="replace")
        liens = sorted(set(_LIEN.findall(contenu))) or ["(aucun)"]
    except OSError:
        liens = ["(fichier absent)"]
    criteres = [c.get("texte", "") for c in t.get("criteres", [])]
    return (f"tache {t['fichier']} (« {t.get('but', '')} ») : etat "
            f"« {t.get('etat')} », {t.get('tours')} appel(s)\n"
            "criteres ecrits dans la consigne donnee au modele :\n"
            + "\n".join(f"  - {c}" for c in criteres)
            + "\nliens et ressources vraiment presents dans le fichier : "
            + ", ".join(liens))


# ------------------------------------------- les faits etablis (sans modele)
# Ce que MAEL SAIT de ses traces, avant toute interpretation. Premier essai
# reel (08/10/2026) : phi4-mini avait dit « le modele a ignore le critere »
# alors que c'est la consigne de MAEL qui exigeait un <main> dans
# footer.html, et « verifie que les fichiers existent » pour un style.css
# dont chaque ecriture avait ete COUPEE (trop longue). Les faits sont montres
# au modele, et le juge des diagnostics les lui oppose.
_TOUTES = ORIGINES


def _sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte.lower())
                   if unicodedata.category(c) != "Mn")


def _critere(message: str) -> str:
    m = re.search(r"non tenu : (.+?)(?: \(critere|$)", message)
    return m.group(1).strip() if m else ""


def etablir_fait(cle: str, c: Constat, tache: dict | None) -> Fait | None:
    crit = _critere(c.message)
    ecrits = {x.get("texte", "") for x in (tache or {}).get("criteres", [])}
    if cle == "fragment-traite-en-page":
        return Fait(f"{c.fichier} est un MORCEAU de page (en-tete, pied de "
                    "page) ; la consigne que MAEL lui a donnee exigeait "
                    "pourtant, comme a une page complete : « "
                    + (crit or c.message) + " »", ("consigne", "programme"),
                    r"consigne|critere|exig|demand|plan|comme une page|"
                    r"page complete|morceau|fragment",
                    (r"(ajout|mets|inclu|place)\w* (un |le |des )?<(main|h1)>",
                     "un morceau de page n'a ni <main> ni <h1> : la lecon ne "
                     "doit pas les lui ajouter, mais ne plus les lui exiger"))
    if cle in {"lien-navigation-manquant", "ressource-non-chargee",
               "structure-de-page"} and crit:
        if crit in ecrits:
            return Fait(f"le critere « {crit} » etait ECRIT dans la consigne "
                        f"de {c.fichier}, et le fichier ne le tient pas",
                        ("modele", "consigne"),
                        r"suivi|ignor|oubli|consigne|critere|respect|omis|"
                        r"manqu|pas (mis|ajoute|inclu)",
                        (r"(ajout|inclu|insere|inser|mets|ecri|verifi)"
                         r"[^.]*(dans|a) la consigne",
                         "le critere etait DEJA ecrit dans la consigne : l'y "
                         "ajouter ne change rien ; dis comment le faire TENIR "
                         "(le rappeler, le verifier, le reparer)"))
        return Fait(f"le critere « {crit} » n'apparait PAS dans la consigne "
                    f"de {c.fichier}", ("consigne", "programme"),
                    r"consigne|critere|absent|manqu|pas (dit|ecrit|demande)")
    if cle == "script-plante":
        return Fait(f"{c.fichier}:{c.ligne} plante dans le navigateur : "
                    f"{c.message}", ("modele", "consigne"),
                    r"null|absent|introuvable|existe pas|element|selecteur|"
                    r"\bid\b|getelement|queryselector")
    if cle == "contraste":
        return Fait(f"{c.fichier}:{c.ligne} {c.message}",
                    ("modele", "consigne"), r"couleur|contraste|fond|css")
    if cle == "cible-trop-petite":
        return Fait(f"{c.fichier}:{c.ligne} {c.message}",
                    ("modele", "consigne"),
                    r"taille|px|petit|css|padding|marge|espace")
    if cle == "lien-casse":
        return Fait(f"{c.fichier}:{c.ligne} {c.message} (ni au plan, ni dans "
                    "le projet)", ("modele", "consigne"),
                    r"plan|existe|invent|absent|lien|chemin")
    return None


def fait_du_plan(brut: str) -> Fait | None:
    if not brut.strip():
        return None
    lignes = expliquer_plan(brut)
    barre = sum("« / »" in r for _l, _ok, r in lignes)
    if barre:
        return fait_chemins_barre(len(lignes), barre)
    if not any(ok for _l, ok, _r in lignes):
        return Fait("aucune ligne de la reponse n'est au format « - fichier"
                    ".ext : but »", ("modele", "consigne"),
                    r"format|liste|ligne")
    return None


def fait_chemins_barre(total: int, barre: int) -> Fait:
    """Le fait des missions du 08/10 : des chemins en « / » ecartes. Depuis
    le 09/10 le lecteur les GARDE (levier plan-chemins-tolerants) ; le fait
    reste pour juger les diagnostics de cette famille."""
    return Fait(f"le modele a propose {total} fichier(s) ; le "
                f"lecteur du plan de MAEL en a ecarte {barre} parce que "
                "leur chemin commence par « / » (il ne garde qu'un chemin "
                "qui commence par une lettre ou un chiffre)",
                ("programme", "consigne"),
                r"/|barre|slash|chemin|lecteur|ecart|rejet|absolu|"
                r"commence",
                (r"exclu|rejet|ecart|refus|ignor",
                 "le lecteur ECARTE deja ces chemins, et "
                 "c'est ce qui bloque ; la lecon doit les faire GARDER "
                 "(par exemple en retirant le « / » du debut)"))


def fait_du_fichier_manquant(t: dict, tours: str) -> Fait:
    coupes = sorted(set(re.findall(r"generation coupee \(([^)]+)\)", tours)))
    if coupes:
        return Fait(f"les appels pour ecrire {t['fichier']} ont ete COUPES "
                    f"par MAEL ({', '.join(coupes)}) : le fichier n'a jamais "
                    "ete ecrit en entier", _TOUTES,
                    r"coup|long|trop|taille|limite|interromp|deborde",
                    (r"exist\w* (avant|deja)|presence|verifi\w* que [^.]*"
                     r"exist",
                     "le fichier manquait parce que son ecriture a ete COUPEE"
                     " : verifier qu'il existe ne change rien ; dis comment "
                     "l'ecrire en entier (plus court, en plusieurs fois)"))
    return Fait(f"{t['fichier']} : {t.get('tours')} appel(s), jamais valide "
                f"(etat « {t.get('etat')} »)", _TOUTES,
                r"valid|echou|appel|ecrit|reussi")


def _faits_en_texte(f: Famille, retrait: str = "") -> str:
    """Les premiers faits, et le compte des autres : 15 criteres « mene a »
    non tenus disent la meme chose, et la memoire du modele est courte."""
    l = [f"{retrait}- {x.texte}" for x in f.faits[:FAITS_MAX]]
    if len(f.faits) > FAITS_MAX:
        l.append(f"{retrait}- (et {len(f.faits) - FAITS_MAX} autre(s) fait(s)"
                 " du meme genre)")
    return "\n".join(l)


# ------------------------------------------------- le juge des diagnostics
_ANCRE = re.compile(r"<\w+>|\b[\w-]+\.(?:html?|css|js|py|php)\b|«|/|\bplan\b|"
                    r"consigne|tache|lecteur|menu|pied de page|en-tete|"
                    r"chemin|critere|\d+ ?px|\bnav\b|feuille de style")
_ARTICLE = {"consigne": "la consigne", "programme": "le programme",
            "modele": "le modele"}


def juger_diagnostic(f: Famille) -> list[str]:
    """Les raisons de refuser un diagnostic ; vide = accepte. Mecanique,
    sans modele : il oppose au diagnostic les faits que MAEL a etablis."""
    if not (f.cause and f.levier):
        return ["format non tenu : il faut les lignes CAUSE / LEVIER (et "
                "LECON si LEVIER est AUCUN)"]
    raisons = []
    cause, lecon = _sans_accents(f.cause), _sans_accents(f.lecon)
    proposes = [l.id for l in leviers.pour(f.cle)]
    choisi = leviers.PAR_ID.get(f.levier)
    libre = f.levier == leviers.AUCUN     # seule une lecon libre est jugee
    # 5e essai reel : « un lien vers un fichier qui n'existe pas » — la cause
    # recopiait le titre, et passait parce que le titre contient les mots
    # attendus. Recopier la faiblesse n'est pas l'expliquer.
    titre = _sans_accents(f.titre).strip(" .")
    if titre and _sans_accents(f.cause).strip(" .").startswith(titre[:40]):
        raisons.append("ta CAUSE recopie la faiblesse au lieu de l'expliquer :"
                       " pars du fait etabli"
                       + (f" : {f.faits[0].texte}" if f.faits else ""))
    if libre:
        if not f.lecon:
            raisons.append("LEVIER AUCUN : ecris en LECON le levier qui "
                           "manque (une action precise)")
    elif not choisi or f.levier not in proposes:
        raisons.append(f"LEVIER « {f.levier.lstrip('?')} » n'est pas dans la "
                       "liste de cette faiblesse : choisis "
                       + " ou ".join(proposes) + ", ou AUCUN")
    if f.faits:
        permises = set(f.faits[0].origines)
        for x in f.faits[1:]:
            permises &= set(x.origines)
        permises = permises or {o for x in f.faits for o in x.origines}
        # Le modele en faute (consigne claire, non suivie) : renforcer la
        # consigne ou reparer apres lui, les deux corrigent. Sinon, le levier
        # doit changer ce que les faits designent.
        if (choisi and f.levier in proposes and "modele" not in permises
                and choisi.origine not in permises):
            raisons.append(
                f"le levier {choisi.id} change {_ARTICLE[choisi.origine]}, "
                "mais le fait etabli designe "
                + " ou ".join(_ARTICLE[o] for o in ORIGINES if o in permises)
                + f" : {f.faits[0].texte} — choisis un levier qui le change")
        if not any(re.search(x.indices, cause) for x in f.faits):
            raisons.append("ta CAUSE ne s'appuie sur aucun fait etabli ; "
                           f"pars de celui-ci : {f.faits[0].texte}")
    for x in f.faits if libre else ():
        if x.contresens and re.search(x.contresens[0], lecon):
            raisons.append("ta LECON va a contresens : " + x.contresens[1])
            break
    if libre and f.lecon and not _ANCRE.search(lecon):
        raisons.append("ta LECON est generale (elle repete la regle) : dis "
                       "OU elle s'applique (le plan, la consigne d'une tache, "
                       "le lecteur du plan, quel fichier) et QUOI faire "
                       "exactement")
    return raisons


class SeRelire:
    def __init__(self, backend, racine: Path, *,
                 annoncer: Callable[[str], None] | None = None):
        self.backend = backend
        self.racine = Path(racine)
        self.annoncer = annoncer or (lambda _m: None)
        self.appels = 0
        self.secondes = 0.0

    # ------------------------------------------------------ 1. les faits
    def relever(self) -> list[Famille]:
        etat = _lire_json(self.racine / ETAT_MISSIONS)
        familles: dict[str, Famille] = {}
        montres: set[tuple[str, str, str]] = set()

        def ajouter(cle: str, c: Constat, preuve: str,
                    fait: Fait | None = None):
            f = familles.setdefault(cle, Famille(cle, TITRES[cle]))
            c.famille = cle
            f.constats.append(c)
            if fait:
                f.ajouter_fait(fait)
            # Une preuve par fichier : 8 criteres non tenus du meme
            # footer.html ne sont qu'UN exemple (les autres fichiers aussi
            # meritent d'etre vus).
            if (cle, c.mission, c.fichier) in montres:
                return
            if preuve and len(f.preuves) < EXEMPLES_MAX:
                montres.add((cle, c.mission, c.fichier))
                f.preuves.append(preuve)

        for mid, m in etat.items():
            dossier = self.racine / mid
            if m.get("verdict") == "RIEN PRODUIT":
                preuve, brut = self._preuve_plan(dossier,
                                                 m.get("demande", ""))
                ajouter("plan-illisible",
                        Constat(mid, "(plan)", 0, "aucune tache"), preuve,
                        fait_du_plan(brut))
                continue
            try:
                texte = (dossier / JOURNAL).read_text(encoding="utf-8")
            except OSError:
                continue
            chantier = _lire_json(dossier / ETAT)
            prevus = {t["fichier"] for t in chantier.get("taches", [])}
            existants = {p.relative_to(dossier).as_posix()
                         for p in dossier.rglob("*") if p.is_file()}
            for c in constats_du_journal(texte, mid):
                cle = classer(c, prevus, existants)
                preuve = (f"mission {mid} — `{c.fichier}:{c.ligne}` "
                          f"{c.message}")
                tache = next((t for t in chantier.get("taches", [])
                              if t["fichier"] == c.fichier), None)
                fait = etablir_fait(cle, c, tache)
                if tache and cle in {"fragment-traite-en-page",
                                     "structure-de-page", "ressource-non-chargee",
                                     "lien-navigation-manquant"}:
                    preuve += "\n" + _preuve_tache(dossier, tache)
                elif cle == "script-plante":
                    preuve += ("\nextrait de " + c.fichier + " :\n"
                               + _extrait(dossier, c.fichier, c.ligne))
                if cle == "fichier-du-plan-jamais-ecrit":
                    t = next((t for t in chantier.get("taches", [])
                              if f'"{t["fichier"]}"' in c.message), None)
                    if t:
                        # Une preuve par fichier MANQUANT, pas par page.
                        c = Constat(c.mission, t["fichier"], c.ligne,
                                    c.message)
                        preuve = (f"mission {mid} — {t['fichier']} est "
                                  "appele par les pages mais n'existe pas.\n"
                                  f"la tache {t['fichier']} : etat "
                                  f"« {t.get('etat')} », {t.get('tours')} "
                                  f"appel(s), {t.get('secondes', 0):.0f} s\n"
                                  "ses appels dans mon journal :\n"
                                  + _tours_du_journal(texte, t["fichier"]))
                        fait = fait_du_fichier_manquant(
                            t, _tours_du_journal(texte, t["fichier"]))
                ajouter(cle, c, preuve, fait)
        rangees = sorted(familles.values(), key=lambda f: f.poids,
                         reverse=True)
        return rangees

    def _preuve_plan(self, dossier: Path, demande: str
                     ) -> tuple[str, str]:
        """La reponse du plan, gardee par le chantier ; absente (missions
        lancees avant cette trace) : MAEL rejoue son propre appel de plan."""
        try:
            brut = (dossier / PLAN_BRUT).read_text(encoding="utf-8")
            source = "reponse gardee pendant la mission"
        except OSError:
            if self.backend is None:
                return (f"demande : {demande}\n(reponse du plan non "
                        "gardee)", "")
            self.annoncer(f"{dossier.name} : pas de trace du plan, je "
                          "rejoue mon appel de plan…")
            ch = Chantier(self.backend, Espace(dossier))
            debut = time.monotonic()
            ch.planifier(demande)
            self.secondes += time.monotonic() - debut
            self.appels += 1
            brut = ch.plan_brut
            trace = dossier / PLAN_BRUT
            trace.parent.mkdir(parents=True, exist_ok=True)
            trace.write_text(brut, encoding="utf-8")
            source = "appel de plan rejoue pendant la relecture"
        lignes = "\n".join(f"  {l}\n    -> {r}"
                           for l, _ok, r in expliquer_plan(brut)[:10])
        return (f"mission {dossier.name} — demande : {demande}\n"
                f"reponse du modele au plan ({source}), et ce que le "
                f"lecteur du plan de MAEL en a fait :\n{lignes}", brut)

    # --------------------------------------------------- 2. le diagnostic
    def diagnostiquer(self, f: Famille) -> Famille:
        """Diagnostic par le modele, JUGE par MAEL ; refuse, il est refait
        (conversation neuve) avec les raisons du refus. Toujours refuse au
        dernier essai : garde, marque, et PAS ecrit dans les lecons."""
        base = (f"FAIBLESSE : {f.titre}\n"
                f"Vue {len(f.constats)} fois, dans {len(f.missions)} "
                f"mission(s) : {', '.join(f.missions)}.\n\n")
        if f.faits:
            base += ("FAITS ETABLIS par MAEL (ta CAUSE doit partir de l'un "
                     "d'eux) :\n" + _faits_en_texte(f) + "\n\n")
        base += "PREUVES :\n\n" + "\n\n".join(f.preuves)
        # Les leviers en DERNIER : un petit modele suit mieux la fin.
        base += ("\n\nLEVIERS possibles pour cette faiblesse :\n"
                 + leviers.en_texte(leviers.pour(f.cle))
                 + f"\n{leviers.AUCUN} : aucun ne corrige la cause (dis en "
                 "LECON le levier qui manque)")
        message = base
        for essai in range(1, ESSAIS_MAX + 1):
            debut = time.monotonic()
            rep = self.backend.completer(
                systeme=SYSTEME_DIAGNOSTIC,
                messages=[{"role": "user", "content": message}],
                role_modele="codeur")
            self.secondes += time.monotonic() - debut
            self.appels += 1
            f.essais = essai
            lire_diagnostic(rep.texte, f)
            f.refus = juger_diagnostic(f)
            if not f.refus:
                break
            self.annoncer("  diagnostic refuse par mon juge : "
                          + " ; ".join(f.refus)[:200])
            message = (base + "\n\n[ton diagnostic precedent]\n"
                       + rep.texte.strip()[:800]
                       + "\n\n[REFUSE par le juge de MAEL]\n"
                       + "\n".join(f"- {r}" for r in f.refus)
                       + "\n\nRefais ton diagnostic : les trois lignes.")
        return f

    # ------------------------------------------------------- 3. l'ecrit
    def lancer(self) -> list[Famille]:
        self.annoncer("je relis mes journaux de missions…")
        familles = self.relever()
        self.annoncer(f"{sum(len(f.constats) for f in familles)} echec(s) "
                      f"en {len(familles)} famille(s)")
        for i, f in enumerate(familles[:FAMILLES_MAX], 1):
            if self.backend is None:
                break
            self.annoncer(f"diagnostic {i}/{min(len(familles), FAMILLES_MAX)}"
                          f" : {f.titre}")
            self.diagnostiquer(f)
        (self.racine / BILAN).write_text(self.bilan(familles),
                                         encoding="utf-8")
        # Ses angles morts : ce qu'il n'a pas pu verifier, ses BESOINS, et
        # ce qu'il corrige lui-meme (sans modele : ce sont des faits).
        _texte, angles = angles_morts.rediger(
            self.racine, list(_lire_json(self.racine / ETAT_MISSIONS)))
        self.annoncer(f"{len(angles)} angle(s) mort(s) — voir "
                      f"{angles_morts.BESOINS}")
        ecrire_lecons(self.racine / LECONS,
                      familles + familles_des_angles_morts(angles))
        return familles

    def bilan(self, familles: list[Famille]) -> str:
        etat = _lire_json(self.racine / ETAT_MISSIONS)
        conformes = sum(m.get("verdict") == "CONFORME" for m in etat.values())
        l = ["# Bilan de MAEL — ce que j'ai appris de mes missions", "",
             f"- Relu le {time.strftime('%Y-%m-%d %H:%M')} : {len(etat)} "
             f"mission(s), {conformes} conforme(s)",
             f"- {sum(len(f.constats) for f in familles)} echec(s) releves "
             f"par mes juges, en {len(familles)} famille(s)",
             f"- Diagnostic : {self.appels} appel(s) au modele, "
             f"{self.secondes / 60:.1f} min", "",
             "Les FAITS viennent de mes juges et de mes journaux ; la CAUSE,"
             " l'ORIGINE et la LECON sont mon interpretation : elles restent"
             " « proposees » tant qu'une relance des missions ne montre pas"
             " de progres.", ""]
        for i, f in enumerate(familles, 1):
            l += [f"## {i}. {f.titre}", "",
                  f"- **Vue** {len(f.constats)} fois dans "
                  f"{len(f.missions)} mission(s) : {', '.join(f.missions)}"]
            if f.faits:
                l += ["- **Faits etablis** (sans modele) :",
                      _faits_en_texte(f, "  ")]
            if f.lecon:
                l += [f"- **Cause (selon moi)** : {f.cause}",
                      f"- **Change** : {f.origine or '(a construire)'} "
                      "(ce que le levier corrige)",
                      (f"- **Levier choisi** : `{f.levier}` — {f.lecon}"
                       if f.levier != leviers.AUCUN else
                       f"- **Levier MANQUANT (propose par moi)** : "
                       f"{f.lecon}")]
            if f.essais:
                l += ["- **Mon juge** : " + (
                    f"accepte au {f.essais}e essai" if not f.refus else
                    f"REFUSE apres {f.essais} essai(s), lecon NON retenue : "
                    + " ; ".join(f.refus))]
            if not f.lecon and f.brut:
                l += ["- **Diagnostic illisible** (le modele n'a pas suivi "
                      "le format) :", "", "```", f.brut.strip()[:800], "```"]
            elif not f.essais:
                l += ["- pas encore diagnostiquee"]
            l += ["", "<details><summary>preuves</summary>", "", "```"]
            l += ["\n\n".join(f.preuves)[:3000], "```", "", "</details>", ""]
        return "\n".join(l)


def familles_des_angles_morts(angles) -> list[Famille]:
    """Un angle mort que MAEL sait corriger lui-meme devient une lecon
    proposee : le levier est donne par le fait (pas de diagnostic)."""
    out = []
    for genre, levier in angles_morts.CORRIGEABLES.items():
        vus = [a for a in angles if a.genre == genre]
        if not vus:
            continue
        f = Famille(genre, TITRES[genre], levier=levier, origine="programme",
                    lecon=leviers.PAR_ID[levier].action,
                    cause="; ".join(f"{a.mission} : {a.detail}"
                                    for a in vus)[:300])
        f.constats = [Constat(a.mission, a.objet, 0, a.detail) for a in vus]
        out.append(f)
    return out


def lire_diagnostic(texte: str, f: Famille) -> None:
    """Les trois lignes du modele ; un format non tenu est garde tel quel et
    signale, jamais complete a sa place."""
    propre = texte.replace("*", "")

    def champ(nom: str) -> str:
        m = re.search(rf"(?im)^\s*{nom}\s*:\s*(.+)$", propre)
        return m.group(1).strip() if m else ""
    f.cause = champ("CAUSE")
    choix = champ("LEVIER")
    f.levier = leviers.lire(choix, leviers.pour(f.cle)) if choix else ""
    if choix and not f.levier:
        f.levier = "?" + choix[:60]           # inconnu : le juge le dira
    libre = champ("LE[CÇ]ON")
    l = leviers.PAR_ID.get(f.levier)
    # La lecon d'un levier est SON action (applicable), et son origine est
    # ce qu'il change ; un levier manquant garde la proposition du modele.
    f.lecon = l.action if l else libre
    f.origine = l.origine if l else ""
    if not (f.cause and f.levier):
        f.cause = f.origine = f.lecon = f.levier = ""
        f.brut = texte


def ecrire_lecons(chemin: Path, familles: list[Famille]) -> None:
    """lecons.yaml : une lecon par famille. Une lecon VALIDEE (par une
    relance) n'est jamais ecrasee ; une proposee est remplacee par la
    nouvelle relecture."""
    try:
        anciennes = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    except OSError:
        anciennes = {}
    par_cle = {l["famille"]: l for l in anciennes.get("lecons", [])}
    date = time.strftime("%Y-%m-%d")
    for f in familles:
        if not (f.lecon or f.refus):
            continue                      # pas diagnostiquee
        if par_cle.get(f.cle, {}).get("etat") == "validee":
            continue
        etat = ("refusee par le juge" if f.refus else
                "levier manquant" if f.levier == leviers.AUCUN else
                "proposee")
        par_cle[f.cle] = {
            "famille": f.cle, "faiblesse": f.titre, "levier": f.levier,
            "lecon": f.lecon, "origine": f.origine, "cause": f.cause,
            "vue": len(f.constats), "missions": f.missions,
            "etat": etat, "date": date}
        if f.refus:
            # Jamais appliquee : elle reste visible, avec ses raisons, pour
            # suivre ce que MAEL ne sait pas encore diagnostiquer.
            par_cle[f.cle]["refus"] = f.refus
    chemin.write_text(
        "# Les lecons de MAEL, ecrites par lui en relisant ses missions.\n"
        "# levier : une action du catalogue (leviers.py) que MAEL sait "
        "appliquer.\n"
        "# etat : proposee -> validee (une relance montre un progres) ou "
        "rejetee ; levier manquant = aucun levier ne convient (a construire)."
        "\n" + yaml.safe_dump(
            {"lecons": list(par_cle.values())}, allow_unicode=True,
            sort_keys=False, width=88), encoding="utf-8")
