"""Tests des corrections tirees de l'EXAMEN des 100 missions (09/10/2026).

Chaque test fige une faiblesse VUE dans l'examen, pour qu'elle ne revienne
pas (consigne du responsable : « on corrige tout, sinon ca va regresser »).
Aucun modele, aucun reseau.
    ./venv/Scripts/python.exe -m pytest brain/tests_examen_100.py -q
"""
from types import SimpleNamespace

import httpx
import pytest

from brain.backends import ollama as mod_ollama
from brain.backends.sante import MoteurEnPanne, charabia
from brain.codage import memoire, reparation
from brain.codage.espace import Espace
from brain.codage.juges import GRAVITE, Defaut

B = GRAVITE.BLOQUANT


@pytest.fixture(autouse=True)
def _sans_outils_externes(monkeypatch):
    monkeypatch.setenv("MAEL_SANS_OUTILS", "1")
    monkeypatch.setenv("MAEL_SANS_NAVIGATEUR", "1")
    monkeypatch.setenv("MAEL_SANS_EXECUTION", "1")
    monkeypatch.setenv("MAEL_SANS_PROFESSEURS", "1")


PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Nos pains</title>
<link rel="stylesheet" href="styles.css">
</head>
<body>
<nav aria-label="Menu">
  <ul>
    <li><a href="index.html">Accueil</a></li>
    <li><a href="page.html">Page complete</a></li>
  </ul>
