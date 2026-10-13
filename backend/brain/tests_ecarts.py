"""Tests de l'etape 5 : le code juge les sorties, pas le modele.

Les sorties sont celles que produisent reellement les commandes des fiches
(formats de stat, dpkg-query, systemctl, findmnt, sshd -T...).
"""
from brain.bibliotheque import ecarts
from brain.bibliotheque.ecarts import STATUT, lire, normaliser_commande


def _s(sortie, **spec):
    return lire(sortie, spec).statut


def test_valeur_sysctl():
    spec = dict(lecteur="valeur", comparateur="egal", attendu="0")
    assert _s("0\n", **spec) is STATUT.CONFORME
    assert _s("1\n", **spec) is STATUT.ECART
    assert _s("net.ipv4.ip_forward = 0", **spec) is STATUT.CONFORME
    assert _s("", **spec) is STATUT.INDETERMINE


def test_affectations_persistantes():
    spec = dict(lecteur="affectations", comparateur="toutes_egales",
                champ="net.ipv4.ip_forward", attendu="0")
    bon = "/etc/sysctl.d/60-sentinelle.conf:net.ipv4.ip_forward = 0\n"
    assert _s(bon, **spec) is STATUT.CONFORME
    conflit = bon + "/etc/sysctl.d/99-docker.conf:net.ipv4.ip_forward=1\n"
    assert _s(conflit, **spec) is STATUT.ECART
    assert _s("", **spec) is STATUT.ECART        # non persistant
    assert _s("/etc/sysctl.conf:# net.ipv4.ip_forward = 1\n" + bon,
              **spec) is STATUT.CONFORME          # commentaire ignore


def test_stat_droits_au_plus():
    spec = dict(lecteur="stat", champ="droits", comparateur="droits_au_plus",
                attendu="0640")
    assert _s("640 root shadow /etc/shadow", **spec) is STATUT.CONFORME
    assert _s("600 root root /etc/shadow", **spec) is STATUT.CONFORME  # + strict
    assert _s("644 root shadow /etc/shadow", **spec) is STATUT.ECART
    assert _s("2640 root shadow /etc/shadow", **spec) is STATUT.ECART  # setgid
    # stat sans droits : rien sur stdout -> on ne conclut pas
    assert _s("", **spec) is STATUT.INDETERMINE
    assert _s("stat: cannot stat '/x': Permission denied", **spec) \
        is STATUT.INDETERMINE


def test_stat_proprietaire_plusieurs_fichiers():
    spec = dict(lecteur="stat", champ="proprietaire", comparateur="dans",
                attendu=["0", "root"])
    sortie = ("644 root root /etc/cron.d/a\n"
              "644 www-data root /etc/cron.d/b\n")
    lecture = lire(sortie, spec)
    assert lecture.statut is STATUT.ECART and "/etc/cron.d/b" in lecture.constate
    assert _s("644 root root /etc/cron.d/a", **spec) is STATUT.CONFORME


def test_stat_groupe():
    spec = dict(lecteur="stat", champ="groupe", comparateur="dans",
                attendu=["root", "shadow"])
    assert _s("640 root shadow /etc/shadow", **spec) is STATUT.CONFORME
    assert _s("640 root adm /etc/shadow", **spec) is STATUT.ECART


def test_dpkg():
    present = dict(lecteur="dpkg", comparateur="installe", attendu=["auditd"])
    absent = dict(lecteur="dpkg", comparateur="absent", attendu=["telnetd"])
    assert _s("auditd install ok installed", **present) is STATUT.CONFORME
    assert _s("", **present) is STATUT.ECART
    assert _s("auditd deinstall ok config-files", **present) is STATUT.ECART
    assert _s("", **absent) is STATUT.CONFORME
    assert _s("telnetd:amd64 install ok installed", **absent) is STATUT.ECART


def test_systemctl():
    actif = dict(lecteur="systemctl", comparateur="actif")
    inactif = dict(lecteur="systemctl", comparateur="inactif")
    assert _s("enabled\nactive\n", **actif) is STATUT.CONFORME
    assert _s("disabled\ninactive\n", **actif) is STATUT.ECART
    assert _s("masked\ninactive\n", **inactif) is STATUT.CONFORME
    assert _s("inactive\n", **inactif) is STATUT.CONFORME   # service absent
    assert _s("disabled\nactive\n", **inactif) is STATUT.ECART
    assert _s("enabled\ninactive\n", **inactif) is STATUT.ECART
    assert _s("", **inactif) is STATUT.INDETERMINE


