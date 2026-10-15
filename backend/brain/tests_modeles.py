"""Tests de la reconnaissance du modele de l'utilisateur (brain/modeles.py).

Ce qui est verifie ici n'est pas du confort : c'est qu'une machine inconnue
ne fait jamais sortir une trace d'appel Python, et qu'un modele ecarte par le
banc de mesure n'est JAMAIS choisi tout seul.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from brain import machine, modeles, reglages


def _m(nom, go=4.0, **extra):
    return modeles.Modele(nom=nom, octets=int(go * 1024 ** 3), **extra)


# --------------------------------------------------------------------------- #
# Reconnaitre un modele sous ses variantes
# --------------------------------------------------------------------------- #
def test_variante_quantifiee_est_le_meme_modele():
    assert modeles.correspond("qwen2.5:3b", "qwen2.5:3b-instruct-q4_K_M")
    assert modeles.correspond("qwen2.5:3b", "qwen2.5:3b")


def test_latest_est_reconnu_comme_la_version_par_defaut():
    # « ollama pull mistral » pose « mistral:latest » : c'est bien lui.
    assert modeles.correspond("mistral:7b", "mistral:latest")
    assert modeles.correspond("mistral", "mistral:latest")


def test_deux_tailles_ne_se_remplacent_jamais():
    assert not modeles.correspond("qwen2.5:3b", "qwen2.5:7b")
    assert not modeles.correspond("qwen2.5:3b", "llama3.1:3b")


def test_nom_exact_gagne_sur_la_variante():
    presents = [_m("qwen2.5:3b-instruct-q8_0"), _m("qwen2.5:3b")]
    assert modeles.trouver("qwen2.5:3b", presents).nom == "qwen2.5:3b"


# --------------------------------------------------------------------------- #
# Le choix automatique
# --------------------------------------------------------------------------- #
def _petite_machine(go=8.0, libre=5.0):
    """Un portable modeste : 8 Go, pas de carte graphique."""
    return machine.Capacite(ram_totale=int(go * machine.GO),
                            ram_libre=int(libre * machine.GO))


def _grosse_machine(go=64.0, vram=24.0):
    return machine.Capacite(ram_totale=int(go * machine.GO),
                            ram_libre=int(go * 0.8 * machine.GO),
                            vram=int(vram * machine.GO), gpu="RTX 4090")


def test_le_prefere_le_mieux_place_est_choisi_a_categorie_egale():
    savoir = {"preferes": ["qwen3:8b", "mistral:7b"], "mesures": [],
              "exclus": [], "non_conversationnels": [],
              "categories_milliards": [3, 7, 13, 27], "marge_memoire_octets": 0}
    presents = [_m("mistral:7b", 4.1, parametres="7.2B"),
                _m("qwen3:8b", 5.2, parametres="8.0B")]
    choix = modeles.choisir(presents, savoir, capacite=_grosse_machine())
    assert choix.modele.nom == "qwen3:8b"


def test_un_modele_inconnu_plus_grand_passe_devant_un_connu_plus_petit():
    """Le point souleve par le responsable : la communaute a souvent mieux
    que nos modeles. La garde etant dans le code, un modele plus capable ne
    coute rien en surete -- il gagne, et on dit qu'il n'est pas mesure."""
    savoir = modeles.connus()
    presents = [_m("qwen2.5:3b", 1.8, parametres="3.1B"),
                _m("gpt-oss:20b", 13.0, parametres="20.9B")]
    choix = modeles.choisir(presents, savoir, capacite=_grosse_machine())
    assert choix.modele.nom == "gpt-oss:20b"
    assert any("jamais ete mesure" in n for n in choix.notes)


def test_sur_une_petite_machine_le_gros_modele_est_ecarte():
    """L'autre public : 8 Go de memoire. Un 20b ne doit JAMAIS etre choisi,
    meme s'il est installe et meilleur."""
    savoir = modeles.connus()
    presents = [_m("qwen2.5:3b", 1.8, parametres="3.1B"),
                _m("gpt-oss:20b", 13.0, parametres="20.9B")]
    choix = modeles.choisir(presents, savoir, capacite=_petite_machine())
    assert choix.modele.nom == "qwen2.5:3b"


def test_si_rien_ne_tient_on_prend_le_plus_petit_en_le_disant():
    """On ne refuse pas de demarrer : c'est sa machine, c'est son choix."""
    savoir = modeles.connus()
    presents = [_m("llama3.3:70b", 42.0, parametres="70.6B"),
                _m("gpt-oss:20b", 13.0, parametres="20.9B")]
    choix = modeles.choisir(presents, savoir, capacite=_petite_machine())
    assert choix.modele.nom == "gpt-oss:20b"
    assert any("depasse ce que cette machine" in n for n in choix.notes)


