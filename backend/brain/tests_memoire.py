"""Tests de la memoire d'audit : avancement d'etape, constats, persistance.

Aucun modele, aucun reseau.
    ./venv/Scripts/python.exe -m brain.tests_memoire   (via le lanceur maison)
"""
import tempfile
from pathlib import Path

from brain.memoire import ETAPES, MemoireAudit, _extraire_constats


def _neuf():
    return MemoireAudit.ouvrir("t", Path(tempfile.mkdtemp()), perimetre="localhost")


def test_etape_depart():
    assert _neuf().etape == "observer"          # perimetre defini
    m = MemoireAudit.ouvrir("t", Path(tempfile.mkdtemp()))
    assert m.etape == "perimetre"               # pas de perimetre


def test_avancement_par_lectures():
    m = _neuf()
    m.enregistrer_commande("ls", "lecture", executee=True)
    assert m.etape == "observer"
    m.enregistrer_commande("ss -tlnp", "lecture", executee=True)
    assert m.etape == "verifier"                # 2e lecture


def test_modification_va_a_proposer():
    m = _neuf()
    m.enregistrer_commande("systemctl restart sshd", "modification")
    assert m.etape == "proposer"


def test_etape_ne_recule_pas():
    m = _neuf()
    m.enregistrer_commande("systemctl restart sshd", "modification")  # proposer
    m.enregistrer_commande("ls", "lecture", executee=True)            # observer
    assert m.etape == "proposer"                # on garde le plus avance


def test_extraction_constat():
    texte = ("**Constat** — root autorise en SSH.\n"
             "**Risque** — force brute directe.\n"
             "**Gravite** — elevee.\n"
             "**Action** — PermitRootLogin no.")
    cs = _extraire_constats(texte)
    assert len(cs) == 1
    assert cs[0].gravite == "elevee"            # normalise, sans point
    assert "root" in cs[0].resume


def test_constat_fait_avancer_a_expliquer():
    m = _neuf()
    n = m.enregistrer_constats("**Constat** — x.\n**Gravite** — faible.")
    assert n == 1 and m.etape == "expliquer"


def test_persistance_et_reprise():
    d = Path(tempfile.mkdtemp())
    m = MemoireAudit.ouvrir("persist", d, perimetre="localhost")
    m.enregistrer_commande("cat /etc/ssh/sshd_config", "lecture", executee=True)
    m.enregistrer_constats("**Constat** — root SSH.\n**Gravite** — elevee.")
    m2 = MemoireAudit.ouvrir("persist", d)      # nouveau processus simule
    assert m2.etape == "expliquer"
    assert len(m2.commandes) == 1
    assert len(m2.constats) == 1
    assert m2.constats[0].gravite == "elevee"


def test_ordre_des_etapes():
    assert ETAPES == ["perimetre", "observer", "verifier", "expliquer", "proposer"]


def test_requalification_met_a_jour_sans_dupliquer():
    m = _neuf()
    m.enregistrer_constats("**Constat** — PostgreSQL expose sur 0.0.0.0:5432.\n"
                           "**Gravite** — critique.")
    assert len(m.constats) == 1 and m.constats[0].gravite == "critique"
    # Meme sujet (port 5432), gravite revue a la baisse : on met a jour.
    n = m.enregistrer_constats("**Constat** — PostgreSQL sur 5432, filtre en "
                               "amont.\n**Gravite** — faible.")
    assert len(m.constats) == 1                 # pas de doublon
    assert m.constats[0].gravite == "faible"
    assert m.constats[0].gravite_precedente == "critique"
    assert n == 1


def test_sujets_differents_ne_fusionnent_pas():
    m = _neuf()
    m.enregistrer_constats("**Constat** — PostgreSQL expose sur 5432.\n"
                           "**Gravite** — critique.")
    m.enregistrer_constats("**Constat** — SSH autorise le mot de passe.\n"
                           "**Gravite** — moyenne.")
    assert len(m.constats) == 2                 # deux sujets distincts
