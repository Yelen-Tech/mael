"""La DELIBERATION ENTRE PROFESSEURS, par programme, sans le modele.

Decision du responsable (08/10/2026) : « la deliberation doit se faire entre
professeurs, sans le modele, car il prendrait beaucoup de temps » ; « si
les professeurs sont corrects avec leur deliberation, on a gagne ».

La methode validee (6 temps) :
  1. REALITE      : ce qui est observe — la NATURE du probleme (creer,
                    corriger, diagnostiquer, migrer, traduire, etendre), les
                    langages, l'existant, les services externes, l'enjeu ;
  2. CONNAISSANCE : ce que dit la bibliotheque (fiches sourcees et datees) ;
  3. CALCUL       : les nombres, calcules par programme (unites, seuils et
                    leurs voisins, fichiers, plafond) ;
  4. HUMAIN       : pour qui, le risque pour la personne, ce qu'il faut lui
                    demander ou lui dire ;
  5. HYPOTHESES   : au moins deux pour un diagnostic, tirees des fiches ;
  6. CONCLURE     : decisions, besoins, ce qu'il ne faut PAS faire, comment
                    verifier, ce qui refuterait la conclusion, CONFIANCE.

ARBITRAGE : un fait de Realite l'emporte sur une supposition ; un nombre de
Calcul l'emporte sur une estimation ; un risque eleve vu par Humain impose
la prudence (sauvegarde, mode test) ; la Connaissance dit COMMENT, jamais
contre un fait. Chaque element garde son professeur et sa source.
Le JUGE (programme) refuse une deliberation incomplete ou trop sure d'elle.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from . import professeurs as pr


def _norm(texte: str) -> str:
    t = unicodedata.normalize("NFKD", texte.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[’'`]", " ", t)


# ------------------------------------------------ 1. REALITE : la nature
NATURES = (
    ("migrer", r"\b(passe[rz]?|migr\w*|transfer\w*)\b.*\b(sqlite|postgres\w*|"
     r"mysql|base)\b|sans perdre"),
    ("traduire", r"version (anglaise|francaise|en \w+)|tradu\w+|multilingue"
     r"|aussi en (anglais|francais)"),
    # Une NEGATION de fonctionnement (« ne fait rien », « ne repond plus »)
    # decrit une panne : c'est un diagnostic, quelle que soit la phrase.
    ("diagnostiquer", r"\bne\s+(\w+\s+){0,2}?(pas|plus|rien)\b|\berreur\b|"
     r"cannot read|exception|trop lent|\blente?\b|repond en \d"),
    ("corriger", r"s affiche mal|deborde|zoomer|\bspams?\b|casse|ne s affiche"),
    ("etendre", r"\b(ma|mon|mes)\b[^.]*\b(doit|accepter|ajout\w*)\b|protege"
     r"\w* (mon|ma|mes)|securis\w* (mon|ma|mes)"),
    # Une CREATION se dit par ses tournures generales, pas par un sujet :
    # sans elles, la nature reste INCONNUE (phase de test du 08/10/2026 :
    # le defaut « creer » faisait repondre a « mon site a ete pirate »).
    ("creer", r"^\s*(un|une|des|le|la|les|a|an|the)\b|\b(cree[rz]?|fai[st]|"
     r"fabrique\w*|construi\w*|develop\w*|programme|create|build|make)\b|"
     r"\bje veux (un|une|des)\b|\bil me faut\b"),
)
SERVICES = (
    ("paiement", r"orange money|moov|mobile money|paypal|stripe|paiement|"
     r"payer|carte bancaire"),
    ("meteo", r"\bmeteo\b|weather"),
    ("e-mail", r"e-?mail|\bmail\b|courriel"),
    ("sms", r"\bsms\b"),
)
_DONNEES = r"sans perdre|mes donnees|ma base|base \w+ a \w+|existant"
_SECURITE = r"protege|securis|connecte|mot de passe|droits|authentif"
_ARGENT = r"paiement|money|payer|carte bancaire|prix"


def nature(texte: str) -> str:
    t = _norm(texte)
    for n, motif in NATURES:
        if re.search(motif, t):
            return n
    return "inconnue"


def services(texte: str) -> list[str]:
    t = _norm(texte)
    return [n for n, motif in SERVICES if re.search(motif, t)]


# ------------------------------------------------ 3. CALCUL : les nombres
@dataclass
class Nombre:
    texte: str
    calcul: str


def nombres(texte: str) -> list[Nombre]:
    t = _norm(texte)
    out = []
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(secondes?|s\b|minutes?|ms\b)",
                         t):
        v, u = float(m.group(1).replace(",", ".")), m.group(2)
        ms = v * (1000 if u.startswith("s") else 60_000 if u.startswith("m")
                  and u != "ms" else 1)
        out.append(Nombre(f"{m.group(0)} = {ms:.0f} ms", f"{m.group(0)} "
                          "converti (1 s = 1 000 ms)"))
    for m in re.finditer(r"(moins de|plus de|au moins|seuil de|sous|au-dessous"
                         r" de)\s+(\d+)", t):
        n = int(m.group(2))
        out.append(Nombre(f"seuil {n} : tester {n - 1}, {n} et {n + 1}",
                          f"« {m.group(0)} » : la limite et ses voisins (une "
                          "erreur < contre <= se cache a la limite)"))
    return out


# --------------------------------------------------------- la decision
@dataclass
class Element:
    texte: str
    professeur: str
    source: str


@dataclass
class Decision:
    probleme: str
    nature: str = "creer"
    langages: list[str] = field(default_factory=list)
    fiches: list[str] = field(default_factory=list)
    decisions: list[Element] = field(default_factory=list)
    hypotheses: list[Element] = field(default_factory=list)
    besoins: list[Element] = field(default_factory=list)
    ne_pas: list[Element] = field(default_factory=list)
    verifier: list[Element] = field(default_factory=list)
    risque: str = "faible"
    confiance: str = "haute"
    pourquoi_confiance: str = ""
    refutation: str = ""
    refus: list[str] = field(default_factory=list)

    def tous(self) -> list[Element]:
        return (self.decisions + self.hypotheses + self.besoins + self.ne_pas
                + self.verifier)

    def texte(self) -> str:
        def bloc(titre, elements):
            return ([f"{titre} :"] + [f"- {e.texte} [{e.professeur}]"
                                      for e in elements]) if elements else []
        l = ["[decisions du conseil des professeurs]",
             f"nature : {self.nature} ; risque : {self.risque} ; confiance : "
             f"{self.confiance} ({self.pourquoi_confiance})"]
        l += bloc("decisions", self.decisions)
        l += bloc("hypotheses a departager", self.hypotheses)
        l += bloc("a demander a la personne", self.besoins)
        l += bloc("a ne PAS faire", self.ne_pas)
        l += bloc("pour verifier", self.verifier)
        if self.refutation:
            l.append(f"ce qui refuterait : {self.refutation}")
        return "\n".join(l)


def _demande_a_la_personne(dep: dict) -> bool:
    return "demander" in dep.get("pourquoi", "")


def deliberer(probleme: str, fichiers_max: int = 8) -> Decision:
    """Les quatre professeurs, puis l'arbitrage. Aucun appel au modele."""
    from . import savoir_faire
    c = pr.comprendre(probleme)
    f = pr.etablir(probleme, c, fichiers_max=fichiers_max)
    t = _norm(probleme)
    d = Decision(probleme=probleme, nature=nature(probleme),
                 langages=sorted(f.langages))
    # « Vague » ne vaut que pour une CREATION : « ma boutique doit accepter
    # Orange Money » ou « mon API est lente » sont des problemes precis.
    vague = c.vague and d.nature == "creer"
    sv = services(probleme)

    # 1. REALITE
    if d.nature in {"corriger", "diagnostiquer", "migrer", "etendre",
                    "traduire"}:
        d.ne_pas.append(Element("tout refaire : partir de l'existant", "realite",
                                f"le probleme est de nature « {d.nature} »"))
    if sv:
        d.besoins.append(Element(
            f"service externe ({', '.join(sv)}) : MAEL travaille hors ligne et "
            "ne peut pas l'appeler pendant le chantier", "realite",
            "MAEL est un outil local (machine sans acces aux services)"))
        d.ne_pas.append(Element("inventer l'API du service ou ses donnees",
                                "realite", "aucune documentation fournie"))

    # 2. CONNAISSANCE
    notes = savoir_faire.pour_conseil_note(probleme)
    fiches = [x for _s, x in notes]
    score = notes[0][0] if notes else 0     # mots SPECIFIQUES communs
    d.fiches = [x.id for x in fiches]
    if fiches:
        principale = fiches[0]
        src = principale.source.split(" — ")[0]
        for etape in principale.comment:
            d.decisions.append(Element(etape, "connaissance", src))
        for h in principale.hypotheses:
            d.hypotheses.append(Element(h, "connaissance", src))
        for v in principale.verifier:
            d.verifier.append(Element(v, "connaissance", src))
        for dep in principale.dependances:
            if _demande_a_la_personne(dep):
                d.besoins.append(Element(dep["nom"], "connaissance", src))
        # Les fiches secondaires ne decident pas : elles ajoutaient des
        # decisions hors sujet (le menu commun pour un affichage mobile, la
        # carte produit pour un stock). Elles restent citees dans d.fiches.

    # 3. CALCUL
    for n in nombres(probleme):
        cible = d.verifier if n.texte.startswith("seuil") else d.decisions
        cible.append(Element(n.texte, "calcul", n.calcul))
    if d.nature == "creer":
        prevus = pr.fichiers_prevus(f)
        if vague or re.search(r"\bcomme\b", t):
            d.decisions.append(Element(
                f"plafond du chantier : {f.fichiers_max} fichiers — une "
                "PREMIERE ETAPE qui marche seule", "calcul",
                "chantier.TACHES_MAX"))
        else:
            d.decisions.append(Element(
                f"environ {prevus} fichier(s) (plafond {f.fichiers_max})",
                "calcul", "professeur calcul : fichiers_prevus"))
    if d.nature == "traduire":
        d.decisions.append(Element("chaque page existe en 2 langues : le "
                                   "nombre de pages double", "calcul",
                                   "une page par langue (fiche traduire)"))

    # 4. HUMAIN
    argent = bool(re.search(_ARGENT, t)) and "paiement" in sv
    donnees = bool(re.search(_DONNEES, t)) or d.nature == "migrer"
    securite = bool(re.search(_SECURITE, t))
    if argent or donnees or securite:
        d.risque = "eleve"
    elif re.search(r"spam", t):
        d.risque = "moyen"
    if argent:
        d.decisions.append(Element("de l'argent reel : le mode test du "
                                   "fournisseur d'abord, jamais en direct",
                                   "humain", "risque financier pour la "
                                   "personne"))
    if donnees:
        d.decisions.append(Element("SAUVEGARDER avant toute modification",
                                   "humain", "risque de perte de donnees"))
    if d.nature == "traduire":
        d.decisions.append(Element("la traduction est RELUE par un humain",
                                   "humain", "une traduction automatique peut "
                                   "dire le contraire"))
    if vague or (d.nature == "creer" and re.search(r"\bcomme\b", t)):
        d.besoins.append(Element("ce que la premiere etape doit contenir "
                                 "(la proposer, la faire valider)", "humain",
                                 "demande trop vague ou trop grande"))

    # 5. HYPOTHESES (un diagnostic sans deux hypotheses n'en est pas un)
    if d.nature == "diagnostiquer":
        d.decisions.insert(0, Element("MESURER ou reproduire avant de "
                                      "corriger : ne pas deviner", "realite",
                                      "methode : observation avant "
                                      "conclusion"))
        d.ne_pas.append(Element("deviner la cause sans mesure", "realite",
                                "methode scientifique"))

    # 6. CONCLURE : confiance et refutation
    # La CONFIANCE mesure la pertinence, pas seulement « une fiche existe »
    # (phase de test du 08/10/2026 : 7 fausses assurances sur 12).
    if d.nature == "inconnue":
        d.confiance, d.pourquoi_confiance = "basse", ("la nature du probleme "
                                                      "n'est pas reconnue")
        d.besoins.append(Element("preciser le probleme : que faut-il "
                                 "creer, corriger ou expliquer ?", "humain",
                                 "nature non reconnue par le professeur "
                                 "realite"))
    elif not fiches:
        d.confiance, d.pourquoi_confiance = "basse", ("aucune fiche de la "
                                                      "bibliotheque ne couvre "
                                                      "ce probleme")
        d.besoins.append(Element("preciser le probleme", "humain",
                                 "la bibliotheque ne le couvre pas"))
    elif d.nature == "diagnostiquer" and len(d.hypotheses) < 2:
        d.confiance, d.pourquoi_confiance = "basse", "moins de deux "\
            "hypotheses connues"
    elif score < 3:
        d.confiance, d.pourquoi_confiance = "moyenne", (
            f"le savoir trouve ne touche le probleme que par {score} mots")
    elif d.besoins:
        d.confiance, d.pourquoi_confiance = "moyenne", ("depend de ce que la "
                                                        "personne fournira")
    else:
        d.pourquoi_confiance = "fait etabli et savoir source"
    d.refutation = (
        "la mesure montre une autre cause que les hypotheses"
        if d.nature == "diagnostiquer" else
        "la verification echoue" if d.verifier else
        "les juges trouvent un defaut bloquant")
    d.refus = juger(d)
    return d