def test_modules_noyau():
    spec = dict(lecteur="modprobe", comparateur="interdit", champ="usb-storage")
    complet = ("/etc/modprobe.d/usb.conf:install usb-storage /bin/false\n"
               "/etc/modprobe.d/usb.conf:blacklist usb_storage\n")
    assert _s(complet, **spec) is STATUT.CONFORME     # - et _ equivalents
    lecture = lire("/etc/modprobe.d/usb.conf:blacklist usb-storage\n", spec)
    assert lecture.statut is STATUT.ECART and "install" in lecture.constate
    assert _s("/etc/modprobe.d/x.conf:#install usb-storage /bin/false\n"
              "/etc/modprobe.d/x.conf:blacklist usb-storage", **spec) \
        is STATUT.ECART                                # commentee
    charge = dict(lecteur="aucune_ligne", comparateur="vide")
    assert _s("", **charge) is STATUT.CONFORME
    assert _s("usb_storage  81920  0", **charge) is STATUT.ECART


def test_montage():
    actif = dict(lecteur="findmnt", comparateur="option_presente",
                 attendu="nodev")
    assert _s("/tmp tmpfs tmpfs rw,nosuid,nodev,noexec,relatime", **actif) \
        is STATUT.CONFORME
    assert _s("/tmp /dev/sda3 ext4 rw,relatime", **actif) is STATUT.ECART
    assert _s("", **actif) is STATUT.INDETERMINE      # pas de partition
    fstab = dict(lecteur="fstab", comparateur="option_presente",
                 attendu="nodev")
    assert _s("UUID=ab /tmp ext4 defaults,nodev,nosuid 0 2", **fstab) \
        is STATUT.CONFORME
    assert _s("UUID=ab /tmp ext4 defaults 0 2", **fstab) is STATUT.ECART


def test_kconfig():
    non = dict(lecteur="kconfig", comparateur="egal",
               champ="CONFIG_KEXEC", attendu="n")
    assert _s("# CONFIG_KEXEC is not set", **non) is STATUT.CONFORME
    assert _s("CONFIG_KEXEC=y", **non) is STATUT.ECART
    assert _s("", **non) is STATUT.INDETERMINE
    oui = dict(lecteur="kconfig", comparateur="egal",
               champ="CONFIG_STRICT_KERNEL_RWX", attendu="y")
    assert _s("CONFIG_STRICT_KERNEL_RWX=y", **oui) is STATUT.CONFORME
    # En-tete lu, option absente : inexistante dans ce noyau.
    tete = "# Linux/x86 6.8.0-45-generic Kernel Configuration"
    assert _s(tete, **non) is STATUT.CONFORME
    assert _s(tete, **oui) is STATUT.INDETERMINE
    # Option propre a arm64 sur un noyau x86 : sans objet, jamais un ecart.
    arm = dict(oui, champ="CONFIG_ARM64_SW_TTBR0_PAN", architectures=["arm64"])
    assert _s(tete, **arm) is STATUT.INDETERMINE
    # Nom d'avant 6.9 et nouveau nom (MITIGATION_) lus tous les deux.
    ret = dict(oui, champ="CONFIG_RETPOLINE",
               noms=["CONFIG_RETPOLINE", "CONFIG_MITIGATION_RETPOLINE"])
    assert _s(tete + "\nCONFIG_MITIGATION_RETPOLINE=y", **ret) \
        is STATUT.CONFORME
    assert _s(tete + "\n# CONFIG_MITIGATION_RETPOLINE is not set", **ret) \
        is STATUT.ECART


def test_arguments_demarrage():
    audit = dict(lecteur="cmdline", comparateur="egal", champ="audit",
                 attendu="1")
    ligne = "BOOT_IMAGE=/vmlinuz-6.8.0 root=UUID=x ro quiet splash"
    assert _s(ligne + " audit=1", **audit) is STATUT.CONFORME
    assert _s(ligne, **audit) is STATUT.ECART
    assert _s(ligne + " audit=0", **audit) is STATUT.ECART
    backlog = dict(lecteur="cmdline", comparateur="au_moins",
                   champ="audit_backlog_limit", attendu="8192")
    assert _s("ro audit_backlog_limit=16384", **backlog) is STATUT.CONFORME
    assert _s("ro audit_backlog_limit=64", **backlog) is STATUT.ECART
    sans_valeur = dict(lecteur="cmdline", comparateur="egal", champ="pti")
    assert _s("ro pti", **sans_valeur) is STATUT.CONFORME
    grub = dict(lecteur="grub", comparateur="egal", champ="audit",
                attendu="1")
    assert _s('GRUB_CMDLINE_LINUX="audit=1"', **grub) is STATUT.CONFORME
    assert _s('GRUB_CMDLINE_LINUX=""\nGRUB_CMDLINE_LINUX_DEFAULT="quiet"',
              **grub) is STATUT.ECART
    assert _s("", **grub) is STATUT.INDETERMINE


