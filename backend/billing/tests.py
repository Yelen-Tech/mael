"""Tests du socle : cles d'API, portee, quotas, cloisonnement entre clients.

Le test le plus important de ce fichier est `test_cloisonnement_*` : une
requete oubliee qui laisse fuiter les donnees d'un client vers un autre est
la faute qui tue une plateforme de securite. On la verifie explicitement.
"""
from django.test import TestCase
from django.urls import reverse

from core.models import Organisation
from modules.reputation.models import Indicateur

from .models import ApiCall, ApiKey, Module, Quota


class SocleTestCase(TestCase):
    """Deux organisations, pour pouvoir verifier le cloisonnement partout."""

    def setUp(self):
        self.org_a = Organisation.objects.create(nom="Client A")
        self.org_b = Organisation.objects.create(nom="Client B")
        self.cle_a, self.clair_a = ApiKey.generer(
            organisation=self.org_a, libelle="A", portee=[Module.REPUTATION]
        )
        self.cle_b, self.clair_b = ApiKey.generer(
            organisation=self.org_b, libelle="B", portee=[Module.REPUTATION]
        )
        for org in (self.org_a, self.org_b):
            Quota.objects.create(
                organisation=org, module=Module.REPUTATION, plafond_mensuel=100
            )
        Indicateur.objects.create(
            type="ip", valeur="185.220.101.7", score=0.94, verdict="malveillant"
        )
        self.url = reverse("reputation")

    def appel(self, cle=None, valeur="185.220.101.7"):
        entetes = {"HTTP_X_API_KEY": cle} if cle else {}
        return self.client.post(
            self.url, {"valeur": valeur}, content_type="application/json", **entetes
        )


class CleApiTests(SocleTestCase):
    def test_cle_en_clair_nest_jamais_stockee(self):
        self.assertNotIn(self.clair_a, self.cle_a.empreinte)
        # seul un prefixe court est conserve, pour que le client reconnaisse sa cle
        self.assertTrue(self.clair_a.startswith(self.cle_a.prefixe))
        self.assertEqual(len(self.cle_a.empreinte), 64)

    def test_deux_cles_donnent_deux_empreintes(self):
        self.assertNotEqual(self.cle_a.empreinte, self.cle_b.empreinte)

    def test_resolution_par_la_valeur_en_clair(self):
        self.assertEqual(ApiKey.resoudre(self.clair_a), self.cle_a)

    def test_cle_inventee_non_resolue(self):
        self.assertIsNone(ApiKey.resoudre("sk_sent_nimportequoi"))
        self.assertIsNone(ApiKey.resoudre(""))
        self.assertIsNone(ApiKey.resoudre("pas-le-bon-prefixe"))

    def test_cle_revoquee_non_resolue(self):
        self.cle_a.active = False
        self.cle_a.save()
        self.assertIsNone(ApiKey.resoudre(self.clair_a))


class AccesTests(SocleTestCase):
    def test_sans_cle_refuse(self):
        """La faute la plus grave possible : repondre a un appel non authentifie."""
        self.assertEqual(self.appel().status_code, 403)

    def test_cle_inventee_refusee(self):
        self.assertEqual(self.appel("sk_sent_bidon").status_code, 403)

    def test_cle_valide_acceptee(self):
        reponse = self.appel(self.clair_a)
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()["verdict"], "malveillant")

    def test_hors_portee_refuse(self):
        self.cle_a.portee = [Module.SURFACE]
        self.cle_a.save()
        self.assertEqual(self.appel(self.clair_a).status_code, 403)

    def test_ip_non_autorisee_refusee(self):
        self.cle_a.ip_autorisees = ["203.0.113.1"]
        self.cle_a.save()
        self.assertEqual(self.appel(self.clair_a).status_code, 403)

    def test_ip_autorisee_acceptee(self):
        self.cle_a.ip_autorisees = ["127.0.0.1"]
        self.cle_a.save()
        self.assertEqual(self.appel(self.clair_a).status_code, 200)

    def test_organisation_suspendue_refusee(self):
        self.org_a.actif = False
        self.org_a.save()
        self.assertEqual(self.appel(self.clair_a).status_code, 403)


class QuotaTests(SocleTestCase):
    def test_depassement_refuse(self):
        quota = Quota.objects.get(organisation=self.org_a, module=Module.REPUTATION)
        quota.plafond_mensuel = 2
        quota.save()
        for _ in range(2):
            ApiCall.objects.create(
                organisation=self.org_a, module=Module.REPUTATION, cible="x"
            )
        self.assertEqual(self.appel(self.clair_a).status_code, 403)

    def test_depassement_autorise_passe(self):
        quota = Quota.objects.get(organisation=self.org_a, module=Module.REPUTATION)
        quota.plafond_mensuel = 1
        quota.depassement_autorise = True
        quota.save()
        ApiCall.objects.create(
            organisation=self.org_a, module=Module.REPUTATION, cible="x"
        )
        self.assertEqual(self.appel(self.clair_a).status_code, 200)

    def test_quota_dun_client_nempeche_pas_lautre(self):
        quota = Quota.objects.get(organisation=self.org_a, module=Module.REPUTATION)
        quota.plafond_mensuel = 0
        quota.save()
        self.assertEqual(self.appel(self.clair_a).status_code, 403)
        self.assertEqual(self.appel(self.clair_b).status_code, 200)


class CloisonnementTests(SocleTestCase):
    """Un client ne doit jamais voir les donnees d'un autre."""

    def test_cloisonnement_du_journal(self):
        self.appel(self.clair_a)
        self.appel(self.clair_b)
        from billing import journal

        journal.vider(limite=1000)

        appels_a = ApiCall.objects.filter(organisation=self.org_a)
        appels_b = ApiCall.objects.filter(organisation=self.org_b)
        self.assertEqual(appels_a.count(), 1)
        self.assertEqual(appels_b.count(), 1)
        self.assertNotEqual(
            appels_a.first().cle_id, appels_b.first().cle_id
        )

    def test_cloisonnement_des_quotas(self):
        for org in (self.org_a, self.org_b):
            quota = Quota.objects.get(organisation=org, module=Module.REPUTATION)
            self.assertEqual(quota.organisation_id, org.id)
            self.assertEqual(quota.consommation_du_mois(), 0)

        ApiCall.objects.create(
            organisation=self.org_a, module=Module.REPUTATION, cible="x"
        )
        quota_a = Quota.objects.get(organisation=self.org_a, module=Module.REPUTATION)
        quota_b = Quota.objects.get(organisation=self.org_b, module=Module.REPUTATION)
        self.assertEqual(quota_a.consommation_du_mois(), 1)
        self.assertEqual(quota_b.consommation_du_mois(), 0)


class JournalTests(SocleTestCase):
    def test_appel_reussi_journalise(self):
        from billing import journal

        self.appel(self.clair_a)
        journal.vider(limite=1000)
        ligne = ApiCall.objects.filter(organisation=self.org_a).first()
        self.assertIsNotNone(ligne)
        self.assertEqual(ligne.module, "reputation")
        self.assertEqual(ligne.verdict, "malveillant")
        self.assertIsNotNone(ligne.latence_ms)

    def test_appel_refuse_non_journalise(self):
        """Un appel bloque par la permission n'entre jamais dans la vue,
        donc il n'est pas facture. C'est voulu : on ne facture pas un refus."""
        from billing import journal

        self.appel()
        journal.vider(limite=1000)
        self.assertEqual(ApiCall.objects.count(), 0)
