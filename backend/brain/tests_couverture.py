"""Tests de la couverture du 18/09/2026 : lecteurs audit, PAM, sudo, et
rendu des conditions Jinja de ComplianceAsCode.

Sorties au format reel : auditctl -l, fichiers rules.d, /etc/pam.d,
sudoers, faillock.conf, pwquality.conf, findmnt.
"""
from brain.bibliotheque.ecarts import STATUT, lire
from brain.bibliotheque.importeurs import rendu_jinja


def _s(sortie, **spec):
    return lire(sortie, spec).statut


# --------------------------------------------------------------- auditd
AUDITCTL = """\
-w /etc/passwd -p wa -k identity
-w /etc/sudoers.d -p wa -k scope
-a always,exit -F arch=b64 -S chmod,fchmod,fchmodat -F auid>=1000 -F auid!=-1 -F key=perm_mod
-a always,exit -F arch=b32 -S chmod,fchmod,fchmodat -F auid>=1000 -F auid!=-1 -F key=perm_mod
-a always,exit -F arch=b64 -S unlink,rename -F auid>=1000 -F key=delete
-a always,exit -F arch=b64 -S open,openat -F exit=-EACCES -F auid>=1000 -F key=access
-a always,exit -F arch=b32 -S open,openat -F exit=-EACCES -F auid>=1000 -F key=access
-a always,exit -S all -F path=/usr/bin/sudo -F perm=x -F auid>=1000 -F key=privileged
"""


def test_audit_surveillance():
    spec = dict(lecteur="audit", comparateur="surveille", attendu="wa")
    assert _s(AUDITCTL, champ="/etc/passwd", **spec) is STATUT.CONFORME
    assert _s(AUDITCTL, champ="/etc/sudoers.d/", **spec) is STATUT.CONFORME
    assert _s(AUDITCTL, champ="/etc/shadow", **spec) is STATUT.ECART
    # -p w seulement : les changements d'attributs (a) echappent
    assert _s("-w /etc/group -p w -k identity", champ="/etc/group",
              **spec) is STATUT.ECART


def test_audit_appels_b32_et_b64():
    spec = dict(lecteur="audit", comparateur="appels")
    assert _s(AUDITCTL, champ="fchmod", **spec) is STATUT.CONFORME
    lecture = lire(AUDITCTL, dict(spec, champ="rename"))
    assert lecture.statut is STATUT.ECART and "b32" in lecture.constate
    assert _s(AUDITCTL, champ="chown", **spec) is STATUT.ECART


def test_audit_echecs_eacces_et_eperm():
    spec = dict(lecteur="audit", comparateur="appels", champ="openat",
                options=[["exit=-EACCES"], ["exit=-EPERM"]])
    lecture = lire(AUDITCTL, spec)
    assert lecture.statut is STATUT.ECART and "EPERM" in lecture.constate
    complet = AUDITCTL + (
        "-a always,exit -F arch=b64 -S openat -F exit=-EPERM -F key=access\n"
        "-a always,exit -F arch=b32 -S openat -F exit=-EPERM -F key=access\n")
    assert _s(complet, **spec) is STATUT.CONFORME


def test_audit_execution_et_sorties_vides():
    spec = dict(lecteur="audit", comparateur="execution", attendu="x")
    assert _s(AUDITCTL, champ="/usr/bin/sudo", **spec) is STATUT.CONFORME
    assert _s(AUDITCTL, champ="/usr/sbin/usermod", **spec) is STATUT.ECART
    # sans root : rien -> on ne conclut pas ; « No rules » -> ecart
    assert _s("", champ="/usr/bin/sudo", **spec) is STATUT.INDETERMINE
    assert _s("No rules", champ="/usr/bin/sudo", **spec) is STATUT.ECART
    # format fichier rules.d (-k au lieu de -F key=)
    assert _s("-a always,exit -F path=/usr/bin/sudo -F perm=x -k priv",
              champ="/usr/bin/sudo", **spec) is STATUT.CONFORME


