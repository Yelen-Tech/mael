"""Importeur ComplianceAsCode -> fiches v2 (Linux Ubuntu/Debian, ANSSI + CIS).

Source : https://github.com/ComplianceAsCode/content (BSD-3-Clause), clonee
dans `data/sources/complianceascode` a une version etiquetee (ex. v0.1.82).

Perimetre :
  - toutes les regles de linux_os/guide ;
  - gabarits pris en charge : `sshd_lineinfile` (ici) et ceux de
    `gabarits_cac.GABARITS` (sysctl, droits/proprietaires de fichiers,
    paquets, services, modules noyau, montages, compilation du noyau,
    arguments de demarrage) ;
  - regles citees par au moins un referentiel retenu (CIS Ubuntu 22.04 /
    24.04, CIS Debian 12, ANSSI-BP-028). Une regle citee par aucun n'est pas
    importee : on n'importe pas les regles contradictoires hors profil
    (ex. sshd_enable_x11_forwarding).

    python -m brain.bibliotheque.importeurs.complianceascode \\
        --source ../data/sources/complianceascode [--sortie DOSSIER] [--simuler]

Idempotent : relancer sur la meme version ne change rien. Une fiche deja
relue (etat != brouillon) n'est jamais ecrasee : elle est signalee « a revoir »
si la source a change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .. import taxonomie as taxo
from . import gabarits_cac, rendu_jinja

DOSSIER_SSH = "linux_os/guide/services/ssh"
DOSSIER_REGLES = "linux_os/guide"

# Referentiels retenus : fichier de controles -> (nom, systeme applicable).
REFERENTIELS = {
    "cis_ubuntu2204": ("CIS", "ubuntu==22.04"),
    "cis_ubuntu2404": ("CIS", "ubuntu==24.04"),
    "cis_debian12": ("CIS", "debian==12"),
    "anssi": ("ANSSI", None),          # guide generique GNU/Linux
}

GRAVITES = {"low": "faible", "medium": "moyenne", "high": "elevee",
            "unknown": "moyenne"}

GABARITS_SUPPORTES = {"sshd_lineinfile", *gabarits_cac.GABARITS}

# Dossier ComplianceAsCode -> domaine de fiche (a defaut du gabarit).
DOMAINES_DOSSIER = {
    "services/ssh": "acces", "system/accounts": "comptes",
    "system/permissions": "fichiers", "system/network": "reseau",
    "system/software": "paquets", "system/logging": "journaux",
    "auditing": "journaux", "system/kernel_build_config": "noyau",
    "system/bootloader-grub2": "systeme", "system/selinux": "systeme",
    "system/apparmor": "systeme", "services": "services",
}

RELECTURES = Path(__file__).with_name("relectures_complianceascode.yaml")
RECETTES = Path(__file__).with_name("recettes_cac.yaml")
RISQUES_FR = Path(__file__).with_name("risques_fr.yaml")

_NOTE_RECETTE = ("Recette Sentinelle : regle ecrite a la main dans "
                 "ComplianceAsCode (sans gabarit) ; commande et critere "
                 "rediges d'apres sa description et sa verification (OCIL). "
                 "A relire en priorite.")


def lire_recettes(chemin: Path = RECETTES) -> dict:
    if not chemin.exists():
        return {}
    return (yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}).get(
        "recettes") or {}


# {var:NOM} = valeur du premier referentiel qui la fixe ; {union:NOM} = union
# ordonnee des listes (separees par des virgules) de TOUS les referentiels :
# une fiche vaut pour Ubuntu 22.04, 24.04 et Debian 12, un algorithme fort
# admis par l'un ne doit pas etre signale faible sur un autre.
_REF_VARIABLE = re.compile(r"\{((?:var|union):[a-z0-9_]+)\}")


def resoudre_recette(valeur, resoudre):
    """Remplace « {var:NOM} » / « {union:NOM} » par la valeur du referentiel. Leve KeyError
    si une variable est introuvable (la regle est alors ignoree)."""
    if isinstance(valeur, dict):
        return {k: resoudre_recette(v, resoudre) for k, v in valeur.items()}
    if isinstance(valeur, list):
        return [resoudre_recette(v, resoudre) for v in valeur]
    if not isinstance(valeur, str) or not _REF_VARIABLE.search(valeur):
        return valeur

    def _une(m):
        v = resoudre(m.group(1))
        if v is None:
            raise KeyError(m.group(1))
        return str(v)
    entiere = _REF_VARIABLE.fullmatch(valeur)
    if entiere:
        v = resoudre(entiere.group(1))
        if v is None:
            raise KeyError(entiere.group(1))
        return v
    return _REF_VARIABLE.sub(_une, valeur)

CONFIG_SSHD = "/etc/ssh/sshd_config"


# --------------------------------------------------------------------------- #
# Lecture de la source
# --------------------------------------------------------------------------- #
def _sans_macros(texte: str) -> str:
    """rule.yml contient des macros Jinja ({{{ ... }}}, {{% ... %}}). On retire
    les lignes qui n'en sont faites et on neutralise les macros en ligne."""
    lignes = []
    for ligne in texte.splitlines():
        brut = ligne.strip()
        if brut.startswith(("{{{", "{{%", "{{#")):
            continue
        lignes.append(re.sub(r"\{\{\{.*?\}\}\}", "", ligne))
    return "\n".join(lignes)


def _texte_propre(texte: str) -> str:
    texte = re.sub(r"<[^>]+>", "", texte or "")
    return " ".join(texte.split())


@dataclass
class Regle:
    id: str
    titre: str
    gravite: str
    justification: str
    gabarit: str | None
    vars: dict
    chemin: Path
    # Regle a conditions Jinja dont le gabarit differe selon le produit :
    # {produit: (gabarit, vars)}. Vide = identique partout.
    rendus: dict = field(default_factory=dict)
    # « platform » de la source (ex. « x86_64_arch ») : restreint la regle a
    # une architecture. Vide = toutes.
    plateforme: str = ""


