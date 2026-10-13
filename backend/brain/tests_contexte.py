"""Tests du contexte systeme et du filtrage des fiches (etape 2.4.2).

Deterministe, sans modele ni machine Linux : les sorties sont rejouees.
"""
import tempfile
from pathlib import Path

from brain import bibliotheque as bib
from brain import contexte as cx
from brain.garde import NIVEAU, classer
from brain.memoire import MemoireAudit

OS_UBUNTU = '''PRETTY_NAME="Ubuntu 22.04.4 LTS"
NAME="Ubuntu"
VERSION_ID="22.04"
ID=ubuntu
ID_LIKE=debian
'''
OS_ROCKY = 'NAME="Rocky Linux"\nVERSION_ID="9.3"\nID="rocky"\nID_LIKE="rhel centos fedora"\n'
OS_ALPINE = "NAME=\"Alpine Linux\"\nID=alpine\nVERSION_ID=3.19.1\n"
SERVICES = """ssh.service        loaded active running OpenBSD Secure Shell server
nginx.service      loaded active running A high performance web server
getty@tty1.service loaded active running Getty on tty1
postgresql@14-main.service loaded active running PostgreSQL Cluster 14-main
"""


def _fiche(os_, services=None):
    f = bib.Fiche(id="x", titre="x", domaine="acces")
    f.applicable = {"os": os_, **({"services": services} if services else {})}
    return f


def test_les_commandes_de_detection_sont_des_lectures():
    assert classer(cx.CMD_OS).niveau is NIVEAU.LECTURE
    assert classer(cx.CMD_SERVICES).niveau is NIVEAU.LECTURE


def test_analyse_os_release():
    c = cx.analyser_os_release(OS_UBUNTU)
    assert (c.os_id, c.version, c.famille) == ("ubuntu", "22.04", "debian")
    c = cx.analyser_os_release(OS_ROCKY)
    assert (c.os_id, c.version, c.famille) == ("rocky", "9.3", "rhel")
    c = cx.analyser_os_release(OS_ALPINE)
    assert c.famille == "alpine"
    assert not cx.analyser_os_release("").connu


def test_analyse_services():
    assert cx.analyser_services(SERVICES) == ["nginx", "openssh", "postgresql"]


def test_detection_avec_executeur_rejoue():
    sorties = {cx.CMD_OS: OS_UBUNTU, cx.CMD_SERVICES: SERVICES}
    c = cx.detecter(lambda cmd: sorties.get(cmd))
    assert c.connu and c.services_connus and "openssh" in c.services
    # Machine sans systemd : services inconnus, donc pas de filtrage dessus.
    c = cx.detecter(lambda cmd: OS_ALPINE if cmd == cx.CMD_OS else None)
    assert c.connu and not c.services_connus


def test_declaration_operateur_et_perimetre():
    c = cx.depuis_declaration("ubuntu:22.04")
    assert (c.os_id, c.version, c.origine) == ("ubuntu", "22.04", "operateur")
    c = cx.depuis_declaration("serveur-web (RHEL 9)", origine="perimetre")
    assert (c.os_id, c.version, c.famille) == ("rhel", "9", "rhel")
    assert not cx.depuis_declaration("10.0.0.0/24, exemple.fr").connu


def test_applicabilite_systeme():
    ubuntu = cx.Contexte("ubuntu", "22.04", "debian")
    rocky = cx.Contexte("rocky", "9.3", "rhel")
    assert cx.applicable(_fiche(["linux"]), ubuntu)[0]
    assert cx.applicable(_fiche(["ubuntu>=20.04"]), ubuntu)[0]
    assert not cx.applicable(_fiche(["ubuntu>=24.04"]), ubuntu)[0]
    assert not cx.applicable(_fiche(["rhel>=8"]), ubuntu)[0]
    assert cx.applicable(_fiche(["rhel>=8"]), rocky)[0]        # rebuild RHEL
    assert not cx.applicable(_fiche(["rhel>=10"]), rocky)[0]
    assert cx.applicable(_fiche(["debian"]), ubuntu)[0]        # famille sans version
    assert not cx.applicable(_fiche(["debian>=11"]), ubuntu)[0]  # 22 != debian 11
    # Contexte inconnu : aucun filtrage.
    assert cx.applicable(_fiche(["rhel>=8"]), cx.Contexte())[0]


def test_applicabilite_services():
    avec = cx.Contexte("ubuntu", "22.04", "debian", services=["nginx"],
                       services_connus=True)
    assert not cx.applicable(_fiche(["linux"], ["openssh"]), avec)[0]
    assert cx.applicable(_fiche(["linux"], ["nginx>=1.18"]), avec)[0]
    inconnus = cx.Contexte("ubuntu", "22.04", "debian")
    assert cx.applicable(_fiche(["linux"], ["openssh"]), inconnus)[0]


def test_variante_choisie_selon_la_famille():
    pare_feu = next(f for f in bib.toutes() if f.id == "ports-pare-feu")
    rhel = cx.Contexte("rocky", "9.3", "rhel")
    texte_rhel = pare_feu.pour_le_modele(rhel)
    assert "firewall-cmd --list-all" in texte_rhel
    assert "ufw status" not in texte_rhel
    texte_ubuntu = pare_feu.pour_le_modele(cx.Contexte("ubuntu", "22.04", "debian"))
    assert "ufw status" in texte_ubuntu and "firewall-cmd" not in texte_ubuntu


def test_recuperation_filtree_par_contexte():
    # Serveur sans SSH detecte : la fiche SSH est ecartee, et on le dit.
    sans_ssh = cx.Contexte("ubuntu", "22.04", "debian", services=["nginx"],
                           services_connus=True)
    fiches, motif = bib.recuperer("ssh autorise root ?", n=2, contexte=sans_ssh)
    assert all("openssh" not in f.applicable.get("services", []) for f in fiches)
    assert "ecartee" in motif and "service absent" in motif
    # Avec SSH : retenues.
    avec_ssh = cx.Contexte("ubuntu", "22.04", "debian", services=["openssh"],
                           services_connus=True)
    fiches, _ = bib.recuperer("ssh autorise root ?", n=2, contexte=avec_ssh)
    assert {"ssh-durcissement", "cac-sshd-disable-root-login"} & {f.id for f in fiches}
    # Fiche importee pour Debian 12 / Ubuntu 22.04-24.04 : ecartee sur RHEL 9
    # (une fiche importee valable pour tout Linux peut, elle, remonter).
    rhel = cx.Contexte("rhel", "9.4", "rhel", services=["openssh"],
                       services_connus=True)
    fiches, motif = bib.recuperer("ssh autorise root ?", n=2, contexte=rhel)
    assert all(cx.applicable(f, rhel)[0] for f in fiches)
    assert "cac-sshd-disable-root-login" not in {f.id for f in fiches}
    assert "PermitRootLogin" in motif and "hors champ" in motif


def test_contexte_memorise_dans_laudit():
    m = MemoireAudit.ouvrir("c", Path(tempfile.mkdtemp()), perimetre="srv")
    m.fixer_contexte(cx.Contexte("ubuntu", "22.04", "debian",
                                 origine="detection"))
    relu = MemoireAudit.charger("c", m.dossier)
    assert cx.Contexte.depuis_dict(relu.contexte).os_id == "ubuntu"
    assert "ubuntu 22.04" in relu.resume_pour_prompt()
    assert "ubuntu 22.04" in relu.resume_humain()
    # Contexte inconnu : rien de memorise, rien d'affirme au modele.
    m.fixer_contexte(cx.Contexte())
    assert m.contexte is None and "Systeme audite" not in m.resume_pour_prompt()