# ------------------------------------------------ pwquality / faillock
def test_pwquality_bornes_et_defauts():
    minlen = dict(lecteur="affectations", comparateur="au_moins",
                  champ="minlen", attendu="14", defaut="8")
    assert _s("/etc/security/pwquality.conf:minlen = 14", **minlen) \
        is STATUT.CONFORME
    assert _s("/etc/security/pwquality.conf:minlen=16", **minlen) \
        is STATUT.CONFORME
    assert _s("/etc/security/pwquality.conf:minlen = 10", **minlen) \
        is STATUT.ECART
    # rien d'ecrit : le defaut du module (8) s'applique -> ecart
    lecture = lire("", minlen)
    assert lecture.statut is STATUT.ECART and "defaut : 8" in lecture.constate
    dcredit = dict(lecteur="affectations", comparateur="au_plus",
                   champ="dcredit", attendu="-1", defaut="0")
    assert _s("dcredit = -1", **dcredit) is STATUT.CONFORME
    assert _s("", **dcredit) is STATUT.ECART
    repetitions = dict(lecteur="affectations", comparateur="entre",
                       champ="maxrepeat", attendu=[1, 3], defaut="0")
    assert _s("maxrepeat = 3", **repetitions) is STATUT.CONFORME
    assert _s("", **repetitions) is STATUT.ECART       # 0 = desactive


def test_faillock():
    deny = dict(lecteur="affectations", comparateur="entre", champ="deny",
                attendu=[1, 5], defaut="3")
    assert _s("/etc/security/faillock.conf:deny = 5", **deny) is STATUT.CONFORME
    assert _s("/etc/security/faillock.conf:deny = 10", **deny) is STATUT.ECART
    assert _s("", **deny) is STATUT.CONFORME            # defaut 3
    unlock = dict(lecteur="affectations", comparateur="entre",
                  champ="unlock_time", attendu=[900, None], defaut="600",
                  accepte=["0"])
    assert _s("unlock_time = 0", **unlock) is STATUT.CONFORME
    assert _s("unlock_time = 1200", **unlock) is STATUT.CONFORME
    assert _s("", **unlock) is STATUT.ECART             # defaut 600 < 900


# ------------------------------------------------------------------ PAM
def test_pam_arguments():
    spec = dict(lecteur="pam", comparateur="arguments",
                champ="pam_pwhistory.so",
                attendu=[{"nom": "remember", "operation": "au_moins",
                          "valeur": "24"}, {"nom": "use_authtok"}])
    ok = "password requisite pam_pwhistory.so remember=24 use_authtok"
    assert _s(ok, **spec) is STATUT.CONFORME
    assert _s("password [success=1 default=ignore] "
              "/lib/x86_64-linux-gnu/security/pam_pwhistory.so remember=30 "
              "use_authtok", **spec) is STATUT.CONFORME
    lecture = lire("password requisite pam_pwhistory.so remember=5", spec)
    assert lecture.statut is STATUT.ECART and "remember=5" in lecture.constate
    assert _s("# " + ok, **spec) is STATUT.ECART          # commentee
    assert _s("", **spec) is STATUT.ECART
    roue = dict(lecteur="pam", comparateur="arguments", champ="pam_wheel.so",
                attendu=[{"nom": "use_uid"}, {"nom": "group",
                                              "valeur": "sugroup"}])
    assert _s("auth required pam_wheel.so use_uid group=sugroup", **roue) \
        is STATUT.CONFORME


# ----------------------------------------------------------------- sudo
def test_sudo_defaults():
    sortie = ("Defaults\tenv_reset\n"
              "Defaults\tmail_badpass\n"
              'Defaults\tsecure_path="/usr/local/sbin:/usr/sbin"\n'
              "Defaults use_pty, logfile=\"/var/log/sudo.log\"\n"
              "Defaults:admin !requiretty\n")
    pty = dict(lecteur="sudo_defaults", comparateur="option", champ="use_pty")
    assert _s(sortie, **pty) is STATUT.CONFORME
    log = dict(lecteur="sudo_defaults", comparateur="option", champ="logfile",
               attendu="/var/log/sudo.log")
    assert _s(sortie, **log) is STATUT.CONFORME
    # Defaults:admin n'est pas global
    assert _s(sortie, lecteur="sudo_defaults", comparateur="option",
              champ="requiretty") is STATUT.ECART
    assert _s(sortie + "Defaults !use_pty\n", **pty) is STATUT.ECART
    assert _s("", **pty) is STATUT.INDETERMINE           # sudoers illisible
    umask = dict(lecteur="sudo_defaults", comparateur="option", champ="umask",
                 attendu="0027")
    assert _s("Defaults umask=0022", **umask) is STATUT.ECART