def test_une_categorie_superieure_gagne_meme_contre_un_modele_mesure():
    savoir = {"preferes": ["qwen2.5:3b"], "mesures": ["qwen2.5:3b"],
              "exclus": [], "non_conversationnels": [],
              "categories_milliards": [3, 7, 13, 27], "marge_memoire_octets": 0}
    presents = [_m("qwen2.5:3b", 1.8, parametres="3.1B"),
                _m("inconnu:14b", 9.0, parametres="14.0B")]
    choix = modeles.choisir(presents, savoir, capacite=_grosse_machine())
    assert choix.modele.nom == "inconnu:14b"


def test_a_categorie_egale_le_modele_mesure_gagne_sur_l_inconnu():
    savoir = {"preferes": [], "mesures": ["llama3.1:8b"], "exclus": [],
              "non_conversationnels": [],
              "categories_milliards": [3, 7, 13, 27], "marge_memoire_octets": 0}
    presents = [_m("llama3.1:8b", 4.9, parametres="8.0B"),
                _m("inconnu:9b", 5.4, parametres="9.0B")]
    choix = modeles.choisir(presents, savoir, capacite=_grosse_machine())
    assert choix.modele.nom == "llama3.1:8b"


def test_un_modele_ecarte_par_le_banc_n_est_jamais_choisi():
    """Critere d'EXCLUSION : un modele qui echoue la categorie « refuser » ne
    doit pas etre pris, meme s'il est le plus capable de la machine."""
    savoir = {"preferes": ["mistral:7b"], "mesures": [],
              "exclus": ["mistral:7b"], "exclus_pourquoi": {},
              "non_conversationnels": [],
              "categories_milliards": [3, 7, 13, 27], "marge_memoire_octets": 0}
    presents = [_m("mistral:7b", 4.1, parametres="7.2B"),
                _m("inconnu:3b", 2.0, parametres="3.0B")]
    choix = modeles.choisir(presents, savoir, capacite=_grosse_machine())
    assert choix.modele.nom == "inconnu:3b"


def test_un_modele_de_vectorisation_n_est_jamais_choisi():
    """Il ne sait pas dialoguer : le choisir serait une panne garantie."""
    savoir = {"preferes": [], "mesures": [], "exclus": [],
              "non_conversationnels": ["embed"],
              "categories_milliards": [3, 7, 13, 27], "marge_memoire_octets": 0}
    presents = [_m("nomic-embed-text", 0.3), _m("inconnu:7b", 4.0)]
    choix = modeles.choisir(presents, savoir, capacite=_grosse_machine())
    assert choix.modele.nom == "inconnu:7b"


def test_aucun_candidat_utilisable_rend_rien():
    savoir = {"preferes": [], "mesures": [], "exclus": [],
              "non_conversationnels": ["embed"],
              "categories_milliards": [3], "marge_memoire_octets": 0}
    assert modeles.choisir([_m("nomic-embed-text", 0.3)], savoir,
                           capacite=_grosse_machine()) is None


def test_la_particularite_d_un_modele_est_dite():
    # connus() rend le dictionnaire PARTAGE du processus : s'en remettre a
    # son etat, c'est dependre de ce qu'un autre test lui a fait. On le
    # relit du fichier (signale en revue interne le 22/09 : echec flottant).
    savoir = modeles.connus(recharger=True)
    choix = modeles.choisir([_m("deepseek-r1:8b", 4.9, parametres="8.0B")],
                            savoir, capacite=_grosse_machine())
    assert any("raisonnement visible" in n for n in choix.notes)


def test_taille_estimee_quand_ollama_ne_la_donne_pas():
    """Un modele sans parameter_size ne doit pas tomber en categorie 0 : on
    l'estime sur le poids du fichier."""
    assert modeles.milliards(_m("mystere:x", 4.8)) > 7
    assert modeles.categorie(_m("mystere:x", 4.8)) >= 2


# --------------------------------------------------------------------------- #
# La resolution complete
# --------------------------------------------------------------------------- #
def test_modele_present_sert_sans_un_mot():
    modeles.oublier()
    valeurs = dict(reglages.defauts(), modele="qwen2.5:3b")
    # machine FIXEE : sans elle, le resultat dependait de la memoire de la
    # machine qui lance les tests (CI Linux 3,8 Go, 12/10/2026)
    r = modeles.resoudre("expert", valeurs=valeurs, enregistrer=False,
                         disponibles=[_m("qwen2.5:3b", 2.0)],
                         capacite=_grosse_machine())
    assert r.nom == "qwen2.5:3b" and r.origine == "reglage"
    assert r.messages == []


