"""Tests des connaissances generales (etape 2 du plan : les langages).

Lancables sans Django (voir docs/avancement.md). Les cas de schema sont
synthetiques ; le chargement et la recherche servent de garde-fou de
regression sur le corpus reel (une fiche invalide doit etre signalee,
jamais silencieuse).
"""
from __future__ import annotations

from brain import connaissances
from brain.connaissances import schema


def _fiche_valide() -> dict:
    """La plus petite fiche qui passe le schema."""
    return {
        "id": "langage-test",
        "schema": schema.SCHEMA_ACTUEL,
        "nom": "Langage de test",
        "resume": "Un resume court pour les tests.",
        "famille": "langage",
        "version": 1,
        "etat": "brouillon",
        "mots_cles": ["test"],
        "caracteristiques": {
            "paradigmes": ["impératif"],
            "typage": "statique",
            "execution": "compilé",
            "memoire": "manuelle",
        },
        "securite": [{
            "titre": "Un piège",
            "risque": "Ce qui peut arriver.",
            "conseil": "Ce qu'il faut faire.",
            "gravite": "moyenne",
        }],
        "sources": [{"titre": "Documentation officielle",
                     "url": "https://example.org/doc"}],
    }


def _erreurs(donnees: dict) -> list[str]:
    erreurs, _ = schema.valider(donnees)
    return erreurs


# --------------------------------------------------------------------------- #
# Schema : le code refuse une fiche douteuse avant qu'elle n'atteigne le modele
# --------------------------------------------------------------------------- #
def test_schema_fiche_valide_sans_erreur():
    assert _erreurs(_fiche_valide()) == []


def test_schema_pas_un_dictionnaire():
    erreurs, _ = schema.valider(["pas", "un", "dict"])
    assert erreurs


def test_schema_identite():
    for mutation in (
        lambda d: d.pop("id"),
        lambda d: d.update(id="Mauvaise_Casse"),
        lambda d: d.update(schema=999),
        lambda d: d.update(nom=""),
        lambda d: d.update(resume="x" * 301),
        lambda d: d.update(famille="cuisine"),
    ):
        d = _fiche_valide()
        mutation(d)
        assert _erreurs(d), mutation


def test_schema_id_doit_correspondre_au_fichier():
    from pathlib import Path
    erreurs, _ = schema.valider(_fiche_valide(), Path("autre-nom.yaml"))
    assert any("ne correspond pas" in e for e in erreurs)


def test_schema_cycle_de_vie():
    d = _fiche_valide()
    d["version"] = 0
    assert _erreurs(d)
    d = _fiche_valide()
    d["etat"] = "parfait"
    assert _erreurs(d)
    # une fiche verifiee doit dater sa relecture
    d = _fiche_valide()
    d["etat"] = "verifie"
    assert _erreurs(d)
    d["verifie_le"] = "2026-09-20"
    assert _erreurs(d) == []
    # pas de relecture datee dans le futur
    d["verifie_le"] = "2999-01-01"
    assert _erreurs(d)
    # date presente sans etat verifie : avertissement, pas erreur
    d = _fiche_valide()
    d["verifie_le"] = "2026-09-20"
    erreurs, avert = schema.valider(d)
    assert not erreurs and avert


def test_schema_retrouvabilite_et_caracteristiques():
    d = _fiche_valide()
    d["mots_cles"] = []
    assert _erreurs(d)
    d = _fiche_valide()
    d["caracteristiques"]["paradigmes"] = []
    assert _erreurs(d)
    d = _fiche_valide()
    del d["caracteristiques"]["memoire"]
    assert _erreurs(d)


def test_schema_points_de_securite():
    d = _fiche_valide()
    d["securite"] = []
    assert _erreurs(d)
    d = _fiche_valide()
    d["securite"][0]["gravite"] = "terrible"
    assert _erreurs(d)
    d = _fiche_valide()
    del d["securite"][0]["conseil"]
    assert _erreurs(d)


def test_schema_sources_https_exiges():
    d = _fiche_valide()
    d["sources"] = []
    assert _erreurs(d)
    d = _fiche_valide()
    d["sources"][0]["url"] = "http://example.org/doc"   # pas de http en clair
    assert _erreurs(d)


