"""POST /v1/auth/check   -- score de risque d'une tentative de connexion
POST /v1/password/check -- ce mot de passe figure-t-il dans une fuite

Plan bloquant. Trois regles, comme pour le module Reputation :

  1. aucun appel de modele, aucun appel reseau sortant
  2. compteurs en Redis, profil en base mais hors du chemin critique
  3. fail-open : en cas de panne interne, on renvoie « autoriser » avec un
     score nul. Notre indisponibilite ne doit jamais empecher les
     utilisateurs d'un client de se connecter.

**Nous ne decidons pas, nous recommandons.** La reponse porte une decision
suggeree ; c'est l'application du client qui l'applique ou non.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.authentication import JournaliseAppel, PorteeModule
from intel import geo

from . import fenetres, signaux
from .identite import empreinte, empreinte_appareil
from .models import (
    MotDePasseCompromis,
    ProfilCompte,
    ReseauDeConfiance,
    SelOrganisation,
)
from .signaux import COURTE, MOYENNE, Contexte

logger = logging.getLogger("sentinelle.audit")

REPONSE_SURE = {
    "score": 0.0,
    "decision": "autoriser",
    "signaux": [],
    "degrade": True,
    "note": "evaluation indisponible, aucune restriction recommandee",
}


def ip_valide(valeur: str) -> str | None:
    try:
        return str(ipaddress.ip_address(valeur.strip()))
    except (ValueError, AttributeError):
        return None


class AuthCheckView(JournaliseAppel, APIView):
    """Score de risque d'une tentative de connexion.

    Corps attendu :
        identifiant   (obligatoire) courriel ou nom d'utilisateur -- jamais stocke
        ip            (obligatoire)
        user_agent    (optionnel)
        succes        (optionnel, defaut false) la tentative a-t-elle abouti
        pays          (optionnel) code ISO deux lettres, si le client le connait
    """

    module = "authguard"
    permission_classes = [IsAuthenticated, PorteeModule]

    def post(self, request):
        donnees = request.data if isinstance(request.data, dict) else {}
        identifiant = str(donnees.get("identifiant", "")).strip()
        ip = ip_valide(str(donnees.get("ip", "")))

        if not identifiant or ip is None:
            return Response(
                {"detail": "« identifiant » et « ip » sont obligatoires ; "
                           "« ip » doit etre une adresse valide."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        organisation = request.user.organisation
        with self.journal(request, cible=ip) as j:
            try:
                corps = self._evaluer(
                    organisation=organisation,
                    identifiant=identifiant,
                    ip=ip,
                    user_agent=str(donnees.get("user_agent", "")),
                    succes=bool(donnees.get("succes", False)),
                    pays=str(donnees.get("pays", "")).upper()[:2],
                )
            except Exception:  # noqa: BLE001
                logger.exception("authguard: evaluation impossible, fail-open")
                corps = dict(REPONSE_SURE)
            j.verdict = corps["decision"]
            j.score = corps["score"]
            return Response(corps)

    # ---------------------------------------------------------------- interne
    def _evaluer(self, *, organisation, identifiant, ip, user_agent, succes, pays):
        # Le client n'a pas a connaitre la geolocalisation. S'il ne la fournit
        # pas, on la resout : mise en cache, donc gratuite sur adresse repetee.
        if not pays:
            pays = geo.pays_de(ip)

        sel = SelOrganisation.pour(organisation)
        emp_compte = empreinte(identifiant, sel)
        emp_appareil = empreinte_appareil(user_agent, sel)

        profil = ProfilCompte.objects.filter(
            organisation=organisation, empreinte=emp_compte
        ).first()

        # --- alimenter les fenetres AVANT d'evaluer : la tentative en cours
        # --- compte, sinon le tout premier essai d'une rafale passe toujours.
        #
        # Les agregats par IP ne comptent QUE les echecs. Sans cela, un bureau
        # derriere un routeur NAT -- une seule IP publique pour vingt employes --
        # declencherait le signal de bourrage d'identifiants sur du trafic
        # parfaitement normal. Un robot de bourrage produit des echecs en masse ;
        # un bureau produit des succes. C'est cette difference qui porte le signal.
        if not succes:
            fenetres.incrementer("echec_compte", emp_compte, fenetre=COURTE)
            fenetres.incrementer("echec_ip", ip, fenetre=COURTE)
            fenetres.ajouter_distinct("comptes_par_ip", ip, emp_compte, fenetre=MOYENNE)
            fenetres.ajouter_distinct("ip_par_compte", emp_compte, ip, fenetre=MOYENNE)

        ctx = Contexte(
            organisation=organisation,
            reseau_de_confiance=ReseauDeConfiance.couvre(organisation, ip),
            empreinte_compte=emp_compte,
            ip=ip,
            empreinte_appareil=emp_appareil,
            succes=succes,
            pays=pays,
            appareils_connus=list(profil.appareils_connus) if profil else [],
            pays_connus=list(profil.pays_connus) if profil else [],
            premiere_connexion=profil is None,
        )
        evaluation = signaux.evaluer(ctx)
        corps = evaluation.en_json()
        corps["compte_connu"] = profil is not None

        # --- mise a jour du profil, seulement sur succes ---
        if succes:
            self._enregistrer_succes(organisation, emp_compte, emp_appareil, pays, profil)

        return corps

    @staticmethod
    def _enregistrer_succes(organisation, emp_compte, emp_appareil, pays, profil):
        """Apres un succes : on remet les compteurs d'echec a zero et on
        apprend le contexte. Sans la remise a zero, un utilisateur qui se
        trompe quatre fois puis reussit resterait « suspect » cinq minutes."""
        fenetres.reinitialiser("echec_compte", emp_compte, fenetre=COURTE)
        if pays:
            fenetres.memoriser("dernier_pays", emp_compte, pays, duree=MOYENNE)

        if profil is None:
            profil = ProfilCompte.objects.create(
                organisation=organisation, empreinte=emp_compte
            )
        profil.enregistrer_succes(empreinte_appareil=emp_appareil, pays=pays)


class PasswordCheckView(JournaliseAppel, APIView):
    """Ce mot de passe figure-t-il dans une fuite connue.

    Deux modes, tous deux sans jamais recevoir le mot de passe en clair :

      - `prefixe` : le client calcule l'empreinte SHA-1, envoie les 5 premiers
        caracteres, et recoit tous les suffixes connus. Il compare chez lui.
        **Nous n'apprenons rien** -- c'est le protocole k-anonymat, a preferer.

      - `empreinte` : le client envoie l'empreinte SHA-1 complete. Plus simple
        a integrer, mais nous apprenons quelle empreinte a ete testee.

    Le mot de passe en clair est refuse, meme si le client l'envoie.
    """

    module = "authguard"
    permission_classes = [IsAuthenticated, PorteeModule]
    LIMITE_SUFFIXES = 1000

    def post(self, request):
        donnees = request.data if isinstance(request.data, dict) else {}

        if "mot_de_passe" in donnees:
            return Response(
                {"detail": "N'envoyez jamais un mot de passe en clair. "
                           "Calculez son empreinte SHA-1 et envoyez « prefixe » "
                           "(les 5 premiers caracteres) ou « empreinte »."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        prefixe = str(donnees.get("prefixe", "")).strip().upper()
        empreinte_complete = str(donnees.get("empreinte", "")).strip().upper()

        if empreinte_complete:
            if len(empreinte_complete) != 40:
                return Response(
                    {"detail": "« empreinte » doit etre un SHA-1 de 40 caracteres."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            prefixe, suffixe = empreinte_complete[:5], empreinte_complete[5:]
            with self.journal(request, cible=f"mdp:{prefixe}") as j:
                trouve = MotDePasseCompromis.objects.filter(
                    prefixe=prefixe, suffixe=suffixe
                ).first()
                j.verdict = "compromis" if trouve else "inconnu"
                return Response({
                    "compromis": trouve is not None,
                    "occurrences": trouve.occurrences if trouve else 0,
                    "corpus_charge": MotDePasseCompromis.objects.exists(),
                })

        if len(prefixe) != 5 or not all(c in "0123456789ABCDEF" for c in prefixe):
            return Response(
                {"detail": "« prefixe » doit etre 5 caracteres hexadecimaux "
                           "(les 5 premiers du SHA-1 du mot de passe)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with self.journal(request, cible=f"mdp:{prefixe}") as j:
            suffixes = list(
                MotDePasseCompromis.objects.filter(prefixe=prefixe)
                .order_by("-occurrences")
                .values_list("suffixe", "occurrences")[: self.LIMITE_SUFFIXES]
            )
            j.verdict = "liste"
            return Response({
                "prefixe": prefixe,
                "suffixes": [{"suffixe": s, "occurrences": n} for s, n in suffixes],
                "corpus_charge": MotDePasseCompromis.objects.exists(),
            })


def empreinte_sha1(mot_de_passe: str) -> str:
    """Utilitaire pour les tests et la documentation client."""
    return hashlib.sha1(mot_de_passe.encode()).hexdigest().upper()  # noqa: S324
