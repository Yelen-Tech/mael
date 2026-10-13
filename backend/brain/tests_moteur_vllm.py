"""Le moteur vLLM (13/10/2026) : le grand modele installe sur la machine de
MAEL. Le reseau est simule (httpx.MockTransport) : ce sont les VRAIES
requetes que MAEL construit qui sont lues."""
import json
import logging

import httpx
import pytest

from brain.backends import llamacpp as mod_llama
from brain.backends.sante import MoteurEnPanne
from brain.backends.vllm import VllmBackend
from brain.modeles import ProblemeDeModele

LOCAL = {"MODELE": "Qwen/Qwen3-Coder"}          # URL par defaut : 127.0.0.1


def _reseau(monkeypatch, reponses):
    """Les requetes envoyees, et une file de reponses (contenu, statut ou
    exception)."""
    envoyees, file = [], list(reponses)

    def traiter(requete: httpx.Request) -> httpx.Response:
        envoyees.append(requete)
        r = file.pop(0)
        if isinstance(r, Exception):
            raise r
        if isinstance(r, int):
            return httpx.Response(r, json={"error": "x"})
        return httpx.Response(200, json={
            "choices": [{"message": {"content": r}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3}})
    vrai_client = httpx.Client

    def client(**k):
        return vrai_client(transport=httpx.MockTransport(traiter), **k)
    monkeypatch.setattr(mod_llama.httpx, "Client", client)
    return envoyees


@pytest.fixture
def sans_attente(monkeypatch):
    monkeypatch.setattr("brain.backends.vllm.time.sleep", lambda s: None)


def test_sur_la_machine_meme_sans_cle(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    envoyees = _reseau(monkeypatch, ['{"fichiers": ["a.py"], "raison": "r"}'])
    b = VllmBackend(LOCAL)
    r = b.completer(systeme="s", messages=[{"role": "user", "content": "q"}],
                    role_modele="codeur", schema={"type": "object"},
                    max_jetons=500)
    req = envoyees[0]
    corps = json.loads(req.content)
    assert str(req.url) == "http://127.0.0.1:8000/v1/chat/completions"
    assert "authorization" not in req.headers
    assert corps["model"] == "Qwen/Qwen3-Coder" and corps["max_tokens"] == 500
    assert corps["response_format"]["type"] == "json_schema"
    assert r.donnees == {"fichiers": ["a.py"], "raison": "r"}
    assert r.modele == "Qwen/Qwen3-Coder" and r.jetons_entree == 7
    assert caplog.text == ""                 # rien ne sort : rien a dire


def test_url_avec_v1_non_doublee():
    assert VllmBackend({**LOCAL, "URL": "http://127.0.0.1:9000/v1/"}).base \
        == "http://127.0.0.1:9000"


def test_autre_machine_avec_cle_https_obligatoire(caplog):
    caplog.set_level(logging.WARNING)
    with pytest.raises(ProblemeDeModele) as e:
        VllmBackend({**LOCAL, "URL": "http://10.0.0.5:8000", "CLE": "k-1"})
    assert "HTTPS" in str(e.value)
    b = VllmBackend({**LOCAL, "URL": "https://gpu.interne:8000",
                     "CLE": "k-secret-1"})
    assert b._entetes == {"Authorization": "Bearer k-secret-1"}
    assert "k-secret" not in repr(b) and "k-secret" not in caplog.text
    assert "gpu.interne" in caplog.text      # l'envoi hors machine est DIT


def test_modele_manquant_dit_quoi_faire():
    with pytest.raises(ProblemeDeModele) as e:
        VllmBackend({})
    assert "BRAIN_VLLM_MODELE" in str(e.value)


def test_surcharge_puis_reponse(monkeypatch, sans_attente):
    _reseau(monkeypatch, [503, "- a.py : corrige"])
    b = VllmBackend(LOCAL)
    r = b.completer(systeme="s", messages=[{"role": "user", "content": "q"}],
                    role_modele="codeur")
    assert r.texte == "- a.py : corrige" and b.relances == 1


def test_panne_durable(monkeypatch, sans_attente):
    _reseau(monkeypatch, [httpx.ConnectError("x"), httpx.ConnectError("x")])
    with pytest.raises(MoteurEnPanne):
        VllmBackend(LOCAL).completer(
            systeme="s", messages=[{"role": "user", "content": "q"}],
            role_modele="codeur")


def test_requete_refusee_remonte_tout_de_suite(monkeypatch, sans_attente):
    _reseau(monkeypatch, [400])
    b = VllmBackend(LOCAL)
    with pytest.raises(httpx.HTTPStatusError):
        b.completer(systeme="s", messages=[{"role": "user", "content": "q"}],
                    role_modele="codeur")
    assert b.relances == 0                     # pas de nouvel essai inutile


def test_envergure_d_apres_la_carte_du_modele():
    from brain.codage.envergure import lire
    e = lire(VllmBackend({**LOCAL, "MILLIARDS": 80, "CONTEXTE": 131072}))
    assert e.milliards == 80 and e.contexte == 131072
    assert lire(VllmBackend(LOCAL)).milliards >= 20     # grand par defaut


def test_brain_backend_vllm(monkeypatch):
    """Avant le 13/10, ce choix importait un fichier absent."""
    from django.conf import settings

    from brain.backends.base import obtenir_backend
    monkeypatch.setitem(settings.BRAIN, "VLLM", LOCAL)
    monkeypatch.setitem(settings.BRAIN, "BACKEND", "vllm")
    assert isinstance(obtenir_backend(), VllmBackend)
    monkeypatch.setitem(settings.BRAIN, "BACKEND", "remote")
    with pytest.raises(ValueError):            # pas d'API exterieure
        obtenir_backend()
