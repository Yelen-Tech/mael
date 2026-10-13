"""`mael audit` (13/10/2026) : un regard qui n'a pas tourne n'est jamais
« rien trouve » ; seules les regles de SECURITE du code entrent ; Trivy lit
un depot hors ligne, enferme."""
import json

import pytest

from brain import audit
from brain.tools import registre
from brain.tools.base import Observation, OutilEchoue

TRIVY = {
    "Results": [
        {"Target": "requirements.txt", "Class": "lang-pkgs",
         "Vulnerabilities": [
             {"VulnerabilityID": "CVE-2023-32681", "PkgName": "requests",
              "InstalledVersion": "2.25.0", "FixedVersion": "2.31.0",
              "Severity": "MEDIUM", "Title": "Proxy-Authorization leak"},
             {"VulnerabilityID": "CVE-2022-42969", "PkgName": "py",
              "InstalledVersion": "1.10.0", "FixedVersion": "1.11.0",
              "Severity": "HIGH", "Title": "ReDoS"}]},
        {"Target": "Dockerfile", "Class": "config",
         "Misconfigurations": [
             {"AVDID": "AVD-DS-0002", "Title": "Image user should not be "
              "'root'", "Severity": "HIGH", "Status": "FAIL",
              "Resolution": "Add 'USER <non root user name>'",
              "CauseMetadata": {"StartLine": 1}},
             {"AVDID": "AVD-DS-0001", "Title": "ok", "Severity": "LOW",
              "Status": "PASS"}]}]}


def test_trivy_depot_hors_ligne_et_enferme():
    outil = registre["failles_depot"]
    args = outil.commande(cible="/cible")
    assert args[:3] == ["fs", "--scanners", "vuln,misconfig"]
    for drapeau in ("--offline-scan", "--skip-db-update",
                    "--skip-java-db-update", "--skip-check-update"):
        assert drapeau in args
    docker = outil.arguments_docker("img@sha256:x", args, "C:/depot")
    assert docker[docker.index("--network") + 1] == "none"
    assert "--read-only" in docker
    assert any("readonly" in a for a in docker if a.startswith("type=bind"))


def test_trivy_depot_lit_failles_et_configuration():
    obs = Observation(outil="failles_depot", cible="/cible")
    registre["failles_depot"].analyser("bruit\n" + json.dumps(TRIVY), obs)
    codes = [c["code"] for c in obs.constats]
    assert codes[0] == "depot.lu"
    assert codes[1] == "CVE-2022-42969"                 # elevee d'abord
    assert "CVE-2023-32681" in codes and "AVD-DS-0002" in codes
    assert "AVD-DS-0001" not in codes                   # PASS : pas un constat
    root = next(c for c in obs.constats if c["code"] == "AVD-DS-0002")
    assert root["gravite"] == "elevee" and root["details"]["ligne"] == 1


def test_trivy_sans_rapport_n_est_pas_rien_trouve():
    with pytest.raises(OutilEchoue, match="PAS"):
        registre["failles_depot"].analyser("panic: db missing",
                                           Observation("x", "y"))


def _depot(tmp_path):
    (tmp_path / "app.py").write_text(
        "import sqlite3\n\n"
        "def chercher(con, nom):\n"
        "    return con.execute(f\"SELECT * FROM clients WHERE nom = "
        "'{nom}'\").fetchall()\n", encoding="utf-8")
    (tmp_path / "index.html").write_text("<p>sans doctype</p>\n",
                                         encoding="utf-8")
    return tmp_path


def test_sans_docker_audit_incomplet_et_dit(tmp_path):
    r = audit.auditer(_depot(tmp_path), docker_ok=lambda: "Docker ne "
                      "repond pas : demarrer Docker Desktop")
    assert set(r.non_verifie) == {"secrets", "dependances"}
    assert any(c.regard == "code" for c in r.constats)
    md = audit.en_markdown(r)
    assert "AUDIT INCOMPLET" in md and "Ce n'est PAS « rien trouve »" in md
    assert r.code_sortie == 1          # l'injection prime : eleve
    r2 = audit.auditer(tmp_path, regards=("secrets",),
                       docker_ok=lambda: "Docker absent")
    assert r2.code_sortie == 2 and not r2.constats


