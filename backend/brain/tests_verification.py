"""Tests de la verification des commandes contre les fiches (etape 2.3).

Deterministe, sans modele.
"""
import json
import tempfile
from pathlib import Path

from brain.bibliotheque import toutes
from brain.bibliotheque.verification import STATUT, verifier
from brain.memoire import MemoireAudit


def _statut(commande):
    return verifier(commande).statut


def test_toutes_les_commandes_des_fiches_sont_conformes():
    for f in toutes():
        for obs in f.observer:
            assert _statut(obs.commande) in {STATUT.CONFORME, STATUT.USUEL}, \
                (f.id, obs.commande, verifier(obs.commande).ecarts)


def test_options_courtes_regroupees_tolerees():
    assert _statut("ss -ltn") is STATUT.CONFORME          # sous-ensemble de -tlnp
    assert _statut("sudo ss -tlnp") is STATUT.CONFORME    # sudo ignore
    assert _statut("sshd -T | grep -i permitrootlogin") is STATUT.CONFORME


def test_option_inventee_detectee_et_nommee():
    v = verifier("ss -tulnpx")
    assert v.statut is STATUT.NON_VERIFIE
    assert "-x" in v.motif
    assert "ss -tulnp" in v.references


def test_openssl_options_a_tiret_simple():
    ok = "openssl s_client -connect exemple.fr:443 -servername exemple.fr"
    assert _statut(ok) is STATUT.CONFORME
    assert _statut("openssl s_client -connect x:443 -tlsextdebug") \
        is STATUT.NON_VERIFIE
    # -noout ne doit pas etre decoupe en lettres : -nout reste une invention.
    assert _statut("openssl x509 -nout -dates") is STATUT.NON_VERIFIE


def test_boucle_de_fiche_depliee_sans_joker():
    assert _statut("openssl s_client -connect x:443 -tls1_2") is STATUT.CONFORME
    assert _statut("openssl s_client -connect x:443 -tls1_4") \
        is STATUT.NON_VERIFIE
    # Une boucle proposee est depliee : une valeur inventee est reperee.
    boucle = ("for p in tls1_2 tls1_4; do echo | openssl s_client "
              "-connect x:443 -$p; done")
    v = verifier(boucle)
    assert v.statut is STATUT.NON_VERIFIE and "-tls1_4" in v.motif


def test_sous_commande_absente():
    assert _statut("openssl genrsa 2048") is STATUT.NON_VERIFIE
    assert _statut("systemctl is-active nginx") is STATUT.CONFORME
    assert _statut("systemctl restart ssh") is STATUT.NON_VERIFIE


def test_outil_hors_fiche_et_utilitaires():
    assert _statut("nmap -sV exemple.fr") is STATUT.HORS_FICHE
    assert _statut("cat /etc/ssh/sshd_config") is STATUT.USUEL
    # Un outil connu en ecart l'emporte sur un outil hors fiche.
    v = verifier("nmap exemple.fr; ss -tlnpz")
    assert v.statut is STATUT.NON_VERIFIE
    assert all("nmap" not in e for e in v.ecarts)


def test_message_de_correction_donne_les_commandes_verifiees():
    msg = verifier("dig +trace exemple.fr").message_correction()
    assert "+trace" in msg
    assert "dig +short MX DOMAINE" in msg


def test_memoire_garde_la_verification_et_relit_les_anciens_audits():
    with tempfile.TemporaryDirectory() as d:
        m = MemoireAudit.ouvrir("a1", Path(d), perimetre="exemple.fr")
        m.enregistrer_commande("ss -tulnpx", "lecture",
                               verification="non_verifie")
        m.sauver()
        relu = MemoireAudit.charger("a1", Path(d))
        assert relu.commandes[0].verification == "non_verifie"
        assert "non verifiees" in relu.resume_humain()

        # Audit ecrit avant l'etape 2.3 : pas de champ verification.
        ancien = json.loads(m.fichier.read_text(encoding="utf-8"))
        for c in ancien["commandes"]:
            c.pop("verification")
        m.fichier.write_text(json.dumps(ancien), encoding="utf-8")
        assert MemoireAudit.charger("a1", Path(d)).commandes[0].verification == ""
