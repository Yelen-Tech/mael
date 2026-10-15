"""Le bac a sable (couche 6) avec le VRAI navigateur — 16/10/2026.

Couverture mesuree a 62 % : le passage dans Chromium etait toujours
desactive pendant les tests (MAEL_SANS_NAVIGATEUR=1). Or c'est la que se
joue la regle de securite : RIEN NE SORT de la machine. Un petit projet
piege est ouvert pour de vrai ; le test est saute si Playwright ou Chromium
manque (et le bilan doit alors le DIRE, verifie a part).
    ./venv/Scripts/python.exe -m pytest brain/tests_bac_a_sable_navigateur.py -q
"""
import pytest

from brain.codage import bac_a_sable

PIEGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Piege</title>
<script src="https://cdn.exemple-externe.com/suivi.js"></script>
</head><body>
<main>
<h1>Titre</h1>
<p style="color:#bbbbbb;background:#ffffff">texte peu contraste</p>
<img src="absente.png" alt="image absente">
<div style="width:1400px">bloc trop large pour un telephone</div>
</main>
<script>
console.error("message perso");
nexistePas.appeler();
</script>
</body></html>
"""

SAINE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Saine</title></head>
<body><main><h1>Bonjour</h1><p>Une page sans defaut.</p></main></body></html>
"""


def _chromium_disponible() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:                                   # noqa: BLE001
        return False


avec_navigateur = pytest.mark.skipif(not _chromium_disponible(),
                                     reason="Playwright / Chromium absent")


@avec_navigateur
def test_la_page_piegee_ouverte_pour_de_vrai_rien_ne_sort(tmp_path,
                                                         monkeypatch):
    monkeypatch.delenv("MAEL_SANS_NAVIGATEUR", raising=False)
    (tmp_path / "index.html").write_text(PIEGE, encoding="utf-8")
    (tmp_path / "saine.html").write_text(SAINE, encoding="utf-8")
    (tmp_path / "app.py").write_text("print('serveur')\n")
    defauts = bac_a_sable.juger(tmp_path, ["index.html", "saine.html",
                                           "app.py"])
    par_regle = {d.regle: d for d in defauts}
    # la regle de securite : l'appel exterieur est COUPE, et dit
    externe = par_regle["ressource-externe"]
    assert "cdn.exemple-externe.com" in externe.message
    assert "coupe" in externe.message
    # ce que l'execution reelle revele
    assert "nexistePas" in par_regle["js-erreur-execution"].message
    assert any("absente.png" in d.message for d in defauts
               if "introuvable" in d.message)
    assert "message perso" in par_regle["console-erreur"].message
    assert par_regle["debordement-mobile"].fichier == "index.html"
    # la page saine ne declenche rien
    assert not [d for d in defauts if d.fichier == "saine.html"]
    r = bac_a_sable.dernier_rapport
    assert r.pages == ["index.html", "saine.html"] and not r.non_ouvertes
    assert r.serveur == ["app.py"]                 # lu, jamais execute
    bilan = " ".join(bac_a_sable.limites())
    assert "pages ouvertes dans un navigateur" in bilan
    assert "app.py" in bilan
    if r.axe:                                      # axe-core embarque
        assert any("contrast" in d.regle or "1.4.3" in d.norme
                   for d in defauts)


def test_sans_navigateur_le_bilan_le_dit(tmp_path, monkeypatch):
    """Jamais « rien a signaler » quand rien n'a ete ouvert."""
    monkeypatch.setenv("MAEL_SANS_NAVIGATEUR", "1")
    (tmp_path / "index.html").write_text(SAINE, encoding="utf-8")
    assert bac_a_sable.juger(tmp_path, ["index.html"]) == []
    assert "navigateur non lance" in " ".join(bac_a_sable.limites())


def test_playwright_absent_dit(tmp_path, monkeypatch):
    monkeypatch.delenv("MAEL_SANS_NAVIGATEUR", raising=False)
    monkeypatch.setattr(bac_a_sable, "_playwright", lambda: None)
    (tmp_path / "index.html").write_text(SAINE, encoding="utf-8")
    assert bac_a_sable.juger(tmp_path, ["index.html"]) == []
    assert "Playwright absent" in " ".join(bac_a_sable.limites())


def test_le_code_serveur_est_nomme_jamais_execute(tmp_path):
    (tmp_path / "serveur.js").write_text("const e = require('express')\n")
    (tmp_path / "client.js").write_text("document.title = 'x'\n")
    (tmp_path / "api.php").write_text("<?php echo 1;")
    assert bac_a_sable.code_serveur(
        tmp_path, ["serveur.js", "client.js", "api.php", "absent.js"]) == [
        "serveur.js", "api.php"]