</nav>
<main><h1>Nos pains</h1>
<p>Voir <a href="fantome.html">la suite</a> ici.</p></main>
</body>
</html>"""


def _ecrire(tmp_path, nom, texte):
    (tmp_path / nom).write_text(texte, encoding="utf-8")


# ------------------------------------------------ reparations programmees
def test_ajoute_le_script_du_plan_qui_manque(tmp_path):
    # Mission 001 : « charge js/main.js » non tenu, solution connue, laisse.
    _ecrire(tmp_path, "nos-pains.html", PAGE)
    d = Defaut("nos-pains.html", 1, "critere-non-tenu", B,
               'critere de la tache non tenu : charge js/main.js : '
               '<script src="js/main.js" defer></script>', "plan")
    faites = reparation.reparer(Espace(tmp_path), [d], ["nos-pains.html"])
    texte = (tmp_path / "nos-pains.html").read_text(encoding="utf-8")
    assert faites and '<script src="js/main.js" defer></script>\n</head>' \
        in texte
    # Deja la : rien n'est double.
    assert reparation.reparer(Espace(tmp_path), [d], ["nos-pains.html"]) == []
    assert texte.count("js/main.js") == 1


def test_ajoute_le_lien_du_menu_qui_manque(tmp_path):
    _ecrire(tmp_path, "index.html", PAGE)
    d = Defaut("index.html", 1, "critere-non-tenu", B,
               'critere de la tache non tenu : mene a contact.html : '
               '<a href="contact.html">', "plan")
    reparation.reparer(Espace(tmp_path), [d], ["index.html", "contact.html"])
    texte = (tmp_path / "index.html").read_text(encoding="utf-8")
    nav = texte[texte.index("<nav"):texte.index("</nav>")]
    assert '<li><a href="contact.html">Contact</a></li>' in nav


def test_retire_le_lien_vers_une_page_hors_du_plan(tmp_path):
    # Mission 007 : page.html et contact.html, ni au plan ni au projet.
    _ecrire(tmp_path, "index.html", PAGE)
    defauts = [Defaut("index.html", 12, "fichier-absent", B,
                      'href="page.html" : ce fichier n\'existe pas (lien '
                      'casse)', "HTML"),
               Defaut("index.html", 16, "fichier-absent", B,
                      'href="fantome.html" : ce fichier n\'existe pas (lien '
                      'casse)', "HTML")]
    faites = reparation.reparer(Espace(tmp_path), defauts, ["index.html"])
    texte = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert len(faites) == 2
    assert "page.html" not in texte and "Page complete" not in texte  # <li> retire
    assert "Voir la suite ici." in texte                    # le mot reste
    assert '<a href="index.html">Accueil</a>' in texte        # le reste intact


def test_ne_retire_pas_un_lien_vers_une_page_du_plan(tmp_path):
    _ecrire(tmp_path, "index.html", PAGE)
    d = Defaut("index.html", 12, "fichier-absent", B,
               'href="page.html" : ce fichier n\'existe pas (lien casse)',
               "HTML")
    reparation.reparer(Espace(tmp_path), [d], ["index.html", "page.html"])
    assert "page.html" in (tmp_path / "index.html").read_text(
        encoding="utf-8")


def test_cibles_24px_dans_l_unique_feuille_une_seule_fois(tmp_path):
    _ecrire(tmp_path, "index.html", PAGE)
    _ecrire(tmp_path, "styles.css", "body { color: #1f2937; }\n")
    d = Defaut("index.html", 1, "cible-trop-petite", B,
               "All touch targets must be 24px large [axe-core target-size]",
               "WCAG 2.2 — 2.5.8")
    fichiers = ["index.html", "styles.css"]
    assert reparation.reparer(Espace(tmp_path), [d], fichiers)
    assert reparation.reparer(Espace(tmp_path), [d], fichiers) == []
    css = (tmp_path / "styles.css").read_text(encoding="utf-8")
    assert css.count("MAEL : zones cliquables") == 1
    assert "min-height: 24px" in css and css.startswith("body")


def test_leviers_programmes_declares_appliques():
    from brain.codage import leviers
    for l in ("reparer-ressources-du-head", "reparer-liens-du-menu",
              "reparer-lien-hors-plan", "reparer-cibles-24px"):
        assert l in leviers.APPLIQUES and l in leviers.PAR_ID


# ------------------------------------------------- la memoire de travail
def _d(regle, msg="m", fichier="a.html"):
    return Defaut(fichier, 1, regle, B, msg, "n")


def test_memoire_retient_et_constate_la_resolution():
    m = memoire.Memoire()
    m.montres([_d("img-alt"), _d("contraste")])
    m.constater("a.html", [_d("contraste")])
    assert m.resolus() == 1 and [p.regle for p in m.ouverts()] == ["contraste"]


def test_chaque_probleme_restant_dit_pourquoi():
    m = memoire.Memoire()
    m.montres([_d("img-alt")])
    m.montres([_d("img-alt")])
    restes = [_d("img-alt"), _d("contraste"), _d("regle-inconnue-x"),
              _d("img-alt", fichier="verrou.html")]
    lignes = memoire.rapport(m, restes, {"verrou.html"})
    assert "SOLUTION CONNUE non appliquee par le modele en 2 essai(s)" \
        in lignes[0]
    assert "OUTIL MANQUANT" in lignes[1]
    assert "SAVOIR MANQUANT" in lignes[2]
    assert "VERROU" in lignes[3]


def test_finition_reprend_tous_les_fichiers_en_plusieurs_passes():
    from brain.codage import chantier
    assert chantier.FICHIERS_EN_FINITION >= 8 and chantier.PASSES_FINITION >= 2


# --------------------------------------------------------- le charabia
VRAI_CHARABIA = (
    "Je esoter ( teacher andesil ( 1 1  Mark andin   and  Mark 1  and of "
    "course 1 1  and you t is le Tu as le 1 1 1 1 andmeta 1  and 1  and j es "
    "le estime vous nous le 1 1 1  and le 1  and  and es  and   and  and is "
    "le  and  and  and ierenqueuaitainsque vous vous le  and  and ")


def test_charabia_reel_de_l_examen_reconnu():
    assert charabia(VRAI_CHARABIA)
    assert charabia("") == "reponse vide" and charabia("  \n") == "reponse vide"


@pytest.mark.parametrize("texte", [
    "- index.html : l'accueil avec le menu\n- style.css : les styles\n"
    "- js/main.js : le menu sur telephone\n" * 4,
    "body { color: #1f2937; background: #fff; }\nnav a { padding: 8px; }\n"
    * 10,
    "<!DOCTYPE html>\n<html lang=\"fr\"><head><title>A</title></head>"
    "<body><main><h1>Le maquis</h1><p>Le poulet braise est a 2 500 FCFA, "
    "le riz gras a 1 000 FCFA, et le jus de bissap a 300 FCFA.</p></main>"
    "</body></html>" * 3,
    "OK",
])
def test_charabia_pas_de_faux_positif(texte):
    assert charabia(texte) == ""


# ----------------------------------------- le moteur : borne, sonde, relance
class _Rep:
    def __init__(self, contenu=None, statut=200):
        self.status_code = statut
        self._contenu = contenu

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("POST", "http://x")
            raise httpx.HTTPStatusError("x", request=req,
                                        response=httpx.Response(
                                            self.status_code, request=req))

    def json(self):
        return self._contenu


def _moteur(monkeypatch, reponses):
    """Un OllamaBackend dont le reseau rend `reponses` (textes, statuts ou
    exceptions), dans l'ordre ; les corps envoyes sont gardes."""
    monkeypatch.setattr(mod_ollama, "settings", SimpleNamespace(BRAIN={
        "BASE_URL": "http://x", "TIMEOUT": 5, "NUM_CTX": 4096}))
    b = mod_ollama.OllamaBackend()
    b.modele_pour = lambda role: "phi4-mini"
    envoyes, relances = [], []
    b.relancer = lambda modele: relances.append(modele)
    file = list(reponses)

    class Client:
        def __init__(self, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json):
            envoyes.append(json)
            r = file.pop(0)
            if isinstance(r, Exception):
                raise r
            if isinstance(r, int):
                return _Rep(statut=r)
            return _Rep({"message": {"content": r}})
    monkeypatch.setattr(mod_ollama.httpx, "Client", Client)
    return b, envoyes, relances


