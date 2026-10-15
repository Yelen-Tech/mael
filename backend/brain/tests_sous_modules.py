"""Sous-modules git (astropy-6938, Kaggle 15/10) : l'archive GitHub laisse
les sous-modules vides ; MAEL les telecharge au commit exact du gitlink."""
import io
import json
import tarfile

from brain.codage import sous_modules as sm


def _archive(nom: str, fichiers: dict[str, str]) -> bytes:
    """Une vraie archive tar.gz « depot-sha/fichier » en memoire."""
    brut = io.BytesIO()
    with tarfile.open(fileobj=brut, mode="w:gz") as t:
        for chemin, contenu in fichiers.items():
            donnees = contenu.encode()
            m = tarfile.TarInfo(f"{nom}/{chemin}")
            m.size = len(donnees)
            t.addfile(m, io.BytesIO(donnees))
    return brut.getvalue()


def _gitmodules(dossier, corps: str):
    (dossier / ".gitmodules").write_text(corps, encoding="utf-8")


def test_lire_gitmodules_absent(tmp_path):
    assert sm.lire_gitmodules(tmp_path) == []


def test_lire_gitmodules_deux_sections(tmp_path):
    _gitmodules(tmp_path, '[submodule "astropy_helpers"]\n'
                          '\tpath = astropy_helpers\n'
                          '\turl = https://github.com/astropy/'
                          'astropy-helpers.git\n'
                          '[submodule "cextern"]\n'
                          '\tpath = cextern\n'
                          '\turl = ../cextern.git\n')
    assert sm.lire_gitmodules(tmp_path) == [
        ("astropy_helpers", "https://github.com/astropy/astropy-helpers.git"),
        ("cextern", "../cextern.git")]


def test_depot_de_urls():
    repo = "astropy/astropy"
    assert sm._depot_de("https://github.com/astropy/astropy-helpers.git",
                        repo) == "astropy/astropy-helpers"
    assert sm._depot_de("git@github.com:astropy/astropy-helpers.git",
                        repo) == "astropy/astropy-helpers"
    assert sm._depot_de("git://github.com/astropy/astropy-helpers",
                        repo) == "astropy/astropy-helpers"
    assert sm._depot_de("../astropy-helpers.git",
                        repo) == "astropy/astropy-helpers"
    assert sm._depot_de("https://gitlab.com/a/b.git", repo) is None


def test_completer_telecharge_et_extrait_au_gitlink(tmp_path, monkeypatch):
    dossier, archives = tmp_path / "depot", tmp_path / "archives"
    dossier.mkdir()
    _gitmodules(dossier, '[submodule "astropy_helpers"]\n'
                         '\tpath = astropy_helpers\n'
                         '\turl = ../astropy-helpers.git\n')
    appels = []

    def faux_run(cmd, **kw):
        appels.append(cmd[-1])
        if "api.github.com" in cmd[-1]:
            assert "ref=C0MM17" in cmd[-1]
            sortie = json.dumps({"type": "submodule", "sha": "5HA",
                                 "submodule_git_url":
                                 "https://github.com/astropy/"
                                 "astropy-helpers.git"})
            return subprocess_sortie(0, stdout=sortie)
        assert cmd[-1] == ("https://codeload.github.com/astropy/"
                           "astropy-helpers/tar.gz/5HA")
        (archives / "astropy__astropy-helpers").mkdir(parents=True,
                                                      exist_ok=True)
        (archives / "astropy__astropy-helpers" / "5HA.tar.part").write_bytes(
            _archive("astropy-helpers-5HA", {"ah_bootstrap.py": "x = 1\n"}))
        return subprocess_sortie(0)

    monkeypatch.setattr(sm.subprocess, "run", faux_run)
    assert sm.completer("astropy/astropy", "C0MM17", dossier,
                        archives) == []
    assert (dossier / "astropy_helpers" / "ah_bootstrap.py").is_file()
    # le cache est pose : un second appel ne telecharge plus rien
    appels.clear()
    assert sm.completer("astropy/astropy", "C0MM17", dossier,
                        archives) == []
    assert appels == []


def test_completer_api_en_echec_dit_le_manquant(tmp_path, monkeypatch):
    dossier = tmp_path / "depot"
    dossier.mkdir()
    _gitmodules(dossier, '[submodule "h"]\n\tpath = h\n\turl = ../h.git\n')
    monkeypatch.setattr(sm.subprocess, "run",
                        lambda cmd, **kw: subprocess_sortie(22))
    monkeypatch.setattr(sm.time, "sleep", lambda s: None)
    assert sm.completer("a/a", "C", dossier, tmp_path / "archives") == ["h"]


def test_completer_ignore_un_sous_module_deja_rempli(tmp_path, monkeypatch):
    dossier = tmp_path / "depot"
    (dossier / "h").mkdir(parents=True)
    (dossier / "h" / "deja.txt").write_text("la", encoding="utf-8")
    _gitmodules(dossier, '[submodule "h"]\n\tpath = h\n\turl = ../h.git\n')

    def interdit(cmd, **kw):
        raise AssertionError("aucun telechargement attendu")

    monkeypatch.setattr(sm.subprocess, "run", interdit)
    assert sm.completer("a/a", "C", dossier, tmp_path / "archives") == []


def test_completer_sans_gitmodules_ne_fait_rien(tmp_path, monkeypatch):
    monkeypatch.setattr(sm.subprocess, "run",
                        lambda cmd, **kw: (_ for _ in ()).throw(
                            AssertionError("aucun appel attendu")))
    assert sm.completer("a/a", "C", tmp_path, tmp_path / "archives") == []


class subprocess_sortie:                              # noqa: N801
    """Le minimum de subprocess.CompletedProcess pour les doubles."""

    def __init__(self, returncode: int, stdout: str = ""):
        self.returncode = returncode
        self.stdout = stdout
