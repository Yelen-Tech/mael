"""`mael installer` (13/10/2026) : rien sans accord, le modele d'origine
DIT, empreinte verifiee, reprise apres coupure, archive enfermee. Reseau
simule (httpx.MockTransport) : aucun octet ne sort pendant les tests."""
import hashlib
import io
import json
import tarfile
import zipfile
from collections import namedtuple
from pathlib import Path

import httpx
import pytest

from brain import installation as inst
from brain.backends import llamacpp


def _f(nom: str, contenu: bytes, sha: str = "") -> inst.Fichier:
    return inst.Fichier(f"https://exemple.test/{nom}", nom, len(contenu),
                        sha or hashlib.sha256(contenu).hexdigest())


def _client(fichiers: dict[str, bytes], vus: list | None = None,
            ignore_range: bool = False) -> httpx.Client:
    def traiter(req: httpx.Request) -> httpx.Response:
        if vus is not None:
            vus.append(req)
        corps = fichiers[req.url.path.lstrip("/")]
        plage = req.headers.get("range")
        if plage and not ignore_range:
            debut = int(plage.split("=")[1].rstrip("-"))
            return httpx.Response(206, content=corps[debut:])
        return httpx.Response(200, content=corps)
    return httpx.Client(transport=httpx.MockTransport(traiter))


@pytest.fixture
def racine(tmp_path, monkeypatch):
    monkeypatch.setattr(inst, "_racine_mael", lambda: tmp_path)
    monkeypatch.setattr(llamacpp, "_racine_mael", lambda: tmp_path)
    return tmp_path


# ------------------------------------------------------------ catalogue
def test_catalogue_fige_et_honnete():
    m = inst.CATALOGUE["mael-coder"]
    assert m.base == "Qwen/Qwen3-Coder-30B-A3B-Instruct"
    assert m.licence == "Apache-2.0"
    assert len(m.source.sha256) == 64 and "/resolve/" in m.source.url
    assert "/resolve/main/" not in m.source.url          # revision figee
    for fichiers in inst.MOTEURS.values():
        for f in fichiers:
            assert f.url.startswith("https://github.com/ggml-org/llama.cpp/"
                                    "releases/download/b11122/")
            assert len(f.sha256) == 64
    carte = inst.carte(m)
    assert "PAS un modele entraine" in carte and m.base in carte
    assert "Apache-2.0" in carte and m.source.sha256 in carte


def test_plan_annonce_le_modele_d_origine(racine, monkeypatch):
    monkeypatch.setattr("brain.machine.memoire", lambda: (8 * inst.Go, 0))
    monkeypatch.setattr("brain.machine.carte_graphique", lambda: None)
    plan = inst.preparer(systeme="Windows")
    texte = "\n".join(plan.lignes())
    assert "MAEL-Coder" in texte and "Qwen/Qwen3-Coder-30B-A3B-Instruct" \
        in texte and "Apache-2.0" in texte
    assert plan.acceleration == "cpu"
    assert any("8.0 Go" in a for a in plan.avertissements)  # machine trop petite
    assert plan.a_telecharger > 18 * inst.Go


def test_rien_a_refaire(racine, monkeypatch):
    monkeypatch.setattr("brain.machine.carte_graphique", lambda: None)
    (racine / "modeles").mkdir()
    (racine / "modeles" / "mael-coder.gguf").write_bytes(b"x")
    (racine / "moteur" / "llama-b11122").mkdir(parents=True)
    (racine / "installe.json").write_text(json.dumps(
        {"modele": "MAEL-Coder", "moteur": "b11122-cpu"}))
    assert inst.preparer(systeme="Linux", acceleration="cpu"
                         ).a_telecharger == 0


# -------------------------------------------------------- telechargement
def test_telecharge_et_verifie(tmp_path):
    contenu = b"modele" * 1000
    f = _f("m.gguf", contenu)
    p = inst.telecharger(f, tmp_path / "m.gguf", _client({"m.gguf": contenu}))
    assert p.read_bytes() == contenu
    assert not (tmp_path / "m.gguf.partiel").exists()


def test_empreinte_fausse_detruit(tmp_path):
    f = _f("m.gguf", b"vrai contenu", sha="0" * 64)
    with pytest.raises(inst.InstallationImpossible, match="FAUSSE"):
        inst.telecharger(f, tmp_path / "m.gguf",
                         _client({"m.gguf": b"vrai contenu"}))
    assert list(tmp_path.iterdir()) == []                 # rien ne reste


def test_reprise_apres_coupure(tmp_path):
    contenu = bytes(range(256)) * 50
    (tmp_path / "m.gguf.partiel").write_bytes(contenu[:4000])
    vus = []
    inst.telecharger(_f("m.gguf", contenu), tmp_path / "m.gguf",
                     _client({"m.gguf": contenu}, vus))
    assert vus[0].headers["range"] == "bytes=4000-"
    assert (tmp_path / "m.gguf").read_bytes() == contenu


