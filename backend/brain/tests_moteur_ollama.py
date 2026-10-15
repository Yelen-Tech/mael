"""Le moteur OLLAMA (ollama.py) — 16/10/2026.

Couverture mesuree a 53 % : la RELANCE (dechargement puis attente que le
modele quitte la memoire), le flux et les pannes en flux n'etaient pas
testes. Un faux Ollama A ETAT (modeles charges, file de reponses) lit les
vraies requetes que MAEL construit.
    ./venv/Scripts/python.exe -m pytest brain/tests_moteur_ollama.py -q
"""
import json

import httpx
import pytest

from brain.backends import ollama as mod
from brain.backends.sante import MoteurEnPanne

MODELE = "qwen3:8b"
VRAI_CLIENT = httpx.Client


class FauxOllama:
    def __init__(self, reponses):
        self.reponses = list(reponses)      # texte, int (statut), Exception
        self.charges = {MODELE}
        self.requetes: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requetes.append(req)
        chemin = req.url.path
        if chemin == "/api/generate":       # keep_alive 0 : decharger
            self.charges.discard(json.loads(req.content)["model"])
            return httpx.Response(200, json={})
        if chemin == "/api/ps":
            return httpx.Response(200, json={"models": [
                {"name": m} for m in self.charges]})
        if chemin == "/api/show":
            return httpx.Response(200, json={"model_info": {
                "general.parameter_count": 8.2e9}})
        corps = json.loads(req.content)
        self.charges.add(corps["model"])
        r = self.reponses.pop(0) if len(self.reponses) > 1 else \
            self.reponses[0]
        if isinstance(r, Exception):
            raise r
        if isinstance(r, int):
            return httpx.Response(r, json={"error": "x"})
        if isinstance(r, dict):                       # message complet
            message = r
        else:
            message = {"role": "assistant", "content": r}
        if corps.get("stream"):
            lignes = [json.dumps({"message": {"content": m + " "}})
                      for m in message.get("content", "").split(" ") if m]
            lignes.insert(1, "{ligne illisible")
            lignes.append(json.dumps({"message": {
                "content": "", "tool_calls": message.get("tool_calls")},
                "done": True, "prompt_eval_count": 9, "eval_count": 4}))
            return httpx.Response(200, content="\n".join(lignes).encode())
        return httpx.Response(200, json={"message": message,
                                         "prompt_eval_count": 9,
                                         "eval_count": 4})


@pytest.fixture
def ollama(monkeypatch):
    def installer(*reponses):
        faux = FauxOllama(reponses)

        def client(**k):
            return VRAI_CLIENT(transport=httpx.MockTransport(faux), **k)
        monkeypatch.setattr(mod.httpx, "Client", client)
        monkeypatch.setattr(mod.time, "sleep", lambda s: None)
        monkeypatch.setattr(mod.OllamaBackend, "modele_pour",
                            lambda self, role: MODELE)
        b = mod.OllamaBackend()
        b.faux = faux
        return b
    return installer


def _q(b, **k):
    return b.completer(systeme="s", messages=[{"role": "user",
                                               "content": "q"}], **k)


def _chats(b):
    return [json.loads(r.content) for r in b.faux.requetes
            if r.url.path == "/api/chat"]


def test_corps_garde_en_memoire_borne_et_contraint(ollama):
    b = ollama('{"verdict": "ok"}')
    r = _q(b, schema={"type": "object"}, max_jetons=300)
    corps = _chats(b)[0]
    assert corps["keep_alive"] and corps["options"]["num_predict"] == 300
    assert corps["format"] == {"type": "object"}
    assert r.donnees == {"verdict": "ok"} and r.jetons_entree == 9


def test_consigne_trop_longue_contexte_agrandi_et_plafonne(ollama):
    b = ollama("ok")
    b.completer(systeme="x" * 60_000, messages=[])
    assert _chats(b)[0]["options"]["num_ctx"] == mod.CONTEXTE_MAX


def test_erreur_500_le_modele_est_decharge_puis_la_question_reposee(ollama):
    b = ollama(500, "la bonne reponse")
    r = _q(b)
    assert r.texte == "la bonne reponse" and b.relances == 1
    chemins = [q.url.path for q in b.faux.requetes]
    assert chemins == ["/api/chat", "/api/generate", "/api/ps", "/api/chat"]
    assert json.loads(b.faux.requetes[1].content) == {"model": MODELE,
                                                      "keep_alive": 0}


def test_delai_depasse_deux_fois_panne_dite(ollama):
    b = ollama(httpx.ReadTimeout("lent"))
    with pytest.raises(MoteurEnPanne) as e:
        _q(b)
    assert "delai depasse, meme apres relance" in str(e.value)


def test_erreur_4xx_remonte_sans_relance(ollama):
    b = ollama(404)
    with pytest.raises(httpx.HTTPStatusError):
        _q(b)
    assert b.relances == 0


def test_charabia_relance(ollama):
    b = ollama("and " * 40, "Une vraie reponse, avec des mots.")
    assert _q(b).texte.startswith("Une vraie") and b.relances == 1


def test_appels_d_outils_recoltes_meme_sans_texte(ollama):
    appel = {"function": {"name": "lire", "arguments": {"f": "a.py"}}}
    b = ollama({"role": "assistant", "content": "", "tool_calls": [appel]})
    r = _q(b, outils=[{"type": "function"}])
    assert r.appels_outils == [{"nom": "lire", "arguments": {"f": "a.py"}}]
    assert b.relances == 0           # une reponse VIDE mais avec outils : saine


def test_flux_morceaux_ligne_illisible_ignoree(ollama):
    b = ollama("un deux trois")
    f = b.flux(systeme="s", messages=[{"role": "user", "content": "q"}])
    assert "".join(f).split() == ["un", "deux", "trois"]
    assert f.reponse.texte.split() == ["un", "deux", "trois"]
    assert f.reponse.jetons_entree == 9 and f.reponse.jetons_sortie == 4


def test_flux_charabia_long_relance_et_panne(ollama):
    b = ollama("and " * 80)
    f = b.flux(systeme="s", messages=[{"role": "user", "content": "q"}])
    with pytest.raises(MoteurEnPanne):
        list(f)
    assert b.relances == 1


def test_flux_delai_et_erreur_500_relancent(ollama):
    for panne, attendu in ((httpx.ReadTimeout("x"), "delai depasse"),
                           (503, "erreur 503")):
        b = ollama(panne)
        with pytest.raises(MoteurEnPanne) as e:
            list(b.flux(systeme="s", messages=[]))
        assert attendu in str(e.value) and b.relances == 1


def test_sonde_et_sante(ollama):
    assert ollama("5").verifier_sante() == ""
    assert ollama("7", "5").verifier_sante() == "relance"
    with pytest.raises(MoteurEnPanne) as e:
        ollama("7").verifier_sante()
    assert "2 + 3" in str(e.value)
    assert ollama(httpx.ConnectError("absent")).sonde(MODELE) is False


def test_envergure(ollama):
    e = ollama("ok").envergure()
    assert round(e.milliards, 1) == 8.2 and e.modele == MODELE