def test_chaque_appel_a_une_longueur_maximale(monkeypatch):
    b, envoyes, _ = _moteur(monkeypatch, ["- index.html : accueil"])
    b.completer(systeme="s", messages=[{"role": "user", "content": "q"}],
                max_jetons=700)
    assert envoyes[0]["options"]["num_predict"] == 700
    b2, envoyes2, _ = _moteur(monkeypatch, ["reponse"])
    b2.completer(systeme="s", messages=[{"role": "user", "content": "q"}])
    assert envoyes2[0]["options"]["num_predict"] == 2048


def test_consigne_trop_longue_agrandit_le_contexte(monkeypatch):
    b, envoyes, _ = _moteur(monkeypatch, ["ok"])
    b.completer(systeme="s" * 15000, messages=[{"role": "user",
                                                 "content": "q"}])
    assert envoyes[0]["options"]["num_ctx"] == 6144
    b, envoyes, _ = _moteur(monkeypatch, ["ok"])
    b.completer(systeme="court", messages=[{"role": "user", "content": "q"}])
    assert envoyes[0]["options"]["num_ctx"] == 4096     # pas de rechargement


def test_charabia_relance_le_modele_puis_repond(monkeypatch):
    b, envoyes, relances = _moteur(monkeypatch, [VRAI_CHARABIA,
                                                 "- index.html : accueil"])
    r = b.completer(systeme="s", messages=[{"role": "user", "content": "q"}])
    assert r.texte == "- index.html : accueil" and relances == ["phi4-mini"]


@pytest.mark.parametrize("pannes", [
    [VRAI_CHARABIA, ""],
    [500, 500],
    [httpx.ReadTimeout("t"), httpx.ReadTimeout("t")],
])
def test_moteur_abime_meme_relance_leve_moteur_en_panne(monkeypatch, pannes):
    b, _, relances = _moteur(monkeypatch, pannes)
    with pytest.raises(MoteurEnPanne):
        b.completer(systeme="s", messages=[{"role": "user", "content": "q"}])
    assert relances == ["phi4-mini"]


def test_sonde_et_sante(monkeypatch):
    b, _, relances = _moteur(monkeypatch, ["5"])
    assert b.verifier_sante() == ""
    b, _, relances = _moteur(monkeypatch, ["and and 1", "Cinq."])
    assert b.verifier_sante() == "relance" and relances
    b, _, _ = _moteur(monkeypatch, ["", ""])
    with pytest.raises(MoteurEnPanne):
        b.verifier_sante()


# ---------------------------------------------- les missions et la panne
MISSIONS_YAML = """missions:
""" + "".join(f"""  - id: 0{i}-page
    titre: page {i}
    demande: une page d'accueil
""" for i in range(1, 6))