# ---------------------------------------------- partitions, lignes, grub
def test_partitions_et_lignes():
    spec = dict(lecteur="findmnt", comparateur="monte")
    assert _s("/var/log /dev/mapper/vg-log ext4 rw,relatime", **spec) \
        is STATUT.CONFORME
    assert _s("", **spec) is STATUT.ECART
    presente = dict(lecteur="lignes", comparateur="presente")
    assert _s("/etc/security/pwquality.conf:enforce_for_root", **presente) \
        is STATUT.CONFORME
    assert _s("/etc/security/pwquality.conf:# enforce_for_root", **presente) \
        is STATUT.ECART
    assert _s("", lecteur="lignes", comparateur="vide") is STATUT.CONFORME
    absent = dict(lecteur="cmdline", comparateur="absent", champ="nosmap")
    assert _s("ro quiet", **absent) is STATUT.CONFORME
    assert _s("ro quiet nosmap", **absent) is STATUT.ECART


# ------------------------------------------------------ rendu Jinja
def test_rendu_jinja_choisit_la_branche_du_systeme():
    texte = ("title: x\n"
             "{{% if 'ubuntu' in product %}}\n"
             "template:\n    name: systemd_dropin_configuration\n"
             "{{% elif product == 'debian12' %}}\n"
             "template:\n    name: debian_seul\n"
             "{{% else %}}\n"
             "template:\n    name: shell_lineinfile\n"
             "{{% endif %}}\n")
    ubuntu = {"product": "ubuntu2204", "families": ["debian-like", "ubuntu"]}
    debian = {"product": "debian12", "families": ["debian-like"]}
    rhel = {"product": "rhel9", "families": ["rhel-like"]}
    assert "systemd_dropin_configuration" in rendu_jinja.rendre(texte, ubuntu)
    assert "shell_lineinfile" not in rendu_jinja.rendre(texte, ubuntu)
    assert "debian_seul" in rendu_jinja.rendre(texte, debian)
    assert "shell_lineinfile" in rendu_jinja.rendre(texte, rhel)


def test_rendu_jinja_expressions_et_imbrication():
    p = {"product": "ubuntu2404", "families": ["debian-like", "ubuntu"],
         "sshd_distributed_config": "true", "pwquality_path": "/etc/pwq.conf"}
    ev = rendu_jinja.evaluer
    assert ev("product in ['ubuntu2404']", p)
    assert ev("'ubuntu' in product and 'debian' not in product", p)
    assert ev("'ol' in families or 'ubuntu' in product", p)
    assert not ev("product not in ['ubuntu2404', 'debian12']", p)
    assert ev('sshd_distributed_config == "true"', p)
    assert not ev("inconnu.appel()", p)            # illisible -> faux
    texte = ("{{% if 'ubuntu' in product %}}\n"
             "a: 1\n"
             "{{% if product == 'ubuntu2204' %}}\nb: 2\n{{% endif %}}\n"
             "{{% endif %}}\n"
             "path: {{{ pwquality_path }}}\n")
    rendu = rendu_jinja.rendre(texte, p)
    assert "a: 1" in rendu and "b: 2" not in rendu
    assert "path: /etc/pwq.conf" in rendu


# -------------------------------------------- recettes (regles sans gabarit)
def test_registre_des_recettes_coherent():
    from brain.bibliotheque import taxonomie
    from brain.bibliotheque.importeurs import complianceascode as cac
    from brain.bibliotheque.importeurs import gabarits_cac
    recettes = cac.lire_recettes()
    assert len(recettes) >= 60
    for rid, r in recettes.items():
        if "ignorer" in r:
            assert r["ignorer"], rid                  # raison obligatoire
            continue
        assert r["gabarit"] in gabarits_cac.GABARITS, rid
        assert r.get("theme") in taxonomie.THEMES, rid


