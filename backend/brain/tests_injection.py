"""Tests de l'injection ciblee du savoir (etape 4 du pipeline)."""
from brain import bibliotheque as bib
from brain import contexte as cx
from brain.bibliotheque import evaluation, injection, recherche

UBUNTU = cx.Contexte("ubuntu", "22.04", "debian", services=["openssh"],
                     services_connus=True)
ROCKY = cx.Contexte("rocky", "9.3", "rhel", services=["openssh"],
                    services_connus=True)


def _savoir(question, contexte=UBUNTU, budget=injection.BUDGET_JETONS):
    trouvailles, themes, _ = recherche.chercher(question, contexte=contexte, n=6)
    return injection.construire(trouvailles, contexte, themes, budget_jetons=budget)


def test_une_seule_fiche_principale_et_des_proches_en_une_ligne():
    s = _savoir("le routage IP est-il désactivé ?")
    assert s.texte.count("FICHE PRINCIPALE") == 1
    assert "sysctl -n net.ipv4.ip_forward" in s.texte
    assert s.proches and all("« " not in ligne for ligne in
                             s.texte.split("Fiches proches")[1].splitlines())


def test_referentiels_du_seul_systeme_audite():
    s = _savoir("le routage IP est-il désactivé ?")
    assert "CIS 3.3.1 (niveau 1)" in s.texte and "ANSSI R12" in s.texte
    assert "Ubuntu 24.04" not in s.texte and "Debian 12" not in s.texte
    assert "CIS CIS" not in _savoir("quels ports sont ouverts sur le serveur ?").texte


def test_commande_de_la_famille_du_systeme():
    ubuntu = _savoir("quels ports sont ouverts sur le serveur ?")
    rocky = _savoir("quels ports sont ouverts sur le serveur ?", contexte=ROCKY)
    assert "ufw status" in ubuntu.texte and "firewall-cmd" not in ubuntu.texte
    assert "firewall-cmd --list-all" in rocky.texte


def test_risque_non_traduit_non_montre():
    assert injection.semble_anglais("This ensures a user login will be terminated.")
    assert not injection.semble_anglais("Un nombre bas de tentatives freine la force brute.")
    s = _savoir("le routage IP est-il désactivé ?")
    assert "Routing protocol daemons" not in s.texte
    # Risque traduit (fiche SSH relue) : montre.
    s = _savoir("combien de tentatives de connexion ssh sont autorisées ?")
    assert "Pourquoi : Un nombre bas de tentatives" in s.texte


def test_budget_respecte_sans_perdre_l_essentiel():
    s = _savoir("quels ports sont ouverts sur le serveur ?", budget=200)
    assert s.retraits                                  # il a fallu couper
    assert "ss -tulnp" in s.texte and "Attendu" in s.texte   # jamais retires
    assert "Attention" not in s.texte


def test_proches_sans_doublon_de_titre():
    s = _savoir("Est-ce que root peut se connecter en SSH ?")
    lignes = [l for l in s.texte.split("Fiches proches")[-1].splitlines() if l.startswith("  - ")]
    assert len(lignes) == len(set(lignes))


def test_moitie_moins_de_jetons_que_l_ancien_assemblage():
    jeu = evaluation.charger()
    avant = apres = 0
    for q in jeu["questions"]:
        trouvailles, themes, _ = recherche.chercher(q["question"], contexte=UBUNTU, n=6)
        avant += injection.estimer_jetons(bib.assembler([t.fiche for t in trouvailles[:2]], UBUNTU))
        apres += injection.construire(trouvailles, UBUNTU, themes).jetons
    assert apres <= 0.6 * avant, (avant, apres)
