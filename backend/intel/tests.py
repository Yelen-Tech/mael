"""Tests de l'agregation, de la liste blanche et des plages.

Ces tests figent les decisions documentees dans `agregation.py` et
`listeblanche.py`. Si quelqu'un modifie un seuil ou une ponderation, un
test tombe et force a assumer le changement.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from modules.reputation.models import Flux, Indicateur, Plage

from .agregation import (
    SEUIL_MALVEILLANT,
    appliquer_decroissance,
    calculer_score,
    facteur_age,
    integrer,
    sante_des_flux,
    verdict_pour,
)
from .base import Brut
from .listeblanche import est_blanchi


class BaseIntelTestCase(TestCase):
    def setUp(self):
        for nom, poids in [
            ("feodo", 1.6), ("spamhaus_drop", 1.5), ("urlhaus", 1.4),
            ("abuseipdb", 1.2), ("tor_exit", 0.4),
        ]:
            Flux.objects.create(nom=nom, poids=poids)
        self.poids = dict(Flux.objects.values_list("nom", "poids"))


class ScoreTests(BaseIntelTestCase):
    def test_source_unique_rend_son_score(self):
        self.assertAlmostEqual(calculer_score({"feodo": 0.9}, self.poids), 0.9, 3)

    def test_corroboration_augmente_le_score(self):
        seul = calculer_score({"feodo": 0.8}, self.poids)
        deux = calculer_score({"feodo": 0.8, "urlhaus": 0.8}, self.poids)
        self.assertGreater(deux, seul)

    def test_bonus_de_corroboration_plafonne(self):
        beaucoup = {f"source{i}": 0.5 for i in range(20)}
        self.assertLessEqual(calculer_score(beaucoup, {}), 1.0)

    def test_source_de_faible_poids_pese_moins(self):
        fort = calculer_score({"feodo": 0.6}, self.poids)
        faible = calculer_score({"tor_exit": 0.6}, self.poids)
        # meme score brut, mais combine a une autre source le poids compte
        mixte_fort = calculer_score({"feodo": 0.9, "tor_exit": 0.1}, self.poids)
        mixte_faible = calculer_score({"feodo": 0.1, "tor_exit": 0.9}, self.poids)
        self.assertEqual(fort, faible)  # seul, le poids se simplifie
        self.assertGreater(mixte_fort, mixte_faible)

    def test_aucune_source_donne_zero(self):
        self.assertEqual(calculer_score({}, self.poids), 0.0)

    def test_seuils_de_verdict(self):
        self.assertEqual(verdict_pour(0.95), Indicateur.Verdict.MALVEILLANT)
        self.assertEqual(verdict_pour(0.50), Indicateur.Verdict.SUSPECT)
        self.assertEqual(verdict_pour(0.10), Indicateur.Verdict.INCONNU)


class ListeBlancheTests(TestCase):
    def test_resolveurs_dns_publics_proteges(self):
        for ip in ["8.8.8.8", "1.1.1.1", "9.9.9.9"]:
            self.assertTrue(est_blanchi("ip", ip), ip)

    def test_plages_privees_protegees(self):
        for ip in ["127.0.0.1", "10.1.2.3", "192.168.1.1", "172.16.0.5"]:
            self.assertTrue(est_blanchi("ip", ip), ip)

    def test_domaines_critiques_proteges(self):
        for domaine in ["google.com", "www.google.com", "windowsupdate.com"]:
            self.assertTrue(est_blanchi("domaine", domaine), domaine)

    def test_ip_quelconque_non_blanchie(self):
        self.assertFalse(est_blanchi("ip", "185.220.101.7"))

    def test_url_jamais_blanchie_meme_sur_domaine_protege(self):
        """Constate sur les donnees reelles d'URLhaus : les attaquants
        hebergent leurs charges sur Google Drive et GitHub. Bloquer l'URL
        precise ne casse rien ; blanchir l'URL laisse passer le maliciel."""
        self.assertFalse(
            est_blanchi("url", "https://drive.google.com/uc?id=charge_malveillante")
        )
        self.assertFalse(
            est_blanchi("url", "https://raw.githubusercontent.com/x/y/charge.exe")
        )
        # mais le domaine lui-meme reste protege
        self.assertTrue(est_blanchi("domaine", "drive.google.com"))


