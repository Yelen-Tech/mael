"""Tests du moteur de recherche (etape 3 du pipeline)."""
from brain import contexte as cx
from brain.bibliotheque import recherche

UBUNTU = cx.Contexte("ubuntu", "22.04", "debian", services=["openssh"],
                     services_connus=True)


def test_aiguillage_vers_le_theme():
    assert "parametres-reseau" in recherche.aiguiller("le routage IP est-il désactivé ?")
    assert "ssh" in recherche.aiguiller("root peut-il se connecter en SSH ?")
    themes = recherche.aiguiller("niveau de journalisation du serveur ssh")
    assert {"ssh", "journalisation"} <= set(themes)      # plusieurs themes possibles
    assert recherche.aiguiller("quelle est la meteo demain ?") == {}


def test_synonymes_expression_la_plus_longue():
    ajouts = recherche.expansions("le routage par la source est-il refusé ?")
    assert "accept_source_route" in ajouts and "ip_forward" not in ajouts
    assert "ip_forward" in recherche.expansions("le routage IP est-il actif ?")


def test_racine_et_mots_vides():
    assert recherche._racine("redirections") == "redirection"
    assert recherche._racine("journalises") == "journalis"
    requete = recherche.Index._requete("la machine est-elle configurée ?")
    assert requete is None                          # que des mots vides


def test_aiguillage_souple_n_exclut_rien():
    # « désactivé » ne doit plus noyer « routage » sous les services.
    trouvailles, themes, _ = recherche.chercher("le routage IP est-il désactivé ?",
                                                contexte=UBUNTU, n=2)
    assert trouvailles[0].fiche.id in {"cac-sysctl-net-ipv4-ip-forward",
                                       "cac-sysctl-net-ipv6-conf-all-forwarding"}


def test_filtres_stricts_systeme_et_niveau():
    # Fiche Debian 12 / Ubuntu 24.04 : ecartee sur Ubuntu 22.04, avec raison.
    trouvailles, _, ecartees = recherche.chercher("rsyslog est-il en marche ?",
                                                  contexte=UBUNTU)
    ids = {t.fiche.id for t in trouvailles}
    assert not ids & {"cac-service-rsyslog-enabled", "cac-package-rsyslog-installed"}
    assert any("hors champ" in e for e in ecartees)
    # Niveau client CIS 1 + ANSSI intermediaire : une option de compilation
    # ANSSI « eleve » est ecartee ; sans niveau, elle est trouvee.
    q = "le noyau est-il compilé avec la protection de pile ?"
    sans, _, _ = recherche.chercher(q, contexte=UBUNTU)
    avec, _, ecartees = recherche.chercher(q, contexte=UBUNTU, niveau=(1, "intermediaire"))
    assert any("stackprotector" in t.fiche.id for t in sans)
    assert not any("stackprotector" in t.fiche.id for t in avec)
    assert any("niveau" in e for e in ecartees)


def test_themes_du_lexique_existent_dans_la_taxonomie():
    from brain.bibliotheque.taxonomie import THEMES
    assert set(recherche.lexique()["themes"]) <= set(THEMES)


def test_chemin_pointe_reste_une_phrase():
    # Bug corrige : « /etc/cron.d » se reduisait a « cron » et rejoignait crontab.
    requete = recherche.Index._requete("le répertoire /etc/cron.d est-il protégé ?")
    assert '"etc cron d"' in requete
    trouvailles, _, _ = recherche.chercher("Le répertoire /etc/cron.d est-il protégé ?",
                                           contexte=UBUNTU, n=2)
    assert all("cron-d" in t.fiche.id for t in trouvailles)


def test_routeur_et_annonces_de_routeur():
    # « routeur » seul -> routage ; « annonces de routeur » (plus long) -> accept_ra.
    assert "ip_forward" in recherche.expansions("la machine fait-elle office de routeur ?")
    ajouts = recherche.expansions("les annonces de routeur IPv6 sont-elles acceptées ?")
    assert "accept_ra" in ajouts and "ip_forward" not in ajouts
