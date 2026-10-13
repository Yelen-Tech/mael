"""Tests du module Connexions.

Deux familles de tests, d'importance egale :

  - les attaques sont detectees, et **pour la bonne raison** (le code du
    signal compte autant que le score : c'est lui qui dicte la reponse)
  - l'utilisateur legitime n'est pas gene, et le bureau derriere un routeur
    NAT non plus -- un produit qui bloque les vrais utilisateurs est jete

Les fenetres glissantes utilisent Redis. En test, on les remplace par un
transport en memoire : le code teste reste le meme.
"""
from django.test import TestCase
from django.urls import reverse

from billing.models import ApiKey, Module, Quota
from core.models import Organisation

from . import fenetres
from .identite import empreinte, empreinte_appareil
from .models import MotDePasseCompromis, ProfilCompte, ReseauDeConfiance
from .signaux import SEUIL_DEFI, SEUIL_REFUS, combiner, decider
from .views import empreinte_sha1

UA_PC = "Mozilla/5.0 (Windows NT 10.0) Chrome/120"
UA_TEL = "Mozilla/5.0 (Linux; Android 14) Chrome/120"


class MemoireRedis:
    """Transport Redis en memoire, suffisant pour les operations utilisees."""

    def __init__(self):
        self.valeurs, self.ensembles = {}, {}

    def pipeline(self):
        parent = self

        class Tube:
            def __init__(self):
                self.ops = []

            def incr(self, cle):
                self.ops.append(("incr", cle))
                return self

            def expire(self, cle, duree):
                self.ops.append(("expire", cle))
                return self

            def sadd(self, cle, membre):
                self.ops.append(("sadd", cle, membre))
                return self

            def scard(self, cle):
                self.ops.append(("scard", cle))
                return self

            def execute(self):
                sortie = []
                for op in self.ops:
                    if op[0] == "incr":
                        parent.valeurs[op[1]] = parent.valeurs.get(op[1], 0) + 1
                        sortie.append(parent.valeurs[op[1]])
                    elif op[0] == "sadd":
                        parent.ensembles.setdefault(op[1], set()).add(op[2])
                        sortie.append(1)
                    elif op[0] == "scard":
                        sortie.append(len(parent.ensembles.get(op[1], set())))
                    else:
                        sortie.append(True)
                return sortie

        return Tube()

    def get(self, cle):
        valeur = self.valeurs.get(cle)
        return str(valeur).encode() if valeur is not None else None

    def set(self, cle, valeur, ex=None):
        self.valeurs[cle] = valeur
        return True

    def scard(self, cle):
        return len(self.ensembles.get(cle, set()))

    def delete(self, cle):
        self.valeurs.pop(cle, None)
        return 1


class BaseAuthTestCase(TestCase):
    def setUp(self):
        fenetres._client = MemoireRedis()
        fenetres._indisponible = False

        self.org = Organisation.objects.create(nom="Banque de test")
        _, self.clair = ApiKey.generer(
            organisation=self.org, libelle="Test", portee=[Module.AUTHGUARD]
        )
        Quota.objects.create(
            organisation=self.org, module=Module.AUTHGUARD,
            plafond_mensuel=1_000_000,
        )
        self.url = reverse("auth-check")
        self.entetes = {"HTTP_X_API_KEY": self.clair}

    def tearDown(self):
        fenetres._client = None
        fenetres._indisponible = False

    def essai(self, identifiant, ip, succes=False, ua=UA_PC, pays=""):
        reponse = self.client.post(
            self.url,
            {"identifiant": identifiant, "ip": ip, "succes": succes,
             "user_agent": ua, "pays": pays},
            content_type="application/json",
            **self.entetes,
        )
        return reponse.json()

    @staticmethod
    def codes(corps):
        return {s["code"] for s in corps["signaux"]}


class CombinaisonTests(TestCase):
    def test_combinaison_probabiliste_pas_une_somme(self):
        """Trois signaux a 0.3 donnent 0.657, pas 0.9."""
        self.assertAlmostEqual(combiner([0.3, 0.3, 0.3]), 0.657, 3)

    def test_jamais_plus_de_un(self):
        self.assertLessEqual(combiner([0.9] * 20), 1.0)

    def test_aucun_signal_donne_zero(self):
        self.assertEqual(combiner([]), 0.0)

    def test_decision_selon_les_seuils(self):
        self.assertEqual(decider(SEUIL_REFUS), "refuser")
        self.assertEqual(decider(SEUIL_DEFI), "defier")
        self.assertEqual(decider(0.0), "autoriser")