def test_modele_absent_choisit_dit_et_enregistre():
    """La situation la plus frequente chez un inconnu : le defaut livre avec
    MAEL n'est pas chez lui."""
    modeles.oublier()
    with tempfile.TemporaryDirectory() as dossier:
        avant = os.environ.get("MAEL_DOSSIER")
        os.environ["MAEL_DOSSIER"] = dossier
        try:
            valeurs = dict(reglages.defauts(), modele="qwen3:30b-a3b")
            r = modeles.resoudre("expert", valeurs=valeurs,
                                 disponibles=[_m("llama3.1:8b", 4.9)])
            assert r.nom == "llama3.1:8b"
            assert r.origine == "automatique"
            assert r.enregistre is True
            assert any("llama3.1:8b" in m for m in r.messages)
            ecrit = json.loads(
                (Path(dossier) / "reglages.json").read_text(encoding="utf-8"))
            assert ecrit["modele"] == "llama3.1:8b"
        finally:
            if avant is None:
                os.environ.pop("MAEL_DOSSIER", None)
            else:
                os.environ["MAEL_DOSSIER"] = avant


def test_aucun_modele_installe_dit_la_commande_a_copier():
    modeles.oublier()
    try:
        modeles.resoudre("expert", valeurs=reglages.defauts(),
                         enregistrer=False, disponibles=[])
    except modeles.AucunModeleInstalle as souci:
        assert "ollama pull" in souci.humain()
        return
    raise AssertionError("un depart sans modele doit etre refuse clairement")


def test_modele_impose_absent_ne_recoit_aucun_remplacant():
    """Banc de mesure et --modele : le nom demande tourne, ou on s'arrete.
    Substituer en silence ferait porter a un resultat le nom d'un modele qui
    n'a jamais repondu."""
    modeles.oublier()
    try:
        modeles.resoudre("expert", valeurs=reglages.defauts(),
                         souhaite="qwen2.5:14b", exiger_exact=True,
                         enregistrer=False,
                         disponibles=[_m("llama3.1:8b", 4.9)])
    except modeles.ModeleImposeAbsent as souci:
        assert "qwen2.5:14b" in souci.humain()
        return
    raise AssertionError("un modele impose absent doit arreter MAEL")


def test_le_reglage_gagne_sur_le_defaut_du_code():
    valeurs = dict(reglages.defauts(), modele="mistral:7b")
    assert modeles.demande("expert", valeurs) == ("mistral:7b", "reglage")
    assert modeles.demande("expert", reglages.defauts())[1] == "defaut"


def test_modele_exclu_mais_demande_sert_en_le_disant():
    """L'utilisateur reste maitre chez lui : on n'interdit pas, on previent.

    Le fichier de connaissances du processus n'est PAS modifie ici : un test
    qui ecrit dans un cache partage fait echouer un autre test, plus tard,
    sans rapport apparent."""
    modeles.oublier()
    reel = modeles.connus(recharger=True)
    faux = dict(reel, exclus=["mistral:7b"], exclus_pourquoi={})
    modeles._connus = faux
    try:
        valeurs = dict(reglages.defauts(), modele="mistral:7b")
        r = modeles.resoudre("expert", valeurs=valeurs, enregistrer=False,
                             disponibles=[_m("mistral:7b", 4.1)])
        assert r.nom == "mistral:7b"
        assert any("refuser" in m for m in r.messages)
    finally:
        modeles._connus = None
        modeles.connus(recharger=True)


# --------------------------------------------------------------------------- #
# Lecture de la reponse d'Ollama, et affichage
# --------------------------------------------------------------------------- #
def test_lecture_de_la_liste_ollama():
    donnees = {"models": [
        {"name": "llama3.1:8b", "size": 4920753328,
         "details": {"family": "llama", "parameter_size": "8.0B",
                     "quantization_level": "Q4_K_M"}},
        {"model": "qwen2.5:3b", "size": 1929000000, "details": {}},
        {"name": "", "size": 1},
    ]}
    lus = modeles._depuis_tags(donnees)
    assert [m.nom for m in lus] == ["llama3.1:8b", "qwen2.5:3b"]
    assert lus[0].taille == "4.6 Go" and lus[0].parametres == "8.0B"


