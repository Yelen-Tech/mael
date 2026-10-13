"""Tests du module Reputation : detection du type, fail-open, cache, plages."""
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from billing.models import ApiKey, Module, Quota
from core.models import Organisation

from .models import Indicateur, Plage
from .views import deviner_type


class DevinerTypeTests(TestCase):
    def test_adresses_ip(self):
        for valeur in ["8.8.8.8", "185.220.101.7", "::1", "2001:db8::1"]:
            self.assertEqual(deviner_type(valeur), Indicateur.Type.IP, valeur)

    def test_urls(self):
        for valeur in ["http://x.bf/a", "https://x.bf/a?b=c"]:
            self.assertEqual(deviner_type(valeur), Indicateur.Type.URL, valeur)

    def test_domaines(self):
        for valeur in ["exemple.bf", "sous.exemple.co.uk"]:
            self.assertEqual(deviner_type(valeur), Indicateur.Type.DOMAINE, valeur)

    def test_empreintes(self):
        for valeur in ["a" * 32, "b" * 40, "c" * 64]:
            self.assertEqual(deviner_type(valeur), Indicateur.Type.EMPREINTE, valeur)

    def test_valeurs_refusees(self):
        for valeur in ["", "   ", "pas-une-cible!!", "a" * 600, "999.999.999.999"]:
            self.assertIsNone(deviner_type(valeur), repr(valeur))

    def test_cidr_refuse_en_entree(self):
        """Une plage n'est pas une cible d'interrogation : le client demande
        une adresse, on resout la plage qui la contient."""
        self.assertIsNone(deviner_type("45.13.0.0/24"))


class ReputationApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.org = Organisation.objects.create(nom="Client")
        _, self.clair = ApiKey.generer(
            organisation=self.org, libelle="T", portee=[Module.REPUTATION]
        )
        Quota.objects.create(
            organisation=self.org, module=Module.REPUTATION, plafond_mensuel=10_000
        )
        Indicateur.objects.create(
            type="ip", valeur="185.220.101.7", score=0.94, verdict="malveillant",
            categories=["c2"], sources={"feodo": 0.95},
        )
        Plage.objects.create(
            cidr="45.13.0.0/24", version=4,
            debut=int.from_bytes(bytes([45, 13, 0, 0]), "big"),
            fin=int.from_bytes(bytes([45, 13, 0, 255]), "big"),
            score=0.9, verdict="malveillant", categories=["plage_detournee"],
            sources={"spamhaus_drop": 0.9},
        )
        self.url = reverse("reputation")

    def appel(self, valeur):
        return self.client.post(
            self.url, {"valeur": valeur}, content_type="application/json",
            HTTP_X_API_KEY=self.clair,
        )

    def test_indicateur_connu(self):
        corps = self.appel("185.220.101.7").json()
        self.assertEqual(corps["verdict"], "malveillant")
        self.assertEqual(corps["score"], 0.94)
        self.assertEqual(corps["sources"], ["feodo"])

    def test_indicateur_inconnu_renvoie_inconnu_et_200(self):
        reponse = self.appel("203.0.113.55")
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()["verdict"], "inconnu")
        self.assertEqual(reponse.json()["score"], 0.0)

    def test_casse_indifferente(self):
        Indicateur.objects.create(type="domaine", valeur="mechant.bf", score=0.8,
                                  verdict="malveillant")
        self.assertEqual(self.appel("MeChant.BF").json()["verdict"], "malveillant")

    def test_ip_resolue_via_la_plage(self):
        corps = self.appel("45.13.0.42").json()
        self.assertEqual(corps["verdict"], "malveillant")
        self.assertEqual(corps["correspondance"]["cidr"], "45.13.0.0/24")

    def test_ip_hors_plage_inconnue(self):
        self.assertEqual(self.appel("45.13.1.42").json()["verdict"], "inconnu")

    def test_adresse_exacte_prime_sur_la_plage(self):
        Indicateur.objects.create(type="ip", valeur="45.13.0.42", score=0.2,
                                  verdict="suspect", sources={"otx": 0.2})
        corps = self.appel("45.13.0.42").json()
        self.assertEqual(corps["verdict"], "suspect")
        self.assertNotIn("correspondance", corps)

    def test_valeur_invalide_refusee(self):
        self.assertEqual(self.appel("pas-une-cible!!").status_code, 400)

    def test_cache_utilise(self):
        self.appel("185.220.101.7")
        Indicateur.objects.all().delete()
        # la base est vide, mais le cache repond encore
        self.assertEqual(self.appel("185.220.101.7").json()["verdict"], "malveillant")

    def test_sante_sans_authentification(self):
        reponse = self.client.get(reverse("sante"))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()["base"], "ok")


class NormalisationTests(TestCase):
    def test_valeur_stockee_en_minuscules(self):
        indicateur = Indicateur.objects.create(
            type="domaine", valeur="  MeChant.EXAMPLE.COM  "
        )
        indicateur.refresh_from_db()
        self.assertEqual(indicateur.valeur, "mechant.example.com")


class PlageBornesTests(TestCase):
    def test_bornes_ipv4(self):
        version, debut, fin = Plage.bornes("10.0.0.0/8")
        self.assertEqual(version, 4)
        self.assertEqual(fin - debut + 1, 2 ** 24)

    def test_bornes_ipv6(self):
        version, debut, fin = Plage.bornes("2001:db8::/32")
        self.assertEqual(version, 6)
        self.assertEqual(fin - debut + 1, 2 ** 96)

    def test_cidr_invalide(self):
        self.assertIsNone(Plage.bornes("pas-un-cidr"))
        self.assertIsNone(Plage.bornes("10.0.0.0/99"))
