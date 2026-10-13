"""Tests de la preuve de propriete et du perimetre des outils.

C'est le garde-fou juridique du projet : scanner une cible sans autorisation
ecrite est un delit. Ces tests verifient qu'aucun outil d'inspection ne peut
s'executer sur une cible non prouvee, et qu'un client ne peut pas faire
scanner les actifs d'un autre.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from brain.tools.base import OutilRefuse, registre
from core.models import Organisation

from .models import VALIDITE_PREUVE_JOURS, Actif, ActifManquant, resoudre_cible


class BaseActifTestCase(TestCase):
    def setUp(self):
        self.org_a = Organisation.objects.create(nom="Client A")
        self.org_b = Organisation.objects.create(nom="Client B")
        self.actif = Actif.objects.create(
            organisation=self.org_a, type=Actif.Type.DOMAINE,
            valeur="client-a.bf",
        )

    def prouver(self, actif=None, quand=None):
        actif = actif or self.actif
        actif.methode_preuve = Actif.Preuve.DNS_TXT
        actif.preuve_verifiee_le = quand or timezone.now()
        actif.save()
        return actif


class PreuveTests(BaseActifTestCase):
    def test_sans_preuve_invalide(self):
        self.assertFalse(self.actif.preuve_valide)

    def test_avec_preuve_recente_valide(self):
        self.assertTrue(self.prouver().preuve_valide)

    def test_preuve_expiree_invalide(self):
        vieux = timezone.now() - timedelta(days=VALIDITE_PREUVE_JOURS + 1)
        self.assertFalse(self.prouver(quand=vieux).preuve_valide)

    def test_exiger_preuve_leve_sans_preuve(self):
        with self.assertRaises(PermissionError):
            self.actif.exiger_preuve()

    def test_exiger_preuve_passe_avec_preuve(self):
        self.prouver().exiger_preuve()  # ne doit pas lever

    def test_nouveau_jeton_invalide_la_preuve(self):
        self.prouver()
        jeton = self.actif.nouveau_jeton()
        self.actif.refresh_from_db()
        self.assertTrue(jeton.startswith("sentinelle-verif="))
        self.assertIsNone(self.actif.preuve_verifiee_le)
        self.assertFalse(self.actif.preuve_valide)

    def test_deux_jetons_sont_differents(self):
        premier = self.actif.nouveau_jeton()
        second = self.actif.nouveau_jeton()
        self.assertNotEqual(premier, second)


class ResolutionCibleTests(BaseActifTestCase):
    def test_cible_non_declaree_refusee(self):
        with self.assertRaises(ActifManquant):
            resoudre_cible(self.org_a, "banque-du-voisin.bf")

    def test_cible_declaree_sans_preuve_refusee(self):
        with self.assertRaises(PermissionError):
            resoudre_cible(self.org_a, "client-a.bf")

    def test_cible_prouvee_acceptee(self):
        self.prouver()
        self.assertEqual(resoudre_cible(self.org_a, "client-a.bf"), self.actif)

    def test_sous_domaine_couvert_par_le_parent_prouve(self):
        self.prouver()
        self.assertEqual(
            resoudre_cible(self.org_a, "intranet.client-a.bf"), self.actif
        )

    def test_domaine_ressemblant_non_couvert(self):
        """« pasclient-a.bf » ne doit pas passer pour un sous-domaine
        de « client-a.bf » : la comparaison doit exiger le point."""
        self.prouver()
        with self.assertRaises(ActifManquant):
            resoudre_cible(self.org_a, "pasclient-a.bf")

    def test_actif_dun_client_invisible_pour_lautre(self):
        """Le cloisonnement le plus important du projet."""
        self.prouver()
        with self.assertRaises(ActifManquant):
            resoudre_cible(self.org_b, "client-a.bf")


class PerimetreOutilsTests(BaseActifTestCase):
    """Aucun outil d'inspection ne s'execute sans preuve de propriete."""

    def test_registre_peuple(self):
        self.assertIn("entetes_securite", registre.noms())
        self.assertIn("scan_vulnerabilites", registre.noms())

    def test_outil_refuse_sur_cible_non_declaree(self):
        with self.assertRaises(OutilRefuse):
            registre.appeler(
                "entetes_securite", organisation=self.org_a,
                arguments={"cible": "banque-du-voisin.bf"},
            )

    def test_outil_refuse_sur_cible_sans_preuve(self):
        with self.assertRaises(OutilRefuse):
            registre.appeler(
                "entetes_securite", organisation=self.org_a,
                arguments={"cible": "client-a.bf"},
            )

    def test_outil_refuse_sans_organisation(self):
        with self.assertRaises(OutilRefuse):
            registre.appeler(
                "entetes_securite", organisation=None,
                arguments={"cible": "client-a.bf"},
            )

    def test_outil_refuse_sur_lactif_dun_autre_client(self):
        self.prouver()
        with self.assertRaises(OutilRefuse):
            registre.appeler(
                "entetes_securite", organisation=self.org_b,
                arguments={"cible": "client-a.bf"},
            )

    def test_outil_inconnu_refuse(self):
        with self.assertRaises(OutilRefuse):
            registre.appeler(
                "outil_qui_nexiste_pas", organisation=self.org_a,
                arguments={"cible": "client-a.bf"},
            )

    def test_outil_sans_preuve_requise_ne_verifie_pas_le_perimetre(self):
        """La consultation de notre propre base de reputation n'inspecte
        l'infrastructure de personne : elle n'exige aucune preuve."""
        resultat = registre.appeler(
            "reputation_indicateur", organisation=self.org_a,
            arguments={"cible": "185.220.101.7"},
        )
        self.assertEqual(resultat["outil"], "reputation_indicateur")

    def test_definitions_exposees_au_modele_ne_contiennent_que_les_outils_du_groupe(self):
        """Un outil absent du groupe d'une tache est inappelable, pas
        seulement decourage."""
        from brain.tools.inspection import definitions_pour

        noms = {d["function"]["name"] for d in definitions_pour("triage")}
        self.assertEqual(noms, {"reputation_indicateur"})
        self.assertNotIn("scan_vulnerabilites", noms)
