"""Verification des commandes proposees contre les fiches (etape 2.3).

Un petit modele invente volontiers une option qui « sonne juste » (`ss -tulnpx`,
`openssl s_client -tlsextdebug2`). Ici, le CODE compare chaque commande aux
commandes verifiees de la bibliotheque -- jamais le modele.

Pour chaque segment (`|`, `;`, `&&`...) on isole le binaire reel (sudo saute),
sa sous-commande (openssl s_client, systemctl is-active...) et ses options, puis
on les confronte a l'union des commandes de reference pour ce binaire.

Verdicts, du plus preoccupant au moins preoccupant :

  NON_VERIFIE -- outil connu des fiches, mais option ou sous-commande absente :
                 probable invention. Le terminal demande une correction.
  HORS_FICHE  -- outil qu'aucune fiche ne documente : rien a comparer.
  CONFORME    -- outil, sous-commande et options tous presents dans une fiche.
  USUEL       -- uniquement des utilitaires courants (cat, grep, tail...).

Ce n'est PAS un garde-fou de securite (c'est `brain.garde` qui decide ce qui
s'execute) : c'est un controle de fiabilite. Deterministe, sans reseau.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from enum import Enum

from brain.garde.commandes import _binaire_reel

from . import Fiche, actives


class STATUT(str, Enum):
    NON_VERIFIE = "non_verifie"
    HORS_FICHE = "hors_fiche"
    CONFORME = "conforme"
    USUEL = "usuel"


_RANG = {STATUT.USUEL: 0, STATUT.CONFORME: 1, STATUT.HORS_FICHE: 2,
         STATUT.NON_VERIFIE: 3}

# Utilitaires de lecture/filtrage courants : leurs options ne sont pas
# comparees (standard, sans risque d'invention qui fausse un audit).
USUELS = {
    "echo", "printf", "cat", "less", "more", "head", "tail", "grep", "egrep",
    "fgrep", "awk", "sed", "sort", "uniq", "cut", "tr", "wc", "ls", "stat",
    "file", "true", "false", "test", "[",
}

# Binaires dont le premier argument non-option est une sous-commande.
MULTI_COMMANDES = {
    "openssl", "systemctl", "fail2ban-client", "ip", "docker", "kubectl",
    "git", "apt", "dnf", "yum", "ufw", "firewall-cmd", "nft",
}

# Binaires dont les options longues n'ont qu'un tiret (-servername, -noout) :
# on ne les decoupe jamais en lettres.
TIRET_SIMPLE_LONG = {"openssl", "find", "keytool", "xmllint", "iptables",
                     "ip6tables"}

# Mots-cles de shell en tete de segment (boucles, conditions).
_MOTS_SHELL = {"do", "then", "else", "elif", "done", "fi", "{", "}", "!"}
_BOUCLES = {"for", "while", "until", "if", "case"}
_OPERATEURS = {";", "|", "||", "&&", "&", ";;"}


@dataclass
class Verification:
    statut: STATUT
    ecarts: list[str] = field(default_factory=list)   # « ss : option -x »
    fiches: list[str] = field(default_factory=list)   # ids des fiches citees
    references: list[str] = field(default_factory=list)  # commandes a proposer

    @property
    def motif(self) -> str:
        if self.statut is STATUT.CONFORME:
            return "conforme a la fiche " + ", ".join(self.fiches)
        if self.statut is STATUT.USUEL:
            return "utilitaires courants, rien a verifier"
        if self.statut is STATUT.HORS_FICHE:
            return ("outil non documente par la bibliotheque : "
                    + ", ".join(self.ecarts))
        return "absent des fiches : " + "; ".join(self.ecarts)

    def message_correction(self) -> str:
        """Texte renvoye au modele pour qu'il se corrige (une seule fois)."""
        refs = "\n".join(f"  $ {r}" for r in self.references)
        return (
            "[verification] Ta commande utilise des elements absents des fiches "
            f"verifiees ({'; '.join(self.ecarts)}). N'invente pas d'option. "
            "Reprends avec une commande de la fiche (remplace DOMAINE par la "
            "vraie valeur) ou explique en une phrase pourquoi cette option est "
            "necessaire.\nCommandes verifiees pour cet outil :\n" + refs
        )


# --------------------------------------------------------------------------- #
# Analyse d'une ligne de commande
# --------------------------------------------------------------------------- #
@dataclass
class _Segment:
    binaire: str
    sous_commande: str | None
    options: list[str]


def _options(args: list[str]) -> list[str]:
    opts = []
    for a in args:
        if len(a) < 2 or a == "--" or re.fullmatch(r"-\d+", a):
            continue
        if a[0] == "-" or (a[0] == "+" and a[1].isalpha()):   # +short (dig)
            opts.append(a.split("=", 1)[0])
    return opts