def _lire_rule_yml(texte: str, props: dict | None) -> dict:
    return yaml.safe_load(rendu_jinja.rendre(texte, props)) or {}


def lire_regles(source: Path) -> list[Regle]:
    """Une regle par rule.yml. Les conditions Jinja sont evaluees pour chaque
    produit vise (rendu_jinja) ; la regle porte le rendu du premier produit,
    et `rendus` si le gabarit change d'un produit a l'autre."""
    regles = []
    for chemin in sorted((source / DOSSIER_REGLES).rglob("rule.yml")):
        texte = chemin.read_text(encoding="utf-8")
        # Conditions ({{% %}}) ou proprietes du produit ({{{ nom }}}) :
        # rendu par produit.
        produits = (rendu_jinja.PRODUITS if "{{%" in texte or "{{{" in texte
                    else (None,))
        rendus = {}
        try:
            for produit in produits:
                props = (rendu_jinja.proprietes(source, produit)
                         if produit else {})
                rendus[produit] = _lire_rule_yml(texte, props)
        except yaml.YAMLError:
            # Macros Jinja trop complexes pour etre neutralisees : la regle
            # est ecartee (et comptee), jamais devinee.
            regles.append(Regle(chemin.parent.name, "", "moyenne", "",
                                "(rule.yml illisible sans rendu Jinja)", {},
                                chemin))
            continue
        donnees = next(iter(rendus.values()))
        gabarits = {p: ((d.get("template") or {}).get("name"),
                        (d.get("template") or {}).get("vars") or {})
                    for p, d in rendus.items()}
        gabarit = (donnees.get("template") or {})
        inconnues = sorted(set(re.findall(
            re.escape(rendu_jinja.INCONNUE) + r"(\w+)", repr(gabarits))))
        if inconnues:
            gabarit = {"name": "(variable du produit inconnue : "
                               + ", ".join(inconnues) + ")"}
            gabarits = {}
        regles.append(Regle(
            id=chemin.parent.name,
            titre=str(donnees.get("title", "")).strip(),
            gravite=GRAVITES.get(str(donnees.get("severity", "unknown")),
                                 "moyenne"),
            justification=_texte_propre(donnees.get("rationale", "")),
            gabarit=gabarit.get("name"),
            vars=gabarit.get("vars") or {},
            chemin=chemin,
            rendus=(gabarits if len({repr(g) for g in gabarits.values()}) > 1
                    else {}),
            plateforme=str(donnees.get("platform") or "").strip(),
        ))
    return regles


def _rendu_pour(regle: Regle, cites) -> Regle | str:
    """Si le gabarit depend du produit, prendre celui des systemes qui citent
    la regle (le guide ANSSI, generique, suit le 1er produit). Divergence
    entre systemes cites -> regle ignoree, jamais devinee."""
    if not regle.rendus:
        return regle
    produits = sorted({gabarits_cac.PRODUITS[r.systeme] for r in cites
                       if r.systeme in gabarits_cac.PRODUITS})
    produits = produits or [rendu_jinja.PRODUITS[0]]
    noms = {regle.rendus[p][0] for p in produits}
    if len({(n or "").removesuffix("_guard_var") for n in noms}) == 1 and             len(noms) > 1:
        # Conditionnel sur un systeme, inconditionnel sur un autre : on garde
        # la version conditionnelle (la plus prudente).
        noms = {n for n in noms if n.endswith("_guard_var")}
        produits = [p for p in produits
                    if regle.rendus[p][0] in noms] or produits
    if len(noms) > 1:
        return ("gabarit different selon le systeme ("
                + ", ".join(f"{p}={regle.rendus[p][0]}" for p in produits) + ")")
    # Meme gabarit, valeurs differentes (ex. groupe adm sur Ubuntu, root
    # ailleurs) : on les garde par produit (cle@produit), comme la source.
    vars_ = dict(regle.rendus[produits[0]][1])
    for cle in {c for p in produits for c in regle.rendus[p][1]}:
        valeurs = {p: regle.rendus[p][1].get(cle) for p in produits}
        if len({repr(v) for v in valeurs.values()}) > 1:
            for p, v in valeurs.items():
                vars_[f"{cle}@{p}"] = v
    return Regle(regle.id, regle.titre, regle.gravite, regle.justification,
                 noms.pop(), vars_, regle.chemin, plateforme=regle.plateforme)


@dataclass
class Renvoi:
    nom: str
    document: str
    ref: str
    systeme: str | None


_NIVEAUX_ANSSI = {"minimal": "minimal", "intermediary": "intermediaire",
                  "enhanced": "renforce", "high": "eleve"}


def _niveau(nom: str, niveaux) -> str:
    """Niveau du controle tel que declare par la source : CIS 1/2 (le 2 peut
    gener l'exploitation), ANSSI minimal a eleve."""
    niveaux = [str(n) for n in (niveaux or [])]
    if nom == "CIS":
        serveur = [n for n in niveaux if n.endswith("_server")] or niveaux
        chiffres = sorted({n[1] for n in serveur if re.match(r"l\d", n)})
        return f"niveau {chiffres[0]}" if chiffres else ""
    if nom == "ANSSI" and niveaux:
        return "niveau " + _NIVEAUX_ANSSI.get(niveaux[0], niveaux[0])
    return ""


def _parcourir_controles(controles, chemin_doc, nom, systeme, renvois,
                         variables, niveaux_parent=None):
    for c in controles or []:
        niveaux = c.get("levels") or niveaux_parent
        niveau = _niveau(nom, niveaux)
        ref = f"{c.get('id')} ({niveau})" if niveau else str(c.get("id"))
        for element in c.get("rules") or []:
            element = str(element)
            if "=" in element:
                var, val = element.split("=", 1)
                variables.setdefault(var.strip(), val.strip())
            else:
                renvois.setdefault(element, []).append(
                    Renvoi(nom, chemin_doc, ref, systeme))
        _parcourir_controles(c.get("controls"), chemin_doc, nom, systeme,
                             renvois, variables, niveaux)