def test_panne_du_moteur_n_est_pas_un_echec_et_arrete_la_serie(tmp_path):
    from brain.codage.missions import Missions

    class MoteurEnPanneTotale:
        recus = []

        def completer(self, **k):
            self.recus.append(1)
            raise MoteurEnPanne("phi4-mini : charabia, meme apres relance")
    (tmp_path / "m.yaml").write_text(MISSIONS_YAML, encoding="utf-8")
    ms = Missions(MoteurEnPanneTotale(), tmp_path / "M",
                  tmp_path / "m.yaml").lancer()
    assert [m.etat for m in ms] == ["panne"] * 3 + ["a faire"] * 2
    assert ms[0].verdict == "PANNE DU MOTEUR (a refaire)"
    j = (tmp_path / "M" / "01-page" / "JOURNAL.md").read_text(encoding="utf-8")
    assert "MoteurEnPanne" in j


def test_plan_borne_seulement_si_le_moteur_le_sait(tmp_path):
    from brain.codage.chantier import Chantier
    recus = []

    class Borne:
        accepte_max_jetons = True

        def completer(self, **k):
            recus.append(k)
            return SimpleNamespace(texte="")

    class SansBorne:
        def completer(self, *, systeme, messages, role_modele):
            recus.append("sans")
            return SimpleNamespace(texte="")
    Chantier(Borne(), Espace(tmp_path))._appeler("s", "m", 700)
    Chantier(SansBorne(), Espace(tmp_path))._appeler("s", "m", 700)
    assert recus[0]["max_jetons"] == 700 and recus[1] == "sans"


def test_plan_illisible_puis_plan_contraint_par_schema(tmp_path):
    # Examen : meme sain, le modele rendait une page HTML au lieu du plan.
    from brain.codage.chantier import PLAN_SCHEMA, Chantier
    recus = []

    class Contraignable:
        accepte_max_jetons = True

        def completer(self, **k):
            recus.append(k)
            if k.get("schema") is None:
                return SimpleNamespace(texte="<html>une page</html>",
                                       donnees=None)
            return SimpleNamespace(texte="{}", donnees={"fichiers": [
                {"chemin": "index.html", "contenu": "l'accueil"},
                {"chemin": "style.css", "contenu": "les styles"}]})
    ch = Chantier(Contraignable(), Espace(tmp_path))
    taches = ch.planifier("une page d'accueil")
    assert [t.fichier for t in taches] == ["index.html", "assets/css/style.css"]
    assert recus[-1]["schema"] == PLAN_SCHEMA
    assert "--- plan contraint ---" in ch.plan_brut


# ------------------------------------------- le moteur de MAEL (llama.cpp)
from brain.backends import llamacpp as mod_llama


def _llama(monkeypatch, tmp_path, reponses):
    """Un LlamaCppBackend sans vrai processus : demarrer/relancer sont
    comptes, le reseau rend `reponses` au format OpenAI."""
    (tmp_path / "moteur" / "llama-b11122").mkdir(parents=True, exist_ok=True)
    (tmp_path / "moteur" / "llama-b11122" / "llama-server.exe").write_text("")
    (tmp_path / "modeles").mkdir(exist_ok=True)
    (tmp_path / "modeles" / "phi4-mini.gguf").write_text("")
    monkeypatch.setattr(mod_llama, "_racine_mael", lambda: tmp_path)
    monkeypatch.setattr(mod_llama, "settings", SimpleNamespace(BRAIN={
        "TIMEOUT": 5, "MODELES": {"codeur": "phi4-mini:latest",
                                  "analyste": "x", "tri": "x", "expert": "x"},
        "LLAMACPP": {}}))
    monkeypatch.setattr(mod_llama.LLMBackend, "modele_pour",
                        lambda self, role: role)
    b = mod_llama.LlamaCppBackend()
    vie = {"demarre": 0, "relance": 0}
    b.demarrer = lambda: vie.__setitem__("demarre", vie["demarre"] + 1)
    b.relancer = lambda modele="": vie.__setitem__("relance",
                                                   vie["relance"] + 1)
    envoyes, file = [], list(reponses)

    class Client:
        def __init__(self, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json):
            envoyes.append(json)
            r = file.pop(0)
            if isinstance(r, Exception):
                raise r
            if isinstance(r, int):
                return _Rep(statut=r)
            return _Rep({"choices": [{"message": {"content": r}}],
                         "usage": {"prompt_tokens": 3,
                                   "completion_tokens": 2}})
    monkeypatch.setattr(mod_llama.httpx, "Client", Client)
    return b, envoyes, vie