class PseudonymisationTests(TestCase):
    def test_empreinte_stable(self):
        self.assertEqual(
            empreinte("jean@exemple.bf", "sel1"), empreinte("jean@exemple.bf", "sel1")
        )

    def test_insensible_a_la_casse_et_aux_espaces(self):
        self.assertEqual(
            empreinte("Jean@Exemple.BF", "sel1"),
            empreinte("  jean@exemple.bf  ", "sel1"),
        )

    def test_sels_differents_donnent_empreintes_differentes(self):
        """Empeche de recouper les utilisateurs de deux clients."""
        self.assertNotEqual(
            empreinte("jean@exemple.bf", "sel1"), empreinte("jean@exemple.bf", "sel2")
        )

    def test_identifiant_absent_de_lempreinte(self):
        emp = empreinte("jean@exemple.bf", "sel1")
        self.assertNotIn("jean", emp)
        self.assertNotIn("exemple", emp)

    def test_appareil_insensible_a_la_version_du_navigateur(self):
        """Une mise a jour de navigateur ne doit pas declencher d'alerte."""
        self.assertEqual(
            empreinte_appareil("Mozilla/5.0 (Windows NT 10.0) Chrome/120", "s"),
            empreinte_appareil("Mozilla/5.0 (Windows NT 10.0) Chrome/131", "s"),
        )

    def test_appareil_distingue_telephone_et_ordinateur(self):
        self.assertNotEqual(
            empreinte_appareil(UA_PC, "s"), empreinte_appareil(UA_TEL, "s")
        )


class UtilisateurLegitimeTests(BaseAuthTestCase):
    """Le test le plus important : ne pas gener les vrais utilisateurs."""

    def test_premiere_connexion_autorisee(self):
        corps = self.essai("marie@banque.bf", "41.203.10.5", succes=True, pays="BF")
        self.assertEqual(corps["decision"], "autoriser")
        self.assertEqual(corps["score"], 0.0)
        self.assertFalse(corps["compte_connu"])

    def test_connexions_habituelles_autorisees(self):
        for _ in range(6):
            corps = self.essai("marie@banque.bf", "41.203.10.5", succes=True, pays="BF")
        self.assertEqual(corps["decision"], "autoriser")
        self.assertEqual(corps["signaux"], [])
        self.assertTrue(corps["compte_connu"])

    def test_changement_dip_dans_le_meme_pays_autorise(self):
        self.essai("marie@banque.bf", "41.203.10.5", succes=True, pays="BF")
        corps = self.essai("marie@banque.bf", "41.203.99.1", succes=True, pays="BF")
        self.assertEqual(corps["decision"], "autoriser")

    def test_nouvel_appareil_signale_mais_pas_bloque(self):
        self.essai("marie@banque.bf", "41.203.10.5", succes=True, pays="BF")
        corps = self.essai(
            "marie@banque.bf", "41.203.10.5", succes=True, ua=UA_TEL, pays="BF"
        )
        self.assertIn("appareil_inconnu", self.codes(corps))
        self.assertEqual(corps["decision"], "autoriser")

    def test_succes_remet_le_compteur_a_zero(self):
        """Un utilisateur qui se trompe puis reussit ne doit pas rester suspect."""
        for _ in range(4):
            self.essai("marie@banque.bf", "41.203.10.5")
        self.essai("marie@banque.bf", "41.203.10.5", succes=True, pays="BF")
        corps = self.essai("marie@banque.bf", "41.203.10.5")
        self.assertEqual(corps["score"], 0.0)

    def test_profil_mis_a_jour_seulement_sur_succes(self):
        self.essai("marie@banque.bf", "41.203.10.5", succes=False, pays="BF")
        self.assertEqual(ProfilCompte.objects.count(), 0)
        self.essai("marie@banque.bf", "41.203.10.5", succes=True, pays="BF")
        self.assertEqual(ProfilCompte.objects.count(), 1)