def lire_referentiels(source: Path):
    """(renvois par regle, variables par fichier de controles)."""
    renvois: dict[str, list[Renvoi]] = {}
    variables: dict[str, dict[str, str]] = {}
    for fichier, (nom, systeme) in REFERENTIELS.items():
        chemin = source / "controls" / f"{fichier}.yml"
        if not chemin.exists():
            continue
        d = yaml.safe_load(chemin.read_text(encoding="utf-8"))
        document = f"{d.get('policy', fichier)} v{d.get('version', '?')}"
        vars_fichier: dict[str, str] = {}
        _parcourir_controles(d.get("controls"), document, nom, systeme,
                             renvois, vars_fichier)
        variables[fichier] = vars_fichier
    return renvois, variables


@lru_cache(maxsize=4)
def _fichiers_variables(source: Path) -> dict[str, Path]:
    """Index nom -> fichier .var, construit une fois (catalogue volumineux)."""
    return {c.stem: c for c in (source / "linux_os").rglob("*.var")}


def _options_variable(source: Path, var: str) -> dict:
    chemin = _fichiers_variables(source).get(var)
    if chemin is None:
        return {}
    try:
        return (yaml.safe_load(_sans_macros(chemin.read_text(encoding="utf-8")))
                or {}).get("options") or {}
    except yaml.YAMLError:
        return {}


def resoudre_variable(source: Path, var: str, selecteur: str | None) -> str | None:
    """Valeur concrete d'une variable XCCDF (5_minutes -> 300)."""
    if selecteur is None:
        return None
    for cle, valeur in _options_variable(source, var).items():
        if str(cle) == selecteur:
            return str(valeur)
    return selecteur          # deja une valeur (ex. 10:30:60)


def valeur_par_defaut(source: Path, var: str) -> str | None:
    """Valeur « default » d'une variable quand aucun referentiel ne la fixe."""
    options = _options_variable(source, var)
    if "default" not in options:
        return None
    defaut = options["default"]
    return str(options.get(str(defaut), defaut))


