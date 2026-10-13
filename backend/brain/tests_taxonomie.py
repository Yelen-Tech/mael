"""Tests de la taxonomie du catalogue (etape 2 du pipeline)."""
from brain import bibliotheque as bib
from brain.bibliotheque import taxonomie as taxo


def test_chaque_fiche_est_rangee_sur_tous_les_axes():
    for f in bib.toutes():
        assert taxo.valider(f.taxonomie, f.domaine) == [], f.id
        assert f.applicable.get("os"), f.id                      # cible OS


def test_attribution_du_theme():
    t = taxo.theme_pour_regle
    assert t("services/ssh/ssh_server", "sshd_disable_root_login", "sshd_lineinfile") == "ssh"
    assert t("system/network/network-kernel", "sysctl_net_ipv4_ip_forward", "sysctl") == "parametres-reseau"
    assert t("system/permissions/restrictions", "sysctl_kernel_yama_ptrace_scope", "sysctl") == "parametres-noyau"
    # « group » seul ne suffit pas : un groupe de crontab reste de la planification.
    assert t("services/cron_and_at", "file_groupowner_crontab", "file_groupowner") == "planification"
    assert t("system/permissions/files", "file_groupowner_etc_gshadow", "file_groupowner") == "comptes"
    assert t("services/obsolete", "package_telnet_removed", "package_removed") == "services-inutiles"
    assert t("system/software", "package_aide_installed", "package_installed") == "integrite"


def test_niveaux_structures_depuis_les_references():
    refs = [{"nom": "CIS", "ref": "5.1.8 (niveau 2)"},
            {"nom": "CIS", "ref": "5.1.8 (niveau 1)"},
            {"nom": "ANSSI", "ref": "R33 (niveau renforce)"},
            {"nom": "ANSSI", "ref": "R12 (niveau intermediaire)"}]
    assert taxo.niveaux_depuis_referentiels(refs) == {"cis": 1, "anssi": "intermediaire"}
    assert taxo.niveaux_depuis_referentiels([]) == {"cis": None, "anssi": None}


def test_filtre_par_niveau_de_conformite():
    def niv(cis, anssi):
        return {"niveaux": {"cis": cis, "anssi": anssi}}
    # Politique par defaut recommandee : CIS 1 + ANSSI intermediaire.
    assert taxo.dans_le_niveau(niv(1, None), 1, "intermediaire")
    assert not taxo.dans_le_niveau(niv(2, None), 1, "intermediaire")
    assert taxo.dans_le_niveau(niv(2, "minimal"), 1, "intermediaire")   # ANSSI suffit
    assert not taxo.dans_le_niveau(niv(None, "eleve"), 1, "intermediaire")
    assert taxo.dans_le_niveau(niv(None, None), 1, "intermediaire")     # fiche manuelle


def test_valeurs_hors_liste_refusees():
    assert taxo.valider({"theme": "inconnu", "type_controle": "configuration",
                         "niveaux": {}}, "acces")
    assert taxo.valider({"theme": "ssh", "type_controle": "configuration",
                         "niveaux": {"cis": 3}}, "acces")
    # Theme et domaine doivent concorder.
    assert taxo.valider({"theme": "ssh", "type_controle": "configuration",
                         "niveaux": {}}, "reseau")
