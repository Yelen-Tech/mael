"""Ce que la machine peut porter (machine.py) — 16/10/2026.

Couverture mesuree a 61 % : Linux (/proc/meminfo), macOS et la lecture de
la carte graphique (nvidia-smi) n'etaient jamais exerces sur le poste
Windows du responsable — alors que Kaggle (Linux, 2 x T4) passe par la.
Chaque systeme est simule ici.
    ./venv/Scripts/python.exe -m pytest brain/tests_machine.py -q
"""
import io
import subprocess

import pytest

from brain import machine
from brain.machine import GO, Capacite


@pytest.fixture(autouse=True)
def neuf():
    machine.oublier()
    yield
    machine.oublier()


def _sortie(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr="")


def test_linux_lit_proc_meminfo(monkeypatch):
    contenu = ("MemTotal:       32763292 kB\nMemFree:  1000 kB\n"
               "MemAvailable:   30458188 kB\n")
    monkeypatch.setattr(machine, "open", lambda *a, **k: io.StringIO(contenu),
                        raising=False)
    monkeypatch.setattr(machine.platform, "system", lambda: "Linux")
    total, dispo = machine.memoire()
    assert round(total / GO, 1) == 31.2 and round(dispo / GO, 1) == 29.0


def test_linux_sans_memavailable_et_illisible(monkeypatch):
    monkeypatch.setattr(machine, "open", lambda *a, **k: io.StringIO(
        "MemTotal: 8000000 kB\n"), raising=False)
    total, dispo = machine._meminfo_linux()
    assert total == dispo == 8000000 * 1024        # prudent : tout compte

    def illisible(*a, **k):
        raise OSError("pas de /proc")
    monkeypatch.setattr(machine, "open", illisible, raising=False)
    assert machine._meminfo_linux() == (0, 0)


def test_macos_sysctl_trois_quarts(monkeypatch):
    monkeypatch.setattr(machine.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(machine.subprocess, "run",
                        lambda *a, **k: _sortie(str(16 * GO)))
    assert machine.memoire() == (16 * GO, 12 * GO)
    monkeypatch.setattr(machine.subprocess, "run",
                        lambda *a, **k: _sortie("pas un nombre"))
    assert machine._memoire_macos() == (0, 0)


def test_systeme_inconnu(monkeypatch):
    monkeypatch.setattr(machine.platform, "system", lambda: "Plan9")
    assert machine.memoire() == (0, 0)


def test_carte_graphique_nvidia_smi_kaggle(monkeypatch):
    """Kaggle : deux T4 de 15 360 Mio ; on lit la premiere."""
    monkeypatch.setattr(machine.subprocess, "run", lambda *a, **k: _sortie(
        "Tesla T4, 15360\nTesla T4, 15360\n"))
    nom, vram = machine.carte_graphique()
    assert nom == "Tesla T4" and vram == 15360 * 1024 * 1024


@pytest.mark.parametrize("comportement", ["absent", "code", "vide",
                                          "illisible"])
def test_pas_de_carte_graphique_n_est_pas_une_erreur(monkeypatch,
                                                     comportement):
    def run(*a, **k):
        if comportement == "absent":
            raise FileNotFoundError("nvidia-smi")
        return {"code": _sortie("", 9), "vide": _sortie(""),
                "illisible": _sortie("Tesla T4, beaucoup")}[comportement]
    monkeypatch.setattr(machine.subprocess, "run", run)
    assert machine.carte_graphique() is None


def test_capacite_mesuree_une_fois_et_sans_gpu_si_demande(monkeypatch):
    appels = []
    monkeypatch.setattr(machine, "memoire", lambda: (8 * GO, 3 * GO))
    monkeypatch.setattr(machine, "carte_graphique",
                        lambda: appels.append(1) or ("Tesla T4", 15 * GO))
    c = machine.capacite()
    assert c.vram == 15 * GO and c.gpu == "Tesla T4"
    assert machine.capacite() is c and len(appels) == 1     # en cache
    monkeypatch.setenv("MAEL_SANS_GPU", "1")
    assert machine.capacite(recharger=True).vram == 0


def test_seuils_et_conseils_selon_la_machine():
    portable = Capacite(ram_totale=8 * GO, ram_libre=3 * GO)
    tour = Capacite(ram_totale=64 * GO, ram_libre=40 * GO)
    gpu = Capacite(ram_totale=16 * GO, ram_libre=4 * GO, vram=24 * GO,
                   gpu="RTX 4090")
    inconnue = Capacite()
    assert portable.a_l_aise == int(8 * GO * 0.6)
    assert portable.au_plus_juste == int(8 * GO * 0.9)
    assert machine.profil_conseille(portable) == "court"
    assert machine.profil_conseille(gpu) == "complet"
    assert machine.profil_conseille(inconnue) == "complet"
    assert [machine.budget_savoir_conseille(c) for c in
            (portable, tour, gpu, inconnue)] == [250, 700, 1200, 1200]
    assert [machine.contexte_conseille(c) for c in
            (portable, tour, gpu)] == [4096, 8192, 8192]
    assert machine.tient(4 * GO, portable)
    assert not machine.tient(6 * GO, portable)
    assert machine.tient(6 * GO, portable, serre=True)
    assert machine.tient(10 ** 15, inconnue)        # inconnue : on laisse
    assert "RTX 4090" in gpu.libelle() and "8.0 Go" in portable.libelle()
    assert inconnue.libelle() == "machine de capacite inconnue"
