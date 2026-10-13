"""Le CONSEIL SUR LES VERDICTS DES JUGES (vision du responsable, 08/10/2026).

« Les professeurs ont de grands acces ; couples a la verification des
specialistes et des juges, ca devient l'arme fatale. » Le deroule :
PLAN -> SPECIALISTES (leurs juges precis) -> CONSEIL, qui reflechit sur le
plan ET les verdicts des juges (trouver la solution, DEJOUER LES
IMPERTINENCES) -> puis le modele ecrit.

Ici les professeurs ne devinent plus a partir des mots de la demande : ils
travaillent sur des PREUVES.
  - REALITE      : les defauts releves par les juges (fichier, ligne,
                   regle), le plan, ce qui existe, les ecritures coupees, ce
                   qui n'a pas tourne ;
  - CONNAISSANCE : le savoir cherche PAR LA REGLE du defaut (le champ
                   `juges` des fiches) et les LEVIERS du catalogue par
                   famille d'echec (leviers.py) ;
  - CALCUL       : quel fichier porte la correction (un defaut visuel vu
                   sur une page se corrige dans la feuille de style), le
                   nombre de pages du plan contre celui de la demande ;
  - HUMAIN       : la gravite (securite, puis accessibilite), les reserves
                   a dire (code jamais execute).
Aucun appel au modele.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import leviers
from . import professeurs as pr
from .deliberation import Element
from .remedes import REMEDES

_FRAGMENTS = re.compile(r"(?i)(^|/)(header|footer|nav|menu|en-?tete|"
                        r"pied(-de-page)?)\.html?$")
VISUELLES = {"contraste", "cible-trop-petite"}
GRAVES = {"injection-sql", "xss-serveur", "xss-dom", "secret-en-dur",
          "injection-commande", "csrf-desactive"}
# Le levier choisi par famille d'echec (dans l'ordre de preference).
CHOIX = {
    "fragment-traite-en-page": ["fragments-sans-criteres-de-page"],
    "fichier-du-plan-jamais-ecrit": ["ecrire-en-plusieurs-fois",
                                     "fichier-court-demande"],
    "contraste": ["palette-mesuree", "reparer-liens-soulignes"],
    "cible-trop-petite": ["cibles-24px-dans-la-consigne",
                          "reparer-cibles-24px"],
    "script-plante": ["script-garde-ses-elements", "ids-des-pages-au-script"],
    "lien-navigation-manquant": ["rappel-criteres-en-fin",
                                 "reparer-liens-du-menu"],
    "ressource-non-chargee": ["reparer-ressources-du-head",
                              "rappel-criteres-en-fin"],
    "structure-de-page": ["rappel-criteres-en-fin"],
    "lien-casse": ["reparer-lien-hors-plan", "liens-du-plan-seulement"],
}


@dataclass
class Situation:
    demande: str
    plan: list[str]                                  # fichiers du plan
    defauts: list[dict] = field(default_factory=list)  # fichier, ligne,
    #                                                    regle, message
    existants: list[str] = field(default_factory=list)
    coupures: dict = field(default_factory=dict)     # fichier -> raisons
    limites: list[str] = field(default_factory=list)
    plan_brut: str = ""                              # si le plan est vide


@dataclass
class Solution:
    texte: str
    cible: str            # le fichier qui porte la correction
    famille: str
    professeur: str
    source: str
    levier: str = ""      # id du levier (leviers.py)

    @property
    def pour_le_modele(self) -> bool:
        """Un levier « consigne » s'adresse au modele ; un levier
        « programme » est une action du programme de MAEL (ne plus exiger un
        critere, reparer sans modele) : il va au journal, pas a la consigne."""
        l = leviers.PAR_ID.get(self.levier)
        return l is None or l.origine == "consigne"


@dataclass
class Verdict:
    solutions: list[Solution] = field(default_factory=list)
    impertinences: list[Element] = field(default_factory=list)
    hypotheses: list[Element] = field(default_factory=list)
    ne_pas: list[Element] = field(default_factory=list)
    reserves: list[Element] = field(default_factory=list)
    confiance: str = "haute"
    pourquoi: str = ""

    def texte(self) -> str:
        l = ["[le conseil des professeurs sur les verdicts des juges]",
             f"confiance : {self.confiance} ({self.pourquoi})"]
        if self.impertinences:
            l += ["impertinences dejouees :"] + [
                f"- {e.texte} [{e.professeur}]" for e in self.impertinences]
        if self.solutions:
            l += ["solutions :"] + [f"- dans {s.cible} : {s.texte} "
                                    f"[{s.professeur}]"
                                    for s in self.solutions]
        if self.hypotheses:
            l += ["hypotheses a departager :"] + [
                f"- {e.texte} [{e.professeur}]" for e in self.hypotheses]
        if self.ne_pas:
            l += ["a ne PAS faire :"] + [f"- {e.texte} [{e.professeur}]"
                                         for e in self.ne_pas]
        if self.reserves:
            l += ["reserves :"] + [f"- {e.texte} [{e.professeur}]"
                                   for e in self.reserves]
        return "\n".join(l)


BUDGET_TACHE = 900        # caracteres : la memoire du modele est courte


def pour_la_tache(v: Verdict, fichier: str, budget: int = BUDGET_TACHE
                  ) -> str:
    """Ce que le MODELE doit lire du verdict pour corriger CE fichier : les
    impertinences, les solutions « consigne » qui le visent, ce qui se
    corrige ailleurs, deux hypotheses au plus, ce qu'il ne faut pas faire.
    Le verdict complet va au journal."""
    lignes = ["[le conseil des professeurs a delibere sur ces defauts]"]
    lignes += [f"- impertinence : {e.texte}" for e in v.impertinences]
    for s in v.solutions:
        if s.cible == fichier and s.pour_le_modele:
            lignes.append(f"- solution : {s.texte}")
        elif s.cible != fichier:
            lignes.append(f"- le defaut « {s.famille} » se corrige dans "
                          f"{s.cible}, pas dans {fichier}")
    lignes += [f"- hypothese : {e.texte}" for e in v.hypotheses[:2]]
    lignes += [f"- a ne PAS faire : {e.texte}" for e in v.ne_pas]
    garde = []
    for l in dict.fromkeys(lignes):          # une meme ligne une seule fois
        if len("\n".join(garde + [l])) > budget:
            break
        garde.append(l)
    return "\n".join(garde) if len(garde) > 1 else ""


def _famille(d: dict, prevus: set[str], existants: set[str]) -> str:
    from .lecons import Constat, classer
    return classer(Constat("", d["fichier"], d.get("ligne", 0),
                           d["message"]), prevus, existants)


def _fiches_par_regle(regle: str):
    from . import savoir_faire
    return [f for f in savoir_faire.toutes() if regle in f.juges]


# Les mots qui disent, dans une etape de fiche, qu'elle traite CETTE regle.
MOTS_REGLE = {
    "injection-sql": ("prepar", "parametr", " ? ", "execute"),
    "xss-serveur": ("htmlspecialchars", "echapp"),
    "xss-dom": ("textcontent", "innerhtml"),
    "innerhtml": ("textcontent", "innerhtml"),
    "debug-actif": ("debug",),
    "secret-en-dur": ("environnement", "getenv", "environ"),
    "img-alt": ("<img",),
    "champ-sans-label": ("<label",),
    "selecteur-mort": ("existe", "id "),
    "xxe": ("doctype",),
    "contrat-api": ("route",),
}


def _solution_par_fiche(d: dict, fichier: str, demande: str
                        ) -> tuple[str, object] | None:
    """Les « grands acces » du professeur CONNAISSANCE (banc de la chaine
    du 08/10/2026) : sans levier pour ce defaut, la solution vient de la
    fiche qui fait tenir SA regle — de preference celle du specialiste du
    fichier — et, dans la fiche, de l'etape qui parle de cette regle."""
    from . import savoir_faire, specialistes
    regle = d.get("regle", "")
    fiches = _fiches_par_regle(regle)
    if not fiches:
        return None
    s = specialistes.pour(fichier)
    nom = s.nom if s else ""
    ctx = savoir_faire.contexte_js(fichier, demande) if nom == "js" else ""

    def rang(f):
        if f.specialiste == nom and (not ctx or f.contexte in {ctx, ""}):
            return 0
        return 1 if f.specialiste in {"conseil", "projet"} else 2
    # Une fiche d'un AUTRE langage de code ne sert jamais (lot neuf du
    # 08/10/2026 : htmlspecialchars, du PHP, propose pour un XSS en Python).
    langages = {"html", "css", "js", "python", "php", "java"}
    fiches = [f for f in fiches if f.specialiste == nom
              or f.specialiste not in langages
              or {nom, f.specialiste} <= {"html", "js", "css"}]
    if not fiches:
        return None
    # La fiche dont une etape parle VRAIMENT de la regle, dans l'ordre des
    # rangs (et non la premiere par ordre alphabetique : « carte produit »
    # repondait a une image sans alt dans un formulaire d'inscription).
    mots = MOTS_REGLE.get(regle, ())
    for fiche in sorted(fiches, key=lambda f: (rang(f), f.id)):
        etape = next((c for c in fiche.comment
                      if any(m in c.lower() for m in mots)), None)
        if etape:
            return etape, fiche
    # Aucune etape ne parle de CETTE regle : jamais une etape au hasard (lot
    # neuf du 08/10/2026 : « autocomplete » pour un mot de passe en GET).
    # Le remede du juge, ecrit pour chaque regle bloquante, la dit.
    return None