class ForceBruteTests(BaseAuthTestCase):
    def test_cinq_echecs_declenchent_un_defi(self):
        """Un utilisateur reel ne se trompe pas cinq fois de suite."""
        for _ in range(4):
            self.essai("cible@banque.bf", "197.28.1.1")
        corps = self.essai("cible@banque.bf", "197.28.1.1")
        self.assertIn("force_brute_compte", self.codes(corps))
        self.assertGreaterEqual(corps["score"], SEUIL_DEFI)

    def test_vingt_echecs_font_refuser(self):
        for _ in range(20):
            corps = self.essai("cible@banque.bf", "197.28.1.1")
        self.assertEqual(corps["decision"], "refuser")

    def test_sous_le_seuil_rien_ne_se_declenche(self):
        for _ in range(3):
            corps = self.essai("cible@banque.bf", "197.28.1.1")
        self.assertNotIn("force_brute_compte", self.codes(corps))

    def test_reponse_recommandee_est_de_bloquer_le_compte(self):
        for _ in range(6):
            corps = self.essai("cible@banque.bf", "197.28.1.1")
        signal = next(
            s for s in corps["signaux"] if s["code"] == "force_brute_compte"
        )
        self.assertEqual(signal["details"]["reponse"], "bloquer_le_compte")


class BourrageIdentifiantsTests(BaseAuthTestCase):
    def test_beaucoup_de_comptes_depuis_une_ip_detecte(self):
        for i in range(12):
            corps = self.essai(f"vole{i}@banque.bf", "45.155.205.99")
        self.assertIn("bourrage_identifiants", self.codes(corps))
        self.assertGreaterEqual(corps["score"], SEUIL_DEFI)

    def test_dix_huit_comptes_font_refuser(self):
        for i in range(18):
            corps = self.essai(f"vole{i}@banque.bf", "45.155.205.99")
        self.assertEqual(corps["decision"], "refuser")

    def test_reponse_recommandee_est_de_bloquer_lip(self):
        for i in range(12):
            corps = self.essai(f"vole{i}@banque.bf", "45.155.205.99")
        signal = next(
            s for s in corps["signaux"] if s["code"] == "bourrage_identifiants"
        )
        self.assertEqual(signal["details"]["reponse"], "bloquer_l_ip")


class BureauDerriereNatTests(BaseAuthTestCase):
    """Le faux positif qui aurait bloque le siege de chaque client."""

    def test_vingt_succes_depuis_une_ip_partagee_ne_declenchent_rien(self):
        for i in range(20):
            corps = self.essai(
                f"employe{i}@banque.bf", "41.203.50.7", succes=True, pays="BF"
            )
        self.assertEqual(corps["decision"], "autoriser")
        self.assertNotIn("bourrage_identifiants", self.codes(corps))

    def test_reseau_declare_neutralise_les_signaux_par_ip(self):
        ReseauDeConfiance.objects.create(
            organisation=self.org, cidr="41.203.50.0/24", libelle="Siege"
        )
        for i in range(20):
            corps = self.essai(f"employe{i}@banque.bf", "41.203.50.7")
        self.assertNotIn("bourrage_identifiants", self.codes(corps))

    def test_reseau_declare_conserve_les_signaux_par_compte(self):
        """Une attaque depuis l'interieur reste detectee."""
        ReseauDeConfiance.objects.create(
            organisation=self.org, cidr="41.203.50.0/24", libelle="Siege"
        )
        for _ in range(8):
            corps = self.essai("directeur@banque.bf", "41.203.50.7")
        self.assertIn("force_brute_compte", self.codes(corps))

    def test_reseau_dune_organisation_ne_couvre_pas_lautre(self):
        autre = Organisation.objects.create(nom="Autre banque")
        ReseauDeConfiance.objects.create(
            organisation=autre, cidr="41.203.50.0/24", libelle="Siege"
        )
        self.assertFalse(ReseauDeConfiance.couvre(self.org, "41.203.50.7"))
        self.assertTrue(ReseauDeConfiance.couvre(autre, "41.203.50.7"))


class PulverisationTests(BaseAuthTestCase):
    def test_beaucoup_dip_sur_un_compte_detecte(self):
        for i in range(8):
            corps = self.essai("directeur@banque.bf", f"102.64.{i}.{i + 10}")
        self.assertIn("pulverisation", self.codes(corps))

    def test_reponse_recommandee_est_le_second_facteur(self):
        for i in range(8):
            corps = self.essai("directeur@banque.bf", f"102.64.{i}.{i + 10}")
        signal = next(s for s in corps["signaux"] if s["code"] == "pulverisation")
        self.assertEqual(signal["details"]["reponse"], "exiger_second_facteur")


