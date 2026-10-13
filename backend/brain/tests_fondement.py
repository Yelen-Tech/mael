"""Tests du fondement des constats : pas de constat sans observation.

Deterministe, sans modele. Rejoue le cas vu en direct le 17/09/2026.
"""
import tempfile
from pathlib import Path

from brain.fondement import juge_pour, juger
from brain.memoire import MemoireAudit

CONSTAT_INVENTE = (
    "**Constat** — La directive PermitRootLogin est presente dans "
    "/etc/ssh/sshd_config et prend la valeur 'yes'.\n"
    "**Risque** — L'autorisation de connexion root par SSH est active.\n"
    "**Gravite** — Critique\n"
    "**Action** — Mettre PermitRootLogin no, puis recharger SSH.")


def _audit():
    return MemoireAudit.ouvrir("f", Path(tempfile.mkdtemp()),
                               perimetre="serveur-test")


def test_sans_aucune_commande_le_constat_est_une_hypothese():
    m = _audit()
    m.enregistrer_constats(CONSTAT_INVENTE, juge=juge_pour(m))
    assert len(m.constats) == 1 and not m.constats[0].fonde
    assert m.derniers_non_fondes
    assert m.etape == "observer"              # n'avance PAS a « expliquer »
    assert "HYPOTHESES NON VERIFIEES" in m.resume_pour_prompt()
    assert "HYPOTHESE" in m.resume_humain()


def test_commande_sans_rapport_ne_fonde_pas():
    ok, motif = juger("PermitRootLogin yes en SSH", ["df -h"], [])
    assert not ok and "sans rapport" in motif
    ok, _ = juger("PermitRootLogin yes en SSH", ["ss -tlnp"], [])
    assert not ok


def test_observation_liee_fonde_le_constat():
    # Lien par fiche commune (ssh-durcissement).
    ok, motif = juger("PermitRootLogin yes : root autorise en SSH",
                      ["sshd -T | grep -i permitrootlogin"], [])
    assert ok and "sshd -T" in motif
    # Lien par terme technique commun (grep direct sur le fichier).
    ok, _ = juger("PermitRootLogin yes",
                  ["grep -i permitrootlogin /etc/ssh/sshd_config"], [])
    assert ok
    # Lien par numero de port.
    ok, _ = juger("PostgreSQL 5432 expose sur 0.0.0.0",
                  ["ss -tlnp | grep 5432"], [])
    assert ok


def test_commande_non_executee_ne_compte_pas():
    m = _audit()
    m.enregistrer_commande("sshd -T", "lecture", executee=False)  # simulation
    m.enregistrer_constats(CONSTAT_INVENTE, juge=juge_pour(m))
    assert not m.constats[0].fonde


def test_hypothese_confirmee_apres_observation():
    m = _audit()
    juge = juge_pour(m)
    m.enregistrer_constats(CONSTAT_INVENTE, juge=juge)
    m.enregistrer_commande("sshd -T | grep -i permitrootlogin", "lecture",
                           executee=True)
    devenus = m.reevaluer(juge)
    assert len(devenus) == 1 and m.constats[0].fonde
    assert m.etape == "expliquer"


def test_preuve_humaine_fonde():
    m = _audit()
    m.ajouter_preuve("sortie de sshd -T : permitrootlogin yes")
    m.enregistrer_constats(CONSTAT_INVENTE, juge=juge_pour(m))
    assert m.constats[0].fonde
    assert "humain" in m.constats[0].fondement
    # Persistance des preuves et du statut.
    relu = MemoireAudit.charger("f", m.dossier)
    assert relu.preuves and relu.constats[0].fonde


def test_reformulation_dun_constat_fonde_reste_fondee():
    m = _audit()
    m.enregistrer_commande("sshd -T | grep -i permitrootlogin", "lecture",
                           executee=True)
    m.enregistrer_constats(CONSTAT_INVENTE, juge=juge_pour(m))
    assert m.constats[0].fonde
    # Meme sujet reformule, juge par un juge qui ne voit rien : reste fonde.
    m.enregistrer_constats(CONSTAT_INVENTE, juge=lambda t: (False, "x"))
    assert m.constats[0].fonde and not m.derniers_non_fondes


def test_anciens_audits_restent_fondes():
    m = _audit()
    m.enregistrer_constats(CONSTAT_INVENTE)         # sans juge : compatibilite
    assert m.constats[0].fonde
