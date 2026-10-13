"""Le CORRECTIF d'un ticket sur un depot existant : retouches ciblees.

Point 4.3 de la feuille de route « agent autonome » (12/10/2026). Apres la
localisation (localisation.py), le modele voit SEULEMENT les extraits
designes — les fonctions, numerotees — et repond par des blocs :

    FICHIER: chemin/du/fichier.py
    <<<<<<< CHERCHER
    les lignes actuelles, recopiees exactement
    =======
    les lignes qui les remplacent
    >>>>>>> REMPLACER

Pourquoi ce format plutot que la reecriture d'une plage (retouche.py) : sur
un depot, une correction change souvent 2 lignes dans une fonction de 80 ;
le modele n'ecrit que ce qui change (machine sans carte graphique : ~5
jetons/s).

Surete — rien n'est applique a l'aveugle, chaque refus dit pourquoi et
repart au modele :
  - le fichier doit etre l'un de ceux MONTRES, et pas un fichier de test
    (le test qui reproduit le ticket est une autre etape) ;
  - le texte cherche doit exister UNE SEULE FOIS dans le fichier, et dans un
    extrait montre (le modele ne modifie pas ce qu'il n'a pas vu) ;
  - les numeros « 12| » recopies par megarde sont retires ; les espaces en
    fin de ligne ne comptent pas ;
  - un fichier Python qui ne se lit plus (SyntaxError) n'est pas ecrit ;
  - l'ecriture passe par l'Espace (copie de sauvegarde, chemins bornes).
Le resultat est un DIFF unifie, le correctif tel qu'on le propose.
"""
from __future__ import annotations

import ast
import difflib
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from . import depot, localisation
from .envergure import PETIT, Envergure
from .espace import CheminRefuse, Espace
from .retouche import Extrait, montrer

CONTEXTE = 3                 # lignes autour d'une fonction montree
FENETRE = 60                 # une fonction trop longue : fenetre autour du lieu
TOURS = 3

SYSTEME = """Tu corriges un ticket dans un depot de code existant.
On te montre le ticket et SEULEMENT les extraits utiles, lignes numerotees
« 12| ». Reponds par un ou plusieurs blocs, rien d'autre :

FICHIER: chemin/du/fichier
<<<<<<< CHERCHER
lignes actuelles, recopiees EXACTEMENT depuis un extrait (sans les numeros)
=======
lignes qui les remplacent
>>>>>>> REMPLACER

Regles :
- CHERCHER recopie des lignes entieres d'un extrait montre, assez pour
  etre unique dans le fichier (3 a 8 lignes en general) ;
- change le MOINS possible ; garde l'indentation et le style du depot ;
- ne modifie pas les fichiers de test ;
- corrige la cause, pas le symptome."""

# Pour un PETIT modele, la reponse est imposee par une grammaire (Ollama
# « format ») : premier essai reel phi4-mini du 12/10, il ignorait les blocs
# CHERCHER / REMPLACER et reecrivait une fonction dans un bloc ```python.
SCHEMA_EDITIONS = {
    "type": "object",
    "properties": {"editions": {"type": "array", "minItems": 1, "items": {
        "type": "object",
        "properties": {"fichier": {"type": "string"},
                       "chercher": {"type": "string"},
                       "remplacer": {"type": "string"}},
        "required": ["fichier", "chercher", "remplacer"]}}},
    "required": ["editions"]}

SYSTEME_JSON = """Tu corriges un ticket dans un depot de code existant.
On te montre le ticket et SEULEMENT les extraits utiles, lignes numerotees
« 12| ». Reponds en JSON : {"editions": [{"fichier": "...", "chercher":
"...", "remplacer": "..."}]}.
- fichier : le chemin d'un extrait montre ;
- chercher : des lignes ENTIERES recopiees EXACTEMENT d'un extrait (sans
  les numeros), assez pour etre uniques (3 a 8 lignes) ;
- remplacer : ces lignes corrigees, meme indentation.
Change le MOINS possible ; corrige la cause, pas le symptome ; ne modifie
pas les fichiers de test."""

_BLOC = re.compile(
    r"FICHIER\s*:\s*`?([^\s`]+)`?\s*\n(?:```[\w+-]*\n)?"
    r"<{5,9}\s*(?:CHERCHER|SEARCH)\s*\n(.*?)\n?={5,9}\s*\n(.*?)\n?"
    r">{5,9}\s*(?:REMPLACER|REPLACE)", re.S)
_NUMERO = re.compile(r"^\s*\d+\s?\|\s?")


