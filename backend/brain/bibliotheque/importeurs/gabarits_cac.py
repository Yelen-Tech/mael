"""Gabarits de commandes Sentinelle pour les regles ComplianceAsCode.

Un gabarit ComplianceAsCode decrit CE QUI doit etre vrai (fichier en 0644,
paquet absent, sysctl = 0...). Ici, pour chaque type, NOUS ecrivons COMMENT
le lire : des commandes de LECTURE, verifiees par le garde-fou via le
validateur (une commande qui ecrirait fait ecarter la fiche).

Chaque fonction recoit la regle et un contexte, et rend :
  - un dict « partie » : titre, resume, mots_cles, domaine, observer,
    controle/bon/mauvais, action, pieges (+ services, variantes) ;
  - ou une chaine : la raison pour laquelle la regle est ignoree.

Les textes sont en francais ; le risque (rationale) reste celui de la source
tant qu'il n'est pas traduit a la relecture.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

# Produits ComplianceAsCode correspondant aux systemes des referentiels.
PRODUITS = {"ubuntu==22.04": "ubuntu2204", "ubuntu==24.04": "ubuntu2404",
            "debian==12": "debian12"}

# Quelques mots techniques anglais -> mots-cles francais (recherche).
_TRADUCTIONS = {
    # Correspondance par sous-chaine : eviter les cles trop courtes
    # (« route » est contenu dans « router_solicitations »).
    "ip_forward": ["routage", "passerelle", "transfert"],
    "forwarding": ["routage", "transfert"],
    "redirects": ["redirection", "icmp"],
    "source_route": ["source", "routing"],
    "syncookies": ["syn", "inondation"],
    "rp_filter": ["filtrage", "usurpation"], "log_martians": ["journalisation"],
    "randomize_va_space": ["aslr", "memoire"], "ptrace": ["debogage"],
    "dmesg_restrict": ["journal", "noyau"], "kptr_restrict": ["pointeurs"],
    "shadow": ["mots de passe", "comptes"], "gshadow": ["groupes", "comptes"],
    "passwd": ["comptes", "utilisateurs"], "group": ["groupes"],
    "crontab": ["cron", "planification", "taches"], "cron": ["planification", "taches"],
    "grub": ["demarrage", "chargeur"], "audit": ["audit", "journalisation"],
    "usb": ["usb", "cle usb", "peripherique"], "tmp": ["temporaire"],
    "shm": ["memoire partagee"], "home": ["utilisateurs"],
}


@dataclass
class Contexte:
    produits: list[str]                          # ubuntu2204, debian12...
    valeur_variable: Callable[[str], str | None]  # resolution XCCDF


def _mots(*textes: str) -> set[str]:
    mots: set[str] = set()
    for t in textes:
        for m in re.findall(r"[a-z][a-z0-9]{3,}", str(t).lower()):
            mots.add(m)
        cle = str(t).lower()
        for k, v in _TRADUCTIONS.items():
            if k in cle:
                mots.update(v)
    return mots


def par_produit(vars_: dict, cle: str, produits: list[str]):
    """Valeur d'une variable de gabarit pour les produits cites. Rend
    (valeur unique ou None si divergence, {produit: valeur})."""
    valeurs = {p: vars_.get(f"{cle}@{p}", vars_.get(cle)) for p in produits} \
        if produits else {"*": vars_.get(cle)}
    distinctes = {str(v) if not isinstance(v, list) else tuple(v)
                  for v in valeurs.values()}
    if len(distinctes) == 1:
        return next(iter(valeurs.values())), valeurs
    return None, valeurs


def _quote(texte: str) -> str | None:
    """Entre apostrophes pour le shell ; None si impossible proprement."""
    return None if "'" in texte else f"'{texte}'"


# Erreurs de la SOURCE corrigees a la relecture : variable -> (valeur, motif).
# Seulement quand la source se contredit elle-meme ; la fiche le signale.
CORRECTIONS_VARIABLES = {
    # controls/anssi.yml (R12) cite la regle avec le commentaire « Prevent
    # the Linux kernel from handling the ARP table globally » (= 1) mais sans
    # « _value=enabled » : la valeur retombait sur le defaut 0, l'inverse.
    "sysctl_net_ipv4_conf_all_arp_filter_value": (
        "1", "ANSSI-BP-028 R12 demande arp_filter = 1 ; ComplianceAsCode "
             "0.1.82 oublie de fixer la valeur (defaut 0)"),
}


# Corrections a NE PAS automatiser (relecture 19/09/2026) : le controle
# reste mesure, mais /corriger ne propose rien ; la raison et le danger sont
# ecrits dans la fiche. regle -> (raison, piege).
CORRECTION_MANUELLE = {
    "file_permissions_sudo": (
        "4110 retire l'execution de sudo a tous sauf au groupe du binaire : "
        "a faire seulement avec le groupe dedie (sudogrp) deja en place",
        "Appliquer 4110 avec le groupe root interdit sudo a TOUS les "
        "administrateurs (verrouillage hors de la machine) : creer d'abord "
        "le groupe dedie (regle sudo_dedicated_group) et y placer les "
        "administrateurs."),
    "sudo_add_noexec": (
        "noexec global empeche toute commande lancee par sudo d'executer un "
        "sous-programme : a tester commande par commande",
        "Defaults noexec pour tous casse les commandes qui lancent d'autres "
        "programmes (apt, dpkg, systemctl edit, editeurs...) : le preferer "
        "par commande (NOEXEC:) apres essai."),
    "sudo_add_requiretty": (
        "requiretty bloque sudo sans terminal (scripts, cron, outils "
        "d'automatisation) : a decider avec l'exploitant",
        "Defaults requiretty casse sudo dans les scripts, taches planifiees "
        "et outils d'automatisation (Ansible...) : verifier ces usages "
        "avant de l'activer."),
    "kernel_module_squashfs_disabled": (
        "squashfs est necessaire aux snaps d'Ubuntu : a decider selon l'usage",
        "Desactiver squashfs casse tous les snaps (logiciels installes par "
        "snap sur Ubuntu) : verifier « snap list » avant."),
    "kernel_module_overlayfs_disabled": (
        "overlay est necessaire a Docker, containerd et Podman : a decider "
        "selon l'usage",
        "Desactiver overlay casse tous les conteneurs (Docker, containerd, "
        "Podman) : verifier qu'aucun n'est utilise avant."),
    "kernel_module_udf_disabled": (
        "udf est necessaire au provisionnement de Microsoft Azure : a "
        "decider selon l'hebergement",
        "Microsoft Azure a besoin d'udf pour provisionner ses machines "
        "virtuelles : ne pas le desactiver sur Azure."),
    "grub2_mds_argument": (
        "nosmt desactive l'hyperthreading (moitie des fils d'execution) : "
        "decision de performance a prendre avec l'exploitant",
        "mds=full,nosmt coupe l'hyperthreading au prochain demarrage : "
        "mesurer l'impact sur la charge avant (serveurs de calcul, bases de "
        "donnees)."),
    "grub2_l1tf_argument": (
        "full,force desactive l'hyperthreading sans retour possible a chaud : "
        "decision de performance a prendre avec l'exploitant",
        "l1tf=full,force coupe l'hyperthreading et interdit de le reactiver "
        "sans redemarrer : mesurer l'impact avant ; surtout utile sur un "
        "hyperviseur."),
    "grub2_enable_iommu_force": (
        "iommu=force depend du materiel : certains peripheriques ou machines "
        "virtuelles ne demarrent plus correctement",
        "iommu=force peut rendre inutilisables certains peripheriques (cartes "
        "reseau, GPU) ou machines virtuelles : essayer d'abord sur une "
        "machine identique."),
    "file_cron_allow_exists": (
        "un cron.allow cree vide reserve crontab a root : lister d'abord les "
        "comptes qui en ont besoin",
        "Avant de creer /etc/cron.allow, y inscrire les comptes qui ont une "
        "crontab (ls /var/spool/cron/crontabs) : sinon leurs taches "
        "planifiees ne sont plus acceptees."),
    "file_at_allow_exists": (
        "un at.allow cree vide reserve at a root : lister d'abord les comptes "
        "qui en ont besoin",
        "Avant de creer /etc/at.allow, y inscrire les comptes qui utilisent "
        "at : sinon ils ne peuvent plus planifier de taches."),
    "file_cron_deny_not_exist": (
        "retirer cron.deny sans cron.allow ouvre crontab a TOUS les comptes : "
        "creer et remplir cron.allow d'abord",
        "Sur Debian/Ubuntu, sans cron.allow ni cron.deny, tous les comptes "
        "peuvent utiliser crontab : ne retirer cron.deny qu'une fois "
        "/etc/cron.allow en place."),
    "package_sssd_installed": (
        "installer sssd ne sert qu'avec un annuaire a configurer (IPA, AD, "
        "LDAP) : decision et configuration humaines",
        "Installer sssd seul ne securise rien : il faut le configurer vers "
        "l'annuaire (TLS, validation du certificat)."),
    "sysctl_kernel_modules_disabled": (
        "irreversible sans redemarrage : le retour arriere automatique ne "
        "peut pas fonctionner",
        "kernel.modules_disabled = 1 ne peut plus etre remis a 0 sans "
        "redemarrer, et bloque les pilotes charges ensuite (materiel branche "
        "a chaud, reseau) : a activer en fin de demarrage, apres essai."),
}


# Avertissements ajoutes a la relecture (regles issues d'un gabarit, qui
# n'ont pas de recette) : regle -> texte, place en tete des pieges.
_CHRONY_KEYS = ("Chemin RHEL : sur Debian/Ubuntu la cle est dans "
                "/etc/chrony/chrony.keys (compte _chrony) ; ici « aucune "
                "ligne » ne prouve rien, verifier ce fichier a la main.")
# Gardes « sans objet » ajoutees a la relecture (condition que la source dit
# en texte mais pas en « platform ») : regle -> commande de garde.
_AUTH_DISTANTE = ("grep -qsE 'pam_(sss|ldap|krb5)' /etc/pam.d/common-auth "
                  "|| echo 'SENTINELLE:SANS_OBJET'")
GARDES_RELECTURE = {
    # ANSSI R67 : seulement si l'authentification passe par un annuaire.
    "package_sssd_installed": _AUTH_DISTANTE,
}
_DEV_SHM = ("Sur Debian/Ubuntu, /dev/shm est monte par systemd (nosuid,nodev "
            "d'office) et absent de /etc/fstab : l'absence de ligne fstab "
            "n'est pas un ecart. Pour noexec, ajouter une ligne « tmpfs "
            "/dev/shm tmpfs defaults,nodev,nosuid,noexec 0 0 » a la main (le "
            "playbook refuse un point absent de fstab).")
PIEGES_RELECTURE = {
    "file_permissions_grub2_cfg": (
        "update-grub (a chaque mise a jour du noyau) peut regenerer "
        "grub.cfg avec des droits plus larges : reverifier apres chaque "
        "mise a jour."),
    "mount_option_dev_shm_nodev": _DEV_SHM,
    "mount_option_dev_shm_nosuid": _DEV_SHM,
    "mount_option_dev_shm_noexec": _DEV_SHM,
    "package_sssd_installed": (
        "ANSSI R67 ne vise que l'authentification par annuaire distant (IPA, "
        "AD, LDAP) : sans module PAM distant, la regle est sans objet."),
    "file_groupowner_etc_chrony_keys": _CHRONY_KEYS,
    "file_owner_etc_chrony_keys": _CHRONY_KEYS,
    "file_permissions_etc_chrony_keys": _CHRONY_KEYS,
}


# --------------------------------------------------------------------------- #
# sysctl
# --------------------------------------------------------------------------- #
def sysctl(regle, ctx: Contexte):
    var = regle.vars.get("sysctlvar")
    if not var or not re.fullmatch(r"[a-z0-9_.*-]+", var) or "*" in var:
        return "variable sysctl absente ou generique"
    valeur = regle.vars.get("sysctlval")
    if valeur is None:
        valeur = ctx.valeur_variable(f"{regle.id}_value")
    if valeur is None or isinstance(valeur, (list, dict)):
        return "valeur sysctl attendue introuvable"
    op = str(regle.vars.get("operation", "equals"))
    if op not in {"equals"}:
        return f"operation sysctl non prise en charge ({op})"
    motif = var.replace(".", r"\.")
    dossier = regle.chemin.parts
    return {
        "titre": f"Parametre noyau {var} = {valeur}",
        "resume": f"Le parametre noyau {var} doit valoir {valeur}, en memoire "
                  f"et de facon persistante.",
        "domaine": "reseau" if "network" in dossier else "noyau",
        "mots_cles": {"sysctl", "noyau", "parametre", var.lower(), *_mots(var)},
        "observer": [
            {"commande": f"sysctl -n {var}",
             "but": f"Lire la valeur ACTIVE de {var}",
             "lecture": f"Attendu : {valeur}."},
            {"commande": (f"grep -Rs '^[[:space:]]*{motif}[[:space:]]*=' "
                          f"/etc/sysctl.conf /etc/sysctl.d/ /run/sysctl.d/ "
                          f"/usr/local/lib/sysctl.d/ /usr/lib/sysctl.d/ "
                          f"2>/dev/null"),
             "but": "Verifier la valeur PERSISTANTE (appliquee au redemarrage)",
             "lecture": (f"Valeur retenue au demarrage = derniere affectation "
                         f"(fichiers tries par nom, /etc/sysctl.conf en "
                         f"dernier) : attendu « {var} = {valeur} » ; aucune "
                         f"ligne = non persistant.")},
        ],
        "controle": f"{var} = {valeur}",
        "bon": f"{valeur} en memoire et au demarrage",
        "mauvais": "autre valeur, ou valeur non persistante",
        "action": (f"Ecrire « {var} = {valeur} » dans /etc/sysctl.conf (lu en "
                   f"dernier) puis appliquer avec sysctl --system."),
        "playbook": "infra.sysctl",
        "parametres": {"cle": var, "valeur": str(valeur)},
        "evaluation": [
            {"commande": 0, "lecteur": "valeur", "comparateur": "egal",
             "attendu": str(valeur)},
            # Valeur EFFECTIVE (ordre de systemd-sysctl), pas « toutes les
            # lignes » : un fichier du systeme dans /usr/lib/sysctl.d/ qu'on
            # ne modifie jamais ne doit pas laisser un ecart perpetuel.
            {"commande": 1, "lecteur": "affectations",
             "comparateur": "toutes_egales", "champ": var,
             "attendu": str(valeur), "precedence": "sysctl"},
        ],
        "pieges": ["Le fichier lu en dernier l'emporte (ordre alphabetique "
                   "dans /etc/sysctl.d/) : verifier qu'aucun autre fichier ne "
                   "remet une autre valeur."]
        + ([f"Valeur corrigee par MAEL : "
            f"{CORRECTIONS_VARIABLES[regle.id + '_value'][1]}."]
           if regle.id + "_value" in CORRECTIONS_VARIABLES else []),
    }


# --------------------------------------------------------------------------- #
# Fichiers : droits, proprietaire, groupe
# --------------------------------------------------------------------------- #
def _recursif(regle, ctx) -> bool:
    """« recursive » (ou « recursive@produit ») vrai pour UN des systemes
    cites : la fiche vaut pour tous, on parcourt les sous-dossiers."""
    _, par_p = par_produit(regle.vars, "recursive", ctx.produits)
    return any(str(v).lower() == "true" for v in par_p.values())


# Motif d'exclusion accepte (find -name, et parametre du playbook).
_MOTIF_EXCLU = re.compile(r"[][A-Za-z0-9._*?-]+")


def _exclusions(regle, ctx) -> list[str] | None:
    """« excluded_files » de la source, union des systemes cites (releve a la
    relecture du 19/09/2026 : ignore, /var/log signalait wtmp en 0664 alors
    qu'une autre regle exige ce mode). None si un motif n'est pas citable."""
    _, par_p = par_produit(regle.vars, "excluded_files", ctx.produits)
    exclus: list[str] = []
    for v in par_p.values():
        for m in (v if isinstance(v, list) else ([v] if v else [])):
            if str(m) not in exclus:
                exclus.append(str(m))
    if any(not _MOTIF_EXCLU.fullmatch(m) for m in exclus):
        return None
    return exclus


def _cibles_fichiers(regle, ctx):
    chemins, _ = par_produit(regle.vars, "filepath", ctx.produits)
    if not chemins:
        return "chemin defini hors gabarit"
    chemins = chemins if isinstance(chemins, (list, tuple)) else [chemins]
    regex = regle.vars.get("file_regex")
    regex = regex if isinstance(regex, list) else [regex] * len(chemins)
    recursif = _recursif(regle, ctx)
    exclus = _exclusions(regle, ctx)
    if exclus is None:
        return "motif d'exclusion non pris en charge"
    sauf = "".join(f" ! -name '{m}'" for m in exclus)
    commandes = []
    for chemin, rx in zip(chemins, regex):
        if not re.fullmatch(r"/[\w./+-]*", str(chemin)):
            return "chemin non standard"
        if rx:
            q = _quote(str(rx))
            if q is None:
                return "expression reguliere non citable"
            profondeur = "" if recursif else " -maxdepth 1"
            commandes.append(f"find {chemin}{profondeur} -type f -regextype "
                             f"posix-extended -regex {q}{sauf} -printf '%m %u %g %p\\n' "
                             f"2>/dev/null")
        elif exclus:
            return "exclusions sans expression reguliere"
        elif recursif and str(chemin).endswith("/"):
            commandes.append(f"find {chemin} -printf '%m %u %g %p\\n' 2>/dev/null")
        else:
            commandes.append(f"stat -c '%a %U %G %n' {chemin} 2>/dev/null")
    return chemins, commandes


def _motif_lisible(rx) -> str:
    r"""'^.*\.pub$' -> '*.pub' ; '^.*$' -> '' (tous les fichiers)."""
    rx = str(rx or "")
    if rx in ("", ".*", "^.*$"):
        return ""
    m = re.fullmatch(r"\^?\.\*((?:\\\.|[\w-])+)\$?", rx)
    if m:
        return "*" + m.group(1).replace("\\.", ".")
    # '^.*audit(\.rules|d\.conf)$' -> '*audit.rules, *auditd.conf'
    m = re.fullmatch(r"\^?\.\*([\w-]*)\(((?:\\\.|[\w|-])+)\)\$?", rx)
    if m:
        return ", ".join("*" + (m.group(1) + alt).replace("\\.", ".")
                         for alt in m.group(2).split("|"))
    return f"motif {rx}"


def _liste_lisible(regle, chemins) -> str:
    """Titre : dit QUELS fichiers d'un repertoire sont vises."""
    regex = regle.vars.get("file_regex")
    regex = regex if isinstance(regex, list) else [regex] * len(chemins)
    morceaux = []
    for chemin, rx in zip(chemins, regex):
        if rx is None:
            morceaux.append(str(chemin))
            continue
        motif = _motif_lisible(rx)
        morceaux.append(f"des fichiers {motif} de {chemin}" if motif
                        else f"tous les fichiers de {chemin}")
    return ", ".join(morceaux)


def _de(liste: str) -> str:
    """« de /etc/x », « de tous les fichiers... », mais « des fichiers »."""
    return liste if liste.startswith("des ") else f"de {liste}"


def _fichier(regle, ctx, nature: str, cle: str):
    cibles = _cibles_fichiers(regle, ctx)
    if isinstance(cibles, str):
        return cibles
    chemins, commandes = cibles
    # stat affiche des NOMS : 0 = root ; en groupe, 4 = adm et 42 = shadow
    # (GID fixes de Debian/Ubuntu, paquet base-passwd). Sans cela, un
    # /etc/shadow correct (groupe shadow) serait signale en ecart.
    alias = {"0": "root",
             **({"4": "adm", "42": "shadow"} if nature == "groupe" else {})}
    valeur, par_p = par_produit(regle.vars, cle, ctx.produits)
    if valeur is None:
        # « 42 » ici, « shadow » la : meme exigence ecrite autrement.
        normes = {p: "|".join(sorted({alias.get(v, v)
                                      for v in str(x).split("|")}))
                  for p, x in par_p.items()}
        if len(set(normes.values())) != 1:
            return (f"valeur differente selon le systeme "
                    f"({', '.join(f'{p}={v}' for p, v in par_p.items())})")
        valeur = next(iter(normes.values()))
    valeur = str(valeur).strip()
    if not valeur:
        return "valeur attendue vide"
    liste = _liste_lisible(regle, chemins)
    noms = [alias.get(v, v) for v in valeur.split("|")]
    nom = " ou ".join(noms)
    if nature == "droits":
        evaluation = [{"commande": i, "lecteur": "stat", "champ": "droits",
                       "comparateur": "droits_au_plus", "attendu": valeur}
                      for i in range(len(commandes))]
    else:
        # stat affiche le NOM : on accepte le nom et la valeur de la source.
        acceptes = sorted(set(noms) | set(valeur.split("|")))
        evaluation = [{"commande": i, "lecteur": "stat", "champ": nature,
                       "comparateur": "dans", "attendu": acceptes}
                      for i in range(len(commandes))]
    if nature == "droits":
        titre = f"Droits {_de(liste)} ({valeur} au plus)"
        controle = f"droits <= {valeur}"
        bon = f"{valeur} ou plus strict (aucun droit en plus)"
        lecture = (f"1re colonne = droits en octal : aucun bit ne doit "
                   f"depasser {valeur}.")
        action = f"chmod {valeur} sur les fichiers concernes (u-x,go-wx selon le cas)."
        mots = {"droits", "permissions", "chmod"}
    elif nature == "proprietaire":
        titre = f"Proprietaire {_de(liste)} : {nom}"
        controle = f"proprietaire = {nom}"
        bon = f"proprietaire {nom}"
        lecture = f"2e colonne = proprietaire : attendu {nom}."
        action = f"chown {nom} sur les fichiers concernes."
        mots = {"proprietaire", "chown"}
    else:
        titre = f"Groupe {_de(liste)} : {nom}"
        controle = f"groupe = {nom}"
        bon = f"groupe {nom}"
        lecture = f"3e colonne = groupe : attendu {nom}."
        action = f"chgrp {nom} sur les fichiers concernes."
        mots = {"groupe", "chgrp"}
    return {
        "titre": titre,
        "resume": f"{titre.split(' (')[0]} : {bon}.",
        "domaine": "fichiers",
        "mots_cles": {"fichier", "fichiers", *mots, *_mots(liste)},
        "observer": [{"commande": c,
                      "but": f"Lire droits, proprietaire et groupe ({nature})",
                      "lecture": lecture + " Aucune ligne = fichier absent."}
                     for c in commandes],
        "controle": controle, "bon": bon, "mauvais": "toute autre valeur",
        "action": action,
        "evaluation": evaluation,
        # UN chemin explicite -> fichier-* ; une recherche find -> motif.
        **({"playbook": "infra.fichiers-motif",
            "parametres": {"dossier": str(chemins[0]),
                           "regex": str((regle.vars.get("file_regex") if not
                                         isinstance(regle.vars.get("file_regex"), list)
                                         else regle.vars["file_regex"][0]) or "^.*$"),
                           "nature": nature,
                           "valeur": valeur if nature == "droits" else noms[0],
                           "recursif": "oui" if _recursif(regle, ctx) else "non",
                           **({"exclure": ",".join(_exclusions(regle, ctx))}
                              if _exclusions(regle, ctx) else {})}}
           if len(chemins) == 1 and commandes[0].startswith("find ")
           and (nature == "droits"
                or re.fullmatch(r"[a-z_][a-z0-9_-]*", noms[0]))
           else {}),
        **({"playbook": f"infra.fichier-{nature}",
            "parametres": {"chemin": str(chemins[0]),
                           {"droits": "mode"}.get(nature, nature):
                               valeur if nature == "droits" else noms[0]}}
           if len(chemins) == 1 and commandes[0].startswith("stat ")
           and re.fullmatch(r"/[A-Za-z0-9._/+-]+", str(chemins[0]))
           and (nature == "droits"
                or re.fullmatch(r"[a-z_][a-z0-9_-]*", noms[0]))
           else {}),
        "pieges": ["Sans sudo, certains fichiers (ex. /etc/shadow) ne sont pas "
                   "lisibles par stat/find : relancer avec les droits root."]
        + ([f"Exclus par la source (exigence propre, voir leur fiche) : "
            f"{', '.join(_exclusions(regle, ctx))}."]
           if _exclusions(regle, ctx) else []),
    }


def file_permissions(regle, ctx):
    return _fichier(regle, ctx, "droits", "filemode")


def file_owner(regle, ctx):
    return _fichier(regle, ctx, "proprietaire", "uid_or_name")


def file_groupowner(regle, ctx):
    return _fichier(regle, ctx, "groupe", "gid_or_name")


# --------------------------------------------------------------------------- #
# Paquets
# --------------------------------------------------------------------------- #
def _paquet(regle, ctx, present: bool):
    _, par_p = par_produit(regle.vars, "pkgname", ctx.produits)
    noms = sorted({str(v) for v in par_p.values() if v})
    if not noms or not all(re.fullmatch(r"[a-z0-9][a-z0-9+.:-]*", n) for n in noms):
        return "nom de paquet absent ou non standard"
    liste = " ".join(noms)
    etat = "installe" if present else "absent"
    rpm = str(regle.vars.get("pkgname@rhel9") or regle.vars.get("pkgname") or noms[0])
    return {
        "titre": f"Paquet {' / '.join(noms)} {etat}",
        "resume": f"Le paquet {' / '.join(noms)} doit etre {etat}.",
        "domaine": "services" if "services" in regle.chemin.parts else "paquets",
        "mots_cles": {"paquet", "paquets", "logiciel", "installe", *noms,
                      *_mots(liste)},
        "observer": [{
            "commande": (f"dpkg-query -W -f='${{binary:Package}} ${{Status}}\\n' "
                         f"{liste} 2>/dev/null"),
            "but": f"Savoir si {liste} est installe",
            "lecture": ("« install ok installed » = installe ; aucune ligne ou "
                        "« deinstall » = absent."),
            "variantes": {"rhel": f"rpm -q {rpm}"},
        }],
        "controle": f"paquet {liste} {etat}",
        "evaluation": [{"commande": 0, "lecteur": "dpkg",
                        "comparateur": "installe" if present else "absent",
                        "attendu": noms}],
        **({"playbook": "infra.paquet-installer",
            "parametres": {"paquet": noms[0]}} if present and len(noms) == 1
           else {"playbook": "infra.paquet-retirer",
                 "parametres": {"paquet": " ".join(noms)}} if not present
           else {"sans_playbook": RAISONS_SANS_PLAYBOOK["package_installed"]}),
        "bon": etat,
        "mauvais": "absent" if present else "installe",
        "action": (f"Installer {liste} avec le gestionnaire de paquets."
                   if present else
                   f"Desinstaller {liste} (apt purge) apres avoir verifie "
                   f"qu'aucun service n'en depend."),
        "pieges": ([] if present else
                   ["Un paquet peut etre requis par une application metier : "
                    "confirmer avec l'exploitant avant de le retirer."]),
    }


def package_installed(regle, ctx):
    return _paquet(regle, ctx, True)


def package_removed(regle, ctx):
    return _paquet(regle, ctx, False)


# --------------------------------------------------------------------------- #
# Services
# --------------------------------------------------------------------------- #
def _service(regle, ctx, actif: bool):
    nom, par_p = par_produit(regle.vars, "servicename", ctx.produits)
    if nom is None:
        return (f"nom de service different selon le systeme "
                f"({', '.join(f'{p}={v}' for p, v in par_p.items())})")
    nom = str(nom)
    if not re.fullmatch(r"[a-zA-Z0-9@_.-]+", nom):
        return "nom de service non standard"
    etat = "active et demarre" if actif else "desactive et arrete"
    return {
        "titre": f"Service {nom} {etat}",
        "resume": f"Le service {nom} doit etre {etat}.",
        "domaine": "services",
        "mots_cles": {"service", "services", "demarrage", "systemd", nom.lower(),
                      *_mots(nom)},
        "observer": [{
            "commande": (f"systemctl is-enabled {nom}.service 2>/dev/null; "
                         f"systemctl is-active {nom}.service 2>/dev/null"),
            "but": f"Lire l'etat de demarrage et d'execution de {nom}",
            "lecture": ("Attendu : « enabled » puis « active »." if actif else
                        "Attendu : « disabled » ou « masked » (ou service "
                        "absent) puis « inactive »."),
        }],
        "controle": f"service {nom} {'enabled/active' if actif else 'disabled/inactive'}",
        "evaluation": [{"commande": 0, "lecteur": "systemctl",
                        "comparateur": "actif" if actif else "inactif"}],
        "playbook": "infra.service-" + ("activer" if actif else "desactiver"),
        "parametres": {"service": nom},
        "bon": "enabled et active" if actif else "disabled ou masked, inactive (ou absent)",
        "mauvais": "disabled ou inactive" if actif else "enabled ou active",
        "action": (f"systemctl enable --now {nom}.service" if actif else
                   f"systemctl disable --now {nom}.service (ou mask) apres "
                   f"verification du besoin."),
        "pieges": ["Un service peut etre demarre par une socket systemd : "
                   "verifier aussi « systemctl list-sockets »."],
    }


def service_enabled(regle, ctx):
    return _service(regle, ctx, True)


def service_disabled(regle, ctx):
    return _service(regle, ctx, False)


# --------------------------------------------------------------------------- #
# Modules noyau, montages, compilation du noyau, arguments de demarrage
# --------------------------------------------------------------------------- #
def kernel_module_disabled(regle, ctx):
    mod = str(regle.vars.get("kernmodule") or "")
    if not re.fullmatch(r"[a-z0-9_-]+", mod):
        return "nom de module non standard"
    return {
        "titre": f"Module noyau {mod} desactive",
        "resume": f"Le module noyau {mod} ne doit pas pouvoir etre charge.",
        "domaine": "noyau",
        "mots_cles": {"module", "modules", "noyau", mod, *_mots(mod)},
        "observer": [
            {"commande": f"grep -Rs '{mod}' /etc/modprobe.d/ /lib/modprobe.d/ 2>/dev/null",
             "but": f"Voir si {mod} est interdit de chargement",
             "lecture": (f"Attendu : « install {mod} /bin/false » (ou /bin/true) "
                         f"et « blacklist {mod} ».")},
            {"commande": f"lsmod | grep -w '{mod}'",
             "but": f"Voir si {mod} est charge en ce moment",
             "lecture": "Aucune ligne = non charge."},
        ],
        "controle": f"module {mod} non chargeable",
        "playbook": "infra.module-interdit",
        "parametres": {"module": mod},
        "evaluation": [
            {"commande": 0, "lecteur": "modprobe", "comparateur": "interdit",
             "champ": mod},
            {"commande": 1, "lecteur": "aucune_ligne", "comparateur": "vide"},
        ],
        "bon": f"install {mod} /bin/false + blacklist, non charge",
        "mauvais": "aucune interdiction, ou module charge",
        "action": (f"Ajouter « install {mod} /bin/false » et « blacklist {mod} » "
                   f"dans /etc/modprobe.d/{mod}.conf, puis decharger le module."),
        "pieges": ["Verifier qu'aucun materiel ou usage (ex. stockage USB) "
                   "n'a besoin du module avant de l'interdire."],
    }


def mount_option(regle, ctx):
    point = str(regle.vars.get("mountpoint") or "")
    option = str(regle.vars.get("mountoption") or "")
    if not re.fullmatch(r"/[\w/.-]*", point) or not re.fullmatch(r"[a-z_]+", option):
        return "point de montage ou option non standard"
    return {
        "titre": f"Option {option} sur {point}",
        "resume": f"{point} doit etre monte avec l'option {option}.",
        "domaine": "fichiers",
        "mots_cles": {"montage", "partition", "option", option, *_mots(point, option)},
        "observer": [
            {"commande": f"findmnt -kn {point}",
             "but": f"Lire les options de montage ACTIVES de {point}",
             "lecture": f"La colonne des options doit contenir {option}. "
                        f"Aucune ligne = pas de montage separe."},
            {"commande": f"grep -E '[[:space:]]{point}[[:space:]]' /etc/fstab",
             "but": "Verifier la configuration PERSISTANTE",
             "lecture": f"La 4e colonne doit contenir {option}."},
        ],
        "controle": f"{point} monte avec {option}",
        "playbook": "infra.montage-option",
        "parametres": {"point": point, "option": option},
        "evaluation": [
            {"commande": 0, "lecteur": "findmnt",
             "comparateur": "option_presente", "attendu": option},
            {"commande": 1, "lecteur": "fstab",
             "comparateur": "option_presente", "attendu": option},
        ],
        "bon": f"{option} present (actif et dans /etc/fstab)",
        "mauvais": f"{option} absent",
        "action": (f"Ajouter {option} aux options de {point} dans /etc/fstab puis "
                   f"remonter (mount -o remount {point})."),
        "pieges": [f"Si {point} n'est pas une partition separee, cette regle ne "
                   f"peut pas s'appliquer telle quelle : voir la regle de "
                   f"partition dediee."],
    }


# Architectures de la source -> nom lu dans l'en-tete de /boot/config-*
# (« # Linux/x86 6.8.0 Kernel Configuration »).
ARCHITECTURES = {"x86_64_arch": "x86", "aarch64_arch": "arm64"}
# Options renommees par le noyau 6.9 (prefixe MITIGATION_) : on lit les deux
# noms, sinon un noyau recent passerait pour « option inconnue ».
KCONFIG_RENOMMEES = {
    "CONFIG_RETPOLINE": "CONFIG_MITIGATION_RETPOLINE",
    "CONFIG_PAGE_TABLE_ISOLATION": "CONFIG_MITIGATION_PAGE_TABLE_ISOLATION",
}


def _architectures(plateforme: str) -> list[str] | None:
    """[« x86 »...] si la plateforme ne nomme que des architectures,
    [] si elle ne restreint rien, None si elle dit autre chose."""
    if not plateforme or plateforme == "machine":
        return []
    jetons = [j.strip() for j in plateforme.split(" or ")]
    if all(j in ARCHITECTURES for j in jetons):
        return sorted({ARCHITECTURES[j] for j in jetons})
    return None


def kernel_build_config(regle, ctx):
    config = str(regle.vars.get("config") or "")
    valeur = regle.vars.get("value")
    if valeur is None and regle.vars.get("variable"):
        valeur = ctx.valeur_variable(str(regle.vars["variable"]))
    if not re.fullmatch(r"CONFIG_[A-Z0-9_]+", config) or valeur is None:
        return "option de compilation ou valeur introuvable"
    valeur = str(valeur)
    archis = _architectures(getattr(regle, "plateforme", ""))
    if archis is None:
        return f"plateforme non prise en charge ({regle.plateforme})"
    noms = [config] + ([KCONFIG_RENOMMEES[config]]
                       if config in KCONFIG_RENOMMEES else [])
    motif = (config if len(noms) == 1
             else "CONFIG_(MITIGATION_)?" + config.removeprefix("CONFIG_"))
    attendu = (f"« # {config} is not set »" if valeur == "n"
               else f"« {config}={valeur} »")
    pour = f" ({', '.join(archis)} uniquement)" if archis else ""
    spec = {"commande": 0, "lecteur": "kconfig", "comparateur": "egal",
            "champ": config, "attendu": valeur}
    if len(noms) > 1:
        spec["noms"] = noms
    if archis:
        spec["architectures"] = archis
    pieges = ["/boot/config-<version> peut manquer (images cloud, "
              "conteneurs) : essayer /proc/config.gz si disponible.",
              "Regle issue du guide ANSSI : un ecart est frequent sur les "
              "noyaux generiques, a qualifier plutot qu'a corriger seul."]
    if len(noms) > 1:
        pieges.append(f"Depuis le noyau 6.9 l'option s'appelle {noms[1]} : "
                      "les deux noms sont lus.")
    return {
        "titre": f"Option de compilation du noyau {config} = {valeur}{pour}",
        "resume": f"Le noyau doit etre compile avec {config}={valeur}.",
        "domaine": "noyau",
        "mots_cles": {"noyau", "compilation", "kernel", config.lower(),
                      *_mots(config.replace("CONFIG_", "").replace("_", " "))},
        "observer": [{
            # L'en-tete (« # Linux/x86 6.8.0 ... ») prouve que le fichier a
            # ete lu et donne l'architecture : option absente d'un fichier lu
            # = option inexistante dans ce noyau.
            "commande": (f"grep -E '^# Linux/|^(# )?{motif}( is not set|=)' "
                         f"/boot/config-$(uname -r)"),
            "but": "Lire l'option dans la configuration du noyau en cours",
            "lecture": (f"Attendu : {attendu}. La ligne « # Linux/... » donne "
                        "l'architecture ; option absente = inexistante dans "
                        "ce noyau."),
        }],
        "controle": f"{config} = {valeur}",
        "evaluation": [spec],
        "bon": attendu.strip("« »") + (" (ou option inexistante dans ce noyau)"
                                        if valeur == "n" else ""),
        "mauvais": "autre valeur" + ("" if valeur == "n"
                                     else " (option absente : indetermine)"),
        "action": ("Utiliser un noyau compile avec cette option (noyau de la "
                   "distribution ou recompilation) : ce n'est pas un reglage a "
                   "chaud."),
        "pieges": pieges,
    }


def grub2_bootloader_argument(regle, ctx):
    arg = str(regle.vars.get("arg_name") or "")
    valeur = regle.vars.get("arg_value")
    if valeur is None and regle.vars.get("arg_variable"):
        valeur = ctx.valeur_variable(str(regle.vars["arg_variable"]))
    if not re.fullmatch(r"[a-z0-9_.-]+", arg):
        return "argument de demarrage non standard"
    op = str(regle.vars.get("operation", "equals"))
    if op not in {"equals", "greater than or equal"}:
        return f"operation non prise en charge ({op})"
    attendu = arg if valeur in (None, "") else f"{arg}={valeur}"
    compar = "au moins " if op == "greater than or equal" else ""
    return {
        "titre": f"Argument de demarrage {attendu}",
        "resume": f"Le noyau doit demarrer avec {compar}{attendu}.",
        "domaine": "systeme",
        "mots_cles": {"grub", "demarrage", "noyau", "argument", arg, *_mots(arg)},
        "observer": [
            {"commande": "cat /proc/cmdline",
             "but": "Lire les arguments du demarrage EN COURS",
             "lecture": f"Attendu : {compar}{attendu}."},
            {"commande": "grep -E '^GRUB_CMDLINE_LINUX' /etc/default/grub",
             "but": "Verifier la configuration persistante de GRUB",
             "lecture": f"{attendu} doit figurer dans GRUB_CMDLINE_LINUX."},
        ],
        "controle": f"argument {compar}{attendu}",
        "playbook": "infra.grub-argument",
        "parametres": {"argument": attendu, "action": "ajouter"},
        "evaluation": [
            {"commande": i, "lecteur": lecteur, "champ": arg,
             "comparateur": "au_moins" if compar else "egal",
             "attendu": None if valeur in (None, "") else str(valeur)}
            for i, lecteur in ((0, "cmdline"), (1, "grub"))
        ],
        "bon": f"{compar}{attendu} dans /proc/cmdline et /etc/default/grub",
        "mauvais": "argument absent ou valeur plus faible",
        "action": (f"Ajouter {attendu} a GRUB_CMDLINE_LINUX dans /etc/default/grub, "
                   f"regenerer la configuration (update-grub) et redemarrer."),
        "pieges": ["Le changement ne prend effet qu'apres redemarrage : "
                   "planifier la fenetre de maintenance."],
    }


GABARITS: dict[str, Callable] = {
    "sysctl": sysctl,
    "file_permissions": file_permissions,
    "file_owner": file_owner,
    "file_groupowner": file_groupowner,
    "package_installed": package_installed,
    "package_removed": package_removed,
    "service_enabled": service_enabled,
    "service_disabled": service_disabled,
    "kernel_module_disabled": kernel_module_disabled,
    "mount_option": mount_option,
    "kernel_build_config": kernel_build_config,
    "grub2_bootloader_argument": grub2_bootloader_argument,
}


# --------------------------------------------------------------------------- #
# Couverture (18/09/2026) : audit, authentification, sudo, partitions...
# --------------------------------------------------------------------------- #
# Correction non automatisable : raison ecrite (etape 2.6, champ sans_playbook).
RAISONS_SANS_PLAYBOOK = {
    "kernel_build_config": "option de compilation du noyau : changer de noyau "
                           "ou le recompiler, non automatisable",
    "mount": "partition dediee : repartitionnement a planifier, non "
             "automatisable",
    "pam_options": "pile PAM : a modifier avec pam-auth-update et une session "
                   "root ouverte (une erreur peut bloquer toute connexion)",
    "detecteur": "la commande liste des elements a examiner un par un "
                 "(comptes, fichiers, regles) : la correction (supprimer, "
                 "verrouiller, modifier) reste une decision humaine",
    "fichiers_stat": "droits calcules (PATH, repertoires personnels) : "
                     "correction au cas par cas",
    "cle_valeur": "fichier a sections ou repertoire (dconf, sssd) : "
                  "correction manuelle",
    "package_installed": "nom de paquet different selon le systeme : "
                         "installation manuelle",
}
_CONFIG_ESPACEES = ("auditd.conf", "pwquality.conf", "faillock.conf", "main.cf")


def valeur_a_ecrire(spec: dict):
    """Valeur qu'un playbook ecrit pour satisfaire une evaluation : la borne
    du referentiel (jamais une valeur inventee)."""
    attendu = spec.get("attendu")
    if spec.get("comparateur") == "entre":
        mini, maxi = (list(attendu) + [None, None])[:2]
        return str(maxi if maxi is not None else mini)
    if isinstance(attendu, (list, tuple)):
        return str(attendu[0])
    return str(attendu).split("|")[0]


def liaison_cle_valeur(fichier: str, cle: str, valeur, fmt: str | None = None) -> dict:
    fmt = fmt or ("egal_espaces" if fichier.endswith(_CONFIG_ESPACEES)
                  else "egal")
    return {"playbook": "infra.cle-valeur",
            "parametres": {"fichier": fichier, "cle": cle,
                           "valeur": "" if valeur is None else str(valeur),
                           "format": fmt}}


def lignes_audit(specs: list[dict], auid: bool = False) -> str:
    """Regles auditd (format rules.d) qui satisfont les evaluations. auid :
    filtre des comptes humains (CIS : auid>=1000, auid!=unset)."""
    filtre = " -F auid>=1000 -F auid!=unset" if auid else ""
    lignes = []
    for s in specs:
        if s["comparateur"] == "surveille":
            lignes.append(f"-w {s['champ']} -p wa -k mael")
        elif s["comparateur"] == "execution":
            lignes.append(f"-a always,exit -F path={s['champ']} -F perm=x"
                          f" -F auid>=1000 -F auid!=unset -k mael")
        else:
            for groupe in s.get("options") or [[]]:
                opts = ""
                for o in groupe:
                    opts += (f" -C {o} -F auid!=unset" if o.startswith("euid")
                             else f" -F {o}")
                for arch in ("b32", "b64"):
                    lignes.append(f"-a always,exit -F arch={arch} -S "
                                  f"{s['champ']}{opts}{filtre} -k mael")
    uniques = list(dict.fromkeys(lignes))
    return " | ".join(uniques)


def _texte(v) -> str:
    """YAML lit « yes » comme un booleen : on rend le texte d'origine."""
    if isinstance(v, bool):
        return "yes" if v else "no"
    return "" if v is None else str(v)


_AUDIT_LIRE = [
    {"commande": "auditctl -l",
     "but": "Lire les regles d'audit CHARGEES dans le noyau",
     "lecture": "Une ligne par regle (-w chemin -p wa, ou -a always,exit "
                "-F arch=b64 -S appel...). « No rules » = aucune regle."},
    {"commande": "grep -hs '^-' /etc/audit/rules.d/*.rules",
     "but": "Lire les regles PERSISTANTES (rechargees au demarrage)",
     "lecture": "Memes regles qu'auditctl -l ; absentes ici = perdues au "
                "redemarrage."},
]
_AUDIT_PIEGES = [
    "auditctl -l et /etc/audit/rules.d exigent les droits root (sudo).",
    "Une regle chargee a la main (auditctl -w) disparait au redemarrage : "
    "elle doit aussi etre dans /etc/audit/rules.d/ (puis augenrules --load).",
]
_AUDIT_ACTION = ("Ajouter la regle dans un fichier de /etc/audit/rules.d/ "
                 "(ex. 50-sentinelle.rules), puis « augenrules --load ». Si "
                 "la configuration est immuable (-e 2), redemarrer.")


def _audit(titre, resume, mots, controle, bon, spec, auid=False):
    return {
        "playbook": "infra.audit-regles",
        "parametres": {"regles": lignes_audit([spec], auid)},
        "titre": titre, "resume": resume, "domaine": "journaux",
        "mots_cles": {"audit", "auditd", "auditctl", "journalisation",
                      "tracabilite", *mots},
        "observer": [dict(o) for o in _AUDIT_LIRE],
        "controle": controle, "bon": bon,
        "mauvais": "regle absente (ou absente au redemarrage)",
        "action": _AUDIT_ACTION,
        "evaluation": [dict(spec, commande=0), dict(spec, commande=1)],
        "pieges": list(_AUDIT_PIEGES),
    }


def audit_rules_watch(regle, ctx):
    chemin = regle.vars.get("path")
    if str(regle.vars.get("path_is_variable", "")).lower() == "true":
        chemin = ctx.valeur_variable(str(chemin))
    chemin = _texte(chemin)
    if not re.fullmatch(r"/[\w./+-]*", chemin):
        return "chemin surveille introuvable ou non standard"
    return _audit(
        f"Audit des modifications de {chemin}",
        f"Toute ecriture ou changement d'attribut de {chemin} doit etre trace "
        f"par auditd (-w {chemin} -p wa).",
        {*_mots(chemin), "surveillance", "modification"},
        f"-w {chemin} -p wa", f"regle -w {chemin} -p wa chargee et persistante",
        {"lecteur": "audit", "comparateur": "surveille", "champ": chemin,
         "attendu": "wa"})


def _audit_appel(regle, ctx, nom, options=None, libelle="", auid=False):
    nom = _texte(nom)
    if not re.fullmatch(r"[a-z0-9_]+", nom):
        return "appel systeme non standard"
    if nom in {"create_module", "query_module"}:
        return "appel systeme obsolete (absent des noyaux 64 bits)"
    spec = {"lecteur": "audit", "comparateur": "appels", "champ": nom}
    if options:
        spec["options"] = options
    return _audit(
        f"Audit de l'appel systeme {nom}{libelle}",
        f"L'appel systeme {nom}{libelle} doit etre trace par auditd, en 32 et "
        f"64 bits (-a always,exit -F arch=b32/b64 -S {nom}).",
        {nom, "appel", "systeme", "syscall", *_mots(nom)},
        f"-a always,exit -S {nom} (b32 et b64)",
        f"regles arch=b32 et arch=b64 pour {nom}", spec, auid)


def audit_rules_dac_modification(regle, ctx):
    fiche = _audit_appel(regle, ctx, regle.vars.get("attr"), auid=True)
    if isinstance(fiche, dict):
        fiche["mots_cles"] |= {"droits", "permissions", "proprietaire"}
    return fiche


def audit_rules_file_deletion_events(regle, ctx):
    fiche = _audit_appel(regle, ctx, regle.vars.get("name"), auid=True)
    if isinstance(fiche, dict):
        fiche["mots_cles"] |= {"suppression", "fichier", "renommage"}
    return fiche


def audit_rules_kernel_module_loading(regle, ctx):
    fiche = _audit_appel(regle, ctx, regle.vars.get("name"))
    if isinstance(fiche, dict):
        fiche["mots_cles"] |= {"module", "noyau", "chargement"}
    return fiche


def audit_rules_unsuccessful_file_modification(regle, ctx):
    fiche = _audit_appel(regle, ctx, regle.vars.get("name"),
                         options=[["exit=-EACCES"], ["exit=-EPERM"]],
                         libelle=" en echec (EACCES, EPERM)", auid=True)
    if isinstance(fiche, dict):
        fiche["mots_cles"] |= {"echec", "acces", "refuse", "fichier"}
    return fiche


def audit_rules_privileged_commands(regle, ctx):
    chemin = _texte(regle.vars.get("path"))
    if not re.fullmatch(r"/[\w./+-]*", chemin):
        return "chemin de commande non standard"
    commande = chemin.rsplit("/", 1)[-1]
    return _audit(
        f"Audit de l'execution de {commande}",
        f"Chaque execution de {chemin} (commande privilegiee) doit etre "
        f"tracee par auditd.",
        {commande, "privilegiee", "execution", "commande"},
        f"-a always,exit -F path={chemin} -F perm=x",
        f"regle d'execution sur {chemin}",
        {"lecteur": "audit", "comparateur": "execution", "champ": chemin,
         "attendu": "x"})


# Valeurs par defaut des modules (man pwquality.conf, man faillock.conf) :
# ce qui s'applique quand rien n'est ecrit.
_DEFAUTS_PWQUALITY = {"difok": "1", "minlen": "8", "dcredit": "0",
                      "ucredit": "0", "lcredit": "0", "ocredit": "0",
                      "minclass": "0", "maxrepeat": "0", "maxsequence": "0",
                      "dictcheck": "1", "enforcing": "1"}
_DEFAUTS_FAILLOCK = {"deny": "3", "fail_interval": "900", "unlock_time": "600"}
_OPERATIONS = {"less than or equal": "au_plus",
               "greater than or equal": "au_moins", "equals": "toutes_egales"}
_LIBELLES_PWQ = {
    "minlen": "longueur minimale des mots de passe",
    "dcredit": "chiffres exiges dans les mots de passe",
    "ucredit": "majuscules exigees dans les mots de passe",
    "lcredit": "minuscules exigees dans les mots de passe",
    "ocredit": "caracteres speciaux exiges dans les mots de passe",
    "minclass": "nombre de classes de caracteres exigees",
    "difok": "caracteres differents de l'ancien mot de passe",
    "maxrepeat": "repetitions consecutives d'un caractere",
    "maxsequence": "longueur maximale d'une sequence (abcd, 1234)",
    "dictcheck": "refus des mots du dictionnaire",
    "enforcing": "application stricte de la politique",
}


def accounts_password(regle, ctx):
    var = _texte(regle.vars.get("variable"))
    if not re.fullmatch(r"[a-z_]+", var):
        return "parametre pwquality non standard"
    valeur = ctx.valeur_variable(f"var_password_pam_{var}")
    if valeur is None:
        return "valeur pwquality attendue introuvable"
    comparateur = _OPERATIONS.get(_texte(regle.vars.get("operation")))
    if comparateur is None:
        return "operation pwquality non prise en charge"
    spec = {"lecteur": "affectations", "comparateur": comparateur,
            "champ": var, "attendu": str(valeur)}
    if var in {"maxrepeat", "maxsequence"} and comparateur == "au_plus":
        # 0 = controle desactive : ce n'est pas « au plus N ».
        spec.update(comparateur="entre", attendu=[1, int(valeur)])
    if var in _DEFAUTS_PWQUALITY:
        spec["defaut"] = _DEFAUTS_PWQUALITY[var]
    libelle = _LIBELLES_PWQ.get(var, var)
    sens = {"au_plus": "au plus ", "au_moins": "au moins ",
            "entre": "entre 1 et "}.get(spec["comparateur"], "")
    return {
        "titre": f"Mots de passe : {libelle} ({var} {sens}{valeur})",
        "resume": f"pwquality doit imposer {var} {sens}{valeur} ({libelle}).",
        "domaine": "comptes",
        "mots_cles": {"mot de passe", "mots de passe", "pwquality", "pam",
                      "complexite", "politique", var, *_mots(libelle)},
        "observer": [
            {"commande": (f"grep -Rs '^[[:space:]]*{var}[[:space:]]*=' "
                          f"/etc/security/pwquality.conf "
                          f"/etc/security/pwquality.conf.d/"),
             "but": f"Lire la valeur de {var} configuree pour pwquality",
             "lecture": f"« {var} = N » ; aucune ligne = valeur par defaut "
                        f"du module ({_DEFAUTS_PWQUALITY.get(var, '?')})."},
            {"commande": ("grep -s 'pam_pwquality' "
                          "/etc/pam.d/common-password"),
             "but": "Verifier que pam_pwquality est bien applique",
             "lecture": "Une ligne « password requisite pam_pwquality.so » ; "
                        "aucune = politique non appliquee."},
        ],
        "controle": f"{var} {sens}{valeur}".strip(),
        "bon": f"{var} {sens}{valeur}, module pam_pwquality actif",
        "mauvais": "valeur plus faible, ou module non applique",
        "action": (f"Ecrire « {var} = {valeur} » dans "
                   f"/etc/security/pwquality.conf (paquet libpam-pwquality)."),
        **liaison_cle_valeur("/etc/security/pwquality.conf", var,
                             valeur_a_ecrire(spec)),
        "evaluation": [dict(spec, commande=0),
                       {"commande": 1, "lecteur": "lignes",
                        "comparateur": "presente"}],
        "pieges": ["Des arguments sur la ligne pam_pwquality.so (ex. "
                   "minlen=8) l'emportent sur pwquality.conf : les lire aussi.",
                   "La politique ne s'applique qu'aux NOUVEAUX mots de passe."],
    }


def pam_options(regle, ctx):
    chemin = _texte(regle.vars.get("path"))
    module = _texte(regle.vars.get("module"))
    type_pam = _texte(regle.vars.get("type"))
    if not re.fullmatch(r"/etc/pam\.d/[\w.-]+", chemin) or \
            not re.fullmatch(r"pam_\w+\.so", module) or \
            not re.fullmatch(r"[a-z]+", type_pam):
        return "fichier ou module PAM non standard"
    exigences, lisibles = [], []
    for a in regle.vars.get("arguments") or []:
        if a.get("variable"):
            nom = _texte(a["variable"])
            valeur = ctx.valeur_variable(
                _texte(a.get("variable_name")) or f"var_password_pam_{nom}")
            if valeur is None:
                return f"valeur de {nom} introuvable"
            operation = {"greater than or equal": "au_moins",
                         "less than or equal": "au_plus"}.get(
                _texte(a.get("operation")), "egal")
            exigences.append({"nom": nom, "operation": operation,
                              "valeur": str(valeur)})
            sens = {"au_moins": ">=", "au_plus": "<="}.get(operation, "=")
            lisibles.append(f"{nom}{sens}{valeur}")
        elif a.get("argument_variable"):
            # argument dont le NOM est une valeur de referentiel (sha512...)
            nom = ctx.valeur_variable(_texte(a["argument_variable"]))
            if nom is None:
                return f"valeur de {a['argument_variable']} introuvable"
            exigences.append({"nom": str(nom)})
            lisibles.append(str(nom))
        elif a.get("argument"):
            if a.get("absent"):
                exigences.append({"nom": _texte(a["argument"]), "absent": True})
                lisibles.append(f"sans {_texte(a['argument'])}")
            else:
                exigences.append({"nom": _texte(a["argument"])})
                lisibles.append(_texte(a["argument"]))
    motif = module.replace(".", "\\.")
    attendu = f"{type_pam} {module} {' '.join(lisibles)}".strip()
    return {
        "titre": f"PAM : {module} dans {chemin} ({' '.join(lisibles) or 'present'})",
        "resume": (f"{chemin} doit appeler {module}"
                   + (f" avec {' '.join(lisibles)}." if lisibles else ".")),
        "domaine": "comptes",
        "mots_cles": {"pam", "authentification", module.split(".")[0],
                      *_mots(module, chemin, *lisibles)},
        "observer": [{
            "commande": (f"grep -Es '^[[:space:]]*{type_pam}[[:space:]].*"
                         f"{motif}' {chemin}"),
            "but": f"Lire la ligne {module} de {chemin}",
            "lecture": f"Attendu : « {attendu} » ; aucune ligne = module "
                       f"absent.",
        }],
        "controle": attendu,
        "bon": attendu,
        "mauvais": "module absent, ou option absente / plus faible",
        # pam-auth-update ne gere que les fichiers common-* (Debian/Ubuntu) ;
        # /etc/pam.d/su, login... s'editent directement.
        "action": (f"Ajouter ou completer la ligne {type_pam} ... {module} "
                   f"dans {chemin} "
                   + ("(sur Debian/Ubuntu, de preference via pam-auth-update) "
                      if "/common-" in str(chemin) else "(edition directe) ")
                   + "en gardant une session root ouverte."),
        "evaluation": [{"commande": 0, "lecteur": "pam",
                        "comparateur": "arguments", "champ": module,
                        "attendu": exigences}],
        "pieges": ["Une erreur dans /etc/pam.d peut bloquer toute connexion : "
                   "garder une session root ouverte pendant la modification."],
    }


def pam_account_password_faillock(regle, ctx):
    prm = _texte(regle.vars.get("prm_name"))
    if not re.fullmatch(r"[a-z_]+", prm):
        return "parametre faillock non standard"
    valeur = ctx.valeur_variable(_texte(regle.vars.get("ext_variable")))
    if valeur is None:
        return "valeur faillock attendue introuvable"

    def borne(cle):
        b = regle.vars.get(cle)
        if b is None:
            return None
        return int(valeur) if _texte(b) == "use_ext_variable" else int(b)
    mini, maxi = borne("variable_lower_bound"), borne("variable_upper_bound")
    if mini is None and maxi is None:
        return "bornes faillock absentes"
    spec = {"lecteur": "affectations", "comparateur": "entre", "champ": prm,
            "attendu": [mini, maxi]}
    if prm in _DEFAUTS_FAILLOCK:
        spec["defaut"] = _DEFAUTS_FAILLOCK[prm]
    if prm == "unlock_time":
        spec["accepte"] = ["0"]          # 0 = deverrouillage par l'admin seul
    sens = (f"entre {mini} et {maxi}" if mini is not None and maxi is not None
            else f"au moins {mini}" if mini is not None else f"au plus {maxi}")
    libelles = {"deny": "echecs avant verrouillage",
                "fail_interval": "fenetre de comptage des echecs (s)",
                "unlock_time": "duree de verrouillage (s)",
                "root_unlock_time": "duree de verrouillage de root (s)"}
    return {
        "titre": (f"Verrouillage apres echecs : {libelles.get(prm, prm)} "
                  f"({prm} {sens})"),
        "resume": f"pam_faillock doit avoir {prm} {sens}.",
        "domaine": "comptes",
        "mots_cles": {"verrouillage", "faillock", "echecs", "force brute",
                      "authentification", "pam", prm, *_mots(prm)},
        "observer": [
            {"commande": (f"grep -Rs '^[[:space:]]*{prm}[[:space:]]*=' "
                          f"/etc/security/faillock.conf"),
             "but": f"Lire {prm} dans faillock.conf",
             "lecture": f"« {prm} = N » ; aucune ligne = valeur par defaut "
                        f"({_DEFAUTS_FAILLOCK.get(prm, 'non definie')})."},
            {"commande": ("grep -Es '^[[:space:]]*auth[[:space:]].*"
                          "pam_faillock\\.so' /etc/pam.d/common-auth"),
             "but": "Verifier que pam_faillock est utilise",
             "lecture": "Lignes « auth ... pam_faillock.so preauth / authfail » "
                        "; aucune = verrouillage inactif."},
        ],
        "controle": f"{prm} {sens}",
        "bon": (f"{prm} {sens}, pam_faillock actif"
                + (" (0 = deverrouillage par l'administrateur, accepte)"
                   if prm == "unlock_time" else "")),
        "mauvais": "valeur hors bornes, ou pam_faillock non utilise",
        "action": (f"Ecrire « {prm} = {valeur} » dans "
                   f"/etc/security/faillock.conf et activer pam_faillock "
                   f"(pam-auth-update sur Debian/Ubuntu)."),
        **liaison_cle_valeur("/etc/security/faillock.conf", prm, valeur),
        "evaluation": [dict(spec, commande=0),
                       {"commande": 1, "lecteur": "lignes",
                        "comparateur": "presente"}],
        "pieges": ["Un argument sur la ligne pam_faillock.so (ex. deny=5) "
                   "l'emporte sur faillock.conf.",
                   "Verrouiller trop vite (deny faible) facilite le deni de "
                   "service sur les comptes."],
    }


def sudo_defaults_option(regle, ctx):
    option = _texte(regle.vars.get("option"))
    if not re.fullmatch(r"[a-z_]+", option):
        return "option sudo non standard"
    valeur = None
    if regle.vars.get("variable_name"):
        valeur = ctx.valeur_variable(_texte(regle.vars["variable_name"]))
        if valeur is None:
            return "valeur de l'option sudo introuvable"
    au_plus = regle.vars.get("comparateur") == "au_plus"
    attendu = (f"Defaults {option}" + (" <= " if au_plus else "=") + str(valeur)
               if valeur else f"Defaults {option}")
    spec = {"commande": 0, "lecteur": "sudo_defaults",
            "comparateur": "au_plus" if au_plus else "option", "champ": option}
    if valeur:
        spec["attendu"] = str(valeur)
    if regle.vars.get("defaut") is not None:
        spec["defaut"] = _texte(regle.vars["defaut"])
    return {
        "titre": f"sudo : {attendu}",
        "resume": f"La configuration de sudo doit contenir « {attendu} ».",
        "domaine": "comptes",
        "mots_cles": {"sudo", "sudoers", "elevation", "privileges", "defaults",
                      option, *_mots(option)},
        "observer": [{
            "commande": ("grep -Rhs '^[[:space:]]*Defaults' /etc/sudoers "
                         "/etc/sudoers.d/"),
            "but": "Lire les options globales de sudo",
            "lecture": (f"Attendu : une ligne contenant {option}"
                        + (f"={valeur}" if valeur else "")
                        + f" ; « !{option} » = desactive."),
        }],
        "controle": attendu, "bon": attendu,
        "mauvais": "option absente ou desactivee",
        "action": (f"Ajouter « {attendu} » avec visudo -f "
                   f"/etc/sudoers.d/sentinelle (jamais d'edition directe)."),
        "evaluation": [spec],
        "playbook": "infra.sudo-defaults",
        "parametres": {"option": option,
                       **({"valeur": str(valeur)} if valeur else {})},
        "pieges": ["/etc/sudoers n'est lisible que par root : lancer la "
                   "lecture avec sudo.",
                   "Une erreur de syntaxe dans sudoers bloque sudo : toujours "
                   "passer par visudo."],
    }


def mount(regle, ctx):
    point = _texte(regle.vars.get("mountpoint"))
    if not re.fullmatch(r"/[\w/.-]*", point):
        return "point de montage non standard"
    return {
        "titre": f"Partition separee pour {point}",
        "resume": f"{point} doit etre une partition (ou un montage) separe.",
        "domaine": "fichiers",
        "mots_cles": {"partition", "montage", "separee", "disque",
                      *_mots(point)},
        "observer": [{"commande": f"findmnt -kn {point}",
                      "but": f"Voir si {point} est un montage separe",
                      "lecture": "Une ligne = montage separe ; aucune = "
                                 "meme partition que son parent."}],
        "controle": f"{point} monte a part", "bon": "montage separe",
        "mauvais": f"{point} sur la partition de son parent",
        "action": (f"Prevoir une partition (ou un volume LVM) dedie a {point} "
                   f"et la declarer dans /etc/fstab : se planifie, surtout "
                   f"sur un systeme en production."),
        "evaluation": [{"commande": 0, "lecteur": "findmnt",
                        "comparateur": "monte"}],
        "pieges": ["Repartitionner un systeme en service est risque : a "
                   "planifier (ou a appliquer aux prochaines installations)."],
    }


def file_existence(regle, ctx):
    chemin = _texte(regle.vars.get("filepath"))
    if not re.fullmatch(r"/[\w./+-]*", chemin):
        return "chemin non standard"
    present = _texte(regle.vars.get("exists")).lower() in {"yes", "true"}
    evaluation = [{"commande": 0, "lecteur": "lignes",
                   "comparateur": "presente" if present else "vide"}]
    precisions = []
    if present and regle.vars.get("filemode"):
        mode = _texte(regle.vars["filemode"])
        evaluation.append({"commande": 0, "lecteur": "stat", "champ": "droits",
                           "comparateur": "droits_au_plus", "attendu": mode})
        precisions.append(f"droits {mode} au plus")
    if present and regle.vars.get("fileuid") is not None:
        uid = _texte(regle.vars["fileuid"])
        evaluation.append({"commande": 0, "lecteur": "stat",
                           "champ": "proprietaire", "comparateur": "dans",
                           "attendu": sorted({uid, {"0": "root"}.get(uid, uid)})})
        precisions.append(f"proprietaire {'root' if uid == '0' else uid}")
    etat = "present" if present else "absent"
    detail = f" ({', '.join(precisions)})" if precisions else ""
    return {
        "titre": f"Fichier {chemin} {etat}{detail}",
        "resume": f"{chemin} doit etre {etat}{detail}.",
        "domaine": "fichiers",
        "mots_cles": {"fichier", etat, *_mots(chemin)},
        "observer": [{"commande": f"stat -c '%a %U %G %n' {chemin} 2>/dev/null",
                      "but": f"Voir si {chemin} existe (droits, proprietaire)",
                      "lecture": "Une ligne = present ; aucune = absent."}],
        "controle": f"{chemin} {etat}", "bon": f"{etat}{detail}",
        "mauvais": "absent" if present else "present",
        "action": (f"Creer {chemin}{detail} (touch, chmod, chown)." if present
                   else f"Supprimer {chemin} apres verification."),
        "evaluation": evaluation,
        "playbook": "infra.fichier-existence",
        "parametres": {"chemin": chemin, "etat": etat},
        "pieges": [],
    }


def lineinfile(regle, ctx):
    texte = _texte(regle.vars.get("text"))
    chemin = _texte(regle.vars.get("path"))
    if not texte or "'" in texte or not re.fullmatch(r"/[\w./+-]*", chemin):
        return "ligne ou fichier non standard"
    motif = re.sub(r"([.*\[\]^$\\])", r"\\\1", texte)
    cibles = chemin + (f" {chemin}.d/" if chemin.endswith(".conf") else "")
    return {
        "titre": f"Ligne « {texte} » dans {chemin}",
        "resume": f"{chemin} doit contenir la ligne « {texte} ».",
        "domaine": "comptes" if "pwquality" in chemin else "systeme",
        "mots_cles": {"configuration", *_mots(texte, chemin)},
        "observer": [{"commande": f"grep -Rs '^[[:space:]]*{motif}' {cibles}",
                      "but": f"Chercher « {texte} » dans {chemin}",
                      "lecture": "Une ligne = present ; aucune = absent."}],
        "controle": f"« {texte} » present", "bon": "ligne presente",
        "mauvais": "ligne absente",
        "action": f"Ajouter « {texte} » dans {chemin}.",
        "evaluation": [{"commande": 0, "lecteur": "lignes",
                        "comparateur": "presente"}],
        **(liaison_cle_valeur(chemin, *(re.fullmatch(r"(\w+)\s*=\s*(\S+)", texte).groups()),
                              "egal_espaces")
           if re.fullmatch(r"(\w+)\s*=\s*(\S+)", texte)
           else liaison_cle_valeur(chemin, texte, "", "cle_seule")
           if re.fullmatch(r"\w+", texte) else {}),
        "pieges": [],
    }


def _unite(nom, suffixe, actif: bool, genre: str):
    if not re.fullmatch(r"[a-zA-Z0-9@_.-]+", nom):
        return f"nom de {genre} non standard"
    unite = f"{nom}.{suffixe}"
    etat = "active" if actif else "desactive"
    return {
        "titre": f"{genre.capitalize()} {unite} {etat}",
        "resume": f"L'unite systemd {unite} doit etre {etat}e.",
        "domaine": "services",
        "mots_cles": {"systemd", genre, suffixe, nom.lower(), *_mots(nom)},
        "observer": [{
            "commande": (f"systemctl is-enabled {unite} 2>/dev/null; "
                         f"systemctl is-active {unite} 2>/dev/null"),
            "but": f"Lire l'etat de {unite}",
            "lecture": ("Attendu : « enabled » puis « active »." if actif else
                        "Attendu : « disabled » ou « masked » puis "
                        "« inactive »."),
        }],
        "controle": f"{unite} {'enabled/active' if actif else 'disabled/inactive'}",
        "bon": "enabled et active" if actif else "disabled ou masked, inactive",
        "mauvais": "disabled ou inactive" if actif else "enabled ou active",
        "action": (f"systemctl enable --now {unite}" if actif else
                   f"systemctl disable --now {unite} (ou mask)"),
        "evaluation": [{"commande": 0, "lecteur": "systemctl",
                        "comparateur": "actif" if actif else "inactif"}],
        "playbook": "infra.service-" + ("activer" if actif else "desactiver"),
        "parametres": {"service": unite},
        "pieges": [],
    }


def timer_enabled(regle, ctx):
    return _unite(_texte(regle.vars.get("timername")), "timer", True,
                  "minuteur")


def socket_disabled(regle, ctx):
    return _unite(_texte(regle.vars.get("socketname")), "socket", False,
                  "socket")


def grub2_bootloader_argument_absent(regle, ctx):
    arg = _texte(regle.vars.get("arg_name"))
    if not re.fullmatch(r"[a-z0-9_.-]+", arg):
        return "argument de demarrage non standard"
    return {
        "titre": f"Argument de demarrage {arg} absent",
        "resume": f"Le noyau ne doit pas demarrer avec {arg} (il desactive "
                  f"une protection).",
        "domaine": "systeme",
        "mots_cles": {"grub", "demarrage", "noyau", "argument", arg, *_mots(arg)},
        "observer": [
            {"commande": "cat /proc/cmdline",
             "but": "Lire les arguments du demarrage EN COURS",
             "lecture": f"{arg} ne doit pas figurer."},
            {"commande": "grep -E '^GRUB_CMDLINE_LINUX' /etc/default/grub",
             "but": "Verifier la configuration persistante de GRUB",
             "lecture": f"{arg} ne doit pas figurer."},
        ],
        "controle": f"{arg} absent", "bon": f"{arg} absent",
        "playbook": "infra.grub-argument",
        "parametres": {"argument": arg, "action": "retirer"},
        "mauvais": f"{arg} present",
        "action": (f"Retirer {arg} de GRUB_CMDLINE_LINUX dans "
                   f"/etc/default/grub, update-grub, redemarrer."),
        "evaluation": [
            {"commande": 0, "lecteur": "cmdline", "comparateur": "absent",
             "champ": arg},
            {"commande": 1, "lecteur": "grub", "comparateur": "absent",
             "champ": arg},
        ],
        "pieges": ["Effet au prochain redemarrage seulement."],
    }


# Valeurs par defaut de systemd (man journald.conf) quand rien n'est ecrit.
_DEFAUTS_SYSTEMD = {("/etc/systemd/journald.conf", "Compress"): "yes",
                    ("/etc/systemd/journald.conf", "ForwardToSyslog"): "no",
                    ("/etc/systemd/journald.conf", "Storage"): "auto"}
_BOOLEENS = {"yes": ["yes", "true", "1", "on"],
             "no": ["no", "false", "0", "off"]}


def systemd_dropin_configuration(regle, ctx):
    maitre = _texte(regle.vars.get("master_cfg_file"))
    dossier = _texte(regle.vars.get("dropin_dir")).rstrip("/")
    param = _texte(regle.vars.get("param"))
    valeur = _texte(regle.vars.get("value"))
    if not (re.fullmatch(r"/[\w./-]+", maitre)
            and re.fullmatch(r"/[\w./-]+", dossier)
            and re.fullmatch(r"[A-Za-z]+", param) and valeur):
        return "fichier, parametre ou valeur systemd non standard"
    spec = {"commande": 0, "lecteur": "affectations",
            "comparateur": "toutes_egales", "champ": param, "attendu": valeur}
    if valeur.lower() in _BOOLEENS:
        spec["accepte"] = _BOOLEENS[valeur.lower()]
    if (maitre, param) in _DEFAUTS_SYSTEMD:
        spec["defaut"] = _DEFAUTS_SYSTEMD[(maitre, param)]
    service = maitre.rsplit("/", 1)[-1].split(".")[0]
    section = _texte(regle.vars.get("section")) or "Journal"
    return {
        "titre": f"{service} : {param}={valeur}",
        "resume": (f"{param} doit valoir {valeur} dans la configuration de "
                   f"{service} ({maitre} ou {dossier}/)."),
        "domaine": "journaux" if "journald" in maitre else "systeme",
        "mots_cles": {"systemd", service, param.lower(), *_mots(param, service)},
        "observer": [{
            "commande": (f"grep -Rs '^[[:space:]]*{param}[[:space:]]*=' "
                         f"{maitre} {dossier}/"),
            "but": f"Lire {param} dans la configuration de {service}",
            "lecture": (f"Attendu : « {param}={valeur} » ; aucune ligne = "
                        f"valeur par defaut "
                        f"({_DEFAUTS_SYSTEMD.get((maitre, param), '?')})."),
        }],
        "controle": f"{param}={valeur}", "bon": f"{param}={valeur}",
        "mauvais": "autre valeur",
        "action": (f"Ecrire « [{section}] » puis « {param}={valeur} » dans "
                   f"{dossier}/60-sentinelle.conf, puis systemctl restart "
                   f"systemd-{service}."),
        "evaluation": [spec],
        # Ecrit dans le fichier maitre (section unique [Journal]).
        **liaison_cle_valeur(maitre, param, valeur, "egal"),
        "pieges": [f"Le dernier fichier lu de {dossier}/ l'emporte (ordre "
                   f"alphabetique)."],
    }


GABARITS.update({
    "audit_rules_watch": audit_rules_watch,
    "audit_rules_dac_modification": audit_rules_dac_modification,
    "audit_rules_file_deletion_events": audit_rules_file_deletion_events,
    "audit_rules_kernel_module_loading": audit_rules_kernel_module_loading,
    "audit_rules_unsuccessful_file_modification":
        audit_rules_unsuccessful_file_modification,
    "audit_rules_privileged_commands": audit_rules_privileged_commands,
    "accounts_password": accounts_password,
    "pam_options": pam_options,
    "pam_account_password_faillock": pam_account_password_faillock,
    "sudo_defaults_option": sudo_defaults_option,
    "mount": mount,
    "file_existence": file_existence,
    "lineinfile": lineinfile,
    "timer_enabled": timer_enabled,
    "socket_disabled": socket_disabled,
    "grub2_bootloader_argument_absent": grub2_bootloader_argument_absent,
    "systemd_dropin_configuration": systemd_dropin_configuration,
})


# --------------------------------------------------------------------------- #
# Gabarits des RECETTES Sentinelle (recettes_cac.yaml) : regles que
# ComplianceAsCode ecrit a la main (sans gabarit). La recette donne la
# commande de lecture (souvent celle de la section OCIL de la regle) et le
# critere ; les valeurs viennent des variables des referentiels.
# --------------------------------------------------------------------------- #
def _recette_textes(v: dict) -> dict:
    return {k: _texte(v.get(k)) for k in ("titre", "resume", "controle", "bon",
                                         "mauvais", "action")}


def cle_valeur(regle, ctx):
    """CLE valeur (ou CLE=valeur) dans un ou plusieurs fichiers."""
    v = regle.vars
    fichiers = v.get("fichiers") or []
    cle = _texte(v.get("cle"))
    if not fichiers or not re.fullmatch(r"\$?[A-Za-z_][A-Za-z0-9_-]*", cle):
        return "recette cle_valeur incomplete"
    espace = v.get("sep") == "espace"
    cle_grep = cle.replace("$", "\\$")
    motif = (f"^[[:space:]]*{cle_grep}[[:space:]]" if espace else
             f"^[[:space:]]*(export[[:space:]]+|readonly[[:space:]]+)?{cle}"
             f"[[:space:]]*=")
    grep = "grep -Es" + ("" if not any(f.endswith("/") for f in fichiers)
                         else "R")
    spec = {"commande": 0, "lecteur": "affectations",
            "comparateur": v.get("comparateur", "toutes_egales"),
            "champ": cle, "attendu": v.get("attendu")}
    for option in ("defaut", "accepte"):
        if v.get(option) is not None:
            spec[option] = v[option]
    if espace:
        spec["sep"] = "espace"
    t = _recette_textes(v)
    # Fichier lisible par root seulement : sans marqueur, « rien » serait lu
    # comme « non defini ».
    garde_root = _garde_paquet(v) + (
        f"head -c0 {fichiers[0]} || echo 'SENTINELLE:ILLISIBLE'; "
        if v.get("root") else "")
    observer = [{"commande": f"{garde_root}{grep} '{motif}' {' '.join(fichiers)}",
                 "but": f"Lire {cle} dans {', '.join(fichiers)}",
                 "lecture": _texte(v.get("lecture")) or
                 f"Valeur de {cle} ; aucune ligne = non defini."}]
    evaluation = [spec]
    for extra in v.get("observer_en_plus") or []:
        observer.append({k: extra[k] for k in ("commande", "but", "lecture")})
        evaluation.append({"commande": len(observer) - 1, "lecteur": "lignes",
                           "comparateur": extra.get("attendu", "presente")})
    # Playbook : fichier regulier unique de /etc ou /root (sinon manuel).
    cible = _texte(v.get("playbook_fichier")) or fichiers[0]
    if ("*" not in cible and not cible.endswith("/")
            and re.fullmatch(r"/(etc|root)/[A-Za-z0-9._/-]+", cible)
            and not v.get("sans_playbook")):
        fmt = v.get("format") or ("espace" if espace else None)
        # « ecrire » : parmi plusieurs valeurs admises (SHA512|YESCRYPT), celle
        # que le playbook ecrit (la plus forte) ; elle doit etre admise.
        ecrire = _texte(v.get("ecrire")) or valeur_a_ecrire(spec)
        if v.get("ecrire") is not None and not any(
                ecrire == a for a in str(spec["attendu"]).split("|")):
            return "valeur a ecrire hors des valeurs admises"
        liaison = liaison_cle_valeur(cible, cle, ecrire, fmt)
    else:
        liaison = {"sans_playbook": _texte(v.get("sans_playbook"))
                   or RAISONS_SANS_PLAYBOOK["cle_valeur"]}
    return {
        **liaison,
        "titre": t["titre"], "resume": t["resume"] or t["titre"] + ".",
        "domaine": "comptes",
        "mots_cles": {cle.lower(), *(str(m) for m in v.get("mots_cles") or []),
                      *_mots(cle.replace("_", " "))},
        "observer": observer,
        "controle": t["controle"], "bon": t["bon"],
        "mauvais": t["mauvais"] or "autre valeur, ou non defini",
        "action": t["action"], "evaluation": evaluation,
        "pieges": list(v.get("pieges") or []),
    }


def _garde_paquet(v: dict) -> str:
    """Prefixe « sans objet » si le paquet vise n'est pas installe."""
    paquet = _texte(v.get("paquet"))
    if not paquet:
        return ""
    if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", paquet):
        raise ValueError(f"paquet non standard : {paquet}")
    return (f"dpkg -s {paquet} >/dev/null 2>&1 || "
            f"echo 'SENTINELLE:SANS_OBJET'; ")


def detecteur(regle, ctx):
    """Commande qui liste les elements en defaut : aucune ligne = conforme
    (attendu « vide ») ; ou qui doit trouver une ligne (« presente »)."""
    v = regle.vars
    commande = _garde_paquet(v) + _texte(v.get("commande"))
    if not _texte(v.get("commande")):
        return "recette detecteur sans commande"
    t = _recette_textes(v)
    attendu = v.get("attendu", "vide")
    return {
        "titre": t["titre"], "resume": t["resume"] or t["titre"] + ".",
        "domaine": "comptes",
        "mots_cles": {str(m) for m in v.get("mots_cles") or []},
        "observer": [{"commande": commande, "but": _texte(v.get("but")),
                      "lecture": _texte(v.get("lecture")) or (
                          "Chaque ligne est un element en defaut ; aucune "
                          "ligne = conforme." if attendu == "vide" else
                          "Une ligne = conforme ; aucune = ecart.")}],
        "controle": t["controle"], "bon": t["bon"],
        "mauvais": t["mauvais"] or ("au moins une ligne" if attendu == "vide"
                                    else "aucune ligne"),
        "action": t["action"],
        "evaluation": [{"commande": 0, "lecteur": "lignes",
                        "comparateur": attendu}],
        "pieges": list(v.get("pieges") or []),
    }


def fichiers_stat(regle, ctx):
    """Commande qui produit « droits proprietaire groupe chemin » pour des
    fichiers calcules (ex. repertoires personnels) : droits au plus N."""
    v = regle.vars
    commande = _texte(v.get("commande"))
    mode = _texte(v.get("droits_max"))
    if not commande or not re.fullmatch(r"[0-7]{3,4}", mode):
        return "recette fichiers_stat incomplete"
    t = _recette_textes(v)
    return {
        "titre": t["titre"], "resume": t["resume"] or t["titre"] + ".",
        "domaine": "fichiers",
        "mots_cles": {"droits", "permissions", *(str(m) for m in
                                                 v.get("mots_cles") or [])},
        "observer": [{"commande": commande, "but": _texte(v.get("but")),
                      "lecture": f"1re colonne = droits : au plus {mode}."}],
        "controle": t["controle"] or f"droits <= {mode}",
        "bon": t["bon"] or f"{mode} ou plus strict",
        "mauvais": "droits plus larges", "action": t["action"],
        "evaluation": [{"commande": 0, "lecteur": "stat", "champ": "droits",
                        "comparateur": "droits_au_plus", "attendu": mode}],
        "pieges": list(v.get("pieges") or []),
    }


GABARITS.update({"cle_valeur": cle_valeur, "detecteur": detecteur,
                 "fichiers_stat": fichiers_stat})


def audit_composite(regle, ctx):
    """Plusieurs regles d'audit pour un meme objectif (ex. modifications du
    reseau : appels sethostname/setdomainname + surveillance de /etc/hosts...).
    Chaque element devient une preuve, jugee sur auditctl -l ET rules.d."""
    v = regle.vars
    specs = []
    for chemin in v.get("surveilles") or []:
        specs.append({"lecteur": "audit", "comparateur": "surveille",
                      "champ": _texte(chemin), "attendu": "wa"})
    for chemin in v.get("executions") or []:
        specs.append({"lecteur": "audit", "comparateur": "execution",
                      "champ": _texte(chemin), "attendu": "x"})
    for appel in v.get("appels") or []:
        appel = appel if isinstance(appel, dict) else {"nom": appel}
        spec = {"lecteur": "audit", "comparateur": "appels",
                "champ": _texte(appel["nom"])}
        if appel.get("options"):
            spec["options"] = appel["options"]
        specs.append(spec)
    if not specs:
        return "recette audit_composite vide"
    t = _recette_textes(v)
    lignes = [f"-w {s['champ']} -p {s['attendu']}" for s in specs
              if s["comparateur"] != "appels"]
    lignes += [f"-a always,exit -S {s['champ']}"
               + "".join(f" -F {o}" for g in s.get("options", [[]]) for o in g)
               for s in specs if s["comparateur"] == "appels"]
    fiche = _audit(t["titre"], t["resume"] or t["titre"] + ".",
                   {*(str(m) for m in v.get("mots_cles") or [])},
                   t["controle"] or "; ".join(lignes),
                   t["bon"] or "toutes les regles chargees et persistantes",
                   specs[0])
    fiche["evaluation"] = [dict(s, commande=i) for s in specs for i in (0, 1)]
    fiche["parametres"] = {"regles": lignes_audit(specs)}
    fiche["pieges"] += list(v.get("pieges") or [])
    return fiche


GABARITS.update({"audit_composite": audit_composite})