def test_code_seulement_les_regles_de_securite(tmp_path):
    cs = audit.regard_code(_depot(tmp_path))
    assert cs and all(c.regard == "code" for c in cs)
    assert any("injection-sql" in c.detail for c in cs)
    assert not any("doctype" in (c.detail + c.titre).lower() for c in cs)


def test_outils_reunis_dans_un_rapport(tmp_path, monkeypatch):
    def faux(nom, constats):
        def executer(*, organisation, cible):
            obs = Observation(outil=nom, cible=cible)
            for c in constats:
                obs.ajouter(**c)
            return obs
        monkeypatch.setattr(registre[nom], "executer", executer)
    faux("secrets_exposes", [dict(code="secret.aws", gravite="elevee",
                                  resume="Secret possible (aws) dans "
                                         "/config.py:3",
                                  fichier="/config.py", ligne=3)])
    faux("failles_depot", [
        dict(code="depot.lu", gravite="info", resume="1 fichier",
             fichiers=["requirements.txt"]),
        dict(code="CVE-1", gravite="critique", resume="lib 1.0 : CVE-1",
             fichier="requirements.txt", corrigee_en="1.2")])
    (tmp_path / "vide.py").write_text("x = 1\n", encoding="utf-8")
    r = audit.auditer(tmp_path, docker_ok=lambda: "")
    assert [c.gravite for c in r.constats][:2] == ["critique", "elevee"]
    assert r.code_sortie == 1 and not r.non_verifie
    md = audit.en_markdown(r)
    assert "corrige en 1.2" in md and "requirements.txt" in md
    assert "`/config.py:3`" in md


def test_outil_en_echec_devient_non_verifie(tmp_path, monkeypatch):
    def echoue(**k):
        raise OutilEchoue("delai de 1800 s depasse")
    monkeypatch.setattr(registre["failles_depot"], "executer", echoue)
    monkeypatch.setattr(registre["secrets_exposes"], "executer",
                        lambda **k: Observation("s", "c"))
    r = audit.auditer(tmp_path, regards=("secrets", "dependances"),
                      docker_ok=lambda: "")
    assert "delai" in r.non_verifie["dependances"]
    assert "secrets" not in r.non_verifie and r.code_sortie == 2


def test_cellule_echappee():
    assert audit._cellule("a | b\nc") == "a \\| b c"


def test_question_au_modele_bornee_aux_constats_mesures(tmp_path):
    r = audit.Rapport(tmp_path)
    assert audit.question(r) == ""                       # rien a expliquer
    r.constats = [audit.Constat("code", "elevee", f"injection {i}",
                                "app.py", i, "injection-sql")
                  for i in range(20)]
    r.non_verifie["secrets"] = "Docker absent"
    q = audit.question(r, n=5)
    assert "N'ajoute aucun constat absent" in q
    assert "app.py:4" in q and "app.py:5" not in q
    assert "15 constats de plus" in q
    assert "NON VERIFIE" in q and "Docker absent" in q
    h = audit.resume_humain(r, tmp_path / "r.md", n=3)
    assert "20 elevee" in h and "... et 17 de plus" in h


def test_terminal_slash_audit(tmp_path, monkeypatch):
    """/audit dans le terminal : le code audite, ecrit le rapport, et rend
    la question bornee pour le modele."""
    from contextlib import nullcontext

    from core.management.commands.terminal import Command
    _depot(tmp_path)
    monkeypatch.setattr(audit, "docker_disponible", lambda: "Docker absent")
    c = Command()
    c._attente = lambda: nullcontext()
    sortie = []
    c.stdout.write = lambda t="", *a, **k: sortie.append(str(t))
    q = c._audit_depot(str(tmp_path))
    assert (tmp_path / ".mael" / "AUDIT-SECURITE.md").exists()
    assert "NON VERIFIE" in "\n".join(sortie)
    assert "injection" in q.lower() and "N'ajoute aucun constat" in q
    assert c._audit_depot(str(tmp_path / "absent")) == ""