def test_llama_trouve_ses_fichiers_seul(monkeypatch, tmp_path):
    b, _, _ = _llama(monkeypatch, tmp_path, [])
    assert b.serveur.name == "llama-server.exe"
    from brain.codage.envergure import contexte_pour_la_machine
    assert b.fichier.name == "phi4-mini.gguf"
    assert b.contexte == contexte_pour_la_machine()      # d'apres la machine


def test_llama_sans_fichiers_dit_quoi_faire(monkeypatch, tmp_path):
    from brain.modeles import ProblemeDeModele
    monkeypatch.setattr(mod_llama, "_racine_mael", lambda: tmp_path)
    monkeypatch.setattr(mod_llama, "settings", SimpleNamespace(BRAIN={
        "TIMEOUT": 5, "MODELES": {"codeur": "phi4-mini"}, "LLAMACPP": {}}))
    with pytest.raises(ProblemeDeModele) as exc:
        mod_llama.LlamaCppBackend()
    assert "llama-server" in str(exc.value) and "BRAIN_BACKEND=ollama" \
        in str(exc.value)


def test_llama_borne_et_schema(monkeypatch, tmp_path):
    from brain.codage.chantier import PLAN_SCHEMA
    b, envoyes, vie = _llama(monkeypatch, tmp_path,
                             ['{"fichiers": [{"chemin": "index.html", '
                              '"contenu": "accueil"}]}'])
    r = b.completer(systeme="s", messages=[{"role": "user", "content": "q"}],
                    role_modele="codeur", schema=PLAN_SCHEMA, max_jetons=700)
    assert envoyes[0]["max_tokens"] == 700
    assert envoyes[0]["response_format"]["json_schema"]["schema"] \
        == PLAN_SCHEMA
    assert r.donnees["fichiers"][0]["chemin"] == "index.html"
    assert vie["demarre"] == 1 and vie["relance"] == 0


def test_llama_charabia_relance_puis_repond(monkeypatch, tmp_path):
    b, _, vie = _llama(monkeypatch, tmp_path, [VRAI_CHARABIA, "- a.html : x"])
    r = b.completer(systeme="s", messages=[{"role": "user", "content": "q"}],
                    role_modele="codeur")
    assert r.texte == "- a.html : x" and vie["relance"] == 1


@pytest.mark.parametrize("pannes", [
    [VRAI_CHARABIA, ""], [500, 503],
    [httpx.ReadTimeout("t"), httpx.ConnectError("c")]])
def test_llama_abime_meme_relance(monkeypatch, tmp_path, pannes):
    b, _, vie = _llama(monkeypatch, tmp_path, pannes)
    with pytest.raises(MoteurEnPanne):
        b.completer(systeme="s", messages=[{"role": "user", "content": "q"}],
                    role_modele="codeur")
    assert vie["relance"] == 1


def test_llama_sonde(monkeypatch, tmp_path):
    b, _, vie = _llama(monkeypatch, tmp_path, ["5"])
    assert b.verifier_sante() == ""
    b, _, vie = _llama(monkeypatch, tmp_path, ["OK", "5"])
    assert b.verifier_sante() == "relance" and vie["relance"] == 1
    b, _, _ = _llama(monkeypatch, tmp_path, ["", "je ne sais pas"])
    with pytest.raises(MoteurEnPanne):
        b.verifier_sante()


def test_sonde_juste():
    from brain.backends.sante import sonde_juste
    assert sonde_juste("5") and sonde_juste("La reponse est 5.") \
        and sonde_juste("Cinq")
    assert not sonde_juste("OK") and not sonde_juste("15") \
        and not sonde_juste("")


