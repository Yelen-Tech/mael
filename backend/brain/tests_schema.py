"""Tests du schema v2 et de la validation des fiches (etape 2.4.1).

Deterministe, sans modele.
"""
import copy
from pathlib import Path

from brain.bibliotheque import schema, toutes

PLAYBOOKS = {"app.en-tetes-http"}


def _fiche_valide():
    return {
        "id": "exemple-ssh", "titre": "Exemple", "domaine": "acces",
        "schema": 2, "version": 1, "etat": "verifie",
        "verifie_le": "2026-09-16", "relu_par": "test", "teste_sur": ["ubuntu:22.04"],
        "applicable": {"os": ["ubuntu>=20.04", "rhel>=8"],
                       "services": ["openssh>=7.4"]},
        "source": {"origine": "manuel"},
        "taxonomie": {"theme": "ssh", "type_controle": "configuration",
                      "niveaux": {"cis": 1, "anssi": "intermediaire"}},
        "mots_cles": ["ssh"], "resume": "Resume.",
        "observer": [{"commande": "sshd -T", "but": "b", "lecture": "l",
                      "variantes": {"alpine": "cat /etc/ssh/sshd_config"}}],
        "controles": [{"controle": "PermitRootLogin", "gravite": "elevee",
                       "risque": "r", "action": "a",
                       "referentiels": [{"nom": "CIS", "document": "d"}]}],
        "referentiels": [{"nom": "ANSSI", "document": "d", "ref": None}],
    }


def _valider(d, nom="exemple-ssh.yaml"):
    return schema.valider(d, Path(nom), PLAYBOOKS)


def _avec(modif):
    d = _fiche_valide()
    modif(d)
    return _valider(d)


def test_fiche_valide_sans_erreur_ni_avertissement():
    assert _valider(_fiche_valide()) == ([], [])


def test_toutes_les_fiches_de_la_bibliotheque_sont_valides():
    nb_err, _, texte = schema.rapport()
    assert nb_err == 0, texte
    ids = [f.id for f in toutes()]
    assert len([i for i in ids if not i.startswith("cac-")]) == 9   # manuelles
    assert len(ids) == len(set(ids))                                # ids uniques


def test_observation_qui_ecrit_est_refusee():
    # Le coeur du dispositif : une « lecture » qui modifie n'entre jamais.
    for cmd in ["sed -i 's/yes/no/' /etc/ssh/sshd_config",
                "echo $(touch /tmp/x)", "systemctl restart sshd"]:
        err, _ = _avec(lambda d: d["observer"][0].update(commande=cmd))
        assert any("LECTURE" in e for e in err), cmd
    # ... y compris cachee dans une variante.
    err, _ = _avec(lambda d: d["observer"][0]["variantes"].update(
        rhel="ufw enable"))
    assert any("(rhel)" in e for e in err)


def test_contexte_invalide():
    err, _ = _avec(lambda d: d["applicable"].update(os=["windows>=10"]))
    assert any("applicable.os" in e for e in err)
    err, _ = _avec(lambda d: d["applicable"].update(os=["ubuntu>=vingt"]))
    assert any("applicable.os" in e for e in err)
    err, _ = _avec(lambda d: d.pop("applicable"))
    assert any("applicable.os" in e for e in err)
    err, _ = _avec(lambda d: d["observer"][0]["variantes"].update(
        windows="dir"))
    assert any("famille" in e for e in err)


def test_cycle_de_vie():
    err, _ = _avec(lambda d: d.pop("verifie_le"))
    assert any("verifie_le" in e for e in err)
    err, _ = _avec(lambda d: d.update(verifie_le="2999-01-01"))
    assert any("futur" in e for e in err)
    err, _ = _avec(lambda d: d.update(etat="valide"))
    assert any("etat" in e for e in err)
    # Un brouillon n'a pas besoin de date de relecture.
    err, _ = _avec(lambda d: (d.pop("verifie_le"), d.update(etat="brouillon")))
    assert err == []


def test_fiche_importee_doit_etre_tracable():
    err, _ = _avec(lambda d: d.update(source={"origine": "complianceascode"}))
    assert any("tracabilite" in e for e in err)
    err, _ = _avec(lambda d: d.update(source={
        "origine": "complianceascode", "regle": "sshd_disable_root_login",
        "version": "0.1.74"}))
    assert err == []


def test_controles_et_referentiels():
    err, _ = _avec(lambda d: d["controles"][0].update(gravite="grave"))
    assert any("gravite" in e for e in err)
    err, _ = _avec(lambda d: d["controles"][0].update(playbook="net.inexistant"))
    assert any("introuvable" in e for e in err)
    err, _ = _avec(lambda d: d["controles"][0].update(playbook="app.en-tetes-http"))
    assert err == []
    err, _ = _avec(lambda d: d["referentiels"].append({"nom": "ISO"}))
    assert err


def test_anssi_et_cis_attendus_sur_les_domaines_systeme():
    _, av = _avec(lambda d: d.update(referentiels=[]))
    assert any("ANSSI" in a for a in av)
    # Hors domaines systeme (dns), pas d'exigence CIS.
    _, av = _avec(lambda d: d.update(domaine="dns", referentiels=[],
                                     taxonomie={"theme": "messagerie",
                                                "type_controle": "observation",
                                                "niveaux": {}}))
    assert not any("CIS" in a for a in av)


def test_identite_et_ancien_schema():
    err, _ = _valider(_fiche_valide(), "autre-nom.yaml")
    assert any("ne correspond pas" in e for e in err)
    v1 = copy.deepcopy(_fiche_valide())
    v1["schema"] = 1
    err, _ = _valider(v1)
    assert any("migrer" in e for e in err)
    err, _ = _avec(lambda d: d.update(mots_cles=["tls", 443]))
    assert any("mots_cles" in e for e in err)


def test_fiche_invalide_ecartee_et_obsolete_non_injectee(monkeypatch=None):
    from brain import bibliotheque as bib

    ssh = next(f for f in bib.toutes() if f.id == "ssh-durcissement")
    ssh_etat = ssh.etat
    try:
        ssh.etat = "obsolete"
        fiches, _ = bib.recuperer("ssh autorise root ?", n=2)
        assert all(f.id != "ssh-durcissement" for f in fiches)
    finally:
        ssh.etat = ssh_etat
