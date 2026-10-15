"""Le moteur LLAMA.CPP tenu par MAEL (llamacpp.py) — 16/10/2026.

Couverture mesuree a 54 % : le CYCLE DE VIE du processus (demarrage, panne
au demarrage, arret, relance, orphelin) n'etait pas teste, alors que les
vraies pannes (Kaggle 15/10, examen des 100 missions) etaient la. Ici un
FAUX llama-server tourne pour de vrai, dans son propre processus : MAEL le
lance, l'attend, l'interroge, le tue et le relance exactement comme le vrai.
    ./venv/Scripts/python.exe -m pytest brain/tests_moteur_llamacpp.py -q
"""
import json
import os
import socket
import subprocess
import sys
import textwrap

import pytest
from django.conf import settings as reglages

from brain.backends import llamacpp as mod
from brain.backends.sante import MoteurEnPanne
from brain.modeles import ProblemeDeModele

FAUX_SERVEUR = textwrap.dedent('''
    """Faux llama-server : /health, /v1/models, /v1/chat/completions."""
    import json, os, sys, time
    from http.server import BaseHTTPRequestHandler, HTTPServer
    a = sys.argv
    port = int(a[a.index("--port") + 1])
    if os.environ.get("FAUX_MODE") == "plante":
        sys.exit(3)
    reponses = json.loads(os.environ.get("FAUX_REPONSES", '["5"]'))
    compteur = os.environ.get("FAUX_COMPTEUR", "")

    class H(BaseHTTPRequestHandler):
        def log_message(self, *x):
            pass

        def _json(self, d, code=200):
            b = json.dumps(d).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path == "/health":
                self._json({"status": "ok"})
            elif self.path == "/v1/models":
                self._json({"data": [{"meta": {"n_params": 30.5e9,
                                                "n_ctx": 32768}}]})

        def do_POST(self):
            corps = json.loads(self.rfile.read(
                int(self.headers["Content-Length"])))
            texte = reponses.pop(0) if len(reponses) > 1 else reponses[0]
            if compteur:
                with open(compteur, "a") as f:
                    f.write(json.dumps(corps) + "\\n")
            if corps.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for mot in texte.split(" "):
                    d = {"choices": [{"delta": {"content": mot + " "}}]}
                    self.wfile.write(f"data: {json.dumps(d)}\\n\\n".encode())
                self.wfile.write(b"data: [DONE]\\n\\n")
                return
            self._json({"choices": [{"message": {"content": texte}}],
                        "usage": {"prompt_tokens": 11,
                                  "completion_tokens": 2}})

    HTTPServer(("127.0.0.1", port), H).serve_forever()
''')


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def moteur(tmp_path, monkeypatch):
    """Un LlamaCppBackend dont le « llama-server » est le faux serveur,
    lance pour de vrai (sous-processus Python)."""
    faux = tmp_path / "faux_serveur.py"
    faux.write_text(FAUX_SERVEUR, encoding="utf-8")
    serveur = tmp_path / "llama-server.exe"
    serveur.write_text("")
    modele = tmp_path / "Qwen3-Coder-30B.gguf"
    modele.write_text("")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    commandes = []
    vrai_popen = subprocess.Popen

    def popen(commande, **k):
        commandes.append(list(commande))
        return vrai_popen([sys.executable, str(faux), *commande[1:]], **k)
    monkeypatch.setattr(mod.subprocess, "Popen", popen)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(reglages, "BRAIN", {
        **reglages.BRAIN, "TIMEOUT": 30, "LLAMACPP": {
            "SERVEUR": str(serveur), "MODELE": str(modele),
            "PORT": _port_libre(), "CONTEXTE": 32768, "FILS": 2, "GPU": 0}})
    b = mod.LlamaCppBackend()
    b.commandes = commandes
    yield b
    b.arreter()


def _q(b, **k):
    return b.completer(systeme="s", messages=[{"role": "user",
                                               "content": "q"}],
                       role_modele="codeur", **k)


def test_demarre_attend_repond_et_s_arrete(moteur):
    r = _q(moteur, max_jetons=64)
    assert r.texte == "5" and r.jetons_entree == 11 and r.jetons_sortie == 2
    assert r.modele == "Qwen3-Coder-30B"
    c = moteur.commandes[0]
    assert c[c.index("--host") + 1] == "127.0.0.1"     # jamais le reseau
    assert c[c.index("-c") + 1] == "32768" and "-ngl" not in c
    assert moteur.fichier_pid.read_text() == str(moteur.processus.pid)
    p = moteur.processus
    moteur.arreter()
    assert p.poll() is not None                          # memoire rendue
    assert not moteur.fichier_pid.exists()


def test_cartes_graphiques_et_envergure(moteur):
    moteur.gpu = 999
    e = moteur.envergure()
    assert "-ngl" in moteur.commandes[0]
    assert moteur.commandes[0][moteur.commandes[0].index("-ngl") + 1] == "999"
    assert e.contexte == 32768 and round(e.milliards, 1) == 30.5
    assert e.classe == "grand"


def test_panne_au_demarrage_dite_avec_son_code(moteur, monkeypatch):
    monkeypatch.setenv("FAUX_MODE", "plante")
    with pytest.raises(MoteurEnPanne) as e:
        moteur.demarrer()
    assert "code 3" in str(e.value) and "serveur.log" in str(e.value)


