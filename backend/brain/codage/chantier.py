"""Le chantier : une grande demande, faite tache par tache, sans perdre le fil.

L'atelier (atelier.py) garde toute la conversation : bien pour une page,
mais la memoire d'un petit modele se remplit vite (sixieme essai reel :
3 186 jetons sur 4 096 au 3e tour) et chaque tour ralentit. Le chantier :

  1. PLAN : un appel court decoupe la demande en fichiers (une ligne par
     fichier, pas de code). Il est enregistre dans .mael/chantier.json ;
  2. TACHE PAR TACHE : chaque appel repart d'une conversation NEUVE :
     la demande, le plan (fait / en cours / a faire), la CARTE du projet
     (carte.py), le savoir de la tache, et « ecris UNIQUEMENT ce fichier ».
     La memoire du modele ne grossit plus avec le projet ;
  3. JUGES RAPIDES pendant les taches (sans navigateur, quelques secondes),
     qui ignorent les liens vers des fichiers prevus mais pas encore ecrits ;
     reparation automatique avant tout rappel du modele ;
  4. FINITION : les juges complets (navigateur compris) sur tout le projet,
     puis une correction ciblee par fichier fautif ;
  5. REPRISE : `--reprendre` repart de la premiere tache non finie (coupure,
     machine eteinte, modele qui cale).
"""
from __future__ import annotations

import json
import posixpath
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from ..backends.sante import MoteurEnPanne
from . import (
    bac_a_sable,
    contrats,
    deliberation,
    envergure,
    etapes,
    execution,
    fraicheur,
    juges,
    leviers,
    memoire,
    professeurs,
    reparation,
    retouche,
    savoir_faire,
    specialistes,
)
from . import conseil_juges as cj
from . import demande as fidelite
from .atelier import (
    SYSTEME,
    Bilan,
    Tour,
    _contenu_projet,
    _hors_blocs,
    message_correction,
)
from .carte import carte
from .comprehension import comprendre
from .criteres import Critere, deduire, manques, pour_un_script, verifier
from .espace import CheminRefuse, Espace
from .extraction import extraire
from .juges import GRAVITE, Defaut
from .logistique import Logistique

TACHES_MAX = 8
TOURS_PAR_TACHE = 2      # ecrire, puis une correction ; le reste a la finition
# La finition repart de la MEMOIRE DE TRAVAIL (memoire.py) : tous les
# fichiers fautifs, en plusieurs passes tant qu'elles font baisser le nombre
# de bloquants (examen du 09/10 : trois fichiers seulement, le reste laisse).
FICHIERS_EN_FINITION = 8
PASSES_FINITION = 2
# Un plan tient en quelques lignes : au-dela, le modele tourne en rond
# (examen du 09/10 : 3 800 jetons, 20 minutes).
PLAN_JETONS = 700
# La forme imposee au plan quand le texte libre echoue (_plan_contraint).
PLAN_SCHEMA = {
    "type": "object",
    "properties": {"fichiers": {
        "type": "array", "minItems": 1, "maxItems": 8,
        "items": {"type": "object",
                  # Un VRAI nom de fichier, relatif, d'une extension jugee
                  # (essai reel du 09/10 : « / », « /pains » sans le motif) ;
                  # et une phrase, pas du code (le modele y ecrivait la page).
                  "properties": {
                      "chemin": {"type": "string", "pattern":
                                 r"^[a-z0-9_-]+(/[a-z0-9_-]+)*\."
                                 r"(html|css|js|mjs|jsx|py|php|java)$"},
                      "contenu": {"type": "string", "maxLength": 160,
                                  "pattern": "^[^<>{}]*$"}},
                  "required": ["chemin", "contenu"]}}},
    "required": ["fichiers"],
}
ETAT = ".mael/chantier.json"
PLAN_BRUT = ".mael/plan-brut.txt"   # la reponse du plan, gardee si vide

SYSTEME_PLAN = """Tu es le chef de chantier de MAEL. Tu decoupes une demande
en FICHIERS a ecrire. Tu n'ecris AUCUN code.

Reponds UNIQUEMENT par une liste, une ligne par fichier, exactement ainsi :
- chemin/du/fichier.ext : ce que ce fichier doit contenir (une phrase)

Entre 1 et 8 lignes. S'il y a des pages : d'abord les pages HTML (index.html
en premier), puis le CSS, puis le JavaScript. Une API ou un programme sans
pages n'a AUCUN fichier HTML : son code, puis ses tests. Chemins RELATIFS
simples, jamais de « / » au debut. Un en-tete, un menu ou un pied de page
n'est PAS un fichier : il s'ecrit dans chaque page. Des donnees a garder :
prevois db/schema.sql (les tables) et, si le schema evolue,
db/migrations/001_nom.sql. MAEL range lui-meme les fichiers (dossiers
standard) et ecrit README, requirements.txt, .gitignore, docker-compose.yml."""

_LIGNE_PLAN = re.compile(
    # « /app.py » : le « / » est retire (levier plan-chemins-tolerants).
    r"^\s*(?:[-*•]|\d+[.)])?\s*\**`?/?([\w][\w./-]*\.[A-Za-z0-9]{1,6})`?"
    r"\**\s*[:—–-]\s*(.+?)\s*$")
# Defauts vus sur les PAGES par le navigateur, mais qui se corrigent dans la
# feuille de style : ils appartiennent a la tache CSS.
_VISUELLES = {"contraste", "cible-trop-petite", "debordement-mobile"}
_ORDRE = {".html": 0, ".htm": 0, ".css": 1, ".js": 2, ".mjs": 2, ".jsx": 2}
_LANGAGE = {".htm": "html", ".mjs": "js", ".jsx": "jsx", ".py": "python"}


@dataclass
class Tache:
    fichier: str
    but: str
    etat: str = "a faire"          # a faire | fait (= VERROUILLE) | a revoir
    tours: int = 0
    secondes: float = 0.0
    criteres: list = field(default_factory=list)   # dicts de criteres.py
    verifies: str = ""             # « 4/4, 1 non verifie » a la validation

    def liste_criteres(self) -> list[Critere]:
        return [Critere(**c) for c in self.criteres]


def lire_plan(texte: str, maximum: int = TACHES_MAX) -> list[Tache]:
    """La liste du chef de chantier -> taches validees. Un chemin qui sort du
    projet, un doublon, une extension inconnue : ecartes."""
    taches, vus = [], set()
    for ligne in texte.splitlines():
        m = _LIGNE_PLAN.match(ligne)
        if not m:
            continue
        chemin = m.group(1).strip()
        while chemin.startswith("./"):
            chemin = chemin[2:]
        propre = posixpath.normpath(chemin)
        ext = Path(propre).suffix.lower()
        if (propre.startswith("..") or propre.startswith("/")
                or ext not in juges.EXTENSIONS or propre in vus):
            continue
        vus.add(propre)
        taches.append(Tache(propre, m.group(2).strip().rstrip(".")))
    # index.html d'abord, puis les pages, le CSS, le JS, le reste.
    taches.sort(key=lambda t: (t.fichier != "index.html",
                               _ORDRE.get(Path(t.fichier).suffix.lower(), 3)))
    return taches[:maximum]


# Un fichier de tache depasse rarement 5 000 caracteres (une page complete :
# ~3 500). Au-dela de 9 000 (~2 300 jetons), le modele deborde sa memoire de
# travail de 4 096 jetons (consigne comprise) : on coupe.
LONGUEUR_MAX = 9_000
REPETITIONS_MAX = 8          # 8 dernieres lignes, 2 contenus differents
_OUVERTURE = re.compile(r"(?m)^```[ \t]*([^\n`]*)\n")
_FERMETURE = re.compile(r"(?m)^```[ \t]*$")


def meme_fichier(nom: str, fichier: str) -> bool:
    """Le bloc `nom` est-il le fichier de la tache ? Oui s'il porte son
    chemin, ou son seul NOM : la logistique range style.css dans
    assets/css/, le modele ecrit encore « fichier=style.css » (09/10)."""
    nom = nom.strip().lstrip("/")
    # ...ou la fin de son chemin : js/menu.js pour assets/js/menu.js.
    return nom == fichier or fichier.endswith("/" + nom)