def test_sshd_t():
    egal = dict(lecteur="sshd_t", comparateur="egal", champ="permitrootlogin",
                attendu="no")
    assert _s("permitrootlogin no", **egal) is STATUT.CONFORME
    assert _s("permitrootlogin yes", **egal) is STATUT.ECART
    # sans sudo, sshd -T n'affiche rien : on ne conclut pas
    assert _s("", **egal) is STATUT.INDETERMINE
    maxi = dict(lecteur="sshd_t", comparateur="max", champ="maxauthtries",
                attendu="4")
    assert _s("maxauthtries 3", **maxi) is STATUT.CONFORME
    assert _s("maxauthtries 6", **maxi) is STATUT.ECART
    assert _s("maxauthtries 0", **maxi) is STATUT.ECART
    niveau = dict(lecteur="sshd_t", comparateur="dans", champ="loglevel",
                  attendu=["INFO", "VERBOSE"])
    assert _s("loglevel VERBOSE", **niveau) is STATUT.CONFORME
    assert _s("loglevel QUIET", **niveau) is STATUT.ECART
    starts = dict(lecteur="sshd_t", comparateur="maxstartups",
                  champ="maxstartups", attendu="10:30:60")
    assert _s("maxstartups 10:30:100", **starts) is STATUT.ECART
    assert _s("maxstartups 5:50:40", **starts) is STATUT.CONFORME
    banniere = dict(lecteur="sshd_t", comparateur="fichier", champ="banner",
                    attendu="/etc/issue.net")
    assert _s("banner /etc/issue", **banniere) is STATUT.CONFORME
    assert _s("banner none", **banniere) is STATUT.ECART


def test_normaliser_commande():
    base = "sshd -T | grep -i '^permitrootlogin '"
    assert normaliser_commande(
        "sudo sshd -T 2>/dev/null | grep -i '^permitrootlogin '") == base
    assert normaliser_commande("sysctl net.ipv4.ip_forward") == \
        "sysctl -n net.ipv4.ip_forward"
    assert normaliser_commande("  cat   /proc/cmdline ; ") == "cat /proc/cmdline"


def test_valider_spec():
    assert ecarts.valider_spec(dict(commande=0, lecteur="valeur",
                                    comparateur="egal", attendu="0"), 1) == []
    assert ecarts.valider_spec(dict(commande=2, lecteur="valeur",
                                    comparateur="egal", attendu="0"), 1)
    assert ecarts.valider_spec(dict(commande=0, lecteur="inconnu"), 1)
    assert ecarts.valider_spec(dict(commande=0, lecteur="stat",
                                    comparateur="egal", champ="droits",
                                    attendu="0644"), 1)


def test_fiches_importees_evaluables():
    """Toutes les fiches importees sont jugeables par le code, sauf les
    regles conditionnelles a un choix de l'exploitant (ufw OU nftables...),
    volontairement laissees a la lecture."""
    from brain import bibliotheque
    importees = [f for f in bibliotheque.toutes()
                 if f.source.origine == "complianceascode"]
    assert importees
    sans = [f.id for f in importees
            if not all(c.evaluation for c in f.controles)
            and not any("Regle conditionnelle" in p for p in f.pieges)]
    assert not sans, sans[:5]


def test_de_bout_en_bout_une_commande_plusieurs_fiches():
    """« cat /proc/cmdline » juge d'un coup toutes les fiches d'arguments de
    demarrage ; un argument present est conforme, les autres en ecart."""
    verdicts = ecarts.evaluer_commande(
        "cat /proc/cmdline", "BOOT_IMAGE=/vmlinuz ro audit=1", niveau=None)
    assert len(verdicts) >= 3
    par_statut = {v.statut for v in verdicts}
    assert STATUT.ECART in par_statut
    audit = [v for v in verdicts if v.controle.endswith("audit=1")]
    assert audit and audit[0].statut is STATUT.CONFORME
    # la preuve persistante (/etc/default/grub) reste a observer
    assert audit[0].a_observer


def test_message_modele():
    verdicts = ecarts.evaluer_commande(
        "sudo sshd -T | grep -i '^permitrootlogin '", "permitrootlogin yes")
    assert verdicts and verdicts[0].statut is STATUT.ECART
    msg = ecarts.message_modele(verdicts)
    assert "ECART" in msg and "Ne les rejuge pas" in msg