# ---------------------------------------------------------------- le juge
def juger(d: Decision) -> list[str]:
    """Le juge du conseil : la deliberation est-elle complete, sourcee, et
    pas plus sure que ses preuves ?"""
    r = []
    if not d.decisions:
        r.append("aucune decision")
    for e in d.tous():
        if e.professeur not in pr.PROFESSEURS or not e.source:
            r.append(f"element sans professeur ou sans source : {e.texte[:50]}")
            break
    if d.nature == "diagnostiquer" and len(d.hypotheses) < 2 and \
            d.confiance != "basse":
        r.append("un diagnostic demande au moins deux hypotheses")
    if d.nature == "inconnue" and d.confiance != "basse":
        r.append("nature inconnue : la confiance ne peut etre que basse")
    if d.confiance == "haute" and d.besoins:
        r.append("confiance haute alors que des elements manquent")
    if any(e.texte.startswith("service externe") for e in d.besoins) and \
            not any("inventer" in e.texte for e in d.ne_pas):
        r.append("service externe sans l'interdiction d'inventer son API")
    if d.risque == "eleve" and not any(
            e.professeur == "humain" for e in d.decisions) and not any(
            "SAUVEGARD" in e.texte or "mode test" in e.texte
            for e in d.tous()) and "securis" not in _norm(d.probleme) \
            and "protege" not in _norm(d.probleme):
        r.append("risque eleve sans mesure de prudence")
    return r