class IntegrationTests(BaseIntelTestCase):
    def test_creation_simple(self):
        resultat = integrer("feodo", [Brut(type="ip", valeur="45.13.1.9", score=0.95)])
        self.assertEqual(resultat.crees, 1)
        indicateur = Indicateur.objects.get(valeur="45.13.1.9")
        self.assertEqual(indicateur.verdict, Indicateur.Verdict.MALVEILLANT)

    def test_idempotence(self):
        for _ in range(3):
            integrer("feodo", [Brut(type="ip", valeur="45.13.1.9", score=0.95)])
        self.assertEqual(Indicateur.objects.filter(valeur="45.13.1.9").count(), 1)

    def test_sources_cumulees(self):
        integrer("feodo", [Brut(type="ip", valeur="45.13.1.9", score=0.9)])
        integrer("urlhaus", [Brut(type="ip", valeur="45.13.1.9", score=0.8)])
        indicateur = Indicateur.objects.get(valeur="45.13.1.9")
        self.assertEqual(sorted(indicateur.sources), ["feodo", "urlhaus"])

    def test_valeur_normalisee_en_minuscules(self):
        integrer("urlhaus", [Brut(type="domaine", valeur="MeChant.EXAMPLE.com")])
        self.assertTrue(Indicateur.objects.filter(valeur="mechant.example.com").exists())

    def test_liste_blanche_prime_sur_le_score(self):
        integrer("feodo", [Brut(type="ip", valeur="8.8.8.8", score=0.99)])
        indicateur = Indicateur.objects.get(valeur="8.8.8.8")
        self.assertEqual(indicateur.verdict, Indicateur.Verdict.BENIN)
        self.assertEqual(indicateur.score, 0.0)

    def test_benin_manuel_non_ecrase_par_un_flux(self):
        """Un faux positif corrige a la main par le comptable de la securite
        ne doit pas etre remonte par la collecte suivante."""
        Indicateur.objects.create(
            type="ip", valeur="45.13.1.9", verdict=Indicateur.Verdict.BENIN, score=0.0
        )
        integrer("feodo", [Brut(type="ip", valeur="45.13.1.9", score=0.99)])
        indicateur = Indicateur.objects.get(valeur="45.13.1.9")
        self.assertEqual(indicateur.verdict, Indicateur.Verdict.BENIN)

    def test_tor_seul_ne_suffit_jamais(self):
        """Etre un noeud Tor est un fait contextuel, pas une malveillance."""
        integrer("tor_exit", [Brut(type="ip", valeur="185.100.87.1", score=0.35)])
        indicateur = Indicateur.objects.get(valeur="185.100.87.1")
        self.assertNotEqual(indicateur.verdict, Indicateur.Verdict.MALVEILLANT)
        self.assertLess(indicateur.score, SEUIL_MALVEILLANT)

    def test_cidr_route_vers_plage(self):
        resultat = integrer(
            "spamhaus_drop", [Brut(type="ip", valeur="45.13.0.0/24", score=0.9)]
        )
        self.assertEqual(resultat.plages, 1)
        self.assertEqual(resultat.crees, 0)
        self.assertEqual(Indicateur.objects.filter(valeur="45.13.0.0/24").count(), 0)
        self.assertEqual(Plage.objects.filter(cidr="45.13.0.0/24").count(), 1)

    def test_liste_vide_ne_casse_rien(self):
        resultat = integrer("feodo", [])
        self.assertEqual(resultat.crees, 0)


class PlageTests(BaseIntelTestCase):
    def setUp(self):
        super().setUp()
        integrer("spamhaus_drop", [Brut(type="ip", valeur="45.13.0.0/24", score=0.9)])

    def test_bornes_calculees(self):
        plage = Plage.objects.get(cidr="45.13.0.0/24")
        self.assertEqual(int(plage.fin - plage.debut) + 1, 256)

    def test_adresse_dans_la_plage_trouvee(self):
        self.assertIsNotNone(Plage.contenant("45.13.0.1"))
        self.assertIsNotNone(Plage.contenant("45.13.0.255"))

    def test_adresse_hors_plage_non_trouvee(self):
        self.assertIsNone(Plage.contenant("45.13.1.0"))
        self.assertIsNone(Plage.contenant("8.8.8.8"))

    def test_entree_invalide_ne_leve_pas(self):
        self.assertIsNone(Plage.contenant("pas-une-ip"))
        self.assertIsNone(Plage.contenant(""))

    def test_plage_la_plus_etroite_gagne(self):
        integrer("feodo", [Brut(type="ip", valeur="45.13.0.0/16", score=0.5)])
        plage = Plage.contenant("45.13.0.5")
        self.assertEqual(plage.cidr, "45.13.0.0/24")


class DecroissanceTests(BaseIntelTestCase):
    def test_facteur_age_par_demi_vie(self):
        self.assertAlmostEqual(facteur_age(0), 1.0, 3)
        self.assertAlmostEqual(facteur_age(45), 0.5, 3)
        self.assertAlmostEqual(facteur_age(90), 0.25, 3)

    def test_indicateur_oublie_sort_du_verdict(self):
        integrer("feodo", [Brut(type="ip", valeur="45.13.1.9", score=0.95)])
        indicateur = Indicateur.objects.get(valeur="45.13.1.9")
        self.assertEqual(indicateur.verdict, Indicateur.Verdict.MALVEILLANT)

        Indicateur.objects.filter(pk=indicateur.pk).update(
            derniere_vue=timezone.now() - timedelta(days=150)
        )
        appliquer_decroissance()
        indicateur.refresh_from_db()
        self.assertEqual(indicateur.verdict, Indicateur.Verdict.INCONNU)

    def test_benin_non_touche_par_la_decroissance(self):
        Indicateur.objects.create(
            type="ip", valeur="8.8.8.8", verdict=Indicateur.Verdict.BENIN,
            score=0.0, derniere_vue=timezone.now() - timedelta(days=400),
        )
        appliquer_decroissance()
        self.assertEqual(
            Indicateur.objects.get(valeur="8.8.8.8").verdict,
            Indicateur.Verdict.BENIN,
        )


class SanteFluxTests(BaseIntelTestCase):
    def test_flux_jamais_collecte_signale(self):
        etat = {e["flux"]: e["statut"] for e in sante_des_flux()}
        self.assertEqual(etat["feodo"], "jamais collecte")

    def test_flux_en_erreur_signale(self):
        Flux.objects.filter(nom="feodo").update(
            derniere_collecte=timezone.now(), derniere_erreur="HTTPError: 503"
        )
        etat = {e["flux"]: e["statut"] for e in sante_des_flux()}
        self.assertEqual(etat["feodo"], "en erreur")

    def test_flux_silencieux_signale(self):
        Flux.objects.filter(nom="feodo").update(
            derniere_collecte=timezone.now() - timedelta(days=3)
        )
        etat = {e["flux"]: e["statut"] for e in sante_des_flux()}
        self.assertEqual(etat["feodo"], "silencieux")

    def test_flux_sain(self):
        Flux.objects.filter(nom="feodo").update(derniere_collecte=timezone.now())
        etat = {e["flux"]: e["statut"] for e in sante_des_flux()}
        self.assertEqual(etat["feodo"], "ok")
