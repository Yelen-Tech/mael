"""La bibliotheque de savoir (etape 2.1).

Des FICHES verifiees, une par sujet (SSH, TLS, en-tetes, ports, DNS, journaux).
Le modele ne part JAMAIS de zero : il lit la fiche pertinente pour produire la
bonne commande, avec les bonnes options, et interpreter correctement la sortie.
C'est ce qui corrige le defaut d'un petit modele (inventer des drapeaux).

Une fiche est un fichier YAML dans `fiches/`. Ici : le modele de donnees, le
chargement (une fois par processus) et une recherche par mots-cles (rapide,
deterministe -- les embeddings viendront plus tard si besoin).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml


@dataclass
class Referentiel:
    """Renvoi vers un referentiel (ANSSI, CIS...). `ref` = numero de regle
    exact, laisse vide tant qu'il n'est pas repris d'une source : on n'invente
    jamais un numero."""
    nom: str                         # ANSSI | CIS | STIG | RFC | OWASP | autre
    document: str
    ref: str | None = None


@dataclass
class Controle:
    """Un point de controle : ce qui constitue un probleme, et sa gravite."""
    controle: str
    bon: str = ""
    mauvais: str = ""
    gravite: str = ""
    risque: str = ""
    action: str = ""
    playbook: str | None = None      # id d'un playbook de correction, si existe
    referentiels: list[Referentiel] = field(default_factory=list)
    # Etape 5 : comment le CODE juge ce controle (cf. ecarts.py). Vide =
    # controle lu par le modele seul.
    evaluation: list[dict] = field(default_factory=list)
    # Etape 2.6 : parametres du playbook de correction (valeurs de la fiche).
    parametres: dict = field(default_factory=dict)
    # Pas de playbook : raison ecrite (correction manuelle).
    sans_playbook: str = ""


@dataclass
class CommandeObserv:
    commande: str
    but: str = ""
    lecture: str = ""                # ce qu'on lit dans la sortie
    # Commande propre a une famille de systemes (debian, rhel, alpine...),
    # choisie selon le contexte detecte (etape 2.4.2). `commande` = defaut.
    variantes: dict[str, str] = field(default_factory=dict)

    def toutes_les_commandes(self) -> list[str]:
        return [self.commande, *self.variantes.values()]


@dataclass
class Source:
    origine: str = "manuel"          # manuel | complianceascode | stig | ...
    regle: str | None = None         # identifiant de la regle dans la source
    version: str | None = None       # version de la source importee
    url: str | None = None


@dataclass
class Fiche:
    id: str
    titre: str
    domaine: str                     # cf. schema.DOMAINES
    resume: str = ""
    mots_cles: list[str] = field(default_factory=list)
    observer: list[CommandeObserv] = field(default_factory=list)
    controles: list[Controle] = field(default_factory=list)
    pieges: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)   # texte libre (v1)
    # --- schema v2 (etape 2.4.1) : contexte, tracabilite, cycle de vie ---
    schema: int = 1
    version: int = 1                 # incrementee a chaque changement de fond
    etat: str = "verifie"            # brouillon | verifie | obsolete
    verifie_le: str | None = None    # AAAA-MM-JJ (relecture)
    relu_par: str | None = None      # qui a relu (humain, ou IA par delegation)
    teste_sur: list[str] = field(default_factory=list)   # ubuntu:22.04...
    applicable: dict[str, list[str]] = field(default_factory=dict)
    # Taxonomie (etape 2 du pipeline) : theme, type_controle, niveaux.
    taxonomie: dict = field(default_factory=dict)
    source: Source = field(default_factory=Source)
    referentiels: list[Referentiel] = field(default_factory=list)

    def pour_le_modele(self, contexte=None) -> str:
        """Rendu compact injecte dans le prompt : le savoir utile, sans bruit.
        Avec un contexte connu, seule la variante de sa famille est montree
        (le modele ne choisit pas entre ufw et firewall-cmd : le code l'a
        fait)."""
        from brain.contexte import commande_pour

        etat = " [brouillon importe, non relu]" if self.etat == "brouillon" else ""
        lignes = [f"FICHE « {self.titre} » (domaine : {self.domaine}){etat}"]
        if self.resume:
            lignes.append(self.resume.strip())
        if self.observer:
            lignes.append("Commandes de lecture verifiees :")
            for c in self.observer:
                lignes.append(f"  $ {commande_pour(c, contexte)}")
                if c.but:
                    lignes.append(f"    but : {c.but}")
                if c.lecture:
                    lignes.append(f"    a lire : {c.lecture}")
        if self.controles:
            lignes.append("Points de controle :")
            for c in self.controles:
                bornes = []
                if c.bon:
                    bornes.append(f"bon = {c.bon}")
                if c.mauvais:
                    bornes.append(f"mauvais = {c.mauvais}")
                b = f" ({', '.join(bornes)})" if bornes else ""
                g = f" [{c.gravite}]" if c.gravite else ""
                lignes.append(f"  - {c.controle}{b}{g}")
                if c.action:
                    lignes.append(f"    action : {c.action}")
        if self.pieges:
            lignes.append("Pieges :")
            for p in self.pieges:
                lignes.append(f"  ! {p}")
        if self.referentiels:
            lignes.append("Referentiels : " + " ; ".join(
                f"{r.nom} {r.document}" + (f" ({r.ref})" if r.ref else "")
                for r in self.referentiels))
        return "\n".join(lignes)


# --------------------------------------------------------------------------- #
# Chargement
# --------------------------------------------------------------------------- #
def _dossier_fiches() -> Path:
    return Path(__file__).resolve().parent / "fiches"


def _referentiels(liste) -> list[Referentiel]:
    return [Referentiel(**r) for r in (liste or [])]


def _fiche_depuis_yaml(donnees: dict) -> Fiche:
    controles = []
    for c in donnees.get("controles", []):
        c = dict(c)
        c["referentiels"] = _referentiels(c.get("referentiels"))
        controles.append(Controle(**c))
    verifie_le = donnees.get("verifie_le")
    return Fiche(
        id=donnees["id"],
        titre=donnees.get("titre", donnees["id"]),
        domaine=donnees.get("domaine", "divers"),
        resume=donnees.get("resume", ""),
        mots_cles=[str(m).lower() for m in donnees.get("mots_cles", [])],
        observer=[CommandeObserv(**c) for c in donnees.get("observer", [])],
        controles=controles,
        pieges=list(donnees.get("pieges", [])),
        references=list(donnees.get("references", [])),
        schema=int(donnees.get("schema", 1)),
        version=int(donnees.get("version", 1)),
        etat=donnees.get("etat", "verifie"),
        # YAML lit 2026-09-17 comme une date : on garde le texte ISO.
        verifie_le=str(verifie_le) if verifie_le else None,
        relu_par=donnees.get("relu_par"),
        teste_sur=list(donnees.get("teste_sur", [])),
        applicable={k: list(v) for k, v in
                    (donnees.get("applicable") or {}).items()},
        taxonomie=dict(donnees.get("taxonomie") or {}),
        source=Source(**(donnees.get("source") or {})),
        referentiels=_referentiels(donnees.get("referentiels")),
    )


def lire_fiches() -> list[tuple[Path, dict | None, Exception | None]]:
    """Lit les YAML bruts (chemin, donnees, erreur de lecture)."""
    resultats = []
    for chemin in sorted(_dossier_fiches().rglob("*.yaml")):
        try:
            resultats.append(
                (chemin, yaml.safe_load(chemin.read_text(encoding="utf-8")),
                 None))
        except Exception as exc:  # noqa: BLE001
            resultats.append((chemin, None, exc))
    return resultats


@lru_cache(maxsize=1)
def toutes() -> list[Fiche]:
    """Charge les fiches VALIDES une fois. Une fiche qui echoue a la
    validation (schema.valider) est ecartee et signalee, jamais silencieuse :
    une commande d'observation qui ecrirait ne doit jamais atteindre le
    modele. Les fiches obsoletes sont chargees (tracabilite) mais jamais
    injectees (cf. recuperer)."""
    import logging

    from .schema import valider

    journal = logging.getLogger("sentinelle")
    fiches: list[Fiche] = []
    for chemin, donnees, exc in lire_fiches():
        if exc is not None:
            journal.warning("Fiche illisible %s : %s", chemin.name, exc)
            continue
        erreurs, _ = valider(donnees, chemin)
        if erreurs:
            journal.warning("Fiche invalide %s ecartee : %s", chemin.name,
                            " | ".join(erreurs))
            continue
        fiches.append(_fiche_depuis_yaml(donnees))
    return fiches


def actives() -> list[Fiche]:
    """Fiches utilisables pour un audit (hors obsoletes)."""
    return [f for f in toutes() if f.etat != "obsolete"]


# --------------------------------------------------------------------------- #
# Recuperation (etape 2.2) : trouver la ou les fiches pertinentes.
#
# Deterministe, sans modele. On score chaque fiche sur PLUSIEURS champs (pas
# seulement les mots-cles), on applique un SEUIL pour ne jamais injecter une
# fiche a peine liee, on rend un top-N sous un budget de taille, et on garde la
# CONTINUITE : une relance sans mot-cle fort (« et le 5432 ? ») conserve la
# fiche du tour precedent.
# --------------------------------------------------------------------------- #
SEUIL = 4          # score minimal pour injecter une fiche (un mot-cle = 4)
BUDGET_CAR = 6000  # taille max cumulee du savoir injecte (protege le prompt)

# Mots trop courants pour peser dans un score.
_VIDES = {"des", "les", "une", "sur", "est", "sont", "pour", "avec", "dans",
          "que", "qui", "pas", "mon", "ton", "son", "mes", "aux", "par", "ceci",
          "cela", "quel", "quels", "quelle", "quelles", "verifie", "verifier",
          "audit", "auditer", "regarde", "regarder", "check"}


def _normaliser(texte: str) -> str:
    texte = unicodedata.normalize("NFD", texte.lower())
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return texte


def _jetons(texte: str) -> set[str]:
    return {m for m in re.findall(r"[a-z0-9]{3,}", _normaliser(texte))
            if m not in _VIDES}


def _mots_fiche(f: Fiche) -> dict[str, set[str]]:
    """Jetons de la fiche, regroupes par champ (pour ponderer)."""
    cles: set[str] = set()
    for mc in f.mots_cles:
        cles |= _jetons(mc)
    controles: set[str] = set()
    for c in f.controles:
        controles |= _jetons(c.controle)
    return {
        "cles": cles,
        "titre": _jetons(f.titre),
        "domaine": _jetons(f.domaine),
        "controles": controles,
        "resume": _jetons(f.resume),
    }


def scorer(requete: str) -> list[tuple[int, Fiche]]:
    """Score chaque fiche pour la requete, du meilleur au moins bon. Poids :
    mot-cle 4, titre 3, domaine 3, point de controle 2, resume 1."""
    mots = _jetons(requete)
    if not mots:
        return []
    poids = {"cles": 4, "titre": 3, "domaine": 3, "controles": 2, "resume": 1}
    resultats: list[tuple[int, Fiche]] = []
    for f in actives():
        champs = _mots_fiche(f)
        score = sum(poids[ch] * len(champs[ch] & mots) for ch in poids)
        if score:
            resultats.append((score, f))
    # A score egal, la fiche la plus SPECIFIQUE d'abord (moins de mots-cles :
    # /tmp avant /var/tmp), puis l'id pour un ordre stable.
    resultats.sort(key=lambda s: (-s[0], len(s[1].mots_cles), s[1].id))
    return resultats


def chercher(requete: str, n: int = 2, seuil: int = SEUIL) -> list[Fiche]:
    """Les n fiches dont le score atteint le seuil (les mieux notees d'abord)."""
    return [f for s, f in scorer(requete) if s >= seuil][:n]


def recuperer(requete: str, precedent: Fiche | None = None, n: int = 2,
              contexte=None, niveau: tuple | None = None
              ) -> tuple[list[Fiche], str]:
    """Point d'entree de la recuperation. Rend (fiches, explication).

    Moteur : brain.bibliotheque.recherche (etape 3 du pipeline) — aiguillage
    d'intention vers un theme, synonymes, index SQLite FTS5, filtres stricts
    (systeme, services, niveau de conformite si fourni).
    Continuite : si rien ne ressort mais qu'une fiche etait active au tour
    precedent (et s'applique toujours), on la garde.
    """
    from brain.contexte import applicable

    from . import recherche
    from .taxonomie import THEMES

    trouvailles, themes, ecartees = recherche.chercher(
        requete, contexte=contexte, niveau=niveau, n=n)
    note = (f" ; ecartee(s) pour ce systeme : {' ; '.join(ecartees)}"
            if ecartees else "")
    if trouvailles:
        orientation = (" [theme : " + ", ".join(THEMES[t][0] for t in themes
                                                  if t in THEMES) + "]"
                       if themes else "")
        details = ", ".join(f"{t.fiche.titre} ({t.score:.0f})" for t in trouvailles)
        return ([t.fiche for t in trouvailles],
                f"correspondance : {details}{orientation}{note}")
    if precedent is not None and applicable(precedent, contexte)[0]:
        return [precedent], f"continuite : on reste sur « {precedent.titre} »"
    return [], f"aucune fiche pertinente{note}"


def savoir_pour(requete: str, n: int = 2, precedent: Fiche | None = None) -> str:
    """Texte a injecter pour une requete, sous le budget de taille. Vide si
    rien. (Compat : ancien appel `savoir_pour(requete, n)`.)"""
    fiches, _ = recuperer(requete, precedent=precedent, n=n)
    return assembler(fiches)


def assembler(fiches: list[Fiche], contexte=None) -> str:
    """Concatene les fiches jusqu'au budget de caracteres."""
    morceaux, total = [], 0
    for f in fiches:
        bloc = f.pour_le_modele(contexte)
        if total + len(bloc) > BUDGET_CAR and morceaux:
            break
        morceaux.append(bloc)
        total += len(bloc)
    return "\n\n".join(morceaux)