@dataclass
class Edition:
    fichier: str
    chercher: str
    remplacer: str


@dataclass
class Resultat:
    lieux: list = field(default_factory=list)          # list[localisation.Lieu]
    extraits: list[Extrait] = field(default_factory=list)
    appliquees: list[Edition] = field(default_factory=list)
    refus: list[str] = field(default_factory=list)      # du dernier tour
    tours: int = 0
    diff: str = ""

    @property
    def corrige(self) -> bool:
        return bool(self.diff)


# ------------------------------------------------------------- les extraits
def _plages_du_lieu(lieu, nb_lignes: int) -> list[tuple[int, int]]:
    out = []
    for s in lieu.symboles:
        debut, fin = max(1, s.debut - CONTEXTE), min(nb_lignes,
                                                     s.fin + CONTEXTE)
        if fin - debut > 2 * FENETRE:
            # trop long : une fenetre autour de la ligne de trace, sinon le
            # debut de la fonction
            centre = next((l for l in lieu.lignes if s.debut <= l <= s.fin),
                          s.debut + FENETRE // 2)
            debut = max(debut, centre - FENETRE)
            fin = min(fin, debut + 2 * FENETRE)
        out.append((debut, fin))
    for l in lieu.lignes:                      # trace hors de toute fonction
        if not any(a <= l <= b for a, b in out):
            out.append((max(1, l - 10), min(nb_lignes, l + 10)))
    if not out:                                # aucun symbole : le debut
        out.append((1, min(nb_lignes, 2 * FENETRE)))
    return out


def _fusionner(plages: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for a, b in sorted(plages):
        if out and a <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def choisir_extraits(racine: Path, lieux, budget: int,
                     index: depot.Index | None = None) -> list[Extrait]:
    """Les extraits a montrer, du lieu le plus sur au moins sur, sous le
    budget en caracteres. Les fichiers de test ne sont pas montres a la
    correction."""
    # PAR ORDRE DE PRIORITE (lieu, puis score de la fonction) ; l'ordre des
    # lignes ne sert qu'a la presentation. Essai reel du 12/10 : trie par
    # ligne, Response.__init__ (50 lignes, sans rapport) mangeait le budget
    # avant iter_content, la fonction du ticket — jamais montree.
    choisies: list[tuple[str, int, int]] = []
    total = 0
    for lieu in lieux:
        fi = index.fichiers.get(lieu.fichier) if index else None
        if fi and fi.test:
            continue
        try:
            lignes = (racine / lieu.fichier).read_text(
                encoding="utf-8", errors="replace").split("\n")
        except OSError:
            continue
        for a, b in _plages_du_lieu(lieu, len(lignes)):
            deja = [(x, y) for f, x, y in choisies if f == lieu.fichier]
            if any(x <= a and b <= y for x, y in deja):
                continue                       # deja montre (methode d'une classe)
            taille = sum(len(l) + 6 for l in lignes[a - 1:b])
            if total + taille > budget:
                if not choisies:               # au moins un extrait, coupe
                    while b > a and total + taille > budget:
                        b -= 1
                        taille = sum(len(l) + 6 for l in lignes[a - 1:b])
                else:
                    continue
            choisies.append((lieu.fichier, a, b))
            total += taille
        if total >= budget:
            break
    extraits: list[Extrait] = []
    for f in dict.fromkeys(f for f, _, _ in choisies):
        for a, b in _fusionner([(x, y) for g, x, y in choisies if g == f]):
            extraits.append(Extrait(f, a, b))
    return extraits


def _langage(fichier: str) -> str:
    return depot.LANGAGES.get(Path(fichier).suffix.lower(), "")


def message_initial(ticket: str, lieux, extraits: list[Extrait],
                    textes: dict[str, str], limite_ticket: int) -> str:
    t = ticket.strip()
    if len(t) > limite_ticket:
        t = t[:limite_ticket] + "\n[... ticket coupe ...]"
    pourquoi = []
    for l in lieux:
        if any(e.fichier == l.fichier for e in extraits):
            pourquoi.append(f"- {l.fichier} : {', '.join(l.raisons[:3])}")
    par_fichier: dict[str, list[Extrait]] = {}
    for e in extraits:
        par_fichier.setdefault(e.fichier, []).append(e)
    code = "\n\n".join(montrer(textes[f], es, _langage(f))
                       for f, es in par_fichier.items())
    return (f"TICKET :\n{t}\n\nOU REGARDER (choisi par MAEL) :\n"
            + "\n".join(pourquoi) + f"\n\nEXTRAITS :\n{code}")


# --------------------------------------------------------------- les blocs
def lire_editions(reponse: str) -> list[Edition]:
    out = []
    for m in _BLOC.finditer(reponse):
        def nettoyer(t):
            t = re.sub(r"\n?```\s*$", "", t)
            return "\n".join(_NUMERO.sub("", l) if _NUMERO.match(l) else l
                             for l in t.split("\n"))
        out.append(Edition(m.group(1).strip(), nettoyer(m.group(2)),
                           nettoyer(m.group(3))))
    return out


def editions_json(donnees) -> list[Edition]:
    out = []
    for e in (donnees or {}).get("editions", []) if isinstance(
            donnees, dict) else []:
        if isinstance(e, dict) and e.get("fichier") and e.get("chercher"):
            nettoyer = lambda t: "\n".join(                        # noqa: E731
                _NUMERO.sub("", l) if _NUMERO.match(l) else l
                for l in str(t).split("\n"))
            out.append(Edition(str(e["fichier"]).strip(),
                               nettoyer(e["chercher"]),
                               nettoyer(e.get("remplacer", ""))))
    return out


def editions_fonctions(reponse: str, extraits: list[Extrait],
                       textes: dict[str, str]) -> list[Edition]:
    """Repli : le modele a REECRIT une fonction (bloc ```python commencant
    par « def nom(... ») au lieu de donner un bloc CHERCHER / REMPLACER. Si
    une fonction montree porte ce nom, la reponse la remplace — par une
    Edition ordinaire, donc avec toutes les surete d'appliquer() (unique,
    dans un extrait montre, Python lisible). Reindentee comme l'originale."""
    out = []
    for m in re.finditer(r"(?ms)^```[ \t]*(?:python|py)?[^\n]*\n(.*?)^```",
                         reponse):
        code = m.group(1)
        d = re.search(r"(?m)^([ \t]*)(?:async\s+)?def\s+(\w+)\s*\(", code)
        if not d:
            continue
        nom = d.group(2)
        for f in dict.fromkeys(e.fichier for e in extraits):
            if not f.endswith(".py") or f not in textes:
                continue
            for s in depot.symboles_python(textes[f]):
                if s.nom.rsplit(".", 1)[-1] != nom or s.sorte == "classe":
                    continue
                if not any(e.fichier == f and e.debut <= s.debut and
                           s.fin <= e.fin for e in extraits):
                    continue
                lignes = textes[f].split("\n")
                original = "\n".join(lignes[s.debut - 1:s.fin])
                retrait = re.match(r"[ \t]*", lignes[s.debut - 1]).group(0)
                nouveau = textwrap.dedent(code[d.start():]).rstrip("\n")
                out.append(Edition(f, original, "\n".join(
                    (retrait + l) if l.strip() else l
                    for l in nouveau.split("\n"))))
                break
    return out


def _positions(texte: str, chercher: str) -> list[int]:
    """Debuts (en ligne, 1-indexes) des endroits ou les lignes cherchees
    apparaissent, espaces de fin de ligne ignores."""
    lignes = [l.rstrip() for l in texte.split("\n")]
    cible = [l.rstrip() for l in chercher.strip("\n").split("\n")]
    if not cible or not any(cible):
        return []
    n = len(cible)
    return [i + 1 for i in range(len(lignes) - n + 1)
            if lignes[i:i + n] == cible]


def _syntaxe(fichier: str, texte: str) -> str:
    if not fichier.endswith(".py"):
        return ""
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            ast.parse(texte)
    except SyntaxError as e:
        return f"ligne {e.lineno} : {e.msg}"
    return ""


def nouveaux_defauts(fichier: str, avant: str, apres: str) -> list:
    """Les defauts BLOQUANTS que le changement ajoute (securite surtout :
    eval, shell=True, SQL colle, contamination...). Compte par regle, avant
    / apres : les lignes bougent, un defaut deja present dans le depot n'est
    pas reproche au correctif. Rend les defauts du « apres » des regles qui
    augmentent."""
    from collections import Counter

    from .juges import GRAVITE, juger_fichier

    def bloquants(t):
        try:
            return [d for d in juger_fichier(fichier, t)
                    if d.gravite is GRAVITE.BLOQUANT and d.regle != "py-syntaxe"]
        except Exception:                               # noqa: BLE001
            return []                   # un juge en panne ne bloque rien
    avant_c = Counter(d.regle for d in bloquants(avant))
    apres_d = bloquants(apres)
    apres_c = Counter(d.regle for d in apres_d)
    plus = {r for r, n in apres_c.items() if n > avant_c[r]}
    return [d for d in apres_d if d.regle in plus]


def _cosmetique(fichier: str, avant: str, apres: str) -> bool:
    """Vrai si le changement ne modifie pas le CODE : pour Python, l'arbre
    syntaxique est identique (seuls commentaires et espaces ont bouge)."""
    if not fichier.endswith(".py"):
        return False
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.dump(ast.parse(avant)) == ast.dump(ast.parse(apres))
    except SyntaxError:
        return False


def appliquer(espace: Espace, editions: list[Edition],
              extraits: list[Extrait], tests: set[str] = frozenset()
              ) -> tuple[list[Edition], list[str], list[Extrait]]:
    """Applique les editions sures ; rend (appliquees, refus, extraits
    recales sur le texte modifie)."""
    montres: dict[str, list[tuple[int, int]]] = {}
    for e in extraits:
        montres.setdefault(e.fichier, []).append((e.debut, e.fin))
    textes: dict[str, str] = {}
    appliquees, refus = [], []
    for ed in editions:
        f = ed.fichier.removeprefix("./")
        if f in tests:
            refus.append(f"{f} : fichier de test, non modifie ici")
            continue
        if f not in montres:
            refus.append(f"{f} : ce fichier ne t'a pas ete montre "
                         f"(montres : {', '.join(sorted(montres))})")
            continue
        try:
            texte = textes.get(f) if f in textes else espace.lire(f)
        except (OSError, CheminRefuse) as e:
            refus.append(f"{f} : illisible ({e})")
            continue
        pos = _positions(texte, ed.chercher)
        n = len(ed.chercher.strip("\n").split("\n"))
        if not pos:
            refus.append(f"{f} : le texte CHERCHER n'existe pas tel quel — "
                         "recopie des lignes entieres d'un extrait, sans "
                         "les numeros")
            continue
        if len(pos) > 1:
            refus.append(f"{f} : le texte CHERCHER apparait {len(pos)} fois "
                         f"(lignes {', '.join(map(str, pos[:5]))}) — "
                         "ajoute des lignes voisines pour qu'il soit unique")
            continue
        debut = pos[0]
        fin = debut + n - 1
        if not any(a <= debut and fin <= b for a, b in montres[f]):
            refus.append(f"{f} : lignes {debut}-{fin} hors des extraits "
                         "montres")
            continue
        lignes = texte.split("\n")
        nouveau = ed.remplacer.strip("\n").split("\n") \
            if ed.remplacer.strip("\n") else []
        candidat = "\n".join(lignes[:debut - 1] + nouveau + lignes[fin:])
        erreur = _syntaxe(f, candidat)
        if erreur:
            refus.append(f"{f} : apres ce changement, le fichier ne se lit "
                         f"plus ({erreur}) — non applique")
            continue
        nouveaux = nouveaux_defauts(f, texte, candidat)
        if nouveaux:
            # le correctif ne doit RIEN introduire que les juges de MAEL
            # refusent (eval, shell=True, SQL colle...) — remarque du
            # responsable, 12/10/2026 : MAEL est d'abord un outil de securite
            refus.append(f"{f} : ce changement INTRODUIT un defaut — "
                         + " ; ".join(f"ligne {d.ligne} : {d.message} "
                                      f"({d.norme})" for d in nouveaux[:3])
                         + " — non applique, corrige autrement")
            continue
        if _cosmetique(f, texte, candidat):
            # essai reel du 12/10 : phi4-mini « corrigeait » le ticket en
            # reecrivant des commentaires — ce n'est pas une correction
            refus.append(f"{f} : ce changement ne touche que des commentaires "
                         "ou des espaces — le code fait exactement la meme "
                         "chose ; corrige le CODE")
            continue
        textes[f] = candidat
        # les extraits de ce fichier se decalent apres le changement
        delta = len(nouveau) - n
        montres[f] = [(a if a < debut else a + delta,
                       b + delta if b >= fin else b) for a, b in montres[f]]
        appliquees.append(ed)
    for f, t in textes.items():
        try:
            # le style du fichier d'origine est garde : fins de ligne \r\n
            # ou \n, ligne finale ou non (un diff ne montre que le correctif)
            brut = espace.chemin(f).read_bytes()
            espace.ecrire(f, t, fin_de_ligne="\r\n" if b"\r\n" in brut
                          else "\n", ligne_finale=brut.endswith(b"\n"))
        except CheminRefuse as e:
            refus.append(f"{f} : refuse par l'espace ({e})")
            appliquees = [a for a in appliquees if a.fichier != f]
    recales = [Extrait(f, a, b) for f, plages in montres.items()
               for a, b in plages]
    return appliquees, refus, recales


def diff(originaux: dict[str, str], espace: Espace) -> str:
    morceaux = []
    for f, avant in sorted(originaux.items()):
        try:
            apres = espace.lire(f)
        except (OSError, CheminRefuse):
            continue
        if apres == avant:
            continue
        morceaux.append("".join(difflib.unified_diff(
            avant.splitlines(keepends=True), apres.splitlines(keepends=True),
            fromfile=f"a/{f}", tofile=f"b/{f}")))
    return "".join(morceaux)


# ---------------------------------------------------------------- la boucle
class Correcteur:
    def __init__(self, backend, racine: Path | str, *,
                 envergure: Envergure | None = None, tours: int = TOURS,
                 contraint: bool | None = None):
        self.backend = backend
        self.racine = Path(racine).resolve()
        self.espace = Espace(self.racine)
        self.envergure = envergure or PETIT
        self.tours = tours
        # reponse imposee (JSON par grammaire) : pour un petit modele dont
        # l'envergure est CONNUE ; un grand modele garde le format libre
        self.contraint = (envergure is not None
                          and envergure.classe == "petit") \
            if contraint is None else contraint

    @staticmethod
    def _json(texte: str):
        import json
        try:
            return json.loads(texte)
        except ValueError:
            return None

    def corriger(self, ticket: str, index: depot.Index | None = None,
                 lieux=None, retour: str = "") -> Resultat:
        """retour : ce que les tests ont dit d'une correction precedente
        (deja appliquee — les extraits montrent l'etat actuel)."""
        index = index or depot.indexer(self.racine)
        lieux = lieux if lieux is not None else localisation.localiser(
            index, ticket)
        budget = self.envergure.budget_extraits
        extraits = choisir_extraits(self.racine, lieux, budget, index)
        r = Resultat(lieux=lieux, extraits=extraits)
        if not extraits:
            r.refus = ["aucun endroit a montrer : la localisation n'a rien "
                       "trouve"]
            return r
        fichiers = sorted({e.fichier for e in extraits})
        originaux = {f: self.espace.lire(f) for f in fichiers}
        tests = {f for f, fi in index.fichiers.items() if fi.test}
        premier = message_initial(ticket, lieux, extraits, originaux,
                                  budget // 2)
        if retour:
            premier += ("\n\nUNE PREMIERE CORRECTION EST DEJA APPLIQUEE "
                        "(les extraits montrent l'etat actuel), mais les "
                        f"tests disent :\n{retour}\n\nCorrige ce qui reste.")
        messages = [{"role": "user", "content": premier}]
        for tour in range(1, self.tours + 1):
            r.tours = tour
            if self.contraint:
                rep = self.backend.completer(
                    systeme=SYSTEME_JSON, messages=messages,
                    role_modele="codeur", schema=SCHEMA_EDITIONS)
                editions = editions_json(rep.donnees or
                                         self._json(rep.texte))
            else:
                rep = self.backend.completer(
                    systeme=SYSTEME, messages=messages, role_modele="codeur")
                editions = lire_editions(rep.texte)
            if not editions:
                actuels = {f: self.espace.lire(f) for f in fichiers}
                editions = editions_fonctions(rep.texte, extraits, actuels)
            if not editions:
                r.refus = ["aucune modification lisible (ni bloc CHERCHER / "
                           "REMPLACER, ni fonction reecrite)"]
            else:
                faites, r.refus, extraits = appliquer(
                    self.espace, editions, extraits, tests)
                r.appliquees += faites
            if r.appliquees and not r.refus:
                break
            if tour == self.tours:
                break
            # le modele revoit l'etat ACTUEL des extraits et les refus
            actuels = {f: self.espace.lire(f) for f in fichiers}
            par_fichier: dict[str, list[Extrait]] = {}
            for e in extraits:
                par_fichier.setdefault(e.fichier, []).append(e)
            messages += [
                {"role": "assistant", "content": rep.texte},
                {"role": "user", "content":
                    "Refuse :\n" + "\n".join(f"- {x}" for x in r.refus)
                    + ("\n\nDeja applique : " + ", ".join(
                        a.fichier for a in r.appliquees)
                       if r.appliquees else "")
                    + "\n\nEXTRAITS (etat actuel) :\n" + "\n\n".join(
                        montrer(actuels[f], es, _langage(f))
                        for f, es in par_fichier.items())
                    + "\n\nRenvoie seulement les blocs qui restent."}]
        r.diff = diff(originaux, self.espace)
        return r