def test_choix_du_moteur_llamacpp(monkeypatch, tmp_path):
    from brain.backends import base
    _llama(monkeypatch, tmp_path, [])
    monkeypatch.setattr(base, "settings", SimpleNamespace(
        BRAIN={"BACKEND": "llamacpp"}))
    assert base.obtenir_backend().nom == "llamacpp"


# ------------------- les 12 leviers restes sur le papier (09/10/2026)
from brain.codage import leviers as lv


def test_focus_supprime_rendu_visible(tmp_path):
    # Mission 005 : « outline: none » sur :focus, sans remplacement.
    (tmp_path / "style.css").write_text("a:focus { outline: none; }\n",
                                        encoding="utf-8")
    d = Defaut("style.css", 1, "focus-invisible", B,
               "contour de focus supprime sans remplacement", "WCAG")
    assert reparation.reparer(Espace(tmp_path), [d], ["style.css"])
    css = (tmp_path / "style.css").read_text(encoding="utf-8")
    assert ":focus-visible { outline: 3px solid" in css
    from brain.codage import juges
    assert not [x for x in juges.juger_fichier(tmp_path / "style.css",
                                               "style.css")
                if x.regle == "focus-invisible"]           # le juge est d'accord


def test_liens_du_texte_soulignes(tmp_path):
    (tmp_path / "style.css").write_text("a { color: #1d4ed8; }\n",
                                        encoding="utf-8")
    d = Defaut("index.html", 4, "contraste", B,
               "lien distinguable par la seule couleur [axe-core "
               "link-in-text-block]", "WCAG 1.4.1")
    reparation.reparer(Espace(tmp_path), [d], ["index.html", "style.css"])
    reparation.reparer(Espace(tmp_path), [d], ["index.html", "style.css"])
    css = (tmp_path / "style.css").read_text(encoding="utf-8")
    assert css.count("text-decoration: underline") == 1


def test_regles_toujours_donnees_a_une_page_et_a_un_script():
    pages = ["index.html", "nos-pains.html", "contact.html"]
    r = dict(lv.regles("nos-pains.html", pages, [], []))
    assert '<a href="nos-pains.html" aria-current="page">Nos pains</a>' \
        in r["menu-commun-a-recopier"]
    assert '<a href="index.html">Accueil</a>' in r["menu-commun-a-recopier"]
    s = dict(lv.regles("assets/js/main.js", pages,
                       ["bouton-menu", "menu"], []))
    assert "#bouton-menu, #menu" in s["ids-des-pages-au-script"]   # mission 002
    assert "if (!el) return;" in s["script-garde-ses-elements"]
    assert "120 lignes au plus" in s["fichier-court-demande"]
    assert lv.TOUJOURS <= lv.APPLIQUES


def test_le_rappel_des_criteres_est_la_derniere_chose_lue(tmp_path):
    from brain.codage.chantier import Chantier
    from brain.tests_codage import PAGE_CHANTIER, FauxMoteur, bloc
    moteur = FauxMoteur(["- index.html : l'accueil\n- contact.html : le "
                         "contact\n", bloc("index.html", PAGE_CHANTIER)])
    ch = Chantier(moteur, Espace(tmp_path))
    try:
        ch.lancer("un site de deux pages")
    except IndexError:
        pass
    consigne = moteur.recus[1][0]["content"]
    assert consigne.rstrip().splitlines()[-1].startswith("[rappel] AVANT de "
                                                         "fermer le bloc")
    assert "mene a contact.html" in consigne.rstrip().splitlines()[-1]
    assert "[regles de MAEL — faits du projet]" in consigne
    assert "recopie TEL QUEL ce menu commun" in consigne


def test_un_fragment_n_a_pas_les_criteres_d_une_page():
    from brain.codage.criteres import deduire
    c = deduire("footer.html", "le pied de page", ["index.html",
                                                   "footer.html"])
    assert [x.type for x in c] == ["libre"]


def test_plan_en_barre_garde_et_plan_api_sans_page():
    from brain.codage.chantier import SYSTEME_PLAN, lire_plan
    assert [t.fichier for t in lire_plan("- /app.py : l'API")] == ["app.py"]
    assert "AUCUN fichier HTML" in SYSTEME_PLAN
    assert "jamais de « / » au debut" in SYSTEME_PLAN
    assert "n'est PAS un fichier" in SYSTEME_PLAN