def surveiller(texte: str, fichier: str,
               longueur_max: int = LONGUEUR_MAX) -> str:
    """Pendant que le modele ecrit : « continuer », « fini » (le bloc du
    fichier de la tache est complet) ou « hors-tache » (il a commence un
    bloc pour un AUTRE fichier). Cinquieme essai : pour js/app.js, le modele
    a ecrit les 4 autres fichiers avant le sien — 593 s pour 17 lignes."""
    from .extraction import _ENTETE_COURT, _ENTETE_NOM
    for m in _OUVERTURE.finditer(texte):
        entete = m.group(1).strip()
        nom_m = _ENTETE_NOM.search(entete) or _ENTETE_COURT.match(entete)
        nom = nom_m.group(1).strip() if nom_m else ""
        while nom.startswith("./"):
            nom = nom[2:]
        if nom and not meme_fichier(nom, fichier):
            return "hors-tache"
        if nom and _FERMETURE.search(texte, m.end()):
            return "fini"
    # Garde-fous contre la generation sans fin (sixieme essai : 3 600 jetons
    # pour index.html, bloc jamais ferme, 22 minutes ; au-dela de sa memoire
    # de travail, le modele perd sa consigne et boucle).
    if len(texte) > longueur_max:
        return "trop-long"
    lignes = [l.strip() for l in texte.split("\n") if l.strip()]
    if len(lignes) >= REPETITIONS_MAX and len(
            set(lignes[-REPETITIONS_MAX:])) <= 2:
        return "boucle"
    return "continuer"


PARTIES_MAX = 3          # levier « ecrire-en-plusieurs-fois »


def _debut_sain(texte: str, fichier: str) -> str:
    """Le contenu d'un bloc JAMAIS ferme (generation coupee), raccourci a un
    endroit sain : apres la derniere regle fermee « } » pour du CSS ou du
    JS, apres la derniere ligne complete sinon ; une fin qui boucle (memes
    lignes repetees) est retiree."""
    m = None
    for o in _OUVERTURE.finditer(texte):
        m = o
    if m is None:
        return ""
    corps = texte[m.end():]
    lignes = corps.split("\n")[:-1]          # la derniere est incomplete
    while (len(lignes) >= 2 and lignes[-1].strip()
           and lignes[-1].strip() == lignes[-2].strip()):
        lignes.pop()                         # une boucle : on la retire
    corps = "\n".join(lignes)
    if Path(fichier).suffix.lower() in {".css", ".js", ".mjs"}:
        coupe = corps.rfind("}")
        corps = corps[:coupe + 1] if coupe >= 0 else ""
    return corps


_SCRIPT_SRC = re.compile(r"(?im)^[ \t]*<script\b[^>]*\bsrc=[^>]*>\s*</script>"
                         r"[ \t]*\n?")
_LISTE_NAV = re.compile(r"(?is)(<nav\b[^>]*>\s*<ul>)(.*?)(</ul>)")


def _intitule(page: str) -> str:
    nom = Path(page).stem.replace("-", " ").replace("_", " ")
    return "Accueil" if nom == "index" else nom.capitalize()


def adapter_savoir(savoir: str, pages: list[str], fichier: str) -> str:
    """Les gabarits sont des formes justes GENERALES : leurs liens (/produits,
    /contact) et leurs <script src="menu.js"> ne sont pas ceux du projet, et
    le modele les recopiait (d'ou un js/app.js ajoute a chaque essai). Avant
    de les montrer : les liens d'un menu deviennent les PAGES DU PLAN, et
    les <script src> sont retires (le plan decide des scripts, les criteres
    verifient leur chargement)."""
    if not savoir:
        return savoir
    texte = _SCRIPT_SRC.sub("", savoir)
    if pages:
        dossier = posixpath.dirname(fichier) or "."
        liens = "".join(
            f'\n      <li><a href="{posixpath.relpath(p, dossier)}">'
            f"{_intitule(p)}</a></li>" for p in pages)
        texte = _LISTE_NAV.sub(lambda m: m.group(1) + liens + "\n    "
                               + m.group(3), texte)
    return texte


def _langage(fichier: str) -> str:
    ext = Path(fichier).suffix.lower()
    return _LANGAGE.get(ext, ext.lstrip("."))