def _feuille(s: Situation) -> str:
    return next((f for f in s.plan + s.existants if f.endswith(".css")),
                "la feuille de style")


def deliberer(s: Situation) -> Verdict:
    v = Verdict()
    prevus, existants = set(s.plan), set(s.existants)
    faits = pr.etablir(s.demande)

    # ------------------------------------------- REALITE + CALCUL : le plan
    for f in s.plan:
        if _FRAGMENTS.search(f):
            v.impertinences.append(Element(
                f"{f} est un MORCEAU de page traite comme une page : il "
                "s'ecrit dans chaque page, et ne doit plus recevoir les "
                "criteres d'une page (<main>, <h1>)", "realite",
                f"plan : {f} ; savoir-faire entete-pied-dans-la-page"))
    pages = [f for f in s.plan if f.endswith((".html", ".htm"))
             and not _FRAGMENTS.search(f)]
    if faits.nb_pages and len(pages) > faits.nb_pages:
        v.impertinences.append(Element(
            f"{len(pages)} pages au plan pour {faits.nb_pages} demandee(s) : "
            "le contenu en trop va dans la page demandee", "calcul",
            f"comptage du plan contre la demande ({faits.nb_pages})"))
    if not s.plan and re.search(r"(?m)^\s*(?:[-*•]|\d+[.)])?\s*`?/",
                                s.plan_brut):
        v.impertinences.append(Element(
            "plan illisible : les chemins commencent par « / » — refaire le "
            "plan avec des chemins relatifs", "realite",
            "reponse brute du plan (.mael/plan-brut.txt)"))
    for raison in pr.juger_plan(s.plan, faits) if s.plan else []:
        if "aucun code" in raison:
            v.impertinences.append(Element(raison, "realite",
                                           "juge du plan"))

    # -------------------------- REALITE + CONNAISSANCE : chaque defaut
    vues: set[tuple[str, str]] = set()
    for d in s.defauts:
        fam = _famille(d, prevus, existants)
        cible = d["fichier"]
        if fam in VISUELLES:
            cible = _feuille(s)              # vu sur la page, corrige au CSS
        if fam == "fichier-du-plan-jamais-ecrit":
            m = re.search(r'="([^"]+)"', d["message"])
            cible = m.group(1) if m else cible
        # Deux defauts « autre » du meme fichier (injection SQL ET XSS dans
        # contact.php) sont deux problemes : la cle porte alors la REGLE.
        cle = (fam if fam != "autre" else d.get("regle", fam), cible)
        if cle in vues:
            continue
        vues.add(cle)
        if fam == "lien-casse":
            m = re.search(r'="([^"]+)"', d["message"])
            lien = m.group(1) if m else "?"
            # Le fichier EXISTE sous un autre chemin (lot neuf du 08/10/2026 :
            # css/style.css appele, style.css a la racine) : ce n'est pas un
            # fichier a inventer, c'est un chemin a corriger.
            nom = Path(lien.split("?")[0]).name
            ailleurs = [f for f in s.existants + s.plan
                        if Path(f).name == nom and f != lien.lstrip("./")]
            if ailleurs:
                v.solutions.append(Solution(
                    f"corriger le chemin : {lien} -> {ailleurs[0]} (le "
                    "fichier existe deja)", d["fichier"], "chemin-faux",
                    "calcul", f"{ailleurs[0]} trouve dans le projet"))
                continue
            v.impertinences.append(Element(
                f"{d['fichier']} pointe vers {lien}, hors du plan et du "
                "projet", "realite", f"juge : {d['message'][:60]}"))
            ext = Path(lien.split("?")[0]).suffix.lower()
            if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
                       ".avif"}:
                # Une IMAGE absente n'est pas une page a inventer (banc de
                # la chaine du 08/10/2026 : « inventer la page logo.png »).
                v.ne_pas.append(Element(
                    f"supprimer l'image {lien} : la garder, MAEL pose une "
                    "image provisoire au bon format, a remplacer par la "
                    "vraie", "humain", "reparation des images provisoires "
                    "(option A du responsable)"))
            else:
                quoi = "la page" if ext in {".html", ".htm", ""} else \
                    "le fichier"
                v.ne_pas.append(Element(
                    f"inventer {quoi} {lien} en silence : le lien se retire, "
                    "ou le fichier s'ajoute au plan", "humain",
                    "rien ne se decide a la place de la personne sans etre "
                    "ecrit"))
        if d.get("regle") == "contrat-api":
            # La REALITE du juge d'abord : il connait les routes du serveur.
            # Lot neuf du 08/10/2026 : le conseil citait l'exemple de la
            # fiche (/api/produits) au lieu de la vraie route (/commandes).
            appel = re.search(r'fetch\("([^"]+)"\)', d["message"])
            routes = re.findall(r"/[^\s,)]*",
                                d["message"].split("routes :")[-1])
            if appel and routes:
                dernier = appel.group(1).rstrip("/").rsplit("/", 1)[-1]
                route = next((r for r in routes
                              if r.rstrip("/").endswith("/" + dernier)),
                             routes[0])
                v.solutions.append(Solution(
                    f"appeler {route} (la route du serveur) au lieu de "
                    f"{appel.group(1)}", cible, "contrat-api", "realite",
                    "routes relevees par le juge des contrats"))
                continue
        choix = [l for l in CHOIX.get(fam, []) if l in leviers.PAR_ID]
        if not choix and d.get("regle") == "critere-non-tenu":
            # Un critere quelconque non tenu : le rappeler, pas une fiche au
            # hasard de la regle (generique) « critere-non-tenu ».
            choix = ["rappel-criteres-en-fin"]
        if fam == "fichier-du-plan-jamais-ecrit" and not s.coupures.get(
                cible):
            choix = choix[1:] or choix
        if choix:
            l = leviers.PAR_ID[choix[0]]
            # La famille « autre » se dit par sa regle (« le defaut autre se
            # corrige dans... » ne disait rien au modele).
            nom_fam = fam if fam != "autre" else d.get("regle", fam)
            v.solutions.append(Solution(l.action, cible, nom_fam,
                                        "connaissance",
                                        f"levier {l.id} (leviers.py)", l.id))
        else:
            trouve = _solution_par_fiche(d, cible, s.demande)
            regle = d.get("regle", fam)
            if trouve:
                etape, fiche = trouve
                v.solutions.append(Solution(
                    etape, cible, regle, "connaissance",
                    f"fiche {fiche.id} — {fiche.source.split(' — ')[0]}"))
            elif regle in REMEDES:
                # En secours, le REMEDE du juge : la forme juste de sa regle.
                v.solutions.append(Solution(
                    REMEDES[regle], cible, regle, "connaissance",
                    f"remede du juge « {regle} » (remedes.py)"))
        for fiche in _fiches_par_regle(d.get("regle", "")):
            for h in fiche.hypotheses:
                e = Element(h, "connaissance", fiche.source.split(" — ")[0])
                if e.texte not in {x.texte for x in v.hypotheses}:
                    v.hypotheses.append(e)
        if fam == "fichier-du-plan-jamais-ecrit":
            v.ne_pas.append(Element(
                "reecrire les pages qui appellent ce fichier : elles sont "
                "justes, c'est le fichier qui manque", "realite",
                f"{cible} prevu au plan, absent du projet"))
        if fam == "lien-navigation-manquant":
            v.hypotheses.append(Element(
                "le critere etait deja ecrit dans la consigne : le modele ne "
                "l'a pas suivi", "realite", "critere de la tache (plan)"))

    # ------------------------------------------- HUMAIN : gravite, reserves
    graves = [d for d in s.defauts if d.get("regle") in GRAVES]
    if graves:
        v.solutions.sort(key=lambda x: x.famille not in GRAVES)
    for lim in s.limites:
        if re.search(r"LU mais non execute|tests NON executes|pages NON "
                     r"ouvertes", lim):
            v.reserves.append(Element(
                f"verdict SOUS RESERVE : {lim} — a dire a la personne",
                "humain", "un code jamais execute n'est pas prouve juste"))

    # --------------------------------------------- CONCLURE : la confiance
    sans = [d for d in s.defauts
            if _famille(d, prevus, existants) not in CHOIX
            and not _fiches_par_regle(d.get("regle", ""))
            and d.get("regle", "") not in REMEDES]
    if not s.defauts and not v.impertinences and not v.reserves:
        v.confiance, v.pourquoi = "haute", "aucun defaut ni impertinence"
    elif sans:
        v.confiance, v.pourquoi = "basse", (f"{len(sans)} defaut(s) sans "
                                            "solution connue")
    elif v.reserves:
        v.confiance, v.pourquoi = "moyenne", "des verifications n'ont pas " \
            "tourne"
    elif s.defauts:
        v.confiance, v.pourquoi = "haute", "chaque defaut a sa solution " \
            "connue"
    else:
        v.confiance, v.pourquoi = "haute", "impertinences du plan " \
            "reconnues et dejouees"
    return v
