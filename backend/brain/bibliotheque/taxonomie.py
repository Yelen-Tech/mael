"""Taxonomie du catalogue (etape 2 du pipeline).

Chaque fiche est rangee sur des axes FERMES (listes ci-dessous), verifies par
le validateur :

  domaine        -- grand domaine systeme (champ `domaine` de la fiche)
  theme          -- sujet precis, celui que vise une question d'administrateur
                    (« le routage IP » -> parametres-reseau)
  type_controle  -- nature de la verification (dira a l'etape 5 comment lire
                    la sortie d'une commande)
  niveaux        -- niveau de conformite : CIS 1/2, ANSSI minimal..eleve
  cible OS       -- champ `applicable.os` (inchange)

Le filtrage prealable (niveau choisi par le client, systeme detecte) et
l'aiguillage d'intention (question -> theme) s'appuient sur ces axes.
"""
from __future__ import annotations

import re

# theme -> (libelle francais, domaine parent)
THEMES = {
    "ssh": ("acces a distance SSH", "acces"),
    "authentification": ("authentification et PAM", "comptes"),
    "comptes": ("fichiers de comptes (passwd, shadow, group)", "fichiers"),
    "sessions": ("sessions utilisateurs (umask, inactivite, repertoires "
                 "personnels)", "comptes"),
    "sudo": ("elevation de privileges sudo", "comptes"),
    "pare-feu": ("pare-feu", "reseau"),
    "exposition-reseau": ("ports et services exposes", "reseau"),
    "parametres-reseau": ("parametres reseau du noyau", "reseau"),
    "parametres-noyau": ("parametres de securite du noyau", "noyau"),
    "modules-noyau": ("modules du noyau", "noyau"),
    "compilation-noyau": ("options de compilation du noyau", "noyau"),
    "demarrage": ("demarrage et arguments du noyau", "systeme"),
    "controle-acces": ("controle d'acces obligatoire (AppArmor, SELinux)", "systeme"),
    "integrite": ("integrite des fichiers (AIDE)", "systeme"),
    "montage": ("options de montage des partitions", "fichiers"),
    "fichiers-systeme": ("droits des fichiers et repertoires systeme", "fichiers"),
    "planification": ("taches planifiees (cron, at)", "services"),
    "journalisation": ("journalisation (rsyslog, journald)", "journaux"),
    "audit": ("audit du systeme (auditd)", "journaux"),
    "synchronisation-heure": ("synchronisation de l'heure", "services"),
    "services-inutiles": ("services et logiciels a retirer", "services"),
    "paquets": ("paquets de securite", "paquets"),
    "tls": ("chiffrement TLS", "tls"),
    "cryptographie": ("cryptographie appliquee (cles, echanges, certificats)",
                      "tls"),
    "web": ("securite des sites web", "web"),
    "messagerie": ("DNS et messagerie", "dns"),
}

TYPES_CONTROLE = {
    "configuration", "parametre-noyau", "droits-fichier", "proprietaire-fichier",
    "groupe-fichier", "paquet-present", "paquet-absent", "service-actif",
    "service-inactif", "module-desactive", "option-montage",
    "option-compilation", "argument-demarrage", "observation",
    # couverture du 18/09/2026
    "regle-audit", "option-pam", "option-sudo", "partition-separee",
    "existence-fichier", "argument-absent",
    "detection",          # une commande liste les elements en defaut
}

# Du moins exigeant au plus exigeant.
NIVEAUX_CIS = [1, 2]
NIVEAUX_ANSSI = ["minimal", "intermediaire", "renforce", "eleve"]

# Gabarit ComplianceAsCode -> type de controle.
TYPE_PAR_GABARIT = {
    "sshd_lineinfile": "configuration",
    "sysctl": "parametre-noyau",
    "file_permissions": "droits-fichier",
    "file_owner": "proprietaire-fichier",
    "file_groupowner": "groupe-fichier",
    "package_installed": "paquet-present",
    "package_removed": "paquet-absent",
    "service_enabled": "service-actif",
    "service_disabled": "service-inactif",
    "kernel_module_disabled": "module-desactive",
    "mount_option": "option-montage",
    "kernel_build_config": "option-compilation",
    "grub2_bootloader_argument": "argument-demarrage",
    "audit_rules_watch": "regle-audit",
    "audit_rules_dac_modification": "regle-audit",
    "audit_rules_file_deletion_events": "regle-audit",
    "audit_rules_kernel_module_loading": "regle-audit",
    "audit_rules_unsuccessful_file_modification": "regle-audit",
    "audit_rules_privileged_commands": "regle-audit",
    "accounts_password": "option-pam",
    "pam_options": "option-pam",
    "pam_account_password_faillock": "option-pam",
    "sudo_defaults_option": "option-sudo",
    "mount": "partition-separee",
    "file_existence": "existence-fichier",
    "lineinfile": "configuration",
    "timer_enabled": "service-actif",
    "socket_disabled": "service-inactif",
    "grub2_bootloader_argument_absent": "argument-absent",
    "systemd_dropin_configuration": "configuration",
    "cle_valeur": "configuration",
    "detecteur": "detection",
    "fichiers_stat": "droits-fichier",
    "audit_composite": "regle-audit",
}