def test_feuille_de_secours_quand_le_css_n_a_jamais_pu_etre_ecrit(tmp_path):
    from brain.codage.chantier import Chantier
    from brain.tests_codage import PAGE_CHANTIER, FauxMoteur, bloc
    moteur = FauxMoteur(["- index.html : l'accueil\n- style.css : styles\n",
                         bloc("index.html", PAGE_CHANTIER),
                         "Je ne sais pas.", "Toujours rien.",
                         "Encore rien."])                   # finition ratee
    ch = Chantier(moteur, Espace(tmp_path))
    bilan = ch.lancer("une page d'accueil")
    css = (tmp_path / "assets/css/style.css").read_text(encoding="utf-8")
    assert css.startswith(":root {")                       # la base de MAEL
    assert any("feuille de secours" in r for t in bilan.tours
               for r in t.reparations)
    assert any("feuille de base de MAEL" in s for s in bilan.suppositions)


# ---------------------------- l'anti-oscillation (mission 003 du 08/10)
CSS_003 = """:root {
  --texte: #1f2937;
  --fond: #d7d7d7;
  --fond-clair: #f3f4f6;
}
body { color: var(--texte); background: var(--fond); }
button { background: var(--fond); color: var(--fond-clair); }
@media (prefers-color-scheme: dark) { :root { --fond: #121212; } }
"""


def test_le_fond_de_la_page_ne_se_change_pas_pour_un_bouton():
    from brain.codage import bac_a_sable as b
    f = {"style.css": CSS_003}
    assert b.fonds_de_page(f) == {"#d7d7d7", "#121212"}
    c = b.correction_contraste("#f3f4f6", "#d7d7d7", 4.5, f)
    assert "remplace #f3f4f6 (texte)" in c          # le texte, pas le fond
    # un fond de bouton qui n'est PAS celui de la page : le fond change
    c2 = b.correction_contraste("#ffffff", "#7aa2ff", 4.5,
                                {"style.css": "body{background:#fff}\n"
                                 ".btn{color:#ffffff;background:#7aa2ff}"})
    assert "(fond)" in c2


def test_mael_ne_redefait_jamais_sa_couleur(tmp_path):
    reparation.nouveau_chantier()
    (tmp_path / "style.css").write_text("a { color: #777777; }\n",
                                        encoding="utf-8")

    def defaut(ancienne, nouvelle):
        return Defaut("index.html", 1, "contraste", B,
                      f"contraste mesure 3:1 (x sur y), 4.5:1 exige -> dans "
                      f"style.css (ligne(s) 1) : remplace {ancienne} (texte) "
                      f"par {nouvelle} (contraste 4.6:1)", "WCAG")
    e = Espace(tmp_path)
    assert reparation.reparer(e, [defaut("#777777", "#555555")],
                              ["style.css"])
    # une autre correction voudrait defaire #555555 : refusee, et dite
    assert reparation.reparer(e, [defaut("#555555", "#999999")],
                              ["style.css"]) == []
    assert "#555555" in (tmp_path / "style.css").read_text()
    assert any("conflit de palette : #555555" in l
               for l in reparation.limites())
    reparation.nouveau_chantier()
    assert reparation.limites() == []


# ------------------------------- le juge du SENS (textes, boutons) 09/10
from brain.codage import sens


@pytest.mark.parametrize("html,attendu", [
    ("<footer><p>Pied de page</p></footer>", 1),                 # 001, 005
    ("<footer>Footer</footer>", 1),                              # 004
    ("<p>Lorem ipsum dolor sit amet.</p>", 1),
    ("<p>Tel : +226 00 00 00 00</p>", 1),                        # 004
    ("<p>Votre texte ici</p>", 1),
    # le JUSTE ne doit pas etre vu
    ('<input placeholder="Votre nom" aria-label="Nom">', 0),
    ("<footer><p>© 2026 Boulangerie Wend-Kuuni, Ouaga 2000</p></footer>", 0),
    ("<p>Tel : +226 70 12 34 56</p>", 0),
    ("<h2>Description du pain</h2>", 0),
])
def test_textes_provisoires(html, attendu):
    assert len(sens.provisoires("a.html", html)) == attendu


