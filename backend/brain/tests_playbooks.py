"""Etape 2.6 : playbooks de correction et validation securisee.

Les scripts sont executes en SIMULATION (Git Bash sous Windows, bash sous
Linux) : aucun ne modifie la machine de test. L'application reelle se teste
sur une machine Linux jetable (etape 2.5, Docker ou VM).
"""
import json
import os
import shutil
import tempfile
from pathlib import Path

from brain import playbooks as pbs


def _bash():
    for c in (r"C:\Program Files\Git\bin\bash.exe", shutil.which("bash")):
        if c and os.path.exists(c):
            return c
    return None


EXEMPLES = {
    "infra.sysctl": {"cle": "net.ipv4.ip_forward", "valeur": "0"},
    "infra.fichier-droits": {"chemin": "/etc/mael-inexistant", "mode": "0600"},
    "infra.fichier-proprietaire": {"chemin": "/etc/mael-inexistant",
                                   "proprietaire": "root"},
    "infra.fichier-groupe": {"chemin": "/etc/mael-inexistant", "groupe": "root"},
    "infra.paquet-retirer": {"paquet": "telnetd"},
    "infra.paquet-installer": {"paquet": "auditd"},
    "infra.service-desactiver": {"service": "avahi-daemon"},
    "infra.service-activer": {"service": "auditd"},
    "infra.module-interdit": {"module": "usb-storage"},
    "infra.ssh-directive": {"directive": "PermitRootLogin", "valeur": "no"},
    "infra.cle-valeur": {"fichier": "/etc/login.defs", "cle": "PASS_MAX_DAYS",
                         "valeur": "365", "format": "espace"},
    "infra.sudo-defaults": {"option": "use_pty"},
    "infra.audit-regles": {"regles": "-w /etc/passwd -p wa -k mael"},
    "infra.grub-argument": {"argument": "audit=1", "action": "ajouter"},
    "infra.montage-option": {"point": "/tmp", "option": "nodev"},
    "infra.fichiers-motif": {"dossier": "/etc", "regex": "^/etc/mael-.*$",
                             "nature": "droits", "valeur": "0644",
                             "recursif": "non", "exclure": "[bw]tmp,lastlog.*"},
    "infra.fichier-existence": {"chemin": "/etc/mael-inexistant",
                                "etat": "absent"},
}


def test_structure_et_manifestes():
    tous = pbs.tous()
    assert set(EXEMPLES) <= set(tous)
    for pid, pb in tous.items():
        for f in pb.fichiers():
            assert f.exists(), f"{pid} : {f.name} manquant"
        if pid.startswith("infra."):
            m = pb.manifeste
            assert m["reversible"] and m["simulation"] and m["racine_requise"]
            assert (m.get("source") or {}).get("gabarit"), pid
            for p in pb.parametres:
                assert p.get("motif"), f"{pid} : motif manquant pour {p['nom']}"


def test_sceau_intact_puis_rompu():
    for pid in pbs.tous():
        assert pbs.controler_sceau(pid) == [], pid
    # un script modifie (empreinte differente dans le sceau) est refuse
    vrai = json.loads(pbs.SCEAU.read_text(encoding="utf-8"))
    faux = dict(vrai, **{"infra.sysctl": dict(vrai["infra.sysctl"],
                                              **{"appliquer.sh": "0" * 64})})
    with tempfile.TemporaryDirectory() as d:
        chemin = Path(d) / "sceau.json"
        chemin.write_text(json.dumps(faux), encoding="utf-8")
        ancien, pbs.SCEAU = pbs.SCEAU, chemin
        try:
            assert pbs.controler_sceau("infra.sysctl") == ["appliquer.sh modifie"]
            r = pbs.executer("infra.sysctl", "appliquer",
                             EXEMPLES["infra.sysctl"], "bash", simulation=True)
            assert r.refuse.startswith("sceau rompu") and not r.ok
        finally:
            pbs.SCEAU = ancien


def test_parametres_injection_refusee():
    assert pbs.valider_parametres("infra.sysctl", EXEMPLES["infra.sysctl"]) == []
    assert pbs.valider_parametres("infra.sysctl",
                                  {"cle": "x; rm -rf /", "valeur": "0"})
    assert pbs.valider_parametres("infra.ssh-directive",
                                  {"directive": "PermitRootLogin",
                                   "valeur": "no; reboot"})
    assert pbs.valider_parametres("infra.sysctl", {"cle": "a.b"})   # requis
    assert pbs.valider_parametres("infra.sysctl", {"cle": "a.b"}, complet=False) == []
    assert pbs.valider_parametres("infra.sysctl", {**EXEMPLES["infra.sysctl"],
                                                   "autre": "1"})
    # revenir/detecter ne recoivent que la cle d'etat
    assert pbs.arguments("infra.sysctl", "revenir",
                         EXEMPLES["infra.sysctl"]) == ["net.ipv4.ip_forward"]
    assert pbs.arguments("infra.sysctl", "appliquer", EXEMPLES["infra.sysctl"],
                         simulation=True) == ["--simulation",
                                              "net.ipv4.ip_forward", "0"]


def test_simulations_sans_effet():
    bash = _bash()
    if not bash:
        return
    for pid, params in EXEMPLES.items():
        r = pbs.executer(pid, "appliquer", params, bash, simulation=True)
        # 5 = ssh-directive refuse si sshd_config n'inclut pas sshd_config.d
        assert r.code in (0, 5), (pid, r.code, r.sortie)
        assert not r.refuse
    # injection passee directement au script (hors validation Python) :
    # le script la refuse lui-meme (code 64)
    import subprocess
    script = pbs.obtenir("infra.sysctl").script("appliquer")
    r = subprocess.run([bash, str(script), "--simulation", "x; reboot", "0"],
                       capture_output=True)
    assert r.returncode == 64