# Regles d'attribution du theme, dans l'ordre (la premiere qui correspond
# gagne). Motif teste sur « <chemin de la regle>/<id> ».
_REGLES_THEME = [
    # Le dossier d'audit d'abord : « audit_rules_privileged_commands_sudo »
    # releve de l'audit, pas de sudo.
    (r"^auditing/", "audit"),
    # Avant la planification : « unmap_kernel_at_el0 » contient « _at_ ».
    (r"kernel_config|kernel_build_config", "compilation-noyau"),
    (r"services/ssh/|sshd", "ssh"),
    (r"sudo", "sudo"),
    (r"cron|(^|[/_])at_|/at/", "planification"),
    (r"aide", "integrite"),
    (r"apparmor|selinux", "controle-acces"),
    (r"chrony|timesyncd|ntp", "synchronisation-heure"),
    (r"auditing/|audit", "audit"),
    (r"rsyslog|journald|journal|logrotate|var_log|system/logging/", "journalisation"),
    (r"ufw|nftables|iptables|firewalld", "pare-feu"),
    (r"pam", "authentification"),
    (r"passwd|shadow|etc_group|gshadow", "comptes"),
    (r"mount_option|system/permissions/partitions|disk_partitioning|"
     r"partition_for", "montage"),
    (r"kernel_module", "modules-noyau"),
    (r"grub2|bootloader", "demarrage"),
    (r"sysctl_net", "parametres-reseau"),
    (r"sysctl", "parametres-noyau"),
]


def theme_pour_regle(chemin_relatif: str, regle_id: str, gabarit: str | None) -> str:
    cle = f"{chemin_relatif}/{regle_id}".lower()
    for motif, theme in _REGLES_THEME:
        if re.search(motif, cle):
            return theme
    if gabarit in {"package_removed", "service_disabled"}:
        return "services-inutiles"
    if gabarit in {"package_installed", "service_enabled"}:
        return "paquets"
    return "fichiers-systeme"


_RE_NIVEAU = re.compile(r"\(niveau ([^)]+)\)")


def niveaux_depuis_referentiels(referentiels: list[dict]) -> dict:
    """Niveau le MOINS exigeant auquel la regle est demandee, par referentiel.
    (Une regle CIS niveau 1 s'applique aussi a qui vise le niveau 2.)"""
    cis, anssi = [], []
    for r in referentiels:
        m = _RE_NIVEAU.search(str(r.get("ref") or ""))
        if not m:
            continue
        valeur = m.group(1).strip()
        if r.get("nom") == "CIS" and valeur.isdigit():
            cis.append(int(valeur))
        elif r.get("nom") == "ANSSI" and valeur in NIVEAUX_ANSSI:
            anssi.append(valeur)
    return {
        "cis": min(cis) if cis else None,
        "anssi": min(anssi, key=NIVEAUX_ANSSI.index) if anssi else None,
    }


def valider(taxonomie, domaine: str | None) -> list[str]:
    erreurs = []
    if not isinstance(taxonomie, dict):
        return ["« taxonomie » requise (theme, type_controle, niveaux)"]
    inconnus = set(taxonomie) - {"theme", "type_controle", "niveaux"}
    if inconnus:
        erreurs.append(f"taxonomie : champs inconnus {sorted(inconnus)}")
    theme = taxonomie.get("theme")
    if theme not in THEMES:
        erreurs.append(f"taxonomie.theme « {theme} » inconnu")
    elif domaine and THEMES[theme][1] != domaine:
        erreurs.append(f"taxonomie.theme « {theme} » releve du domaine "
                       f"« {THEMES[theme][1]} », pas « {domaine} »")
    if taxonomie.get("type_controle") not in TYPES_CONTROLE:
        erreurs.append(f"taxonomie.type_controle « "
                       f"{taxonomie.get('type_controle')} » inconnu")
    niveaux = taxonomie.get("niveaux") or {}
    if not isinstance(niveaux, dict) or set(niveaux) - {"cis", "anssi"}:
        erreurs.append("taxonomie.niveaux : attendu {cis, anssi}")
    else:
        if niveaux.get("cis") not in (None, *NIVEAUX_CIS):
            erreurs.append(f"taxonomie.niveaux.cis « {niveaux.get('cis')} » invalide")
        if niveaux.get("anssi") not in (None, *NIVEAUX_ANSSI):
            erreurs.append(f"taxonomie.niveaux.anssi « {niveaux.get('anssi')} » invalide")
    return erreurs


def dans_le_niveau(taxonomie: dict, cis_max: int | None,
                   anssi_max: str | None) -> bool:
    """La fiche releve-t-elle du niveau de conformite vise par le client ?
    Une fiche sans niveau (fiche manuelle, hors referentiel) est gardee."""
    niveaux = (taxonomie or {}).get("niveaux") or {}
    cis, anssi = niveaux.get("cis"), niveaux.get("anssi")
    if cis is None and anssi is None:
        return True
    ok_cis = cis is not None and cis_max is not None and cis <= cis_max
    ok_anssi = (anssi is not None and anssi_max is not None
                and NIVEAUX_ANSSI.index(anssi) <= NIVEAUX_ANSSI.index(anssi_max))
    return ok_cis or ok_anssi