class Chantier:
    def __init__(self, backend, espace: Espace, *, role: str = "codeur",
                 savoir: Callable[[str], str] | None = None,
                 annoncer: Callable[[str], None] | None = None,
                 leviers: set[str] | None = None):
        self.backend = backend
        self.espace = espace
        self.role = role
        # La LOGISTIQUE (logistique.py) : un maillon de la chaine qui range
        # le projet au plan, apres chaque ecriture, et a la fin.
        self.logistique = Logistique(espace)
        # L'ENVERGURE du modele (envergure.py) : les reglages suivent le
        # modele charge ; lue au lancement (le moteur peut demarrer).
        self.env = envergure.PETIT
        # Le chantier PAR ETAPES (etapes.py) : vide pour un projet ordinaire.
        self.etapes: list = []
        self.savoir = savoir
        self.annoncer = annoncer or (lambda _m: None)
        # Les LECONS que MAEL applique (leviers.py) et combien de fois elles
        # ont servi : la verification ne juge pas un levier qui n'a jamais
        # joue.
        self.leviers = set(leviers or ())
        # La memoire de travail : aucun probleme laisse en route.
        self.memoire = memoire.Memoire()
        self.leviers_utilises: dict[str, int] = {}
        # Le temps passe a JUGER (pas a ecrire) et les specialistes appeles :
        # la mesure du gain des specialistes.
        self.jugement = 0.0
        self.specialistes_utilises: dict[str, int] = {}
        # Le savoir-faire donne, et ce qui n'allait pas (perime, manquant).
        self.savoir_faire_utilise: dict[str, int] = {}
        self.savoir_problemes: list[str] = []
        # Le conseil des professeurs (professeurs.py) : ses appels au modele
        # comptent dans les chiffres de la mission.
        self.appels_conseil = 0
        self.secondes_conseil = 0.0
        self.conseil_refus: list[str] = []
        # Le conseil sur les verdicts des juges (conseil_juges.py).
        self.coupures_par_fichier: dict[str, list[str]] = {}
        self.verdicts_conseil = 0
        self.demande = ""
        self.taches: list[Tache] = []
        self.numero = 0               # numero global des appels au modele
        self.signales: list[str] = []  # verrouilles avec un defaut restant
        self.suppositions: list[str] = []  # ce que MAEL a decide a la place
        self.coupure = ""        # pourquoi le dernier flux a ete coupe
        self.provisoires: list[str] = []  # images creees par MAEL
        # La reponse BRUTE du chef de chantier : la preuve que MAEL relit
        # quand le plan n'a rien donne (missions 07 et 10 du 08/10/2026).
        self.plan_brut = ""

    # ------------------------------------------------------- etat sur disque
    @property
    def _fichier_etat(self) -> Path:
        return Path(self.espace.racine) / ETAT

    def _sauver(self):
        self._fichier_etat.parent.mkdir(parents=True, exist_ok=True)
        self._fichier_etat.write_text(json.dumps(
            {"demande": self.demande,
             "suppositions": self.suppositions,
             "taches": [asdict(t) for t in self.taches],
             "etapes": [e.vers_dict() for e in self.etapes]},
            ensure_ascii=False, indent=1), encoding="utf-8")

    def _charger(self) -> bool:
        try:
            d = json.loads(self._fichier_etat.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        self.demande = d.get("demande", "")
        self.suppositions = list(d.get("suppositions", []))
        self.taches = [Tache(**t) for t in d.get("taches", [])]
        self.etapes = [etapes.Etape(**e) for e in d.get("etapes", [])]
        return bool(self.taches or self.etapes)

    # ------------------------------------------------------------- modele
    def _appeler_un_fichier(self, systeme: str, message: str, fichier: str
                            ) -> tuple[str, float]:
        """Appel pour ECRIRE un seul fichier, lu au fil de l'eau : on coupe
        des que son bloc est complet, ou des que le modele part sur un autre
        fichier (la relance le lui dira). Couper le flux ferme la connexion,
        et Ollama arrete alors la generation. Un moteur sans flux (faux
        modele des tests) repond d'un bloc, comme avant."""
        flux = getattr(self.backend, "flux", None)
        if flux is None:
            return self._appeler(systeme, message)
        debut = time.monotonic()
        texte = ""
        self.coupure = ""
        # Un modele plus grand que le petit ecrit plus long d'un coup.
        borne = ({"max_jetons": self.env.jetons_reponse}
                 if self.env.classe != "petit" and getattr(
                     self.backend, "accepte_max_jetons", False) else {})
        generateur = iter(flux(systeme=systeme,
                               messages=[{"role": "user", "content": message}],
                               role_modele=self.role, **borne))
        try:
            for fragment in generateur:
                texte += fragment
                etat = surveiller(
                    texte, fichier, LONGUEUR_MAX if self.env.classe ==
                    "petit" else self.env.longueur_fichier)
                if etat != "continuer":
                    self.coupure = etat if etat != "fini" else ""
                    if etat == "hors-tache":
                        self.annoncer(f"{fichier} : le modele part sur un "
                                      "autre fichier, coupe")
                    elif etat in {"trop-long", "boucle"}:
                        self.annoncer(f"{fichier} : generation coupee "
                                      f"({etat}, {len(texte)} caracteres)")
                    break
        finally:
            close = getattr(generateur, "close", None)
            if close:
                close()
        return texte, time.monotonic() - debut

    def _noter_coupure(self, tour: Tour):
        """La coupure du flux va au tour : le journal des missions la compte,
        et le conseil des professeurs la voit (fichier jamais ecrit)."""
        if self.coupure:
            tour.refus.append(f"generation coupee ({self.coupure})")
            fichier = tour.tache.replace("finition ", "")
            self.coupures_par_fichier.setdefault(fichier, []).append(
                self.coupure)

    def _appeler(self, systeme: str, message: str,
                 max_jetons: int | None = None) -> tuple[str, float]:
        debut = time.monotonic()
        borne = ({"max_jetons": max_jetons} if max_jetons and getattr(
            self.backend, "accepte_max_jetons", False) else {})
        rep = self.backend.completer(
            systeme=systeme, messages=[{"role": "user", "content": message}],
            role_modele=self.role, **borne)
        return rep.texte, time.monotonic() - debut

    # --------------------------------------------------------------- plan
    def _plan_contraint(self, message: str) -> list[Tache]:
        """Dernier recours quand le plan reste illisible : la sortie est
        CONTRAINTE par un schema (le decodage interdit au modele d'ecrire
        autre chose qu'une liste de fichiers). Examen du 09/10 : meme sain,
        phi4-mini repondait une page HTML au lieu du plan. Seulement pour un
        moteur qui sait contraindre (Ollama) ; les faux moteurs des tests,
        non."""
        if not getattr(self.backend, "accepte_max_jetons", False):
            return []
        self.annoncer("plan illisible : je force le format (sortie "
                      "contrainte par schema)")
        try:
            rep = self.backend.completer(
                systeme=SYSTEME_PLAN,
                messages=[{"role": "user", "content": message}],
                role_modele=self.role, schema=self._schema_plan(),
                max_jetons=self.env.jetons_plan)
        except MoteurEnPanne:
            raise
        except Exception as exc:                        # noqa: BLE001
            self.annoncer(f"plan contraint impossible : {exc}")
            return []
        lignes = [f"- {f.get('chemin', '')} : {f.get('contenu', '')}"
                  for f in (rep.donnees or {}).get("fichiers", [])
                  if isinstance(f, dict)]
        self.plan_brut += "\n\n--- plan contraint ---\n" + "\n".join(lignes)
        return lire_plan("\n".join(lignes), self.env.taches_par_lot)

    def _doyen(self, message: str, texte: str, taches: list[Tache],
               faits) -> tuple[list[Tache], str]:
        """Le DOYEN juge le plan rendu contre les faits du conseil (plan
        illisible, API sans son .py ni ses tests...) et le fait refaire UNE
        fois en disant pourquoi ; un plan refait qui ne fait pas mieux n'est
        pas garde."""
        if taches:
            raisons = professeurs.juger_plan([t.fichier for t in taches],
                                             faits)
        elif re.search(r"(?m)^\s*(?:[-*•]|\d+[.)])?\s*\**`?/", texte):
            raisons = ["tes chemins commencent par « / » : ecris des chemins "
                       "RELATIFS (app.py, tests/test_app.py), sinon ils sont "
                       "ecartes"]
        else:
            raisons = ["aucune ligne au format « - fichier.ext : ce qu'il "
                       "contient »"]
        if not raisons:
            return taches, texte
        self.annoncer("doyen : plan refuse — " + " ; ".join(raisons)[:200])
        texte2, _s = self._appeler(
            SYSTEME_PLAN, message + "\n\n[le DOYEN refuse ton plan]\n"
            + "\n".join(f"- {r}" for r in raisons) + "\nRefais le plan.",
            self.env.jetons_plan)
        self.appels_conseil += 1
        self.plan_brut += "\n\n--- doyen ---\n" + texte2
        refait = lire_plan(texte2, self.env.taches_par_lot)
        if refait and len(professeurs.juger_plan(
                [t.fichier for t in refait], faits)) < max(len(raisons), 1):
            return refait, texte2
        if refait and not taches:
            return refait, texte2
        self.suppositions.append("plan garde malgre le doyen : "
                                 + " ; ".join(raisons))
        return taches, texte

    def planifier(self, demande: str, etape: str = "",
                  deja: list[Tache] | None = None) -> list[Tache]:
        """Le plan d'une demande, ou d'UNE ETAPE d'un grand projet (etape =
        sa consigne ; deja = les taches des etapes precedentes)."""
        deja = list(deja or [])
        # COMPRENDRE avant de planifier : fautes, anglais, nombre de pages,
        # contradictions, demande vague. Tout ce que MAEL decide a la place
        # du developpeur devient une SUPPOSITION ecrite.
        c = comprendre(demande)
        self.logistique.demande = demande.strip()
        if etape:
            for s in c.suppositions:
                if s not in self.suppositions:
                    self.suppositions.append(s)
        else:
            self.suppositions = c.suppositions
            for s in self.suppositions:
                self.annoncer(f"compris : {s}")
        message = demande.strip()
        if etape:
            message += "\n\n" + etape
        if c.corrections or c.langue == "en":
            message += f"\n\n[demande comprise par MAEL] {c.texte}"
        if c.nb_pages and not etape:
            message += (f"\n\nLe site a EXACTEMENT {c.nb_pages} page(s) "
                        "HTML.")
        if specialistes.actifs():
            # Conduire un LONG projet : l'ordre, la structure, les
            # dependances se decident ici (savoir_faire/projet.yaml).
            conduite, choix = savoir_faire.pour_plan(message)
            if conduite:
                message += "\n\n" + conduite
                for f in choix.fiches:
                    self.savoir_faire_utilise[f.id] = (
                        self.savoir_faire_utilise.get(f.id, 0) + 1)
        faits = None
        if professeurs.actifs():
            # Le CONSEIL DES PROFESSEURS delibere AVANT le plan, ENTRE EUX,
            # par programme, sans le modele (decision du responsable,
            # 08/10/2026 : « il prendrait beaucoup de temps »). Ses decisions
            # vont au chef de chantier ; ce qu'il faut demander a la personne
            # va au journal.
            self.annoncer("conseil des professeurs : deliberation…")
            debut = time.monotonic()
            d = deliberation.deliberer(
                demande, fichiers_max=self.env.taches_par_lot)
            faits = professeurs.etablir(
                demande, fichiers_max=self.env.taches_par_lot)
            self.secondes_conseil += time.monotonic() - debut
            if not d.refus:
                message += "\n\n" + d.texte()
                self.suppositions += [
                    f"a demander a la personne : {b.texte}"
                    for b in d.besoins
                    if f"a demander a la personne : {b.texte}"
                    not in self.suppositions]
            else:
                self.conseil_refus = d.refus
        self.annoncer("plan : le chef de chantier decoupe la demande…")
        texte, secondes = self._appeler(SYSTEME_PLAN, message,
                                        self.env.jetons_plan)
        self.plan_brut = texte
        taches = lire_plan(texte, self.env.taches_par_lot)
        if faits is not None and not etape:
            # Le doyen juge le plan ENTIER (une API sans son .py...) : une
            # etape n'en est qu'un morceau, il ne la juge pas.
            taches, texte = self._doyen(message, texte, taches, faits)
        if not taches:
            taches = self._plan_contraint(message)

        def nb_html(ts):
            return sum(Path(t.fichier).suffix.lower() in {".html", ".htm"}
                       for t in ts)
        if c.nb_pages and taches and not etape and \
                nb_html(taches) != c.nb_pages:
            # Une seule relance : le plan doit tenir le nombre annonce.
            avant = nb_html(taches)
            self.annoncer(f"plan : {avant} page(s) au lieu de {c.nb_pages}, "
                          "relance")
            texte, s2 = self._appeler(
                SYSTEME_PLAN, message + f"\n\nTon plan avait {avant} page(s) "
                f"HTML : il en faut EXACTEMENT {c.nb_pages}.", self.env.jetons_plan)
            secondes += s2
            self.plan_brut += "\n\n--- relance ---\n" + texte
            refait = lire_plan(texte, self.env.taches_par_lot)
            if refait and nb_html(refait) == c.nb_pages:
                taches = refait
            else:
                self.suppositions.append(
                    f"le plan a {avant} page(s) HTML au lieu des "
                    f"{c.nb_pages} demandees")
        # Des pages sans feuille de style : les pages en appelleront une
        # quand meme (premier essai du chantier : css/style.css partout,
        # jamais prevu). On la prevoit d'office.
        pages = [t for t in taches
                 if Path(t.fichier).suffix.lower() in {".html", ".htm"}]
        if pages and not any(t.fichier.endswith(".css")
                             for t in taches + deja):
            taches.append(Tache("style.css", "la feuille de style commune "
                                "a toutes les pages"))
        # LOGISTIQUE au plan : chaque fichier a son adresse standard ; un
        # morceau de page (footer.html) n'est pas une tache.
        adresses = self.logistique.adresser([t.fichier for t in taches],
                                            [t.fichier for t in deja])
        taches = [t for t in taches
                  if t.fichier not in self.logistique.fragments]
        for t, f in zip(taches, adresses):
            t.fichier = f
        for g in self.logistique.gestes:
            self.annoncer(f"logistique : {g}")
        if self.logistique.fragments:
            self.suppositions.append(
                "en-tete, menu et pied de page ecrits dans chaque page (pas "
                "de fichier a part : " + ", ".join(self.logistique.fragments)
                + ")")
        if deja:
            # une etape ne replanifie jamais un fichier deja fait
            faits_avant = {t.fichier for t in deja}
            taches = [t for t in taches if t.fichier not in faits_avant]
        fichiers = [t.fichier for t in deja] + [t.fichier for t in taches]
        for t in taches:
            t.criteres = [c.vers_dict()
                          for c in deduire(t.fichier, t.but, fichiers)]
        self.annoncer(f"plan : {len(taches)} tache(s) en {secondes:.0f} s")
        return taches

    # ------------------------------------------------------------- etapes
    def _decider_etapes(self, demande: str) -> bool:
        """Grand projet ? Alors l'ARCHITECTE le decoupe en etapes (etapes.py).
        La decision est un calcul sur la demande, dit au journal."""
        prevus = professeurs.fichiers_prevus(professeurs.etablir(
            demande, fichiers_max=self.env.taches_par_lot))
        oui, raison = etapes.faut_des_etapes(demande, self.env.taches_par_lot,
                                             prevus)
        if not oui:
            return False
        self.annoncer(f"etapes : grand projet — {raison} ; l'architecte "
                      "decoupe…")
        consigne = etapes.SYSTEME_ARCHITECTE.format(
            par_lot=self.env.taches_par_lot, max=etapes.ETAPES_MAX)
        lues = []
        if getattr(self.backend, "accepte_max_jetons", False):
            try:
                rep = self.backend.completer(
                    systeme=consigne,
                    messages=[{"role": "user", "content": demande}],
                    role_modele=self.role, schema=etapes.SCHEMA_ETAPES,
                    max_jetons=self.env.jetons_plan)
                lues = etapes.lire_etapes(donnees=rep.donnees)
            except MoteurEnPanne:
                raise
            except Exception as exc:                    # noqa: BLE001
                self.annoncer(f"architecte : sortie contrainte impossible "
                              f"({exc})")
        if len(lues) < 2:
            texte, _s = self._appeler(consigne, demande, self.env.jetons_plan)
            lues = etapes.lire_etapes(texte)
        if len(lues) < 2:
            self.annoncer("etapes : decoupage illisible, un seul plan")
            return False
        self.etapes = lues
        for i, e in enumerate(lues, 1):
            self.annoncer(f"etape {i}/{len(lues)} : {e.nom} — {e.livre}")
        self._sauver()
        return True

    def _executer_etapes(self, bilan: Bilan) -> None:
        """Chaque etape : contrats releves, plan de l'etape, taches ecrites,
        jugees et reparees ; l'etat est garde apres chaque etape."""
        racine = Path(self.espace.racine)
        for i, e in enumerate(self.etapes):
            if e.etat == "faite":
                continue
            ecrits = [t.fichier for t in self.taches
                      if (racine / t.fichier).exists()]
            contr = contrats.relever(racine, ecrits).texte(
                self.env.budget_contrats)
            self.annoncer(f"=== etape {i + 1}/{len(self.etapes)} : {e.nom} "
                          "===")
            nouvelles = self.planifier(
                self.demande, etapes.consigne_etape(
                    i, self.etapes, contr, [t.fichier for t in self.taches]),
                deja=self.taches)
            self.taches += nouvelles
            e.fichiers = [t.fichier for t in nouvelles]
            self._sauver()
            for t in nouvelles:
                self._tache(t, bilan)
            e.etat = "faite"
            bilan.etapes.append(f"{i + 1}. {e.nom} — {e.livre} : "
                                f"{len(nouvelles)} fichier(s) "
                                f"({', '.join(e.fichiers) or 'aucun'})")
            self._sauver()

    # ------------------------------------------------------------ consignes
    def _plan_en_texte(self, courante: Tache | None) -> str:
        l = []
        for t in self.taches:
            etat = ("EN COURS" if t is courante else
                    "fait" if t.etat == "fait" else "a faire")
            l.append(f"  [{etat}] {t.fichier} : {t.but}")
        return "\n".join(l)

    def _savoir_pour(self, t: Tache) -> str:
        """Le savoir de la tache, limite aux gabarits du type de son
        fichier. Un savoir injecte qui ne connait pas `fichier` (ancien
        branchement, tests) est appele sans."""
        if not self.savoir:
            return self._savoir_faire(t)   # le savoir-faire, meme sans gabarit
        texte = f"{t.but} {self.demande}"
        try:
            brut = self.savoir(texte, fichier=t.fichier)
        except TypeError:
            brut = self.savoir(texte)
        pages = [x.fichier for x in self.taches
                 if Path(x.fichier).suffix.lower() in {".html", ".htm"}]
        return "\n\n".join(x for x in (adapter_savoir(brut, pages, t.fichier),
                                       self._savoir_faire(t)) if x)

    def _limites_du_savoir(self) -> list[str]:
        """Un savoir-faire perime ou non reverifie est un PROBLEME (consigne
        du responsable) : il est dit au bilan, comme ce qui n'a pas tourne."""
        if not self.savoir_faire_utilise and not self.savoir_problemes:
            return []
        l = list(dict.fromkeys(self.savoir_problemes))
        l += [f"savoir-faire : {p}" for p in fraicheur.problemes_hors_ligne(
            fraicheur.charger())]
        return l

    def _savoir_faire(self, t: Tache) -> str:
        """Le savoir-faire du SPECIALISTE de la tache (comment, pourquoi,
        dependances), s'il est frais ; ce qui est ecarte ou manque va au
        bilan (savoir_faire.py, fraicheur.py)."""
        if not specialistes.actifs():
            return ""
        texte, choix = savoir_faire.pour_tache(t.fichier,
                                               f"{t.but} {self.demande}")
        for f in choix.fiches:
            self.savoir_faire_utilise[f.id] = (
                self.savoir_faire_utilise.get(f.id, 0) + 1)
        for f, raison in choix.ecartees:
            self.savoir_problemes.append(
                f"savoir-faire perime NON utilise : {f.id} — {raison}")
        self.savoir_problemes += savoir_faire.dependances_absentes(
            choix.fiches)
        return texte

    def _utiliser(self, levier: str):
        self.leviers_utilises[levier] = self.leviers_utilises.get(levier,
                                                                  0) + 1

    def _lecons_pour(self, t: Tache) -> str:
        """Ce que MAEL a appris en se relisant (leviers « consigne »)."""
        pages = [x.fichier for x in self.taches
                 if Path(x.fichier).suffix.lower() in {".html", ".htm"}]
        regles = leviers.consignes(self.leviers, t.fichier, pages)
        for levier, _texte in regles:
            self._utiliser(levier)
        # Les regles TOUJOURS donnees (leviers.TOUJOURS) : des faits du
        # projet (le menu commun, les id des pages), pas des lecons a gagner.
        toujours = [(l, x) for l, x in leviers.regles(
            t.fichier, pages, self._ids_des_pages(), [])]
        bloc = ""
        if regles:
            bloc = ("[lecons de MAEL — tirees de ses missions, a respecter]\n"
                    + "\n".join(f"- {texte}" for _l, texte in regles))
        if toujours:
            bloc += ("\n\n" if bloc else "") + (
                "[regles de MAEL — faits du projet]\n"
                + "\n".join(f"- {texte}" for _l, texte in toujours))
        return bloc

    def _ids_des_pages(self) -> list[str]:
        ids: list[str] = []
        for t in self.taches:
            if Path(t.fichier).suffix.lower() not in {".html", ".htm", ".php"}:
                continue
            try:
                texte = self.espace.lire(t.fichier)
            except (OSError, CheminRefuse):
                continue
            for i in re.findall(r"""\bid\s*=\s*["']([^"']+)["']""", texte):
                if i not in ids:
                    ids.append(i)
        return ids

    def _rappel(self, t: Tache) -> str:
        """Levier rappel-criteres-en-fin : la derniere chose que lit le
        modele, ce sont ses criteres (un petit modele oublie le debut)."""
        textes = [c.texte for c in t.liste_criteres() if c.type != "libre"]
        r = leviers.regles(t.fichier, [], [], textes)
        return next(("[rappel] " + x for l, x in r
                     if l == "rappel-criteres-en-fin"), "")

    def _consigne(self, t: Tache) -> str:
        savoir = self._savoir_pour(t)
        lang = _langage(t.fichier)
        return "\n\n".join(x for x in (
            f"[demande]\n{self.demande}",
            ("[suppositions de MAEL — a respecter]\n"
             + "\n".join(f"- {s}" for s in self.suppositions))
            if self.suppositions else "",
            f"[plan]\n{self._plan_en_texte(t)}",
            "[carte du projet]\n" + (carte(self.espace.racine,
                                           sauf=t.fichier)
                                     or "(projet vide)"),
            savoir,
            "[criteres de la tache — MAEL les verifie avant de valider]\n"
            + "\n".join(f"- {c.texte}" for c in t.liste_criteres()),
            self._lecons_pour(t),
            ("[forme du projet — MAEL la range]\n- "
             + self.logistique.consigne(t.fichier))
            if self.logistique.consigne(t.fichier) else "",
            "[fichiers valides et VERROUILLES — ne les reecris pas, "
            "raccorde-toi a eux]\n" + (", ".join(
                x.fichier for x in self.taches if x.etat == "fait")
                or "(aucun)"),
            f"[tache] Ecris UNIQUEMENT le fichier {t.fichier} : {t.but}.\n"
            f"Un seul bloc : ```{lang} fichier={t.fichier}\n"
            "Raccorde-toi a la carte : memes id, classes, chemins et "
            "couleurs. Les fichiers [a faire] seront ecrits ensuite : tu "
            "peux deja y faire reference.",
            self._rappel(t)) if x)

    def _situation(self, defauts: list[Defaut], limites=()) -> "cj.Situation":
        """L'etat du chantier vu par le conseil : la demande, le plan, les
        verdicts des juges, ce qui existe, les ecritures coupees."""
        racine = Path(self.espace.racine)
        return cj.Situation(
            demande=self.demande, plan=[t.fichier for t in self.taches],
            defauts=[{"fichier": d.fichier, "ligne": d.ligne,
                      "regle": d.regle, "message": d.message}
                     for d in defauts if d.gravite is GRAVITE.BLOQUANT],
            existants=[p.relative_to(racine).as_posix()
                       for p in juges.fichiers_du_projet(racine)],
            coupures=dict(self.coupures_par_fichier), limites=list(limites))

    def _verdict_pour(self, fichier: str, defauts: list[Defaut]) -> str:
        if not professeurs.actifs() or not defauts:
            return ""
        v = cj.deliberer(self._situation(defauts))
        self.verdicts_conseil += 1
        return cj.pour_la_tache(v, fichier)

    def _consigne_correction(self, fichier: str, but: str,
                             defauts: list[Defaut], vus: list[str],
                             reparations: list[str], conseil: str = ""
                             ) -> str:
        lang = _langage(fichier)
        deja = ("[MAEL] deja corrige par MAEL (ne le defais pas) :\n"
                + "\n".join(f"- {r}" for r in reparations)
                if reparations else "")
        return "\n\n".join(x for x in (
            f"[tache] Corrige le fichier {fichier} ({but}).",
            "[fichiers du plan — un lien vers une page, un style ou un "
            "script doit viser l'un d'eux]\n"
            + ", ".join(t.fichier for t in self.taches),
            "[carte du projet]\n" + carte(self.espace.racine),
            "[contenu actuel]\n" + _contenu_projet(self.espace, [fichier]),
            deja,
            message_correction(defauts, vus),
            conseil,
            f"Reecris {fichier} EN ENTIER dans un seul bloc ```{lang} "
            f"fichier={fichier}") if x)

    # ------------------------------------------------------------- juges
    def _etendre_plan(self, defauts: list[Defaut], fichier: str) -> bool:
        """Une page appelle un fichier de CODE qui n'est pas au plan (une
        feuille de style, un script, une autre page) : on ajoute la tache.
        Sans ca, la tache en cours ne peut jamais etre validee — elle n'a
        le droit d'ecrire que son propre fichier (premier essai du
        chantier : trois pages bloquees sur css/style.css).

        Mais SANS DOUBLON (second essai : css/style.css, gallery.html et
        js/app.js ajoutes alors que style.css et photos.html etaient deja au
        plan) :
          - un role deja present au plan (une feuille de style, un script)
            n'est jamais ajoute une seconde fois : c'est le LIEN qui est
            faux, et il est corrige (reparation vers le fichier prevu de
            meme nom, sinon le modele, qui recoit la liste des fichiers
            prevus) ;
          - une PAGE n'est jamais ajoutee d'office : ce serait changer le
            perimetre du site ; les criteres « mene a ... » guident le
            modele vers les pages prevues."""
        prevus = {t.fichier for t in self.taches}
        raccorde = False
        buts = {".css": "la feuille de style commune a toutes les pages",
                ".js": "le script des pages (elements de la carte)",
                ".mjs": "le script des pages (elements de la carte)"}
        roles = {".css": "style", ".js": "script", ".mjs": "script"}
        presents = {roles.get(Path(p).suffix.lower()) for p in prevus}
        for d in defauts:
            if d.fichier != fichier or d.regle != "fichier-absent":
                continue
            m = re.search(r'="([^"]+)"', d.message)
            if not m:
                continue
            cible = posixpath.normpath(posixpath.join(
                posixpath.dirname(fichier),
                m.group(1).split("#")[0].split("?")[0]))
            ext = Path(cible).suffix.lower()
            if (ext not in buts or cible in prevus or cible.startswith("..")
                    or roles[ext] in presents):
                continue
            presents.add(roles[ext])
            # LOGISTIQUE : le fichier ajoute va a son adresse standard, et
            # la page qui l'appelait est raccordee a cette adresse.
            appele, cible = cible, self.logistique.adresse(cible)
            t = Tache(cible, buts[ext])
            prevus.add(cible)
            t.criteres = [c.vers_dict() for c in deduire(
                cible, t.but, sorted(prevus))]
            self.taches.append(t)
            self.annoncer(f"plan etendu : {cible} ({t.but}), appele par "
                          f"{fichier}"
                          + (f" sous {appele}" if appele != cible else ""))
            if appele != cible:
                for g in self.logistique.apres_ecriture(fichier,
                                                        sorted(prevus)):
                    self.annoncer(g)
                    raccorde = True
        self._sauver()
        return raccorde

    def _a_venir(self) -> set[str]:
        return {t.fichier for t in self.taches if t.etat != "fait"}

    def _pertinents(self, defauts: list[Defaut], fichier: str
                    ) -> list[Defaut]:
        """Pendant une tache : les defauts de CE fichier, sauf les liens vers
        des fichiers prevus et pas encore ecrits (ils viendront)."""
        a_venir = self._a_venir() - {fichier}
        css = Path(fichier).suffix.lower() == ".css"
        garde = []
        for d in defauts:
            if css and d.regle in _VISUELLES:
                garde.append(d)          # vu sur une page, corrige dans le CSS
                continue
            if d.fichier != fichier:
                continue
            if d.regle == "fichier-absent":
                m = re.search(r'="([^"]+)"', d.message)
                if m:
                    cible = posixpath.normpath(posixpath.join(
                        posixpath.dirname(fichier),
                        m.group(1).split("#")[0].split("?")[0]))
                    if cible in a_venir:
                        continue
            garde.append(d)
        return garde

    def _juger(self, avant, rapide: bool, fichier: str | None = None
               ) -> tuple[list[Defaut], list[str]]:
        debut = time.monotonic()
        if fichier and specialistes.actifs():
            # Le SPECIALISTE de la tache, premier filtre : seulement les
            # juges, outils et pages qui la concernent.
            defauts, vus, s = specialistes.juger_tache(
                self.espace.racine, fichier, navigateur=not rapide)
            nom = s.nom if s else "jury complet"
            self.specialistes_utilises[nom] = (
                self.specialistes_utilises.get(nom, 0) + 1)
        else:
            defauts, vus = juges.juger_projet(self.espace.racine,
                                              executer=not rapide)
        self.jugement += time.monotonic() - debut
        apres = fidelite.empreinte(self.espace.racine)
        defauts = fidelite.perdus(avant, apres) + defauts
        if not rapide and self.demande:
            visibles = fidelite.atteignables(self.espace.racine, list(apres))
            defauts = fidelite.non_tenues(self.demande, apres,
                                          visibles) + defauts
        return defauts, vus

    def _juger_et_reparer(self, avant, rapide: bool, tour: Tour | None,
                          filtre: Callable[[list[Defaut]], list[Defaut]],
                          fichier: str | None = None,
                          criteres: Callable[[], list[Defaut]] | None = None):
        defauts, vus = self._juger(avant, rapide, fichier)
        for _ in range(2):
            # Les fichiers PREVUS comptent comme cibles d'un lien a corriger :
            # css/style.css -> style.css (au plan, pas encore ecrit).
            prevus = [t.fichier for t in self.taches if t.fichier not in vus]
            # Les CRITERES non tenus passent aussi par la reparation (examen
            # du 09/10 : « charge js/main.js » restait, solution connue).
            faites = reparation.reparer(
                self.espace, filtre(defauts) + (criteres() if criteres else []),
                vus + prevus)
            if not faites:
                break
            if tour is not None:
                tour.reparations += [str(f) for f in faites]
            self.provisoires += [f.fichier for f in faites if f.provisoire]
            self.annoncer(f"{len(faites)} reparation(s) automatique(s)")
            defauts, vus = self._juger(avant, rapide, fichier)
        return defauts, vus

    # ------------------------------------------------------------- ecrire
    def _ecrire_reponse(self, texte: str, fichier: str, tour: Tour):
        ext = extraire(texte)
        tour.refus += ext.ambiguites
        contenu = ext.fichiers.get(fichier)
        if contenu is None:
            # Le bloc au seul NOM du fichier (style.css pour la tache
            # assets/css/style.css, rangee par la logistique).
            memes = [c for n, c in ext.fichiers.items()
                     if meme_fichier(n, fichier)]
            if len(memes) == 1:
                contenu = memes[0]
        if contenu is None and len(ext.fichiers) == 1:
            # Un seul bloc, mal nomme (css/style.css pour style.css) : c'est
            # bien le fichier de la tache — mais SEULEMENT s'il est du meme
            # type. Une page index.html n'est jamais ecrite dans style.css
            # (le banc l'a vu).
            autre, candidat = next(iter(ext.fichiers.items()))
            if Path(autre).suffix.lower() == Path(fichier).suffix.lower():
                contenu = candidat
                tour.refus.append(f"{autre} ecrit sous le nom de la tache "
                                  f"({fichier})")
            else:
                tour.refus.append(f"{autre} ignore : hors de la tache")
                return False
        for autre in ext.fichiers:
            if autre != fichier and len(ext.fichiers) > 1:
                tour.refus.append(f"{autre} ignore : hors de la tache")
        if contenu is None:
            return False
        try:
            self.espace.ecrire(fichier, contenu)
        except CheminRefuse as exc:
            tour.refus.append(str(exc))
            return False
        tour.fichiers.append(fichier)
        tour.reparations += self.logistique.apres_ecriture(
            fichier, [t.fichier for t in self.taches])
        return True

    def _corriger(self, fichier: str, but: str, defauts: list[Defaut],
                  vus: list[str], reparations: list[str], tour: Tour
                  ) -> tuple[bool, str]:
        """Corriger un fichier : par RETOUCHE des lignes fautives quand tous
        ses defauts sont localises (idee du responsable : ne pas faire
        reecrire tout le fichier pour deux lignes), sinon par reecriture
        complete. Une retouche inapplicable retombe sur la reecriture."""
        try:
            texte_fichier = self.espace.lire(fichier)
        except (OSError, CheminRefuse):
            texte_fichier = ""
        # Le CONSEIL des professeurs delibere sur ces defauts (sans modele) ;
        # le modele lit son verdict avant d'ecrire (vision du responsable).
        conseil = self._verdict_pour(fichier, defauts)
        self.memoire.montres([d for d in defauts
                              if self._responsable(d) == fichier])
        nb = texte_fichier.count("\n") + 1
        if texte_fichier and retouche.eligible(defauts, fichier, nb):
            siens = [d for d in defauts if d.fichier == fichier
                     and d.gravite is GRAVITE.BLOQUANT]
            extraits = retouche.plages(siens, fichier, nb)
            message = "\n\n".join(x for x in (
                f"[tache] Corrige {fichier} ({but}) par RETOUCHE : seulement "
                "les extraits ci-dessous.",
                "[carte du projet]\n" + carte(self.espace.racine),
                "[extraits a corriger]\n" + retouche.montrer(
                    texte_fichier, extraits, _langage(fichier)),
                message_correction(siens, vus),
                conseil,
                "Renvoie un bloc ```retouche fichier=... lignes=A-B``` par "
                "extrait, avec ses lignes corrigees.") if x)
            texte, secondes = self._appeler(retouche.SYSTEME_RETOUCHE, message)
            tour.secondes += secondes
            appliquees, refus = retouche.appliquer(self.espace, texte,
                                                   extraits)
            tour.refus += refus
            if appliquees:
                tour.mode = f"retouche ({len(appliquees)} extrait(s))"
                tour.fichiers.append(fichier)
                self.annoncer(f"{fichier} : {len(appliquees)} retouche(s) "
                              f"appliquee(s) en {secondes:.0f} s")
                return True, texte
            # Le modele a renvoye le fichier ENTIER au lieu des retouches :
            # on le prend tel quel (un appel de gagne). Jamais si la reponse
            # contient un bloc de retouche : un extrait de 6 lignes ne doit
            # pas remplacer toute la page.
            if not retouche._BLOC.search(texte) and self._ecrire_reponse(
                    texte, fichier, tour):
                tour.mode = "reecriture (au lieu de la retouche)"
                return True, texte
            self.annoncer(f"{fichier} : retouche inapplicable, reecriture "
                          "complete")
        texte, secondes = self._appeler_un_fichier(
            SYSTEME, self._consigne_correction(fichier, but, defauts, vus,
                                               reparations, conseil), fichier)
        tour.secondes += secondes
        tour.mode = "reecriture"
        self._noter_coupure(tour)
        return self._ecrire_reponse(texte, fichier, tour), texte

    def _preciser_script(self, t: Tache):
        """Un script se fait APRES les pages (ordre du plan) : on lit ce
        qu'elles attendent de lui et on le lui dit, criteres a l'appui."""
        if Path(t.fichier).suffix.lower() not in {".js", ".mjs"} or any(
                c.get("type") == "vise" for c in t.criteres):
            return
        pages = [x.fichier for x in self.taches
                 if Path(x.fichier).suffix.lower() in {".html", ".htm"}
                 and (Path(self.espace.racine) / x.fichier).exists()]
        but, criteres = pour_un_script(self.espace.racine, pages)
        generique = t.but.startswith("le script des pages")
        t.but = but if generique else f"{t.but} : {but}"
        t.criteres = ([c for c in t.criteres if c.get("type") != "libre"]
                      + [c.vers_dict() for c in criteres]) or t.criteres
        self._sauver()

    def _ecrire_en_parties(self, t: Tache, texte: str, tour: Tour) -> bool:
        """Levier « ecrire-en-plusieurs-fois » (lecon de la mission 09 :
        style.css coupe trois fois, 1 528 s, jamais ecrit). On GARDE le debut
        deja ecrit, coupe a un endroit sain, et on demande seulement la
        SUITE, dans une conversation neuve ; on assemble."""
        debut = _debut_sain(texte, t.fichier)
        if not debut.strip():
            return False
        self._utiliser("ecrire-en-plusieurs-fois")
        lang = _langage(t.fichier)
        for partie in range(2, PARTIES_MAX + 1):
            fin = "\n".join(debut.rstrip().splitlines()[-12:])
            message = (
                f"[MAEL] Le fichier {t.fichier} ({t.but}) est trop long pour "
                "une seule reponse : je GARDE son debut. Ecris UNIQUEMENT la "
                "SUITE, sans repeter le debut, et termine le fichier.\n\n"
                f"[les dernieres lignes deja ecrites]\n{fin}\n\n"
                f"[tache] Un seul bloc ```{lang} fichier={t.fichier} qui "
                "contient SEULEMENT la suite, puis ferme le bloc avec ```.")
            suite, secondes = self._appeler_un_fichier(SYSTEME, message,
                                                       t.fichier)
            tour.secondes += secondes
            ext = extraire(suite)
            morceau = ext.fichiers.get(t.fichier)
            if morceau is None and len(ext.fichiers) == 1:
                morceau = next(iter(ext.fichiers.values()))
            if morceau is not None:          # bloc ferme : le fichier est fini
                try:
                    self.espace.ecrire(t.fichier,
                                       debut.rstrip() + "\n" + morceau)
                except CheminRefuse as exc:
                    tour.refus.append(str(exc))
                    return False
                tour.fichiers.append(t.fichier)
                tour.reparations.append(
                    f"{t.fichier} ecrit en {partie} parties (lecon : "
                    "ecrire-en-plusieurs-fois)")
                tour.reparations += self.logistique.apres_ecriture(
                    t.fichier, [x.fichier for x in self.taches])
                return True
            reste = _debut_sain(suite, t.fichier)
            if not reste.strip():
                break
            debut = debut.rstrip() + "\n" + reste
        tour.refus.append(f"{t.fichier} : pas termine en {PARTIES_MAX} "
                          "parties")
        return False

    def _tache(self, t: Tache, bilan: Bilan):
        self._preciser_script(t)
        avant = fidelite.empreinte(self.espace.racine)
        message = self._consigne(t)
        correction = None        # (defauts, vus, reparations) du tour d'avant
        for n in range(1, TOURS_PAR_TACHE + 1):
            self.numero += 1
            self.annoncer(f"tache {t.fichier} : le modele "
                          f"{'ecrit' if n == 1 else 'corrige'}…")
            tour = Tour(numero=self.numero, fichiers=[], bloquants=0,
                        conseils=0, tache=t.fichier)
            bilan.tours.append(tour)
            if correction is not None:
                ecrit, texte = self._corriger(t.fichier, t.but, *correction,
                                              tour)
            else:
                texte, tour.secondes = self._appeler_un_fichier(
                    SYSTEME, message, t.fichier)
                tour.mode = "ecriture"
                self._noter_coupure(tour)
                ecrit = self._ecrire_reponse(texte, t.fichier, tour)
                if (not ecrit and self.coupure in {"trop-long", "boucle"}
                        and "ecrire-en-plusieurs-fois" in self.leviers):
                    ecrit = self._ecrire_en_parties(t, texte, tour)
            t.tours += 1
            t.secondes += tour.secondes
            if not ecrit:
                correction = None
                # Rien d'ecrit pour CETTE tache (troisieme essai : pour
                # script.js, le modele avait reecrit les trois pages). On
                # relance avec une consigne qui le dit, au lieu d'abandonner.
                bilan.explication = _hors_blocs(texte)
                autres = [r.split(" ignore")[0] for r in tour.refus
                          if "hors de la tache" in r]
                pourquoi = {
                    "trop-long": " : ta reponse etait TROP LONGUE et ton bloc "
                                 "n'etait jamais ferme. Ecris un fichier "
                                 "COURT (l'essentiel seulement) et FERME le "
                                 "bloc avec ```",
                    "boucle": " : tu repetais les memes lignes en boucle. "
                              "Ecris le fichier une seule fois et FERME le "
                              "bloc avec ```",
                }.get(self.coupure, "")
                message = (f"[MAEL] Ta reponse ne contenait PAS le fichier "
                           f"{t.fichier}"
                           + (f" (tu as ecrit {', '.join(autres)} : ils sont "
                              "ignores, ils sont deja faits)" if autres else "")
                           + pourquoi
                           + f". Ecris UNIQUEMENT {t.fichier}.\n\n"
                           + self._consigne(t))
                continue
            # La feuille de style est jugee AVEC le navigateur : contraste,
            # taille des zones cliquables et debordement se voient sur les
            # pages, mais se corrigent dans le CSS — avant qu'il soit
            # verrouille (troisieme essai : styles.css validee, puis 5 cibles
            # trop petites decouvertes a la finition, sans pouvoir y toucher).
            # De meme pour un script : ses erreurs A L'EXECUTION ne se voient
            # qu'en ouvrant les pages (cinquieme essai : js/app.js plantait
            # sur les pages sans #bouton-menu, decouvert apres le verrou).
            visuel = Path(t.fichier).suffix.lower() in {".css", ".js", ".mjs"}
            defauts, vus = self._juger_et_reparer(
                avant, not visuel, tour,
                lambda ds: self._pertinents(ds, t.fichier), t.fichier,
                lambda: manques(self.espace.racine, t.fichier,
                                t.liste_criteres()))
            if self._etendre_plan(defauts, t.fichier):
                # La logistique a raccorde la page au fichier ajoute : le
                # jugement d'avant le raccord ne vaut plus, on rejuge.
                defauts, vus = self._juger_et_reparer(
                    avant, not visuel, tour,
                    lambda ds: self._pertinents(ds, t.fichier), t.fichier,
                    lambda: manques(self.espace.racine, t.fichier,
                                    t.liste_criteres()))
            # Les criteres de la tache comptent comme des defauts : la tache
            # n'est validee (et verrouillee) que s'ils passent tous.
            miens = (manques(self.espace.racine, t.fichier,
                             t.liste_criteres())
                     + self._pertinents(defauts, t.fichier))
            self.memoire.constater(t.fichier, miens)
            tour.bloquants = sum(d.gravite is GRAVITE.BLOQUANT for d in miens)
            tour.conseils = len(miens) - tour.bloquants
            if tour.bloquants == 0:
                self._valider(t)
                break
            correction = (miens, vus, tour.reparations)
        if t.etat != "fait":
            t.etat = "a revoir"
        self._sauver()

    # ----------------------------------------------------------- finition
    def _criteres_non_tenus(self) -> list[Defaut]:
        """Les criteres des taches NON validees (les verrouillees les ont
        tous passes pour l'etre). La finition les revérifie : une page peut
        sortir « sans defaut de norme » et manquer quand meme son lien ou
        son formulaire (premier essai du chantier)."""
        d = []
        for t in self.taches:
            if t.etat != "fait":
                d += manques(self.espace.racine, t.fichier,
                             t.liste_criteres())
        return d

    def _valider(self, t: Tache):
        t.etat = "fait"                  # verrouillee : plus jamais reecrite
        resultats = verifier(self.espace.racine, t.fichier,
                             t.liste_criteres())
        ok = sum(1 for _, r in resultats if r)
        libres = sum(1 for _, r in resultats if r is None)
        t.verifies = (f"criteres {ok}/{len(resultats) - libres}"
                      + (f", {libres} non verifie(s)" if libres else ""))

    def _executer_tests(self, vus: list[str]) -> list[Defaut]:
        """Couche 7 : la justesse du code Python, en EXECUTANT les tests
        dans un conteneur sans reseau. Le modele est decharge de la memoire
        avant (8 Go : modele + Docker ensemble, c'est trop)."""
        from . import execution_base
        # La BASE a serveur (PostgreSQL, MySQL...) rejouee dans un conteneur.
        base = execution_base.executer(
            self.espace.racine, vus,
            decharger=getattr(self.backend, "decharger", None))
        if base or execution_base.dernier_rapport.lance:
            self.annoncer(f"finition : base "
                          f"{execution_base.dernier_rapport.base} rejouee en "
                          f"vrai ({len(base)} refus)")
        if not any(f.endswith(".py") for f in vus):
            return base
        try:
            modele = self.backend.modele_pour(self.role)
        except Exception:                          # noqa: BLE001
            modele = ""
        self.annoncer("finition : tests executes en conteneur (modele "
                      "decharge de la memoire)…")
        return base + execution.executer(
            self.espace.racine, vus,
            base_ollama=getattr(self.backend, "base", ""), modele=modele,
            decharger=getattr(self.backend, "decharger", None))

    def _responsable(self, d: Defaut) -> str:
        """Le fichier a corriger pour ce defaut. Un defaut VISUEL vu sur une
        page (contraste, cible trop petite, debordement) se corrige dans
        l'unique feuille de style du plan — a la finition comme pendant les
        taches (cinquieme essai : des cibles trop petites attribuees a
        index.html, verrouillee, au lieu de style.css)."""
        if d.regle in _VISUELLES:
            css = [t.fichier for t in self.taches
                   if Path(t.fichier).suffix.lower() == ".css"]
            if len(css) == 1:
                return css[0]
        return d.fichier

    def _feuille_de_secours(self, t: Tache, tour: Tour) -> None:
        """Levier feuille-de-secours : une feuille de style que le modele
        n'a jamais pu ecrire (coupee trois fois, mission 07 du 08/10) est
        remplacee par la feuille de base de MAEL, deja juste — les pages ne
        restent pas sans style."""
        if not t.fichier.endswith(".css") or (
                Path(self.espace.racine) / t.fichier).exists():
            return
        base = Path(__file__).parent / "gabarits" / "base.css"
        try:
            self.espace.ecrire(t.fichier, base.read_text(encoding="utf-8"))
        except (OSError, CheminRefuse):
            return
        tour.reparations.append(f"{t.fichier} : feuille de secours de MAEL "
                                "(lecon : feuille-de-secours)")
        self.suppositions.append(f"{t.fichier} est la feuille de base de "
                                 "MAEL (le modele n'a pas pu l'ecrire)")

    def _finition(self, bilan: Bilan):
        # Un fichier du plan qui n'existe toujours pas (la tache n'a rien
        # ecrit) : on le fait ecrire ici — un juge ne voit pas un fichier
        # absent, la finition l'aurait laisse de cote (troisieme essai).
        for t in self.taches:
            if t.etat != "fait" and not (Path(self.espace.racine)
                                         / t.fichier).exists():
                self.numero += 1
                self.annoncer(f"finition {t.fichier} : le modele ecrit "
                              "(fichier jamais ecrit)…")
                tour = Tour(numero=self.numero, fichiers=[], bloquants=0,
                            conseils=0, tache=f"finition {t.fichier}")
                texte, tour.secondes = self._appeler_un_fichier(
                    SYSTEME, f"[MAEL] {t.fichier} n'a pas encore ete ecrit."
                    "\n\n" + self._consigne(t), t.fichier)
                self._noter_coupure(tour)
                t.tours += 1
                t.secondes += tour.secondes
                bilan.tours.append(tour)
                self._ecrire_reponse(texte, t.fichier, tour)
                self._feuille_de_secours(t, tour)
        self.annoncer("finition : juges complets sur tout le projet…")
        avant = fidelite.empreinte(self.espace.racine)
        defauts, vus = self._juger_et_reparer(avant, False, None,
                                              lambda ds: ds, None,
                                              self._criteres_non_tenus)
        defauts = self._criteres_non_tenus() + self._executer_tests(vus) \
            + defauts
        ordre = [t.fichier for t in self.taches]
        # VERROU (decision du responsable) : un fichier valide ne repasse
        # jamais par le modele. Il a deja eu les reparations mecaniques
        # ci-dessus ; un defaut qui reste est SIGNALE, pas reecrit.
        verrouilles = {t.fichier for t in self.taches if t.etat == "fait"}
        self.memoire.constater(None, defauts)
        corrections: list[tuple[str, Tour]] = []

        def nb_bloquants(ds):
            return sum(d.gravite is GRAVITE.BLOQUANT for d in ds)
        # Plusieurs passes, tant qu'elles font baisser les bloquants : un
        # probleme ouvert ne se laisse pas apres un seul essai.
        for _passe in range(PASSES_FINITION):
            fautifs = sorted({self._responsable(d) for d in defauts
                              if d.gravite is GRAVITE.BLOQUANT
                              and self._responsable(d) not in verrouilles},
                             key=lambda f: ordre.index(f) if f in ordre
                             else 99)
            if not fautifs:
                break
            avant_passe = nb_bloquants(defauts)
            for fichier in fautifs[:FICHIERS_EN_FINITION]:
                siens = [d for d in defauts if self._responsable(d) == fichier]
                but = next((t.but for t in self.taches
                            if t.fichier == fichier), "corriger les defauts")
                self.numero += 1
                self.annoncer(f"finition {fichier} : le modele corrige…")
                tour = Tour(numero=self.numero, fichiers=[], bloquants=0,
                            conseils=0, tache=f"finition {fichier}")
                bilan.tours.append(tour)
                self._corriger(fichier, but, siens, vus, [], tour)
                corrections.append((fichier, tour))
            defauts, vus = self._juger_et_reparer(avant, False, None,
                                                  lambda ds: ds, None,
                                                  self._criteres_non_tenus)
            defauts = self._criteres_non_tenus() + \
                self._executer_tests(vus) + defauts
            self.memoire.constater(None, defauts)
            if nb_bloquants(defauts) >= avant_passe:
                self.annoncer("finition : plus de progres — chaque probleme "
                              "restant dit pourquoi (memoire de travail)")
                break
        # Les comptes de chaque tour de finition sont ceux APRES le
        # rejugement (le premier essai affichait « 0 bloquant » alors que
        # des defauts restaient).
        for fichier, tour in corrections:
            siens = [d for d in defauts if self._responsable(d) == fichier]
            tour.bloquants = sum(d.gravite is GRAVITE.BLOQUANT for d in siens)
            tour.conseils = len(siens) - tour.bloquants
        self.signales = []
        for t in self.taches:
            reste = any(self._responsable(d) == t.fichier
                        and d.gravite is GRAVITE.BLOQUANT for d in defauts)
            if t.etat == "fait":
                if reste:               # verrouille : on le dit, on n'y touche pas
                    self.signales.append(t.fichier)
            elif not reste and (Path(self.espace.racine) / t.fichier).exists():
                self._valider(t)        # corrige a la finition : verrouille
        bilan.defauts, bilan.fichiers = defauts, vus
        bilan.memoire = memoire.rapport(self.memoire, defauts, verrouilles)
        bilan.resolus = self.memoire.resolus()
        self._sauver()

    # --------------------------------------------------------------- portes
    def _executer(self, bilan: Bilan) -> Bilan:
        reparation.nouveau_chantier()            # le bilan parle de CE chantier
        # Les lecons du navigateur (budget, second essai) : posees pour CE
        # chantier ; un chantier sans lecon retrouve le comportement d'avant.
        bac_a_sable.LECONS = self.leviers & {"budget-selon-les-pages",
                                             "reessayer-page-expiree"}
        # self.taches peut grandir pendant la boucle (plan etendu) : la
        # boucle sur la liste voit les taches ajoutees.
        for t in self.taches:
            if t.etat != "fait":
                self._tache(t, bilan)
        self._finition(bilan)
        # LOGISTIQUE en fin : les fichiers simples (README, .gitignore,
        # requirements.txt, package.json, .env.example), ecrits par MAEL.
        for f in self.logistique.finir(list(dict.fromkeys(self.provisoires))):
            self.annoncer(f"logistique : {f} ecrit par MAEL")
        bilan.logistique = list(self.logistique.gestes)
        bilan.plan = [
            f"[{'valide, verrouille' if t.etat == 'fait' else t.etat}] "
            f"{t.fichier} : {t.but} ({t.tours} appel(s), {t.secondes:.0f} s"
            + (f", {t.verifies}" if t.verifies else "") + ")"
            for t in self.taches]
        bilan.arret = ("chantier termine" if not bilan.bloquants
                       else "chantier termine, defauts restants")
        if self.signales:
            bilan.arret += (" — fichier(s) verrouille(s) avec un defaut "
                            "signale, NON reecrit(s) : "
                            + ", ".join(self.signales))
        from . import execution_base
        bilan.limites = (juges.limites() + reparation.limites()
                         + execution.limites() + execution_base.limites()
                         + self._limites_du_savoir())
        # Le CONSEIL relit la fin du chantier : defauts restants, plan,
        # reserves ; son verdict complet va au journal (sans modele).
        if professeurs.actifs():
            v = cj.deliberer(self._situation(bilan.defauts, bilan.limites))
            if v.solutions or v.impertinences or v.reserves:
                bilan.conseil = v.texte()
        bilan.provisoires = list(dict.fromkeys(self.provisoires))
        bilan.suppositions = list(self.suppositions)
        nav = bac_a_sable.dernier_rapport
        if nav.reessais:
            self.leviers_utilises["reessayer-page-expiree"] = len(nav.reessais)
        if nav.budget > bac_a_sable.BUDGET:
            self._utiliser("budget-selon-les-pages")
        bilan.jugement = self.jugement
        bilan.appels_conseil = self.appels_conseil
        if self.conseil_refus:
            bilan.limites.append("conseil des professeurs : deliberation "
                                 "refusee, plan fait sans elle — "
                                 + " ; ".join(self.conseil_refus))
        bilan.specialistes = dict(self.specialistes_utilises)
        bilan.leviers = {l: self.leviers_utilises.get(l, 0)
                         for l in sorted(self.leviers)}
        return bilan

    def _mesurer(self) -> None:
        self.env = envergure.lire(self.backend)
        if self.env is not envergure.PETIT:
            self.annoncer("moteur : " + self.env.libelle())

    def _schema_plan(self) -> dict:
        s = json.loads(json.dumps(PLAN_SCHEMA))
        s["properties"]["fichiers"]["maxItems"] = self.env.taches_par_lot
        return s

    def lancer(self, demande: str) -> Bilan:
        bilan = Bilan(racine=str(self.espace.racine))
        self._mesurer()
        self.demande = demande.strip()
        if self._decider_etapes(self.demande):
            # GRAND PROJET : etape par etape, puis une finition d'ensemble.
            self._executer_etapes(bilan)
            if not self.taches:
                bilan.arret = "aucune etape n'a donne de plan lisible"
                return bilan
            return self._executer(bilan)
        self.taches = self.planifier(self.demande)
        sante = getattr(self.backend, "verifier_sante", None)
        if not self.taches and sante:
            # Plan illisible : le moteur est-il abime (examen du 09/10 :
            # 40 plans en charabia) ? La sonde le dit ; relance -> on refait
            # le plan ; toujours abime -> MoteurEnPanne (pas un echec).
            if sante(self.role) == "relance":
                self.annoncer("plan illisible : moteur abime, relance, je "
                              "refais le plan")
                self.taches = self.planifier(self.demande)
        if not self.taches:
            bilan.arret = "le chef de chantier n'a donne aucun plan lisible"
            bilan.appels_conseil = self.appels_conseil
            trace = Path(self.espace.racine) / PLAN_BRUT
            trace.parent.mkdir(parents=True, exist_ok=True)
            trace.write_text(self.plan_brut, encoding="utf-8")
            return bilan
        self._sauver()
        return self._executer(bilan)

    def reprendre(self) -> Bilan:
        bilan = Bilan(racine=str(self.espace.racine))
        if not self._charger():
            bilan.arret = f"aucun chantier a reprendre ({ETAT} absent)"
            return bilan
        self._mesurer()
        self.logistique.demande = self.demande
        self.logistique.connaitre([t.fichier for t in self.taches])
        self.annoncer("reprise : " + ", ".join(
            f"{t.fichier} [{t.etat}]" for t in self.taches))
        if any(e.etat != "faite" for e in self.etapes):
            # un grand projet interrompu reprend a son etape
            self.annoncer("reprise des etapes : " + ", ".join(
                f"{e.nom} [{e.etat}]" for e in self.etapes))
            self._executer_etapes(bilan)
        return self._executer(bilan)