def test_pas_pret_a_temps_arrete_et_le_dit(moteur, monkeypatch):
    monkeypatch.setattr(mod, "DEMARRAGE_MAX", 0)
    with pytest.raises(MoteurEnPanne) as e:
        moteur.demarrer()
    assert "pas pret" in str(e.value) and moteur.processus is None


def test_charabia_relance_puis_panne_dite(moteur, monkeypatch, tmp_path):
    """Kaggle et examen des 100 : un moteur abime repond du charabia. MAEL
    relance (nouveau processus) puis abandonne en le DISANT."""
    monkeypatch.setenv("FAUX_REPONSES", json.dumps(["and " * 40]))
    with pytest.raises(MoteurEnPanne) as e:
        _q(moteur)
    assert "meme apres relance" in str(e.value)
    assert moteur.relances == 1 and len(moteur.commandes) == 2


def test_relance_reussie_si_la_reponse_redevient_juste(moteur, monkeypatch):
    monkeypatch.setenv("FAUX_REPONSES", json.dumps(["and " * 40,
                                                     "bonne reponse"]))
    premier = None

    def avant():
        nonlocal premier
        premier = moteur.processus.pid
    moteur.demarrer()
    avant()
    # le faux serveur relance repart de sa file : on la remet pour lui
    monkeypatch.setenv("FAUX_REPONSES", json.dumps(["bonne reponse"]))
    r = _q(moteur)
    assert r.texte == "bonne reponse" and moteur.relances == 1
    assert moteur.processus.pid != premier               # vrai nouveau processus


def test_sonde_fausse_deux_fois_panne(moteur, monkeypatch):
    monkeypatch.setenv("FAUX_REPONSES", json.dumps(["7"]))     # 2 + 3 = 7 ?
    with pytest.raises(MoteurEnPanne) as e:
        moteur.verifier_sante()
    assert "2 + 3" in str(e.value) and moteur.relances == 1
    monkeypatch.setenv("FAUX_REPONSES", json.dumps(["5"]))
    moteur.arreter()
    assert moteur.verifier_sante() == ""


def test_orphelin_d_une_session_precedente_tue(moteur):
    orphelin = subprocess.Popen([sys.executable, "-c",
                                 "import time; time.sleep(120)"])
    moteur.fichier_pid.parent.mkdir(parents=True, exist_ok=True)
    moteur.fichier_pid.write_text(str(orphelin.pid))
    moteur._tuer_orphelin()
    assert orphelin.wait(timeout=20) is not None
    assert not moteur.fichier_pid.exists()


def test_flux_morceau_par_morceau(moteur, monkeypatch):
    monkeypatch.setenv("FAUX_REPONSES", json.dumps(["un deux trois"]))
    f = moteur.flux(systeme="s", messages=[{"role": "user", "content": "q"}],
                    role_modele="codeur")
    morceaux = list(f)
    assert "".join(morceaux).split() == ["un", "deux", "trois"]
    assert len(morceaux) == 3


def test_schema_impose_et_outils_lus(moteur, monkeypatch, tmp_path):
    compteur = tmp_path / "corps.jsonl"
    monkeypatch.setenv("FAUX_COMPTEUR", str(compteur))
    monkeypatch.setenv("FAUX_REPONSES", json.dumps(['{"a": 1}']))
    r = _q(moteur, schema={"type": "object"})
    corps = json.loads(compteur.read_text().splitlines()[-1])
    assert corps["response_format"]["type"] == "json_schema"
    assert r.donnees == {"a": 1}
    appels = mod.LlamaCppBackend._outils_de({"tool_calls": [
        {"function": {"name": "lire", "arguments": '{"f": "a.py"}'}},
        {"function": {"name": "x", "arguments": "{pas du json"}}]})
    assert appels == [{"nom": "lire", "arguments": {"f": "a.py"}},
                      {"nom": "x", "arguments": {}}]


def test_trouver_le_moteur_et_le_modele(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    racine = tmp_path / "MAEL"
    for d in ("moteur/llama-b6000", "moteur/llama-b6500", "modeles"):
        (racine / d).mkdir(parents=True)
    for v in ("b6000", "b6500"):
        (racine / f"moteur/llama-{v}/llama-server.exe").write_text("")
    assert mod.trouver_serveur().parent.name == "llama-b6500"   # la plus recente
    assert mod.trouver_serveur(str(tmp_path / "absent")) is None
    assert mod.trouver_modele() is None                          # aucun gguf
    for n in ("phi4-mini.gguf", "qwen3-coder.gguf"):
        (racine / "modeles" / n).write_text("")
    assert mod.trouver_modele() is None                          # deux : ambigu
    assert mod.trouver_modele(voulu="qwen3-coder:30b").name == "qwen3-coder.gguf"
    (racine / "installe.json").write_text(json.dumps(
        {"fichier": "phi4-mini.gguf"}))
    assert mod.trouver_modele().name == "phi4-mini.gguf"         # pose par mael


def test_moteur_introuvable_dit_quoi_faire(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(reglages, "BRAIN", {**reglages.BRAIN, "LLAMACPP": {}})
    with pytest.raises(ProblemeDeModele) as e:
        mod.LlamaCppBackend()
    assert "llama-server" in str(e.value)
    assert os.path.join("MAEL", "moteur") in " ".join(e.value.conseils)