def test_recette_variables_resolues_ou_regle_ignoree():
    from brain.bibliotheque.importeurs.complianceascode import resoudre_recette
    valeurs = {"var:var_a": "365", "var:var_b": "sugroup"}.get
    vars_ = {"attendu": [1, "{var:var_a}"], "titre": "au plus {var:var_a} j",
             "commande": "grep -E '^{var:var_b}:' /etc/group", "x": 3}
    r = resoudre_recette(vars_, valeurs)
    assert r["attendu"] == [1, "365"] and r["titre"] == "au plus 365 j"
    assert r["commande"] == "grep -E '^sugroup:' /etc/group" and r["x"] == 3
    try:
        resoudre_recette({"a": "{var:inconnue}"}, valeurs)
        assert False, "variable inconnue non signalee"
    except KeyError:
        pass


def test_union_des_listes_de_referentiels():
    """Liste d'algorithmes forts : un algorithme admis par un referentiel
    (ex. sntrup761 pour Ubuntu 24.04) n'est pas signale faible ailleurs."""
    from brain.bibliotheque.importeurs.complianceascode import (
        resoudre_recette,
        union_listes,
    )
    assert union_listes(["b,c", "a,b,c", "c,d"]) == "b,c,a,d"
    r = resoudre_recette({"x": "KexAlgorithms {union:kex}"},
                         {"union:kex": "a,b"}.get)
    assert r == {"x": "KexAlgorithms a,b"}


def test_detecteurs_de_bout_en_bout():
    """Les commandes des recettes sont reconnues et jugees par le code."""
    from brain.bibliotheque import ecarts
    uid0 = "awk -F: '$3 == 0 && $1 != \"root\" {print $1}' /etc/passwd"
    v = ecarts.evaluer_commande(uid0, "toor\n", niveau=None)
    assert v and v[0].statut is STATUT.ECART and "toor" in v[0].constate
    assert ecarts.evaluer_commande(uid0, "", niveau=None)[0].statut \
        is STATUT.CONFORME
    vide = "awk -F: '!$2 {print $1}' /etc/shadow || echo 'SENTINELLE:ILLISIBLE'"
    # sans sudo : le marqueur evite un faux « conforme »
    assert ecarts.evaluer_commande(vide, "SENTINELLE:ILLISIBLE\n",
                                   niveau=None)[0].statut is STATUT.INDETERMINE


def test_login_defs_et_umask():
    spec = dict(lecteur="affectations", comparateur="entre",
                champ="PASS_MAX_DAYS", attendu=[1, 365], sep="espace")
    assert _s("/etc/login.defs:PASS_MAX_DAYS\t365", **spec) is STATUT.CONFORME
    assert _s("PASS_MAX_DAYS 99999", **spec) is STATUT.ECART
    assert _s("# PASS_MAX_DAYS 90", **spec) is STATUT.ECART    # commentee
    umask = dict(lecteur="affectations", comparateur="umask", champ="umask",
                 attendu="027", sep="espace")
    assert _s("/etc/bash.bashrc:umask 077", **umask) is STATUT.CONFORME
    assert _s("/etc/bash.bashrc:umask 022", **umask) is STATUT.ECART
    tmout = dict(lecteur="affectations", comparateur="entre", champ="TMOUT",
                 attendu=[1, 900])
    assert _s("/etc/profile.d/tmout.sh:readonly TMOUT=600", **tmout) \
        is STATUT.CONFORME
    assert _s("/etc/profile.d/tmout.sh:export TMOUT=0", **tmout) is STATUT.ECART


def test_pam_argument_interdit_et_sudo_au_plus():
    spec = dict(lecteur="pam", comparateur="arguments", champ="pam_unix.so",
                attendu=[{"nom": "nullok", "absent": True}])
    assert _s("auth [success=1 default=ignore] pam_unix.so nullok", **spec) \
        is STATUT.ECART
    assert _s("auth [success=1 default=ignore] pam_unix.so try_first_pass",
              **spec) is STATUT.CONFORME
    delai = dict(lecteur="sudo_defaults", comparateur="au_plus",
                 champ="timestamp_timeout", attendu="15", defaut="15")
    assert _s("Defaults env_reset", **delai) is STATUT.CONFORME     # defaut 15
    assert _s("Defaults timestamp_timeout=30", **delai) is STATUT.ECART
    assert _s("Defaults timestamp_timeout=-1", **delai) is STATUT.ECART