def version_source(source: Path) -> str:
    try:
        r = subprocess.run(["git", "-C", str(source), "describe", "--tags"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().lstrip("v")
    except Exception:  # noqa: BLE001
        pass
    return "inconnue"


# --------------------------------------------------------------------------- #
# Construction des fiches
# --------------------------------------------------------------------------- #
def _mots(parametre: str) -> list[str]:
    morceaux = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", parametre)
    return [m.lower() for m in morceaux if len(m) >= 4]


def lexique() -> dict:
    """Titres et mots-cles francais par directive (lexique_sshd.yaml)."""
    chemin = Path(__file__).with_name("lexique_sshd.yaml")
    return yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}


@lru_cache(maxsize=1)
def risques_fr(chemin: Path = RISQUES_FR) -> dict:
    """Risque traduit en francais et relu, par regle (risques_fr.yaml).
    Seul le texte explicatif est traduit : valeurs, gravites et references
    viennent toujours de la source. Une regle citee deux fois est refusee."""
    if not chemin.exists():
        return {}
    donnees = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
    par_regle: dict[str, str] = {}
    for entree in donnees.get("risques") or []:
        texte = " ".join(str(entree["risque"]).split())
        for regle in entree["regles"]:
            if regle in par_regle:
                raise ValueError(f"risques_fr.yaml : {regle} traduite deux fois")
            par_regle[regle] = texte
    return par_regle


def _id_fiche(regle_id: str) -> str:
    return "cac-" + regle_id.replace("_", "-").lower()


@dataclass
class Resultat:
    fiches: dict[str, dict] = field(default_factory=dict)
    ignorees: dict[str, str] = field(default_factory=dict)   # regle -> raison
    perimees: list[str] = field(default_factory=list)       # relecture a refaire


def construire(source: Path, version: str) -> Resultat:
    renvois, variables = lire_referentiels(source)
    recettes = lire_recettes()
    res = Resultat()
    for regle in lire_regles(source):
        recette = None
        if regle.rendus:
            rendue = _rendu_pour(regle, renvois.get(regle.id, []))
            if isinstance(rendue, str):
                res.ignorees[regle.id] = rendue
                continue
            regle = rendue
        # Regle ecartee a la relecture (avec ou sans gabarit) : raison ecrite.
        if (recettes.get(regle.id) or {}).get("ignorer"):
            res.ignorees[regle.id] = f"recette : {recettes[regle.id]['ignorer']}"
            continue
        if regle.gabarit and regle.gabarit.startswith("("):
            res.ignorees[regle.id] = regle.gabarit.strip("()")
            continue
        if regle.gabarit is None and regle.id in recettes                 and renvois.get(regle.id):
            recette = recettes[regle.id]
            try:
                vars_ = resoudre_recette(recette.get("vars") or {},
                                         _valeur_variable(source, variables))
            except KeyError as exc:
                res.ignorees[regle.id] = f"recette : variable {exc} introuvable"
                continue
            regle = Regle(regle.id, regle.titre, regle.gravite,
                          regle.justification, recette["gabarit"], vars_,
                          regle.chemin)
        condition = None
        if regle.gabarit and regle.gabarit.endswith("_guard_var"):
            # Ex. chrony OU timesyncd, ufw OU nftables : la regle ne vaut que
            # si l'exploitant a retenu cet outil. Importee pour le savoir,
            # SANS evaluation (le code ne juge pas un choix qu'il ignore).
            # installed/enabled : si l'outil EST retenu ; removed/disabled :
            # si l'outil N'EST PAS retenu (on retire ce qu'on n'a pas choisi).
            condition = (str(regle.vars.get("variable")),
                         str(regle.vars.get("value")),
                         regle.gabarit.split("_guard_var")[0].endswith(
                             ("_removed", "_disabled")))
            regle = Regle(regle.id, regle.titre, regle.gravite,
                          regle.justification,
                          regle.gabarit.removesuffix("_guard_var"),
                          regle.vars, regle.chemin)
        if regle.gabarit not in GABARITS_SUPPORTES:
            res.ignorees[regle.id] = ("sans gabarit (regle ecrite a la main)"
                                      if regle.gabarit is None else
                                      f"gabarit non pris en charge ({regle.gabarit})")
            continue
        cites = renvois.get(regle.id, [])
        if not cites:
            res.ignorees[regle.id] = "citee par aucun referentiel retenu"
            continue
        if regle.gabarit == "sshd_lineinfile":
            fiche = _fiche_sshd_lineinfile(source, version, regle, cites, variables)
            if fiche is None:
                res.ignorees[regle.id] = "valeur attendue introuvable"
                continue
        else:
            fiche = _fiche_generique(source, version, regle, cites, variables)
            if isinstance(fiche, str):
                res.ignorees[regle.id] = f"{regle.gabarit} : {fiche}"
                continue
        _garder_plateforme(fiche, regle.plateforme)
        if regle.id in gabarits_cac.GARDES_RELECTURE:
            garde = gabarits_cac.GARDES_RELECTURE[regle.id]
            for o in fiche["observer"]:
                if garde not in o["commande"]:
                    o["commande"] = garde + "; " + o["commande"]
        if regle.id in gabarits_cac.PIEGES_RELECTURE:
            fiche["pieges"].insert(0, gabarits_cac.PIEGES_RELECTURE[regle.id])
        if regle.id in gabarits_cac.CORRECTION_MANUELLE:
            raison, piege = gabarits_cac.CORRECTION_MANUELLE[regle.id]
            for c in fiche["controles"]:
                c.pop("playbook", None)
                c.pop("parametres", None)
                c["sans_playbook"] = raison
            fiche["pieges"].insert(0, piege)
        if condition:
            _conditionner(fiche, *condition)
        if recette and recette.get("condition"):
            c = recette["condition"]
            _conditionner(fiche, c["variable"], c["valeur"],
                          bool(c.get("inverse")))
        if recette and recette.get("playbook"):
            for c in fiche["controles"]:
                c["playbook"] = recette["playbook"]["id"]
                c["parametres"] = dict(recette["playbook"].get("parametres") or {})
                c.pop("sans_playbook", None)
        if recette and recette.get("sans_playbook"):
            for c in fiche["controles"]:
                if not c.get("playbook"):
                    c["sans_playbook"] = recette["sans_playbook"]
        _controler_liaisons(fiche)
        if recette:
            fiche["pieges"].append(_NOTE_RECETTE)
            if recette.get("theme"):
                fiche["taxonomie"]["theme"] = recette["theme"]
                fiche["domaine"] = taxo.THEMES[recette["theme"]][1]
        res.fiches[fiche["id"]] = fiche
    appliquer_relectures(res, lire_relectures())
    return res


def union_listes(valeurs) -> str:
    """Union ordonnee de listes « a,b,c » (premier vu, premier garde)."""
    union: list[str] = []
    for v in valeurs:
        union += [e for e in str(v).split(",") if e and e not in union]
    return ",".join(union)


def _valeur_variable(source, variables):
    def _resoudre(ref: str) -> str | None:
        # « NOM » (gabarits) ou « var:NOM » / « union:NOM » (recettes).
        mode, _, var = ref.rpartition(":")
        mode = mode or "var"
        if var in gabarits_cac.CORRECTIONS_VARIABLES:
            return gabarits_cac.CORRECTIONS_VARIABLES[var][0]
        trouvees = [resoudre_variable(source, var, variables.get(f, {}).get(var))
                    for f in REFERENTIELS]
        trouvees = [v for v in trouvees if v is not None]
        if not trouvees:
            return valeur_par_defaut(source, var)
        if mode == "var":
            return trouvees[0]
        return union_listes(trouvees)
    return _resoudre


def _domaine(source: Path, regle) -> str:
    rel = regle.chemin.parent.relative_to(source / DOSSIER_REGLES).as_posix()
    for prefixe in sorted(DOMAINES_DOSSIER, key=len, reverse=True):
        if rel.startswith(prefixe):
            return DOMAINES_DOSSIER[prefixe]
    return "systeme"


def _taxonomie(source, regle, referentiels) -> dict:
    rel = regle.chemin.parent.relative_to(source / DOSSIER_REGLES).as_posix()
    return {
        "theme": taxo.theme_pour_regle(rel, regle.id, regle.gabarit),
        "type_controle": taxo.TYPE_PAR_GABARIT.get(regle.gabarit, "configuration"),
        "niveaux": taxo.niveaux_depuis_referentiels(referentiels),
    }


def _controler_liaisons(fiche: dict) -> None:
    """Un parametre hors du motif du playbook ne fait jamais perdre la fiche :
    la liaison est retiree et la raison ecrite."""
    from brain.playbooks import valider_parametres
    for c in fiche["controles"]:
        if not c.get("playbook"):
            continue
        erreurs = valider_parametres(c["playbook"], c.get("parametres") or {},
                                     complet=False)
        if erreurs:
            c["playbook"] = None
            c.pop("parametres", None)
            c["sans_playbook"] = ("parametres hors du motif du playbook ("
                                  + "; ".join(erreurs) + ") : correction manuelle")


# « platform » de la source -> garde « sans objet » en tete des commandes.
# Releve a la relecture du 19/09/2026 : ignoree, « iptables-persistent
# absent » (platform: package[ufw]) s'appliquait aussi aux machines sous
# iptables, et /corriger aurait retire le paquet qui recharge leurs regles.
# Liste FERMEE de composants optionnels au nom Debian/Ubuntu sur ; les
# paquets toujours presents (pam, bash, sudo, shadow-utils...) ne sont pas
# gardes : un mauvais nom rendrait la regle « sans objet » partout.
PAQUETS_PLATEFORME = {
    "ufw": "ufw", "nftables": "nftables", "iptables": "iptables",
    "firewalld": "firewalld", "chrony": "chrony", "ntp": "ntp",
    "systemd-timesyncd": "systemd-timesyncd", "libreswan": "libreswan",
    "logrotate": "logrotate", "aide": "aide", "apparmor": "apparmor",
    "apport": "apport", "avahi": "avahi-daemon", "squid": "squid",
    "snmpd": "snmpd", "sssd": "sssd-common", "autofs": "autofs",
    "postfix": "postfix", "rsh-server": "rsh-server",
    "systemd-journal-remote": "systemd-journal-remote",
}
SERVICES_PLATEFORME = {"rsyslog", "ufw", "nftables", "iptables", "firewalld"}
_SANS_OBJET_ECHO = "echo 'SENTINELLE:SANS_OBJET'"


def gardes_plateforme(plateforme: str) -> list[str]:
    """Commandes de garde pour une plateforme « a and b and not c » (les
    elements non pris en charge -- machine, conteneur, montage... -- sont
    ignores ; une plateforme avec « or » n'est pas gardee)."""
    if not plateforme or " or " in plateforme:
        return []
    gardes = []
    for jeton in (j.strip() for j in plateforme.split(" and ")):
        m = re.fullmatch(r"(not )?package\[([\w.+-]+)\]", jeton)
        if m and m.group(2) in PAQUETS_PLATEFORME:
            paquet = PAQUETS_PLATEFORME[m.group(2)]
            op = "&&" if m.group(1) else "||"
            gardes.append(f"dpkg -s {paquet} >/dev/null 2>&1 {op} {_SANS_OBJET_ECHO}")
            continue
        m = re.fullmatch(r"service_disabled\[([\w.-]+)\]", jeton)
        if m and m.group(1) in SERVICES_PLATEFORME:
            gardes.append(f"systemctl is-enabled -q {m.group(1)} 2>/dev/null "
                          f"&& {_SANS_OBJET_ECHO}")
    return gardes


def _garder_plateforme(fiche: dict, plateforme: str) -> None:
    gardes = gardes_plateforme(plateforme)
    if not gardes:
        return
    for o in fiche["observer"]:
        manquantes = [g for g in gardes if g not in o["commande"]]
        if manquantes:
            o["commande"] = "; ".join(manquantes) + "; " + o["commande"]
    fiche["pieges"].insert(0, (
        f"Regle limitee par la source a : {plateforme}. Hors de ce cas, la "
        f"commande repond « sans objet » (aucun ecart)."))


def _conditionner(fiche: dict, variable: str, valeur: str,
                  inverse: bool = False) -> None:
    """Regle valable seulement si l'exploitant a choisi `valeur` (chrony ou
    timesyncd, ufw ou nftables...) : dit dans le titre et les pieges, et
    aucune evaluation automatique (elle declarerait un faux ecart a qui a
    fait l'autre choix)."""
    choix = (f"{valeur} n'est pas l'outil retenu" if inverse
             else f"{valeur} est l'outil retenu")
    fiche["titre"] += f" (si {choix})"
    fiche["pieges"].insert(0, (
        f"Regle conditionnelle : ne s'applique que si {choix} ({variable}). "
        f"Demander ou constater l'outil en place avant de conclure ; le code "
        f"ne juge pas cette regle seul."))
    for c in fiche["controles"]:
        c["evaluation"] = []


def _fiche_generique(source, version, regle, cites, variables):
    """Fiche d'une regle a gabarit generique (gabarits_cac). Meme structure
    et meme ordre de champs que les fiches SSH."""
    systemes = sorted({r.systeme for r in cites if r.systeme})
    produits = [gabarits_cac.PRODUITS[s] for s in systemes
                if s in gabarits_cac.PRODUITS]
    ctx = gabarits_cac.Contexte(produits=produits,
                                valeur_variable=_valeur_variable(source, variables))
    partie = gabarits_cac.GABARITS[regle.gabarit](regle, ctx)
    if isinstance(partie, str):
        return partie
    referentiels = []
    for r in cites:
        entree = {"nom": r.nom, "document": r.document, "ref": r.ref}
        if entree not in referentiels:
            referentiels.append(entree)
    applicable = {"os": systemes or ["linux"]}
    pieges = list(partie.get("pieges", []))
    if not regle.justification:
        pieges.append("Risque non documente par la source : a completer.")
    observer = []
    for o in partie["observer"]:
        o = dict(o)
        if not systemes and "variantes" in o:
            pass                                  # guide generique : on garde
        elif systemes and "variantes" in o:
            o.pop("variantes")                    # Debian/Ubuntu seulement
        observer.append(o)
    tax = _taxonomie(source, regle, referentiels)
    return {
        "id": _id_fiche(regle.id),
        "titre": partie["titre"],
        # Le domaine decoule du theme : les deux axes restent coherents.
        "domaine": taxo.THEMES[tax["theme"]][1],
        "schema": 2,
        "version": 1,
        "etat": "brouillon",
        "teste_sur": [],
        "applicable": applicable,
        "taxonomie": tax,
        "source": {
            "origine": "complianceascode",
            "regle": regle.id,
            "version": version,
            "url": ("https://github.com/ComplianceAsCode/content/tree/"
                    f"v{version}/{regle.chemin.parent.relative_to(source).as_posix()}"),
        },
        "mots_cles": sorted(str(m).lower() for m in partie["mots_cles"]),
        "resume": f"{partie['resume']} (regle {regle.id}, ComplianceAsCode {version}).",
        "observer": observer,
        "controles": [{
            "controle": partie["controle"],
            "bon": partie["bon"],
            "mauvais": partie["mauvais"],
            "gravite": regle.gravite,
            # Risque traduit (risques_fr.yaml) sinon texte d'origine anglais.
            "risque": (risques_fr().get(regle.id) or regle.justification
                       or regle.titre),
            "action": partie["action"],
            "playbook": partie.get("playbook"),
            **({"parametres": partie["parametres"]}
               if partie.get("parametres") else {}),
            **({"sans_playbook": partie.get("sans_playbook") or
                gabarits_cac.RAISONS_SANS_PLAYBOOK.get(
                    regle.gabarit, "correction manuelle : voir l'action")}
               if not partie.get("playbook") else {}),
            "evaluation": partie.get("evaluation", []),
        }],
        "pieges": pieges,
        "referentiels": referentiels,
    }


def _fiche_sshd_lineinfile(source, version, regle, cites, variables):
    param = str(regle.vars.get("parameter", "")).strip()
    if not re.fullmatch(r"[A-Za-z]+", param):
        return None
    valeur = regle.vars.get("value")
    note_valeur = ""
    if valeur is None and regle.vars.get("xccdf_variable"):
        var = regle.vars["xccdf_variable"]
        # La valeur est fixee par le referentiel ; on garde la premiere
        # trouvee et on signale si deux referentiels divergent.
        trouvees = {}
        for fichier in REFERENTIELS:
            sel = variables.get(fichier, {}).get(var)
            v = resoudre_variable(source, var, sel)
            if v is not None:
                trouvees[fichier] = v
        if not trouvees:
            return None
        valeur = next(iter(trouvees.values()))
        if len(set(trouvees.values())) > 1:
            note_valeur = (" Valeurs differentes selon le referentiel : "
                           + ", ".join(f"{k}={v}" for k, v in trouvees.items()))
    valeur = str(valeur)
    bas = param.lower()
    systemes = sorted({r.systeme for r in cites if r.systeme})
    referentiels = []
    for r in cites:
        entree = {"nom": r.nom, "document": r.document, "ref": r.ref}
        if entree not in referentiels:
            referentiels.append(entree)

    pieges = [
        "sshd -T exige les droits root ; sans sudo, la commande ne renvoie rien.",
        "Plusieurs fichiers peuvent definir la directive (Include "
        "/etc/ssh/sshd_config.d/*.conf) : la PREMIERE occurrence gagne ; "
        "sshd -T donne la valeur effective.",
    ]
    if str(regle.vars.get("is_default_value", "")).lower() == "true":
        pieges.append(f"« {param} {valeur} » est la valeur par defaut : son "
                      f"absence du fichier est conforme.")
    if note_valeur:
        pieges.append(note_valeur.strip())

    fr = lexique().get(param, {})
    titre = (f"SSH : {fr['titre']} ({param} {valeur})" if fr.get("titre")
             else f"SSH : {param} {valeur} ({regle.titre})")
    attendu = _attendu(param, valeur, fr.get("politique") or {})
    pieges += attendu["pieges"]
    return {
        "id": _id_fiche(regle.id),
        "titre": titre,
        "domaine": "acces",
        "schema": 2,
        "version": 1,
        "etat": "brouillon",
        "teste_sur": [],
        "applicable": {"os": systemes or ["linux"], "services": ["openssh"]},
        "taxonomie": _taxonomie(source, regle, referentiels),
        "source": {
            "origine": "complianceascode",
            "regle": regle.id,
            "version": version,
            "url": ("https://github.com/ComplianceAsCode/content/tree/"
                    f"v{version}/{regle.chemin.parent.relative_to(source).as_posix()}"),
        },
        "mots_cles": sorted({"ssh", "sshd", bas, *_mots(param),
                             *(str(m).lower() for m in fr.get("mots_cles", []))}),
        "resume": (f"La directive sshd {param} doit valoir « {valeur} » "
                   f"(regle {regle.id}, ComplianceAsCode {version})."),
        "observer": [
            {"commande": f"sudo sshd -T 2>/dev/null | grep -i '^{bas} '",
             "but": f"Lire la valeur EFFECTIVE de {param}",
             "lecture": attendu["lecture"]},
            {"commande": (f"grep -Ris '^[[:space:]]*{param}[[:space:]]' "
                          f"{CONFIG_SSHD} /etc/ssh/sshd_config.d/ 2>/dev/null"),
             "but": f"Trouver ou {param} est defini dans les fichiers",
             "lecture": "Chaque ligne donne le fichier et la valeur ecrite ; "
                        "aucune ligne = valeur par defaut."},
        ],
        "controles": [{
            "controle": attendu["controle"],
            "bon": attendu["bon"],
            "mauvais": attendu["mauvais"],
            "gravite": attendu.get("gravite") or regle.gravite,
            # Risque traduit (lexique relu) sinon texte d'origine en anglais.
            "risque": (fr.get("risque") or risques_fr().get(regle.id)
                       or regle.justification or regle.titre),
            "action": (f"Definir « {param} {valeur} » dans {CONFIG_SSHD} (ou "
                       f"un fichier de /etc/ssh/sshd_config.d/), controler "
                       f"avec sshd -t, puis recharger SSH en gardant une "
                       f"session ouverte."),
            "playbook": "infra.ssh-directive",
            "parametres": {"directive": param, "valeur": valeur},
            "evaluation": [dict(attendu["evaluation"], commande=0,
                                lecteur="sshd_t", champ=bas)],
        }],
        "pieges": pieges,
        "referentiels": referentiels,
    }


def _attendu(param: str, valeur: str, politique: dict) -> dict:
    """Ce qui est conforme. Par defaut la source (egalite stricte) ; une
    REGLE SENTINELLE du lexique peut l'assouplir vers un seuil, et elle est
    alors ecrite en clair dans la fiche."""
    bas = param.lower()
    r = {"controle": f"{param} = {valeur}", "bon": f"{param} {valeur}",
         "mauvais": "toute autre valeur",
         "lecture": f"Attendu : « {bas} {valeur.lower()} ». Toute autre "
                    f"valeur est un ecart.",
         "pieges": [],
         "evaluation": {"comparateur": "egal", "attendu": valeur}}
    comparaison = politique.get("comparaison")
    regle_sentinelle = None
    if comparaison == "max":
        r.update(controle=f"{param} <= {valeur}",
                 bon=f"{param} entre 1 et {valeur}",
                 mauvais=f"0, absent avec un defaut plus eleve, ou superieur a {valeur}",
                 lecture=f"Attendu : « {bas} N » avec 1 <= N <= {valeur}. Une "
                         f"valeur plus stricte est conforme.")
        r["evaluation"] = {"comparateur": "max", "attendu": valeur}
        regle_sentinelle = (f"la source exige exactement {valeur} ; une valeur "
                            f"plus stricte (entre 1 et {valeur}) est acceptee.")
    elif comparaison == "maxstartups":
        debut, taux, plein = (valeur.split(":") + ["", "", ""])[:3]
        r.update(controle=f"{param} {valeur} ou plus strict",
                 bon=f"debut <= {debut}, taux >= {taux}, plein <= {plein}",
                 mauvais="limites plus permissives, ou absent avec un defaut plus permissif",
                 lecture=f"Attendu : « {bas} debut:taux:plein » avec debut <= "
                         f"{debut}, taux >= {taux} et plein <= {plein}.")
        r["evaluation"] = {"comparateur": "maxstartups", "attendu": valeur}
        regle_sentinelle = (f"la source exige exactement {valeur} ; une "
                            f"configuration plus stricte est acceptee.")
    elif comparaison == "fichier":
        r.update(controle=f"{param} configure (fichier de banniere)",
                 bon=f"{param} <chemin d'un fichier> (ex. {valeur})",
                 mauvais=f"{param} none, ou absent",
                 lecture=f"Attendu : « {bas} /chemin/fichier ». « none » ou "
                         f"aucune ligne = pas de banniere.")
        r["evaluation"] = {"comparateur": "fichier", "attendu": valeur}
        regle_sentinelle = (f"la source exige le fichier {valeur} ; tout "
                            f"fichier de banniere existant est accepte.")
    if politique.get("acceptees"):
        valeurs = [str(v) for v in politique["acceptees"]]
        r.update(controle=f"{param} dans {{{', '.join(valeurs)}}}",
                 bon=" ou ".join(f"{param} {v}" for v in valeurs),
                 lecture="Attendu : " + " ou ".join(
                     f"« {bas} {v.lower()} »" for v in valeurs) + ".")
        r["evaluation"] = {"comparateur": "dans", "attendu": valeurs}
        regle_sentinelle = (f"la source exige {valeur} ; "
                            f"{', '.join(valeurs)} sont acceptes.")
    if politique.get("gravite"):
        r["gravite"] = politique["gravite"]
        r["pieges"].append(f"Regle Sentinelle : gravite portee a "
                           f"{politique['gravite']} ({politique.get('motif', '')}).")
    if regle_sentinelle:
        r["pieges"].append("Regle Sentinelle : " + regle_sentinelle)
    if politique.get("avertissement"):
        r["pieges"].append(politique["avertissement"])
    return r


# --------------------------------------------------------------------------- #
# Relecture : validation tracee, invalidee si les faits changent
# --------------------------------------------------------------------------- #
_CHAMPS_RELUS = ("titre", "applicable", "observer", "controles", "pieges",
                 "referentiels", "resume")


def empreinte(fiche: dict) -> str:
    """Empreinte de ce qui a ete relu. Exclut la version et l'URL de la
    source : une nouvelle version aux faits identiques reste validee."""
    contenu = {k: fiche.get(k) for k in _CHAMPS_RELUS}
    # L'evaluation (etape 5) traduit mecaniquement les faits relus (valeur,
    # politique) et est couverte par tests_ecarts : elle n'invalide pas une
    # relecture.
    # Idem pour le playbook et ses parametres (etape 2.6) : traduction
    # mecanique des memes faits, scripts relus et scelles a part.
    # (playbook remis a None : forme exacte des fiches deja relues.)
    contenu["controles"] = [{**{k: v for k, v in c.items()
                                if k not in {"evaluation", "parametres",
                                             "sans_playbook"}},
                             "playbook": None}
                            for c in contenu["controles"] or []]
    contenu["resume"] = re.sub(r"ComplianceAsCode [\w.]+", "",
                               str(contenu["resume"]))
    brut = json.dumps(contenu, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()[:16]


def lire_relectures(chemin: Path = RELECTURES) -> dict:
    if not chemin.exists():
        return {}
    return yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}


def appliquer_relectures(res: "Resultat", relectures: dict) -> None:
    """Fiche dont l'empreinte correspond a sa relecture -> verifie. Sinon la
    relecture est perimee : la fiche reste brouillon et est signalee."""
    for fid, fiche in res.fiches.items():
        entree = relectures.get(fiche["source"]["regle"])
        if not entree:
            continue
        if entree.get("empreinte") == empreinte(fiche):
            fiche["etat"] = "verifie"
            fiche["verifie_le"] = str(entree["verifie_le"])
            fiche["relu_par"] = entree["relu_par"]
        else:
            res.perimees.append(fid)


def enregistrer_relecture(res: "Resultat", regles: list[str], par: str,
                          version: str, jour: str,
                          chemin: Path = RELECTURES) -> list[str]:
    relectures = lire_relectures(chemin)
    par_regle = {f["source"]["regle"]: f for f in res.fiches.values()}
    cibles = list(par_regle) if regles == ["tout"] else regles
    faites = []
    for regle in cibles:
        if regle not in par_regle:
            raise SystemExit(f"Regle inconnue ou non importee : {regle}")
        relectures[regle] = {"verifie_le": jour, "relu_par": par,
                             "version_source": version,
                             "empreinte": empreinte(par_regle[regle])}
        faites.append(regle)
    entete = ("# Relectures des fiches importees de ComplianceAsCode.\n"
              "# Une entree valide la fiche tant que son empreinte (faits relus)\n"
              "# ne change pas ; sinon la fiche repasse en brouillon.\n")
    chemin.write_text(entete + yaml.safe_dump(dict(sorted(relectures.items())),
                                              allow_unicode=True, sort_keys=False),
                      encoding="utf-8")
    return faites


# --------------------------------------------------------------------------- #
# Ecriture
# --------------------------------------------------------------------------- #
ENTETE = ("# Fiche GENEREE depuis ComplianceAsCode (BSD-3-Clause) -- voir NOTICE.\n"
          "# Ne pas editer a la main : relancer l'importeur. Pour valider une\n"
          "# fiche apres relecture, passer etat a verifie + verifie_le.\n")


def ecrire(res: Resultat, sortie: Path, simuler: bool = False,
           purger: bool = False) -> dict[str, list[str]]:
    """Ecrit les fiches. Rend le bilan {nouvelles, modifiees, inchangees,
    a_revoir, retirees}. Une fiche retiree est signalee ; avec purger, elle
    est supprimee si elle est encore brouillon (jamais une fiche relue)."""
    bilan = {k: [] for k in ("nouvelles", "modifiees", "inchangees",
                             "a_revoir", "retirees")}
    bilan["relecture_perimee"] = list(res.perimees)
    if not simuler:
        sortie.mkdir(parents=True, exist_ok=True)
    for fid, fiche in sorted(res.fiches.items()):
        chemin = sortie / f"{fid}.yaml"
        texte = ENTETE + yaml.safe_dump(fiche, allow_unicode=True,
                                        sort_keys=False, width=100)
        if chemin.exists():
            actuel = chemin.read_text(encoding="utf-8")
            existant = yaml.safe_load(actuel) or {}
            if (existant.get("etat", "brouillon") != "brouillon"
                    and not existant.get("relu_par")):
                # Fiche validee A LA MAIN dans le fichier (hors registre) :
                if (existant.get("source") or {}) != fiche["source"] or \
                        existant.get("controles") != fiche["controles"]:
                    bilan["a_revoir"].append(fid)
                else:
                    bilan["inchangees"].append(fid)
                continue      # une fiche relue n'est jamais ecrasee
            if actuel == texte:
                bilan["inchangees"].append(fid)
                continue
            bilan["modifiees"].append(fid)
        else:
            bilan["nouvelles"].append(fid)
        if not simuler:
            chemin.write_text(texte, encoding="utf-8")
    if sortie.exists():
        for chemin in sortie.glob("cac-*.yaml"):
            if chemin.stem not in res.fiches:
                bilan["retirees"].append(chemin.stem)   # signale
                existant = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
                if purger and not simuler and                         existant.get("etat", "brouillon") == "brouillon":
                    chemin.unlink()
    return bilan


def main(argv=None) -> int:
    for flux in (sys.stdout,):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    racine = Path(__file__).resolve().parents[4]
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", type=Path,
                   default=racine / "data" / "sources" / "complianceascode")
    p.add_argument("--sortie", type=Path,
                   default=Path(__file__).resolve().parents[1] / "fiches"
                   / "complianceascode")
    p.add_argument("--simuler", action="store_true",
                   help="Ne rien ecrire, afficher le bilan.")
    p.add_argument("--purger", action="store_true",
                   help="Supprimer les fiches retirees encore brouillon.")
    p.add_argument("--valider", default=None,
                   help="Enregistrer la relecture de regles (ids separes par "
                        "des virgules, ou « tout »).")
    p.add_argument("--par", default=None,
                   help="Qui a relu (obligatoire avec --valider).")
    a = p.parse_args(argv)
    if not (a.source / DOSSIER_SSH).exists():
        print(f"Source introuvable : {a.source}")
        return 2

    from brain.bibliotheque.schema import valider

    version = version_source(a.source)
    res = construire(a.source, version)
    if a.valider:
        if not a.par:
            print("--par est obligatoire avec --valider (tracabilite).")
            return 2
        from datetime import date
        faites = enregistrer_relecture(
            res, [r.strip() for r in a.valider.split(",") if r.strip()],
            a.par, version, date.today().isoformat())
        print(f"Relecture enregistree pour {len(faites)} regle(s).")
        res = construire(a.source, version)
    invalides = {}
    for fid, fiche in res.fiches.items():
        erreurs, _ = valider(fiche, Path(f"{fid}.yaml"))
        if erreurs:
            invalides[fid] = erreurs
    for fid in invalides:
        res.ignorees[res.fiches.pop(fid)["source"]["regle"]] = \
            "refusee par le validateur : " + " | ".join(invalides[fid])

    bilan = ecrire(res, a.sortie, simuler=a.simuler, purger=a.purger)
    print(f"ComplianceAsCode {version} -> {a.sortie}")
    print(f"  fiches produites : {len(res.fiches)}")
    for cle, ids in bilan.items():
        print(f"  {cle:11}: {len(ids)}" + (f"  {', '.join(ids)}" if cle in
              ('a_revoir', 'retirees', 'relecture_perimee') and ids else ""))
    raisons: dict[str, int] = {}
    for r in res.ignorees.values():
        raisons[r] = raisons.get(r, 0) + 1
    print(f"  regles ignorees : {len(res.ignorees)}")
    for r, n in sorted(raisons.items(), key=lambda x: -x[1]):
        print(f"    {n:3} {r}")
    return 1 if invalides else 0


if __name__ == "__main__":
    sys.exit(main())
