"""Tests de l'importeur ComplianceAsCode (etape 2.4.3).

Sur une mini-source fabriquee ici : ne depend ni du reseau ni du clone local.
"""
import tempfile
from pathlib import Path

import yaml

from brain.bibliotheque import schema
from brain.bibliotheque.importeurs import complianceascode as cac

REGLE_ROOT = """documentation_complete: true

title: 'Disable SSH Root Login'

description: |-
    add or correct the following line in
    {{{ sshd_config_file() }}}

rationale: |-
    Logging in with a user-specific <b>account</b> provides accountability.

severity: medium

{{{ complete_ocil_entry_sshd_option(default="no", option="PermitRootLogin", value="no") }}}

template:
    name: sshd_lineinfile
    vars:
        parameter: PermitRootLogin
        value: 'no'
        datatype: string
"""

REGLE_VARIABLE = """title: 'Set SSH Client Alive Interval'
severity: high
rationale: Idle sessions are a risk.
template:
    name: sshd_lineinfile
    vars:
        parameter: ClientAliveInterval
        xccdf_variable: sshd_idle_timeout_value
        datatype: int
"""

VARIABLE = """title: 'SSH session Idle time'
type: number
options:
    5_minutes: 300
    10_minutes: 600
"""

REGLE_HORS_REFERENTIEL = REGLE_ROOT.replace("PermitRootLogin", "X11Forwarding")
REGLE_AUTRE_GABARIT = """title: 'Enable SELinux boolean'
severity: medium
template:
    name: sebool
    vars:
        seboolid: ssh_sysadm_login
"""
REGLE_JINJA = """{{% if product in ["rhel9"] %}}
title: x
{{% endif %}}
foo: "a" ~ "b" "c"
"""

CIS = """policy: CIS Benchmark for Ubuntu 22.04 LTS
version: 2.0.0
controls:
    - id: '5.1'
      controls:
          - id: 5.1.20
            levels:
                - l1_server
                - l1_workstation
            rules:
                - sshd_disable_root_login
          - id: 5.1.7
            rules:
                - sshd_set_idle_timeout
                - sshd_idle_timeout_value=5_minutes
"""
ANSSI = """policy: 'ANSSI-BP-028'
version: '2.0'
controls:
    - id: R33
      levels:
          - intermediary
      rules:
          - sshd_disable_root_login
"""


def _source():
    racine = Path(tempfile.mkdtemp())
    ssh = racine / cac.DOSSIER_SSH / "ssh_server"
    for regle, texte in {
        "sshd_disable_root_login": REGLE_ROOT,
        "sshd_set_idle_timeout": REGLE_VARIABLE,
        "sshd_enable_x11_forwarding": REGLE_HORS_REFERENTIEL,
        "package_openssh_installed": REGLE_AUTRE_GABARIT,
        "regle_jinja": REGLE_JINJA,
    }.items():
        (ssh / regle).mkdir(parents=True)
        (ssh / regle / "rule.yml").write_text(texte, encoding="utf-8")
    (ssh / "sshd_idle_timeout_value.var").write_text(VARIABLE, encoding="utf-8")
    (racine / "controls").mkdir()
    (racine / "controls" / "cis_ubuntu2204.yml").write_text(CIS, encoding="utf-8")
    (racine / "controls" / "anssi.yml").write_text(ANSSI, encoding="utf-8")
    return racine


def test_regles_retenues_et_ignorees_avec_raison():
    res = cac.construire(_source(), "0.1.82")
    assert set(res.fiches) == {"cac-sshd-disable-root-login",
                               "cac-sshd-set-idle-timeout"}
    assert "aucun referentiel" in res.ignorees["sshd_enable_x11_forwarding"]
    assert "sebool" in res.ignorees["package_openssh_installed"]
    assert "illisible" in res.ignorees["regle_jinja"]


def test_faits_repris_de_la_source_et_references_exactes():
    fiche = cac.construire(_source(), "0.1.82").fiches["cac-sshd-disable-root-login"]
    assert fiche["etat"] == "brouillon"
    assert fiche["source"] == {
        "origine": "complianceascode", "regle": "sshd_disable_root_login",
        "version": "0.1.82",
        "url": "https://github.com/ComplianceAsCode/content/tree/v0.1.82/"
               "linux_os/guide/services/ssh/ssh_server/sshd_disable_root_login"}
    refs = {(r["nom"], r["ref"]) for r in fiche["referentiels"]}
    assert refs == {("CIS", "5.1.20 (niveau 1)"),
                    ("ANSSI", "R33 (niveau intermediaire)")}   # hierarchie parcourue
    assert fiche["applicable"] == {"os": ["ubuntu==22.04"],
                                   "services": ["openssh"]}
    c = fiche["controles"][0]
    assert c["bon"] == "PermitRootLogin no"
    assert c["gravite"] == "elevee"          # regle Sentinelle (source : medium)
    assert "tracabilite" in c["risque"]            # risque traduit (lexique)
    # Titre et mots-cles francais (lexique) pour la recherche.
    assert "root" in fiche["titre"] and "administrateur" in fiche["mots_cles"]