# ------------------------------------------ 3e vague : auditd, rsyslog...
def test_valeurs_alternatives_et_droits_rsyslog():
    spec = dict(lecteur="affectations", comparateur="toutes_egales",
                champ="disk_full_action", attendu="halt|single")
    assert _s("disk_full_action = SINGLE", **spec) is STATUT.CONFORME
    assert _s("disk_full_action = suspend", **spec) is STATUT.ECART
    assert _s("SENTINELLE:ILLISIBLE\n", **spec) is STATUT.INDETERMINE
    mode = dict(lecteur="affectations", comparateur="droits_au_plus",
                champ="$FileCreateMode", attendu="0640", sep="espace")
    assert _s("/etc/rsyslog.conf:$FileCreateMode 0640", **mode) \
        is STATUT.CONFORME
    assert _s("/etc/rsyslog.conf:$FileCreateMode 0644", **mode) is STATUT.ECART


def test_audit_comparaison_c_et_regle_composite():
    from brain.bibliotheque import ecarts
    execve = dict(lecteur="audit", comparateur="appels", champ="execve",
                  options=[["euid!=uid"]])
    regles = ("-a always,exit -F arch=b64 -S execve -C euid!=uid "
              "-F auid!=-1 -F key=user_emulation\n"
              "-a always,exit -F arch=b32 -S execve -C euid!=uid "
              "-F auid!=-1 -F key=user_emulation\n")
    assert _s(regles, **execve) is STATUT.CONFORME
    # composite : une seule commande juge toutes les preuves de la fiche
    sortie = ("-w /etc/sudoers -p wa -k actions\n"
              "-w /etc/sudoers.d -p wa -k actions\n")
    verdicts = {v.fiche: v for v in ecarts.evaluer_commande(
        "sudo auditctl -l", sortie, niveau=None)}
    assert verdicts["cac-audit-rules-sysadmin-actions"].statut \
        is STATUT.CONFORME
    reseau = verdicts["cac-audit-rules-networkconfig-modification"]
    assert reseau.statut is STATUT.ECART


# ------------------------------------------------ 4e vague : sans objet...
def test_sans_objet_et_valeurs_dconf():
    presente = dict(lecteur="lignes", comparateur="presente")
    lecture = lire("SENTINELLE:SANS_OBJET\n", presente)
    assert lecture.statut is STATUT.INDETERMINE and "sans objet" in lecture.constate
    cle = dict(lecteur="affectations", comparateur="entre", champ="idle-delay",
               attendu=[1, 900])
    assert _s("/etc/dconf/db/local.d/00-securite:idle-delay=uint32 900", **cle) \
        is STATUT.CONFORME
    assert _s("/etc/dconf/db/local.d/00-securite:idle-delay=uint32 0", **cle) \
        is STATUT.ECART
    assert _s("SENTINELLE:SANS_OBJET", **cle) is STATUT.INDETERMINE


def test_ssh_algorithmes_forts_de_bout_en_bout():
    from brain import bibliotheque
    from brain.bibliotheque import ecarts
    fiche = next(f for f in bibliotheque.toutes()
                 if f.id == "cac-sshd-use-strong-ciphers")
    cmd = fiche.observer[0].commande
    faible = "ciphers aes128-cbc,aes256-ctr\n"   # sortie deja filtree par awk ?
    # la commande filtre elle-meme : on simule sa SORTIE
    v = ecarts.evaluer_commande(cmd, "chiffrement faible : aes128-cbc\n",
                                niveau=None)
    assert v and v[0].statut is STATUT.ECART
    assert ecarts.evaluer_commande(cmd, "", niveau=None)[0].statut \
        is STATUT.CONFORME
    assert ecarts.evaluer_commande(cmd, "SENTINELLE:ILLISIBLE\n",
                                   niveau=None)[0].statut is STATUT.INDETERMINE
    assert faible


def test_toutes_les_regles_sans_gabarit_ont_une_recette_valide():
    """Chaque recette active produit une fiche ; aucune n'est refusee."""
    from brain import bibliotheque
    from brain.bibliotheque.importeurs import complianceascode as cac
    ids = {f.source.regle for f in bibliotheque.toutes()}
    actives = [r for r, v in cac.lire_recettes().items() if "ignorer" not in v]
    assert len(actives) >= 170
    manquantes = [r for r in actives if r not in ids]
    assert not manquantes, manquantes[:5]