class VoyageImpossibleTests(BaseAuthTestCase):
    def test_changement_de_pays_rapide_detecte(self):
        self.essai("pdg@banque.bf", "41.203.1.1", succes=True, pays="BF")
        corps = self.essai("pdg@banque.bf", "91.132.1.1", pays="RU")
        self.assertIn("voyage_impossible", self.codes(corps))
        self.assertGreaterEqual(corps["score"], SEUIL_DEFI)

    def test_pays_habituel_ne_declenche_rien(self):
        for _ in range(3):
            self.essai("pdg@banque.bf", "41.203.1.1", succes=True, pays="BF")
        corps = self.essai("pdg@banque.bf", "41.203.1.2", succes=True, pays="BF")
        self.assertNotIn("voyage_impossible", self.codes(corps))

    def test_pays_inconnu_sans_precedent_signale_faiblement(self):
        self.essai("pdg@banque.bf", "41.203.1.1", succes=True, pays="BF")
        ProfilCompte.objects.update(pays_connus=["BF"])
        corps = self.essai("pdg@banque.bf", "197.149.1.1", pays="CI")
        self.assertTrue(
            {"pays_inhabituel", "voyage_impossible"} & self.codes(corps)
        )


class ValidationTests(BaseAuthTestCase):
    def test_identifiant_obligatoire(self):
        reponse = self.client.post(
            self.url, {"ip": "8.8.8.8"}, content_type="application/json",
            **self.entetes,
        )
        self.assertEqual(reponse.status_code, 400)

    def test_ip_obligatoire_et_valide(self):
        for mauvaise in ["", "pas-une-ip", "999.1.1.1"]:
            reponse = self.client.post(
                self.url, {"identifiant": "a@b.bf", "ip": mauvaise},
                content_type="application/json", **self.entetes,
            )
            self.assertEqual(reponse.status_code, 400, mauvaise)

    def test_sans_cle_refuse(self):
        reponse = self.client.post(
            self.url, {"identifiant": "a@b.bf", "ip": "8.8.8.8"},
            content_type="application/json",
        )
        self.assertEqual(reponse.status_code, 403)


class ModeDegradeTests(BaseAuthTestCase):
    def test_sans_redis_les_signaux_de_frequence_sont_inactifs_mais_signales(self):
        """Fail-open : notre panne ne doit pas empecher les connexions.
        Mais le client doit savoir que l'evaluation est partielle."""
        fenetres._client = None
        fenetres._indisponible = True
        corps = self.essai("marie@banque.bf", "41.203.10.5")
        self.assertTrue(corps["degrade"])
        self.assertEqual(corps["decision"], "autoriser")


class MotDePasseTests(BaseAuthTestCase):
    def setUp(self):
        super().setUp()
        self.url_mdp = reverse("password-check")
        empreinte_123456 = empreinte_sha1("123456")
        MotDePasseCompromis.objects.create(
            prefixe=empreinte_123456[:5], suffixe=empreinte_123456[5:],
            occurrences=9_500_000,
        )

    def poster(self, corps):
        return self.client.post(
            self.url_mdp, corps, content_type="application/json", **self.entetes
        )

    def test_clair_refuse(self):
        """Meme si le client l'envoie, on refuse de le recevoir."""
        reponse = self.poster({"mot_de_passe": "123456"})
        self.assertEqual(reponse.status_code, 400)

    def test_k_anonymat_rend_les_suffixes(self):
        empreinte_attendue = empreinte_sha1("123456")
        reponse = self.poster({"prefixe": empreinte_attendue[:5]})
        self.assertEqual(reponse.status_code, 200)
        suffixes = [s["suffixe"] for s in reponse.json()["suffixes"]]
        self.assertIn(empreinte_attendue[5:], suffixes)

    def test_empreinte_complete_rend_un_verdict(self):
        reponse = self.poster({"empreinte": empreinte_sha1("123456")})
        self.assertTrue(reponse.json()["compromis"])

    def test_mot_de_passe_inconnu_non_compromis(self):
        reponse = self.poster({"empreinte": empreinte_sha1("xY7!qw-9Zk2mLp4T")})
        self.assertFalse(reponse.json()["compromis"])

    def test_prefixe_invalide_refuse(self):
        for mauvais in ["ABC", "ZZZZZ", "1234567"]:
            self.assertEqual(self.poster({"prefixe": mauvais}).status_code, 400, mauvais)

    def test_empreinte_de_mauvaise_longueur_refusee(self):
        self.assertEqual(self.poster({"empreinte": "ABCD"}).status_code, 400)