def _segments(commande: str) -> list[_Segment] | None:
    try:
        lex = shlex.shlex(commande, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        jetons = list(lex)
    except ValueError:
        return None
    bruts: list[list[str]] = [[]]
    for t in jetons:
        if t in _OPERATEURS:
            bruts.append([])
        elif t not in {"(", ")"}:
            bruts[-1].append(t)

    segments = []
    for s in bruts:
        while s and s[0] in _MOTS_SHELL:
            s = s[1:]
        if not s or s[0] in _BOUCLES:
            continue          # « for p in ... » : pas une commande a verifier
        binaire, args = _binaire_reel(s)
        base = binaire.rsplit("/", 1)[-1]
        if not base:
            continue
        sous = None
        if base in MULTI_COMMANDES:
            sous = next((a for a in args if not a.startswith(("-", "+"))), None)
        segments.append(_Segment(base, sous, _options(args)))
    return segments


# --------------------------------------------------------------------------- #
# Index des commandes de reference
# --------------------------------------------------------------------------- #
@dataclass
class _Reference:
    fiche: str
    commande: str
    sous_commande: str | None
    options: list[str]


def _indexer(fiches: tuple[Fiche, ...]) -> dict[str, list[_Reference]]:
    index: dict[str, list[_Reference]] = {}
    for f in fiches:
        for obs in f.observer:
            for commande in obs.toutes_les_commandes():   # defaut + variantes
                boucles = _variables_de_boucle(commande)
                for seg in _segments(commande) or []:
                    index.setdefault(seg.binaire, []).append(
                        _Reference(f.id, commande, seg.sous_commande,
                                   _deplier(seg.options, boucles)))
    return index


def _variables_de_boucle(commande: str) -> dict[str, list[str]]:
    """« for p in tls1 tls1_2; do » -> {"p": ["tls1", "tls1_2"]}."""
    return {m.group(1): m.group(2).split()
            for m in re.finditer(r"\bfor\s+(\w+)\s+in\s+([^;]+);", commande)}


def _deplier(options: list[str], boucles: dict[str, list[str]],
             garder_inconnues: bool = False) -> list[str]:
    """Remplace -$p par ses valeurs reelles (-tls1, -tls1_2...). Dans une
    fiche, une variable inconnue n'autorise rien (pas de joker) ; dans une
    commande proposee, elle est gardee telle quelle pour etre signalee."""
    sortie = []
    for o in options:
        m = re.fullmatch(r"(-+)\$\{?(\w+)\}?", o)
        if m and (m.group(2) in boucles or not garder_inconnues):
            sortie += [m.group(1) + v for v in boucles.get(m.group(2), [])]
        else:
            sortie.append(o)
    return sortie


_INDEX: dict[tuple[int, ...], dict[str, list[_Reference]]] = {}


def _index_cache(fiches: tuple[Fiche, ...]) -> dict[str, list[_Reference]]:
    # Les fiches sont chargees une fois par processus (toutes() en cache) :
    # l'identite des objets suffit comme cle.
    cle = tuple(id(f) for f in fiches)
    if cle not in _INDEX:
        _INDEX[cle] = _indexer(fiches)
    return _INDEX[cle]


def _lettres(option: str) -> set[str] | None:
    """-tlnp -> {t,l,n,p}. None si ce n'est pas un groupe d'options courtes."""
    if re.fullmatch(r"-[A-Za-z]+", option):
        return set(option[1:])
    return None


def _ecart_option(option: str, binaire: str, refs: list[_Reference]
                  ) -> str | None:
    """None si l'option est documentee, sinon l'ecart lisible."""
    brutes = {o for r in refs for o in r.options}
    if option in brutes:
        return None
    lettres = None if binaire in TIRET_SIMPLE_LONG else _lettres(option)
    if lettres is None:
        return f"option {option}"
    connues: set[str] = set()
    for o in brutes:
        connues |= _lettres(o) or set()
    inconnues = sorted(lettres - connues)
    if not inconnues:
        return None               # -ltn : lettres toutes documentees (-tlnp)
    if len(option) == 2:
        return f"option {option}"
    return f"option {option} (-{''.join(inconnues)} inconnue)"


def verifier(commande: str, fiches: list[Fiche] | None = None) -> Verification:
    """Compare une commande aux fiches (toute la bibliotheque par defaut)."""
    fiches_t = tuple(fiches if fiches is not None else actives())
    index = _index_cache(fiches_t)
    commande = (commande or "").strip()
    segments = _segments(commande)
    if segments is None:
        return Verification(STATUT.HORS_FICHE, ecarts=["commande non analysable"])
    # Une boucle proposee est depliee aussi : chaque valeur est verifiee
    # (-tls1_4 dans un « for » reste une invention). Variable inconnue = ecart.
    boucles = _variables_de_boucle(commande)
    for seg in segments:
        seg.options = _deplier(seg.options, boucles, garder_inconnues=True)

    pire = STATUT.USUEL
    ecarts: list[str] = []
    cites: list[str] = []
    references: list[str] = []

    def monter(statut: STATUT):
        nonlocal pire
        if _RANG[statut] > _RANG[pire]:
            pire = statut

    for seg in segments:
        refs = index.get(seg.binaire)
        if not refs:
            if seg.binaire not in USUELS:
                monter(STATUT.HORS_FICHE)
                ecarts.append(seg.binaire)
            continue
        if seg.binaire in USUELS and seg.binaire not in MULTI_COMMANDES:
            continue          # grep/tail documentes mais options non comparees

        manques = []
        if seg.sous_commande is not None:
            sous_connues = {r.sous_commande for r in refs}
            if seg.sous_commande not in sous_connues:
                manques.append(f"sous-commande {seg.sous_commande}")
            else:
                refs = [r for r in refs if r.sous_commande == seg.sous_commande]
        for o in seg.options:
            ecart = _ecart_option(o, seg.binaire, refs)
            if ecart:
                manques.append(ecart)

        for r in refs:
            if r.fiche not in cites:
                cites.append(r.fiche)
        if manques:
            monter(STATUT.NON_VERIFIE)
            ecarts.append(f"{seg.binaire} : " + ", ".join(manques))
            for r in index[seg.binaire]:
                if r.commande not in references:
                    references.append(r.commande)
        else:
            monter(STATUT.CONFORME)

    # Un HORS_FICHE ne doit pas masquer les ecarts d'un outil connu.
    if pire is not STATUT.NON_VERIFIE:
        references = []
    if pire is STATUT.NON_VERIFIE:
        ecarts = [e for e in ecarts if " : " in e]
    return Verification(pire, ecarts=ecarts, fiches=cites, references=references)