# --------------------------------------------------------------------------- #
# Chargement du corpus reel
# --------------------------------------------------------------------------- #
def test_corpus_reel_valide_et_charge():
    nb_err, texte = schema.rapport()
    assert nb_err == 0, texte
    toutes = connaissances.toutes()
    assert len(toutes) >= 41   # 9 langages + 10 maths + 8 physique + 6
    # chimie + 8 histoire-geographie (plan Kimi, etapes 2 a 6)
    ids = [c.id for c in toutes]
    assert len(ids) == len(set(ids))             # jamais d'id en double


# --------------------------------------------------------------------------- #
# Recherche par mots-cles : deterministe, sans modele
# --------------------------------------------------------------------------- #
def _premier(requete: str) -> str:
    trouvees = connaissances.recuperer(requete)
    assert trouvees, f"rien trouve pour {requete!r}"
    return trouvees[0].id


def test_recherche_trouve_le_bon_langage():
    assert _premier("débordement de tampon") == "langage-c"
    assert _premier("ownership emprunt") == "langage-rust"
    assert _premier("goroutine concurrence") == "langage-go"
    assert _premier("itérateur conteneur") == "langage-cpp"
    assert _premier("pickle désérialisation") == "langage-python"
    assert _premier("prototype pollution") == "langage-javascript"
    assert _premier("guillemets mktemp") == "langage-bash"
    assert _premier("lfi inclusion fichiers") == "langage-php"
    assert _premier("xxe xml entités") == "langage-java"


def test_recherche_normalise_les_accents():
    assert _premier("debordement tampon") == "langage-c"   # sans accents


def test_recherche_requete_vide_ou_hors_sujet():
    assert connaissances.recuperer("") == []
    assert connaissances.recuperer("   ") == []
    assert connaissances.recuperer("cuisine tarte pommes") == []


def test_recherche_ordre_stable_et_bornee():
    trouvees = connaissances.recuperer("mémoire", n=2)
    assert len(trouvees) <= 2
    scores = [connaissances._score(c, connaissances._jetons("mémoire"))
              for c in trouvees]
    assert scores == sorted(scores, reverse=True)


def test_recherche_inter_familles():
    """La recherche couvre toutes les familles du plan, pas seulement les
    langages (etapes 3 a 6)."""
    assert _premier("secret parfait shannon") == "theorie-de-l-information"
    assert _premier("tempest fuite électromagnétique") == \
        "propagation-radio-et-tempest"
    assert _premier("batteries onduleurs") == "electrochimie-des-batteries"
    assert _premier("frontières pays onu") == "geographie-politique-du-monde"
    assert _premier("enigma vigenère") == "histoire-de-la-cryptographie"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def test_cli_rapport_et_recherche(capsys=None):
    from brain.connaissances.__main__ import main
    assert main([]) == 0                         # rapport : corpus valide
    assert main(["débordement", "tampon"]) == 0  # trouve C
    assert main(["cuisine"]) == 0                # rien, mais pas une erreur


# --------------------------------------------------------------------------- #
# Injection dans le prompt : savoir de fond, borne, honnete
# --------------------------------------------------------------------------- #
def test_pour_prompt_bloc_compact_et_honnete():
    bloc = connaissances.pour_prompt("débordement de tampon en C")
    assert bloc.startswith("CONNAISSANCE")
    assert "PAS un constat" in bloc        # le bloc dit ce qu'il n'est pas
    assert "snprintf" in bloc              # un conseil concret est present
    assert connaissances.pour_prompt("cuisine tarte pommes") == ""


def test_pour_prompt_budget_respecte():
    # budget normal : borne par construction
    bloc = connaissances.pour_prompt("pickle python")
    est = int(len(bloc) / connaissances.CARACTERES_PAR_JETON) + 1
    assert est <= connaissances.BUDGET_JETONS
    # budget serre : l'identite reste, les points de securite sont sacrifies
    bloc = connaissances.pour_prompt("pickle python", budget_jetons=40)
    assert "Python" in bloc
    assert "Désérialisation pickle" not in bloc


# --------------------------------------------------------------------------- #
# Invariant : le savoir general ne decide JAMAIS de la securite
# --------------------------------------------------------------------------- #
def test_connaissances_hors_des_decisions_de_securite():
    """Ni le garde-fou, ni le jugement des ecarts, ni les playbooks ne
    lisent les connaissances : le code decide, le savoir de fond
    n'influence aucun verdict, aucune gravite, aucune correction."""
    from pathlib import Path

    import brain.bibliotheque.ecarts as ecarts
    import brain.garde.commandes as garde
    import brain.playbooks as playbooks
    for module in (garde, ecarts, playbooks):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "connaissances" not in source, module.__name__