@pytest.mark.parametrize("html,js,attendu", [
    # 001 : « Ajouter au panier » qu'aucun script ne vise
    ('<button type="button" class="ajouter">Ajouter</button>',
     "document.getElementById('bouton-menu')", 1),
    # 006 : #calculateTotal jamais relie (le total se calcule a la saisie)
    ('<button type="button" id="calculateTotal">Calculer</button>',
     "document.querySelectorAll('input[data-prix]')", 1),
    # le JUSTE
    ('<button type="button" id="b">Ok</button>',
     "document.getElementById('b').addEventListener('click', f)", 0),
    ('<button type="button" class="ajouter">Ajouter</button>',
     "document.querySelectorAll('.ajouter').forEach(f)", 0),
    ('<button type="button" aria-controls="menu">Menu</button>', "", 0),
    ("<form><button>Envoyer</button></form>", "", 0),          # soumet
    ('<button type="submit">Envoyer</button>', "", 0),
])
def test_boutons_sans_effet(html, js, attendu):
    assert len(sens.boutons_sans_effet({"a.html": html}, js)) == attendu


def test_le_juge_du_sens_est_branche_et_a_ses_remedes(tmp_path):
    from brain.codage import juges
    from brain.codage.remedes import remede
    (tmp_path / "index.html").write_text(
        "<!DOCTYPE html><html lang=\"fr\"><head><title>A</title></head>"
        "<body><main><h1>A</h1><p>Lorem ipsum</p></main></body></html>",
        encoding="utf-8")
    d, _ = juges.juger_projet(tmp_path, outils_externes=False,
                              executer=False)
    assert any(x.regle == "texte-provisoire" for x in d)
    assert remede("texte-provisoire") and remede("bouton-sans-effet")
    assert any("SAVOIR MANQUANT" in l for l in juges.limites())


# ---------------------- l'ENVERGURE : les reglages suivent le modele (09/10)
from brain.codage import envergure as env


@pytest.mark.parametrize("milliards,contexte,classe,taches,longueur", [
    (3.8, 4096, "petit", 8, 9_000),          # phi4-mini : reglages mesures
    (0, 4096, "petit", 8, 9_000),            # inconnu : le petit, prudent
    (7.6, 16384, "moyen", 16, 19_660),
    (32.8, 32768, "grand", 30, 39_321),
    (70, 131072, "grand", 30, 60_000),       # plafonne
])
def test_envergure(milliards, contexte, classe, taches, longueur):
    e = env.Envergure("m", milliards, contexte)
    assert (e.classe, e.taches_par_lot, e.longueur_fichier) == (
        classe, taches, longueur)
    assert e.jetons_plan >= 700 and e.jetons_reponse >= 2048


def test_un_grand_modele_a_un_grand_plan(tmp_path):
    from brain.codage.chantier import Chantier
    plan = "".join(f"- page{i}.html : la page {i}\n" for i in range(25))

    class GrandMoteur:
        accepte_max_jetons = True
        recus = []

        def envergure(self):
            return env.Envergure("grand-codeur", 32.8, 32768)

        def completer(self, **k):
            self.recus.append(k)
            return SimpleNamespace(texte=plan, donnees=None)
    m = GrandMoteur()
    ch = Chantier(m, Espace(tmp_path))
    ch._mesurer()
    taches = ch.planifier("un grand site de 25 pages")
    assert len([t for t in taches if t.fichier.endswith(".html")]) == 25
    assert m.recus[0]["max_jetons"] == 3_000
    # le petit (faux moteur sans envergure) garde ses 8 fichiers
    from brain.codage.chantier import lire_plan
    assert len(lire_plan(plan)) == 8


def test_professeurs_et_plafond_suivent_l_envergure():
    from brain.codage import deliberation, professeurs
    assert professeurs.etablir("un site", fichiers_max=30).fichiers_max == 30
    d = deliberation.deliberer("fais-moi un site comme Jumia",
                               fichiers_max=30)
    assert any("30 fichiers" in e.texte for e in d.decisions)