def test_memoire_ecart_puis_corrige():
    """Un ecart mesure devient un constat FONDE (origine code) ; une mesure
    conforme ulterieure le marque corrige ; tout survit au rechargement."""
    import tempfile
    from pathlib import Path

    from brain.memoire import MemoireAudit
    cmd = "sudo sshd -T | grep -i '^permitrootlogin '"
    with tempfile.TemporaryDirectory() as d:
        m = MemoireAudit("t", Path(d), perimetre="srv")
        bilan = m.enregistrer_verdicts(
            ecarts.evaluer_commande(cmd, "permitrootlogin yes"))
        assert len(bilan["ecarts"]) == 1
        c = bilan["ecarts"][0]
        assert c.fonde and c.origine == "code" and c.gravite
        assert m.etape == "expliquer"
        assert "ecart mesure par le code" in m.resume_pour_prompt()
        # meme ecart re-mesure : pas de doublon
        m.enregistrer_verdicts(ecarts.evaluer_commande(cmd, "permitrootlogin yes"))
        assert len(m.constats) == 1
        bilan = m.enregistrer_verdicts(
            ecarts.evaluer_commande(cmd, "permitrootlogin no"))
        assert bilan["corriges"] and m.constats[0].corrige
        relue = MemoireAudit.charger("t", Path(d))
        assert relue.constats[0].corrige
        assert list(relue.evaluations.values())[0]["statut"] == "conforme"


def test_niveau_client_filtre_les_mesures():
    """Par defaut (CIS 1 + ANSSI intermediaire), une regle ANSSI renforcee
    comme iommu=force n'est pas mesuree : ce n'est pas un ecart pour ce
    client. Au niveau renforce, elle l'est."""
    sortie = "BOOT_IMAGE=/vmlinuz ro quiet"
    defaut = {v.controle for v in ecarts.evaluer_commande(
        "cat /proc/cmdline", sortie)}
    renforce = {v.controle for v in ecarts.evaluer_commande(
        "cat /proc/cmdline", sortie, niveau=(2, "renforce"))}
    assert not any("iommu" in c for c in defaut)
    assert any("iommu" in c for c in renforce)
    assert defaut < renforce


def test_message_modele_borne():
    """13 ecarts d'un coup : le modele n'en recoit que MAX_ECARTS_MODELE en
    detail, les plus graves d'abord ; les autres sont comptes."""
    verdicts = ecarts.evaluer_commande("cat /proc/cmdline", "ro quiet",
                                       niveau=None)
    msg = ecarts.message_modele(verdicts)
    assert msg.count("- ECART [") == ecarts.MAX_ECARTS_MODELE
    assert "autre(s) ECART(s)" in msg
    premiere = msg.split("- ECART [", 1)[1]
    assert premiere.startswith(("critique", "elevee"))


def test_sysctl_valeur_effective():
    """La valeur retenue au demarrage l'emporte (ordre de systemd-sysctl) :
    un fichier du systeme qui garde une autre valeur n'est pas un ecart."""
    spec = dict(lecteur="affectations", comparateur="toutes_egales",
                champ="fs.protected_fifos", attendu="2", precedence="sysctl")
    corrige = ("/usr/lib/sysctl.d/50-default.conf:fs.protected_fifos = 1\n"
               "/etc/sysctl.conf:fs.protected_fifos = 2\n")
    assert _s(corrige, **spec) is STATUT.CONFORME
    # Rien n'ecrase la valeur du systeme -> ecart.
    assert _s("/usr/lib/sysctl.d/50-default.conf:fs.protected_fifos = 1\n",
              **spec) is STATUT.ECART
    # A nom egal, /etc/sysctl.d masque /usr/lib/sysctl.d.
    masque = ("/etc/sysctl.d/50-default.conf:fs.protected_fifos = 2\n"
              "/usr/lib/sysctl.d/50-default.conf:fs.protected_fifos = 1\n")
    assert _s(masque, **spec) is STATUT.CONFORME
    # Tri par nom : 90-x.conf passe apres 60-mael.conf.
    tard = ("/etc/sysctl.d/60-a.conf:fs.protected_fifos = 2\n"
            "/etc/sysctl.d/90-z.conf:fs.protected_fifos = 0\n")
    assert _s(tard, **spec) is STATUT.ECART
    # Sans « precedence » : ancien comportement (toutes les lignes).
    spec.pop("precedence")
    assert _s(corrige, **spec) is STATUT.ECART