def test_fiches_liees_aux_playbooks():
    from brain import bibliotheque
    fiches = {f.id: f for f in bibliotheque.toutes()}
    c = fiches["cac-sysctl-net-ipv4-ip-forward"].controles[0]
    assert c.playbook == "infra.sysctl"
    assert c.parametres == {"cle": "net.ipv4.ip_forward", "valeur": "0"}
    lies = [ct for f in fiches.values() for ct in f.controles if ct.playbook]
    assert len(lies) >= 250
    for ct in lies:
        assert pbs.valider_parametres(ct.playbook, ct.parametres,
                                      complet=False) == []


def test_boucle_corriger_en_simulation():
    """/corriger : sceau, simulation montree, rien applique, trace gardee."""
    bash = _bash()
    if not bash:
        return
    from brain.bibliotheque import ecarts
    from brain.memoire import MemoireAudit
    from core.management.commands.terminal import Command
    with tempfile.TemporaryDirectory() as d:
        c = Command()
        c.executer, c.bash, c.contexte = False, None, None
        c.memoire = MemoireAudit("t", Path(d), perimetre="srv")
        c.memoire.enregistrer_verdicts(ecarts.evaluer_commande(
            "sysctl -n net.ipv4.ip_forward", "1\n", niveau=None))
        sortie = []
        c.stdout.write = lambda t="", *a, **k: sortie.append(str(t))
        c._corriger("")                       # liste
        assert any("infra.sysctl" in l for l in sortie)
        c._corriger("1")                      # simulation
        texte = "\n".join(sortie)
        assert "SIMULATION" in texte and "sceau intact" in texte
        trace = c.memoire.corrections[-1]
        assert trace["playbook"] == "infra.sysctl" and not trace["applique"]
        assert "net.ipv4.ip_forward = 0" in trace["simulation"]


def test_chaque_controle_a_une_correction_ou_une_raison():
    """Etape 2.6 complete : playbook, ou raison ecrite de correction
    manuelle. Aucun controle sans statut."""
    from brain import bibliotheque
    ctl = [(f.id, c) for f in bibliotheque.toutes() for c in f.controles]
    orphelins = [fid for fid, c in ctl if not c.playbook and not c.sans_playbook]
    assert not orphelins, orphelins[:5]
    avec = sum(1 for _, c in ctl if c.playbook)
    # 513 au 18/09 ; la relecture du 19/09 a rendu manuelles ~20 corrections
    # dangereuses (sudo 4110, noexec, squashfs, overlay, nosmt, cron.allow...).
    assert avec >= 480


def test_regles_audit_generees():
    from brain.bibliotheque.importeurs.gabarits_cac import lignes_audit
    regles = lignes_audit([
        {"comparateur": "surveille", "champ": "/etc/passwd"},
        {"comparateur": "appels", "champ": "chmod"},
        {"comparateur": "appels", "champ": "execve", "options": [["euid!=uid"]]},
    ], auid=True)
    lignes = regles.split(" | ")
    assert "-w /etc/passwd -p wa -k mael" in lignes
    assert any("arch=b32 -S chmod" in l for l in lignes)
    assert any("arch=b64 -S chmod" in l and "auid>=1000" in l for l in lignes)
    assert any("-C euid!=uid -F auid!=unset" in l for l in lignes)
    assert pbs.valider_parametres("infra.audit-regles", {"regles": regles}) == []
    # et ces regles satisfont l'evaluation du code
    from brain.bibliotheque.ecarts import STATUT, lire
    sortie = chr(10).join(lignes)
    assert lire(sortie, {"lecteur": "audit", "comparateur": "appels",
                         "champ": "chmod"}).statut is STATUT.CONFORME
    assert lire(sortie, {"lecteur": "audit", "comparateur": "appels",
                         "champ": "execve", "options": [["euid!=uid"]]}
                ).statut is STATUT.CONFORME


def test_revenir_recoit_ses_parametres():
    """Releve a la relecture du 19/09/2026 : revenir.sh de cle-valeur,
    montage-option et fichiers-motif exigeait 2-3 arguments mais n'en
    recevait qu'un -> retour arriere impossible. Chaque script doit recevoir
    au moins les arguments qu'il exige (${N:?...})."""
    import re
    for pid, pb in pbs.tous().items():
        params = {p["nom"]: "x" for p in pb.parametres}
        for etape in ("detecter", "revenir", "verifier"):
            texte = pb.script(etape).read_text(encoding="utf-8")
            exiges = {int(n) for n in re.findall(r"\$\{(\d):\?", texte)}
            recus = len(pbs.arguments(pid, etape, params))
            assert max(exiges, default=0) <= recus, (pid, etape, exiges, recus)
        for nom in pb.manifeste.get("parametres_revenir") or []:
            assert nom in params, (pid, nom)


def test_droits_jamais_ajoutes():
    """chmod : bits actuels ET mode voulu, jamais le mode voulu tel quel."""
    for pid in ("infra.fichier-droits", "infra.fichiers-motif"):
        texte = pbs.obtenir(pid).script("appliquer").read_text(encoding="utf-8")
        assert "& 8#$VOULU" in texte or "& 8#$VALEUR" in texte, pid
