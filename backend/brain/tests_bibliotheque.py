"""Tests de la bibliotheque et de la recuperation (etape 2.2).

Deterministe, sans modele.
"""
from brain import bibliotheque as bib


def test_les_fiches_chargent():
    ids = {f.id for f in bib.toutes()}
    for attendu in ("ssh-durcissement", "tls-configuration", "entetes-http",
                    "ports-pare-feu", "dns-messagerie",
                    "journaux-authentification"):
        assert attendu in ids, attendu


def test_routage_par_domaine():
    cas = {
        "ssh autorise-t-il root ?": "ssh-durcissement",
        "le certificat tls est-il expire ?": "tls-configuration",
        "des en-tetes de securite manquent-ils ?": "entetes-http",
        "quels ports sont exposes ?": "ports-pare-feu",
        "spf dmarc contre l'usurpation de mail": "dns-messagerie",
        "tentatives de force brute dans les journaux": "journaux-authentification",
    }
    for question, fiche_id in cas.items():
        fiches, _ = bib.recuperer(question, n=2)
        ids = [f.id for f in fiches]
        # SSH : la fiche manuelle ou une fiche importee precise sur le sujet.
        ok = (fiche_id in ids if fiche_id != "ssh-durcissement" else
              any(i == fiche_id or i.startswith("cac-sshd") for i in ids))
        assert ok, (question, ids)


def test_hors_sujet_ninjecte_rien():
    fiches, motif = bib.recuperer("quelle est la meteo demain ?")
    assert fiches == []
    assert "aucune" in motif.lower()


def test_seuil_ecarte_les_correspondances_faibles():
    # 'configuration' seul (mot du resume) ne doit pas suffire a injecter.
    fiches, _ = bib.recuperer("montre-moi la configuration")
    assert fiches == []


def test_continuite_sur_relance():
    # 1er tour : question SSH -> fiche SSH.
    fiches, _ = bib.recuperer("ssh autorise root ?", n=1)
    assert "ssh" in fiches[0].mots_cles
    # 2e tour : relance vague sans mot-cle -> on garde la fiche precedente.
    suite, motif = bib.recuperer("et pour ce reglage ?", precedent=fiches[0])
    assert suite and suite[0].id == fiches[0].id
    assert "continuite" in motif.lower()


def test_demande_large_peut_ramener_deux_fiches():
    # 'web tls certificat en-tete' touche deux domaines.
    fiches, _ = bib.recuperer("audite le web : tls, certificat et en-tetes http",
                              n=2)
    ids = {f.id for f in fiches}
    assert "tls-configuration" in ids or "entetes-http" in ids
    assert len(fiches) >= 1


def test_budget_limite_la_taille():
    grande = bib.toutes()
    texte = bib.assembler(grande)
    assert len(texte) <= bib.BUDGET_CAR + max(
        len(f.pour_le_modele()) for f in grande)