def test_serveur_sans_reprise_recommence(tmp_path):
    contenu = b"abcdef" * 500
    (tmp_path / "m.gguf.partiel").write_bytes(contenu[:100])
    inst.telecharger(_f("m.gguf", contenu), tmp_path / "m.gguf",
                     _client({"m.gguf": contenu}, ignore_range=True))
    assert (tmp_path / "m.gguf").read_bytes() == contenu


def test_https_exige(tmp_path):
    f = inst.Fichier("http://exemple.test/m", "m", 1, "0" * 64)
    with pytest.raises(inst.InstallationImpossible, match="HTTPS"):
        inst.telecharger(f, tmp_path / "m", _client({}))


# --------------------------------------------------------------- archive
def test_zip_piege_refuse(tmp_path):
    a = tmp_path / "piege.zip"
    with zipfile.ZipFile(a, "w") as z:
        z.writestr("../../evade.exe", b"x")
    with pytest.raises(inst.InstallationImpossible, match="hors du dossier"):
        inst.extraire(a, tmp_path / "moteur")
    assert not (tmp_path.parent / "evade.exe").exists()


def test_tar_linux_aplati(tmp_path):
    a = tmp_path / "m.tar.gz"
    with tarfile.open(a, "w:gz") as t:
        for nom in ("build/bin/llama-server", "build/bin/libllama.so"):
            info = tarfile.TarInfo(nom)
            info.size = 2
            t.addfile(info, io.BytesIO(b"ok"))
    inst.extraire(a, tmp_path / "moteur")
    assert (tmp_path / "moteur" / "llama-server").exists()
    assert (tmp_path / "moteur" / "libllama.so").exists()


# ------------------------------------------------------- de bout en bout
def _archive_moteur() -> bytes:
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as z:
        z.writestr("llama-server.exe", b"serveur")
    return tampon.getvalue()


def test_installation_complete(racine, monkeypatch):
    moteur, gguf = _archive_moteur(), b"GGUF" * 2000
    fm = _f("moteur.zip", moteur)
    m = inst.CATALOGUE["mael-coder"]
    petit = inst.ModeleCatalogue(**{**m.__dict__,
                                    "source": _f("q.gguf", gguf)})
    plan = inst.Plan(petit, [fm], "cpu", racine)
    etat = inst.installer(plan, _client({"moteur.zip": moteur,
                                         "q.gguf": gguf}))
    assert etat["modele"] == "MAEL-Coder" and etat["base"] == m.base
    assert (racine / "moteur" / "llama-b11122" / "llama-server.exe").exists()
    assert (racine / "modeles" / "mael-coder.gguf").read_bytes() == gguf
    assert "PAS un modele entraine" in (racine / "modeles" /
                                        "MAEL-Coder.md").read_text("utf-8")
    assert json.loads((racine / "installe.json").read_text())["sha256"] \
        == petit.source.sha256
    # le moteur de MAEL le trouve, meme a cote d'un autre modele
    (racine / "modeles" / "phi4-mini.gguf").write_bytes(b"x")
    assert llamacpp.trouver_modele(voulu="phi4-mini:latest").name \
        == "mael-coder.gguf"
    assert llamacpp.trouver_modele(
        reglage=str(racine / "modeles" / "phi4-mini.gguf")).name \
        == "phi4-mini.gguf"                          # le reglage gagne


def test_espace_disque_insuffisant(racine, monkeypatch):
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(inst.shutil, "disk_usage",
                        lambda p: Usage(0, 0, 1 * inst.Go))
    plan = inst.Plan(inst.CATALOGUE["mael-coder"], [], "cpu", racine)
    with pytest.raises(inst.InstallationImpossible, match="espace disque"):
        inst.installer(plan, _client({}))
    assert not (racine / "modeles").exists()


def test_commande_sans_accord_ne_telecharge_rien(racine, monkeypatch,
                                                  capsys):
    from django.core.management import call_command
    monkeypatch.setattr("brain.machine.carte_graphique", lambda: None)
    monkeypatch.setattr("builtins.input", lambda q: "n")
    appels = []
    monkeypatch.setattr(inst, "installer", lambda *a, **k: appels.append(1))
    call_command("installer")
    sortie = capsys.readouterr().out
    assert "Qwen/Qwen3-Coder-30B-A3B-Instruct" in sortie
    assert "Rien n'a ete telecharge" in sortie and appels == []


def test_moteur_par_defaut(racine, monkeypatch):
    from config import settings as s
    monkeypatch.setenv("LOCALAPPDATA", str(racine.parent))
    dossier = racine.parent / "MAEL"
    dossier.mkdir(exist_ok=True)
    assert s._moteur_par_defaut() == "ollama"
    (dossier / "installe.json").write_text(json.dumps({"modele": "MAEL-Coder"}))
    assert s._moteur_par_defaut() == "llamacpp"


def test_chemin_reel_du_catalogue():
    assert Path(inst.CATALOGUE["mael-coder"].fichier_local).suffix == ".gguf"