def test_fichier_de_connaissances_lisible_et_coherent():
    savoir = modeles.connus(recharger=True)
    assert savoir["preferes"], "la liste de preference ne doit pas etre vide"
    assert isinstance(savoir["exclus"], list)
    # Un modele ne peut pas etre a la fois conseille et ecarte.
    doubles = [p for p in savoir["preferes"] if modeles.est_exclu(p, savoir)]
    assert not doubles, f"a la fois preferes et exclus : {doubles}"


def test_l_affichage_marque_celui_qui_sert_et_les_ecartes():
    savoir = {"preferes": [], "exclus": ["vieux:7b"], "exclus_pourquoi": {},
              "non_conversationnels": ["embed"], "plafond_octets": 0}
    lignes = modeles.decrire(
        [_m("llama3.1:8b", 4.9), _m("vieux:7b", 4.0), _m("nomic-embed-text", .3)],
        actif="llama3.1:8b", savoir=savoir)
    assert lignes[0].startswith(" >")
    assert "ecarte par le banc" in lignes[1]
    assert "ne dialogue pas" in lignes[2]


def test_un_fichier_de_connaissances_abime_ne_bloque_pas_le_demarrage():
    avant = modeles.FICHIER_CONNUS
    try:
        modeles.FICHIER_CONNUS = Path("nulle-part-du-tout.json")
        savoir = modeles.connus(recharger=True)
        assert savoir["preferes"] == [modeles.CONSEILLE]
    finally:
        modeles.FICHIER_CONNUS = avant
        modeles._connus = None
        modeles.connus(recharger=True)


# --------------------------------------------------------------------------- #
# Quand l'appel au modele echoue : dire vrai, et quoi faire
# --------------------------------------------------------------------------- #
def test_un_modele_lent_n_est_pas_un_modele_injoignable():
    """Friction n° 1 de l'epreuve L3 : sur un portable sans carte graphique,
    le delai tombe alors que le modele calcule encore. Dire « injoignable »
    envoie l'utilisateur chercher une panne qui n'existe pas."""
    import httpx

    texte = modeles.expliquer_echec(httpx.ReadTimeout("timed out"),
                                    modele="qwen2.5:3b", profil="complet")
    assert "injoignable" not in texte
    assert "delai" in texte
    assert "--profil court" in texte      # le conseil qui divise l'attente
    assert "BRAIN_TIMEOUT" in texte


def test_en_profil_court_on_ne_conseille_pas_le_profil_court():
    import httpx

    texte = modeles.expliquer_echec(httpx.ReadTimeout("timed out"),
                                    modele="qwen2.5:3b", profil="court")
    assert "--profil court" not in texte
    assert "mael modeles" in texte


def test_ollama_coupe_en_cours_de_session_est_dit_comme_tel():
    import httpx

    texte = modeles.expliquer_echec(httpx.ConnectError("refuse"))
    assert "ollama serve" in texte


def test_un_echec_inconnu_donne_de_quoi_nous_le_rapporter():
    texte = modeles.expliquer_echec(ValueError("quelque chose d'inedit"))
    assert "ValueError" in texte and "Machine" in texte


def test_le_profil_suit_la_machine():
    """Un portable de 8 Go sans carte graphique n'a pas a porter le prompt
    complet : 295 s de reponse contre 130 s (mesure du 22/09)."""
    from brain import machine

    petite = machine.Capacite(ram_totale=8 * machine.GO,
                              ram_libre=3 * machine.GO)
    grosse = machine.Capacite(ram_totale=64 * machine.GO,
                              ram_libre=40 * machine.GO,
                              vram=24 * machine.GO, gpu="RTX 4090")
    assert machine.profil_conseille(petite) == "court"
    assert machine.profil_conseille(grosse) == "complet"
    assert machine.profil_conseille(machine.Capacite()) == "complet"


def test_la_console_windows_doit_etre_priee_d_afficher_les_couleurs():
    """Friction L3 : sur la console Windows, les sequences ANSI s'impriment
    en toutes lettres tant qu'on n'a pas active le rendu virtuel. La reponse
    est un OUI/NON franc : si on n'a pas pu, l'appelant coupe la couleur."""
    from brain import machine

    machine._ansi_actif = None
    resultat = machine.activer_sequences_ansi()
    assert isinstance(resultat, bool)
    # Deuxieme appel : la reponse est retenue, pas redemandee au systeme.
    assert machine.activer_sequences_ansi() is resultat


def test_sans_terminal_aucune_couleur_quoi_qu_il_arrive():
    from brain import console

    class FluxRedirige:
        def isatty(self):
            return False

    assert console.couleurs_possibles(FluxRedirige()) is False
