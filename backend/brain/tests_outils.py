"""Outils embarques (19/09/2026) : surface (naabu, subfinder, httpx) et
outils locaux (Trivy, gitleaks, ClamAV). Sans Docker : on teste la ligne
docker produite, la validation des chemins et la lecture des sorties.
"""
import django
from django.conf import settings

if not settings.configured:            # tests lances hors manage.py
    import os
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()

from brain.tools import OutilRefuse, registre  # noqa: E402
from brain.tools.base import Observation, chemin_local_valide  # noqa: E402


def _obs(nom, sortie):
    o = Observation(outil=nom, cible="x")
    registre[nom].analyser(sortie, o)
    return o


def test_outils_inscrits():
    for nom in ("ports_ouverts", "sous_domaines", "services_web",
                "vulnerabilites_paquets", "secrets_exposes", "antivirus"):
        assert nom in registre.noms(), nom


def test_chemins_locaux():
    assert chemin_local_valide("/") == "/"
    assert chemin_local_valide("/var/www") == "/var/www"
    assert chemin_local_valide("C:\\Users\\x") == "C:/Users/x"
    for mauvais in ("var/www", "/var/../etc", "/proc", "/sys/kernel",
                    "/dev/sda", "/run/secrets", "/a,readonly=false", "",
                    "/x\ny"):
        try:
            chemin_local_valide(mauvais)
            assert False, mauvais
        except OutilRefuse:
            pass


def test_ligne_docker_verrouillee():
    """Conteneur verrouille, montage en LECTURE SEULE via --mount."""
    o = registre["vulnerabilites_paquets"]
    ligne = o.arguments_docker("img@sha256:x", ["rootfs", "/cible"], "/var/www")
    assert ligne[:3] == ["docker", "run", "--rm"]
    for attendu in ("--read-only", "--cap-drop", "ALL", "no-new-privileges"):
        assert attendu in ligne
    i = ligne.index("--mount")
    assert ligne[i + 1] == "type=bind,source=/var/www,target=/cible,readonly"
    assert "-v" not in ligne and "--privileged" not in ligne
    assert ligne[ligne.index("--tmpfs") + 1].startswith("/tmp:rw,noexec,nosuid")
    # outil sans reseau
    assert registre["secrets_exposes"].arguments_docker("i", [], "/x")[4] == "none"
    # point d'entree impose (clamav lance clamd sinon)
    l2 = registre["antivirus"].arguments_docker("i", ["/cible"], "/x")
    assert l2[l2.index("--entrypoint") + 1] == "clamscan"


def test_naabu_ports_risques():
    sortie = ('{"host":"a.fr","ip":"10.0.0.1","port":22,"protocol":"tcp"}\n'
              '{"host":"a.fr","ip":"10.0.0.1","port":6379,"protocol":"tcp"}\n'
              '{"ip":"10.0.0.1","port":{"Port":445,"Protocol":0}}\n'
              'bruit\n{"ip":"10.0.0.1","port":22}\n')
    o = _obs("ports_ouverts", sortie)
    par_port = {c["details"]["port"]: c["gravite"] for c in o.constats}
    assert par_port == {22: "info", 6379: "critique", 445: "critique"}
    cmd = registre["ports_ouverts"].commande(cible="a.fr")
    assert cmd[cmd.index("-scan-type") + 1] == "c"      # aucune capacite
    assert "-top-ports" in cmd and "1000" in cmd


def test_subfinder_et_httpx():
    o = _obs("sous_domaines", '{"host":"B.a.fr","source":"crtsh"}\n'
                              '{"host":"b.a.fr"}\n{"host":"c.a.fr"}\n')
    assert [c["details"]["hote"] for c in o.constats] == ["b.a.fr", "c.a.fr"]
    o = _obs("services_web",
             '{"url":"http://a.fr","status_code":200,"title":"<script>x",'
             '"tech":["nginx"],"webserver":"nginx"}\n')
    codes = [c["code"] for c in o.constats]
    assert codes == ["web.service", "web.http-clair"]
    # le titre (texte du site) n'entre jamais dans le resume
    assert "<script>" not in o.constats[0]["resume"]


def test_trivy_tri_et_plafond():
    import json
    vulns = [{"VulnerabilityID": f"CVE-2026-{i}", "PkgName": "p",
              "InstalledVersion": "1", "FixedVersion": "2",
              "Severity": "LOW" if i else "CRITICAL"} for i in range(70)]
    o = _obs("vulnerabilites_paquets",
             "INFO bruit\n" + json.dumps({"Results": [{"Vulnerabilities": vulns}]}))
    assert o.constats[0]["gravite"] == "critique"          # le pire d'abord
    assert len(o.constats) == 61                          # 60 + resume
    assert o.constats[-1]["code"] == "cve.autres"
    cmd = registre["vulnerabilites_paquets"].commande(cible="/cible")
    assert "--ignore-unfixed" in cmd and cmd[-1] == "/cible"


def test_gitleaks_secret_jamais_rapporte():
    import json
    sortie = json.dumps([{"RuleID": "aws-access-token", "File": "/cible/app/.env",
                          "StartLine": 3, "Secret": "REDACTED",
                          "Match": "AWS=REDACTED"}])
    o = _obs("secrets_exposes", sortie)
    c = o.constats[0]
    assert c["details"]["fichier"] == "/app/.env" and c["gravite"] == "elevee"
    assert "Secret" not in c["details"] and "Match" not in c["details"]
    assert "--redact" in registre["secrets_exposes"].commande(cible="/cible")


def test_clamav():
    o = _obs("antivirus", "/cible/tmp/x.bin: Eicar-Test-Signature FOUND\n"
                          "/cible/ok.txt: OK\n")
    assert len(o.constats) == 1
    assert o.constats[0]["details"] == {"fichier": "/tmp/x.bin",
                                        "signature": "Eicar-Test-Signature"}


def test_images_toutes_figees():
    from brain.tools.base import image_figee
    for nom in registre.noms():
        o = registre[nom]
        if o.image:
            assert "@sha256:" in image_figee(o.image), nom


def test_echec_jamais_pris_pour_resultat_propre():
    """Trivy en echec (code 1) rendait « 0 faille » : tout code hors
    codes_succes leve OutilEchoue."""
    from brain.tools import OutilEchoue
    o = registre["vulnerabilites_paquets"]
    o._lancer = lambda args, montage=None: ("FATAL scan error", 1)
    try:
        o.executer(organisation=None, cible="/")
        assert False, "echec avale"
    except OutilEchoue as exc:
        assert "code de sortie 1" in str(exc)
    finally:
        del o._lancer
    assert 1 in registre["antivirus"].codes_succes        # 1 = virus trouve


def test_trivy_hors_ligne():
    o = registre["vulnerabilites_paquets"]
    cmd = o.commande(cible="/cible")
    assert "--skip-db-update" in cmd and "--offline-scan" in cmd
    ligne = o.arguments_docker("i", cmd, "/")
    assert ligne[ligne.index("--network") + 1] == "none"
    assert "type=volume,source=mael-trivy-cache,target=/cache" in ligne
