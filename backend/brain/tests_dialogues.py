"""Tests du corpus de dialogues de reference (etape 10 du plan Kimi).

Le corpus est valide par le code ; l'injection est bornee et etiquetee ;
et comme toujours : un exemple montre le ton, il ne decide rien.
"""
from __future__ import annotations

from pathlib import Path

from brain import dialogues


def _valide() -> dict:
    return {
        "id": "test",
        "theme": "observer",
        "mots_cles": ["test"],
        "echanges": [
            {"role": "humain", "texte": "Une question."},
            {"role": "mael", "texte": "Une reponse."},
        ],
    }


def test_corpus_reel_valide():
    nb_err, texte = dialogues.rapport()
    assert nb_err == 0, texte
    tous = dialogues.tous()
    assert len(tous) >= 12                # un dialogue par theme au 20/09
    themes = {d.theme for d in tous}
    assert themes == dialogues.THEMES     # chaque theme a son dialogue
    ids = [d.id for d in tous]
    assert len(ids) == len(set(ids))


def test_valider_refuse_les_dialogues_douteux():
    assert dialogues.valider(_valide()) == []
    d = _valide()
    d["theme"] = "bavardage"
    assert dialogues.valider(d)
    d = _valide()
    d["echanges"][0]["role"] = "mael"     # commence par l'humain
    assert dialogues.valider(d)
    d = _valide()
    d["echanges"].append({"role": "mael", "texte": "Deux fois de suite."})
    assert dialogues.valider(d)           # alternance rompue
    d = _valide()
    d["echanges"][1]["texte"] = "x" * 601
    assert dialogues.valider(d)           # un exemple est court
    d = _valide()
    d["echanges"] = [{"role": "humain", "texte": "Seul."}]
    assert dialogues.valider(d)           # au moins deux tours
    d = _valide()
    assert dialogues.valider(d, Path("autre-nom.yaml"))  # id != fichier


def test_choisir_trouve_le_bon_dialogue():
    assert dialogues.choisir("peux-tu casser ce mot de passe").id == \
        "refuser_offensif"
    assert dialogues.choisir("fais le bilan").id == "bilan"
    assert dialogues.choisir("corrige cet écart").id == "corriger"
    assert dialogues.choisir("") is None
    assert dialogues.choisir("cuisine tarte pommes") is None


def test_pour_prompt_etiquette_et_borne():
    bloc = dialogues.pour_prompt("fais le bilan")
    assert bloc.startswith("EXEMPLE DE REFERENCE")
    assert "PAS des faits" in bloc
    assert "humain :" in bloc and "mael :" in bloc
    assert dialogues.pour_prompt("cuisine tarte") == ""
    # budget serre : on retire l'exemple plutot que de le tronquer
    assert dialogues.pour_prompt("fais le bilan", budget_jetons=5) == ""


def test_dialogues_hors_des_decisions_de_securite():
    """Garde-fou, ecarts, playbooks, fondement : aucun ne lit le corpus."""
    import brain.bibliotheque.ecarts as ecarts
    import brain.fondement as fondement
    import brain.garde.commandes as garde
    import brain.playbooks as playbooks
    for module in (garde, ecarts, playbooks, fondement):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "dialogues" not in source, module.__name__