def test_variable_resolue_par_le_referentiel():
    fiche = cac.construire(_source(), "0.1.82").fiches["cac-sshd-set-idle-timeout"]
    assert fiche["controles"][0]["controle"] == "ClientAliveInterval <= 300"  # 5_minutes
    assert fiche["controles"][0]["gravite"] == "elevee"
    # Directive absente du lexique : risque d'origine, balises retirees.
    source = _source()
    regle = (source / cac.DOSSIER_SSH / "ssh_server" / "sshd_disable_root_login"
             / "rule.yml")
    regle.write_text(REGLE_ROOT.replace("PermitRootLogin", "PermitTunnel"),
                     encoding="utf-8")
    brute = cac.construire(source, "0.1.82").fiches["cac-sshd-disable-root-login"]
    assert "<b>" not in brute["controles"][0]["risque"]
    assert "account" in brute["controles"][0]["risque"]
    assert "inactif" in fiche["mots_cles"]


def test_fiches_produites_valides_et_commandes_en_lecture():
    for fid, fiche in cac.construire(_source(), "0.1.82").fiches.items():
        erreurs, _ = schema.valider(fiche, Path(f"{fid}.yaml"))
        assert erreurs == [], (fid, erreurs)


def test_ecriture_idempotente_et_fiche_relue_protegee():
    source, sortie = _source(), Path(tempfile.mkdtemp()) / "cac"
    res = cac.construire(source, "0.1.82")
    assert len(cac.ecrire(res, sortie)["nouvelles"]) == 2
    bilan = cac.ecrire(cac.construire(source, "0.1.82"), sortie)
    assert len(bilan["inchangees"]) == 2 and not bilan["modifiees"]

    # L'humain relit une fiche et la valide.
    chemin = sortie / "cac-sshd-disable-root-login.yaml"
    d = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    d.update(etat="verifie", verifie_le="2026-09-17")
    chemin.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False),
                      encoding="utf-8")
    # Nouvelle version de la source : la fiche relue n'est pas ecrasee.
    bilan = cac.ecrire(cac.construire(source, "0.1.83"), sortie)
    assert "cac-sshd-disable-root-login" in bilan["a_revoir"]
    assert yaml.safe_load(chemin.read_text(encoding="utf-8"))["etat"] == "verifie"


def test_regle_disparue_signalee_pas_supprimee():
    source, sortie = _source(), Path(tempfile.mkdtemp()) / "cac"
    cac.ecrire(cac.construire(source, "0.1.82"), sortie)
    (sortie / "cac-ancienne-regle.yaml").write_text("id: x", encoding="utf-8")
    bilan = cac.ecrire(cac.construire(source, "0.1.82"), sortie)
    assert bilan["retirees"] == ["cac-ancienne-regle"]
    assert (sortie / "cac-ancienne-regle.yaml").exists()


def test_regles_sentinelle_ecrites_en_clair():
    seuil = cac._attendu("MaxAuthTries", "4", {"comparaison": "max"})
    assert seuil["controle"] == "MaxAuthTries <= 4"
    assert any(p.startswith("Regle Sentinelle") for p in seuil["pieges"])
    liste = cac._attendu("LogLevel", "INFO", {"acceptees": ["INFO", "VERBOSE"]})
    assert "VERBOSE" in liste["bon"]
    gravite = cac._attendu("PermitRootLogin", "no",
                           {"gravite": "elevee", "motif": "m"})
    assert gravite["gravite"] == "elevee"
    # Sans politique : egalite stricte de la source, aucune mention Sentinelle.
    brut = cac._attendu("PermitTunnel", "no", {})
    assert brut["mauvais"] == "toute autre valeur" and not brut["pieges"]


def test_relecture_tracee_puis_perimee_si_les_faits_changent():
    source = _source()
    registre = Path(tempfile.mkdtemp()) / "relectures.yaml"
    res = cac.construire(source, "0.1.82")
    cac.enregistrer_relecture(res, ["sshd_disable_root_login"], "relecteur",
                              "0.1.82", "2026-09-17", chemin=registre)

    res = cac.construire(source, "0.1.83")          # autre version, memes faits
    cac.appliquer_relectures(res, cac.lire_relectures(registre))
    fiche = res.fiches["cac-sshd-disable-root-login"]
    assert fiche["etat"] == "verifie" and fiche["relu_par"] == "relecteur"
    assert res.fiches["cac-sshd-set-idle-timeout"]["etat"] == "brouillon"
    assert schema.valider(fiche, Path(f"{fiche['id']}.yaml"))[0] == []

    # La source change un fait relu (valeur attendue) : relecture perimee.
    regle = (source / cac.DOSSIER_SSH / "ssh_server" / "sshd_disable_root_login"
             / "rule.yml")
    regle.write_text(REGLE_ROOT.replace("value: 'no'",
                                        "value: 'prohibit-password'"),
                     encoding="utf-8")
    res = cac.construire(source, "0.1.84")
    cac.appliquer_relectures(res, cac.lire_relectures(registre))
    assert res.fiches["cac-sshd-disable-root-login"]["etat"] == "brouillon"
    assert "cac-sshd-disable-root-login" in res.perimees
