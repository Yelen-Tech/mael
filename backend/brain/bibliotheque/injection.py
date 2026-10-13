"""Injection ciblee du savoir dans le prompt (etape 4 du pipeline).

Un petit modele (qwen2.5:3b, contexte 8k) raisonne mieux sur UNE fiche claire
que sur deux fiches presque identiques. On lui donne donc :

  - la FICHE PRINCIPALE, complete mais compacte : ce qui est attendu, les
    commandes de SON systeme seulement, l'action si ecart, 2 pieges au plus,
    et SES referentiels (le CIS de sa distribution, pas les trois) ;
  - quelques FICHES PROCHES en une ligne (titre + attendu), pour qu'il sache
    ce qui existe a cote sans les detailler ;
  - le theme reconnu et le niveau de conformite.

Le tout tient dans un BUDGET EN JETONS. S'il deborde, on retire dans l'ordre :
fiches proches en trop, pieges, risque, commande secondaire. Jamais la
commande principale ni l'attendu.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Estimation prudente pour Qwen sur du francais technique (mesuree sur
# Ollama : ~3,2 caracteres par jeton) ; 3,0 pour garder de la marge.
CARACTERES_PAR_JETON = 3.0
BUDGET_JETONS = 700           # savoir injecte, profil court sur 8k de contexte
MAX_PROCHES = 4
RATIO_PROCHES = 0.5           # une fiche proche doit valoir >= 50 % du score


def estimer_jetons(texte: str) -> int:
    return int(len(texte) / CARACTERES_PAR_JETON) + 1


@dataclass
class Savoir:
    texte: str
    jetons: int
    principale: str | None
    proches: list[str] = field(default_factory=list)
    retraits: list[str] = field(default_factory=list)   # ce qui a ete coupe


def _document_du_systeme(document: str, contexte) -> bool:
    """Le document CIS vise-t-il le systeme audite ? (CIS Benchmark for
    Ubuntu 22.04 LTS v2.0.0 <-> ubuntu 22.04)"""
    if contexte is None or not getattr(contexte, "connu", False):
        return True
    bas = document.lower()
    return (contexte.os_id or "") in bas and (contexte.version or "") in bas


def referentiels_compacts(fiche, contexte) -> str:
    """« CIS 3.3.1 (niveau 1) ; ANSSI R12 (niveau intermediaire) » : le CIS
    du systeme audite (ou, a defaut, le premier), sans doublons."""
    vus, morceaux = set(), []
    cis = [r for r in fiche.referentiels if r.nom == "CIS"]
    cis_systeme = [r for r in cis if _document_du_systeme(r.document, contexte)]
    for r in (cis_systeme or cis[:1]) + [r for r in fiche.referentiels if r.nom != "CIS"]:
        if r.ref:
            texte = f"{r.nom} {r.ref}"
        elif r.document.upper().startswith(r.nom.upper()):
            texte = r.document                      # « CIS Benchmarks... »
        else:
            texte = f"{r.nom} {r.document}"
        if texte not in vus:
            vus.add(texte)
            morceaux.append(texte)
    return " ; ".join(morceaux)


_MOTS_ANGLAIS = {"the", "is", "are", "to", "of", "and", "that", "this", "be",
                 "can", "an", "on", "which", "with", "should", "it", "by"}


def semble_anglais(texte: str) -> bool:
    """Heuristique : le texte d'origine de la source n'a pas ete traduit. On
    ne le montre pas a un petit modele qui repond en francais (melange de
    langues)."""
    mots = re.findall(r"[a-z]+", (texte or "").lower())
    return bool(mots) and sum(m in _MOTS_ANGLAIS for m in mots) / len(mots) > 0.08


def _premiere_phrase(texte: str, limite: int = 220) -> str:
    texte = " ".join((texte or "").split())
    m = re.match(r"(.+?[.!?])(\s|$)", texte)
    phrase = m.group(1) if m else texte
    return phrase if len(phrase) <= limite else phrase[: limite - 1].rstrip() + "…"


def _bloc_principal(fiche, contexte, *, pieges: int, risque: bool,
                    commandes: int) -> str:
    from brain.contexte import commande_pour

    etat = "" if fiche.etat == "verifie" else " [brouillon non relu]"
    lignes = [f"FICHE PRINCIPALE « {fiche.titre} »{etat}"]
    refs = referentiels_compacts(fiche, contexte)
    if refs:
        lignes.append(f"Referentiels : {refs}")
    for c in fiche.controles:
        attendu = f"Attendu : {c.controle}"
        if c.bon:
            attendu += f" (conforme : {c.bon})"
        if c.gravite:
            attendu += f" — gravite {c.gravite}"
        lignes.append(attendu)
        if risque and c.risque and not semble_anglais(c.risque):
            lignes.append(f"Pourquoi : {_premiere_phrase(c.risque)}")
    lignes.append("Commandes de lecture verifiees :")
    for obs in fiche.observer[:commandes]:
        lignes.append(f"  $ {commande_pour(obs, contexte)}")
        if obs.lecture:
            lignes.append(f"    -> {obs.lecture}")
    for c in fiche.controles:
        if c.action:
            lignes.append(f"Si ecart : {c.action}")
    for p in fiche.pieges[:pieges]:
        lignes.append(f"Attention : {p}")
    return "\n".join(lignes)


def _ligne_proche(fiche) -> str:
    attendu = fiche.controles[0].controle if fiche.controles else ""
    return f"  - {fiche.titre}" + (f" (attendu : {attendu})"
                                   if attendu and attendu not in fiche.titre else "")


def construire(trouvailles, contexte=None, themes=None,
               budget_jetons: int = BUDGET_JETONS) -> Savoir:
    """`trouvailles` : liste de recherche.Trouvaille (ou de fiches), classee."""
    from .taxonomie import THEMES

    fiches = [getattr(t, "fiche", t) for t in trouvailles]
    scores = [getattr(t, "score", None) for t in trouvailles]
    if not fiches:
        return Savoir("", 0, None)
    principale = fiches[0]
    proches, titres = [], {principale.titre}
    for fiche, score in zip(fiches[1:], scores[1:]):
        if len(proches) >= MAX_PROCHES:
            break
        if scores[0] and score is not None and score < RATIO_PROCHES * scores[0]:
            continue
        if fiche.titre in titres:          # deux regles au meme titre
            continue
        titres.add(fiche.titre)
        proches.append(fiche)

    entete = []
    if themes:
        libelles = [THEMES[t][0] for t in themes if t in THEMES]
        if libelles:
            entete.append("Theme reconnu : " + ", ".join(libelles))
    if contexte is not None and getattr(contexte, "connu", False):
        entete.append(f"Systeme : {contexte.os_id} {contexte.version or ''}".rstrip())

    # Reductions successives jusqu'a tenir dans le budget.
    reglages = {"proches": len(proches), "pieges": 2, "risque": True,
                "commandes": len(principale.observer)}
    etapes = [("proches", 2, "fiches proches reduites a 2"),
              ("pieges", 0, "pieges retires"),
              ("proches", 0, "fiches proches retirees"),
              ("risque", False, "explication du risque retiree"),
              ("commandes", 1, "commande secondaire retiree")]
    retraits: list[str] = []

    def rendre() -> str:
        blocs = []
        if entete:
            blocs.append(" | ".join(entete))
        blocs.append(_bloc_principal(principale, contexte,
                                     pieges=reglages["pieges"],
                                     risque=reglages["risque"],
                                     commandes=max(1, reglages["commandes"])))
        if reglages["proches"]:
            blocs.append("Fiches proches (a proposer si l'humain elargit, "
                         "sans les detailler) :\n" + "\n".join(
                             _ligne_proche(f) for f in proches[:reglages["proches"]]))
        return "\n".join(blocs)

    texte = rendre()
    for cle, valeur, libelle in etapes:
        if estimer_jetons(texte) <= budget_jetons:
            break
        if (cle == "proches" and reglages[cle] <= valeur) or reglages[cle] == valeur:
            continue
        reglages[cle] = valeur
        retraits.append(libelle)
        texte = rendre()

    return Savoir(texte=texte, jetons=estimer_jetons(texte),
                  principale=principale.id,
                  proches=[f.id for f in proches[:reglages["proches"]]],
                  retraits=retraits)
