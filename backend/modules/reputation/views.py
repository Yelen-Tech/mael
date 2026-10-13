"""POST /v1/reputation -- plan bloquant, budget < 100 ms.

Contraintes de ce plan :
  - aucun appel de modele, aucun appel reseau sortant
  - cache Redis devant la base
  - en cas de panne interne : verdict « inconnu », code 200, jamais 500.
    Le client ne doit jamais couper son trafic a cause de nous.
"""
import ipaddress
import logging
import re

from django.core.cache import cache
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.authentication import JournaliseAppel, PorteeModule

from .models import Indicateur, Plage

logger = logging.getLogger("sentinelle.audit")

DUREE_CACHE = 600  # 10 min
RE_DOMAINE = re.compile(r"^(?=.{1,253}$)([a-z0-9-]{1,63}\.)+[a-z]{2,}$", re.I)
RE_EMPREINTE = re.compile(r"^[a-f0-9]{32}$|^[a-f0-9]{40}$|^[a-f0-9]{64}$", re.I)


def deviner_type(valeur: str) -> str | None:
    """Type d'indicateur deduit de la forme. Refuse ce qu'on ne reconnait pas."""
    valeur = valeur.strip()
    if not valeur or len(valeur) > 512:
        return None
    try:
        ipaddress.ip_address(valeur)
        return Indicateur.Type.IP
    except ValueError:
        pass
    if valeur.lower().startswith(("http://", "https://")):
        return Indicateur.Type.URL
    if RE_EMPREINTE.match(valeur):
        return Indicateur.Type.EMPREINTE
    if RE_DOMAINE.match(valeur):
        return Indicateur.Type.DOMAINE
    return None


REPONSE_INCONNUE = {
    "verdict": Indicateur.Verdict.INCONNU,
    "score": 0.0,
    "categories": [],
    "sources": [],
    "vu_le": None,
}


class ReputationView(JournaliseAppel, APIView):
    """Verdict sur une IP, un domaine, une URL ou une empreinte de fichier."""

    module = "reputation"
    permission_classes = [IsAuthenticated, PorteeModule]

    def post(self, request):
        valeur = str(request.data.get("valeur", "")).strip()
        type_indicateur = deviner_type(valeur)

        if type_indicateur is None:
            return Response(
                {
                    "detail": "Valeur non reconnue. Attendu : adresse IP, domaine, "
                    "URL (http/https) ou empreinte MD5/SHA-1/SHA-256."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        with self.journal(request, cible=valeur) as j:
            corps = self._verdict(type_indicateur, valeur)
            j.verdict = corps["verdict"]
            j.score = corps["score"]
            return Response({"valeur": valeur, "type": type_indicateur, **corps})

    # ---------------------------------------------------------------- interne
    def _verdict(self, type_indicateur: str, valeur: str) -> dict:
        cle_cache = f"rep:{type_indicateur}:{valeur.lower()}"
        en_cache = cache.get(cle_cache)
        if en_cache is not None:
            return en_cache

        try:
            # Exact en minuscules, jamais iexact : iexact force un UPPER()
            # qui rend l'index (type, valeur) inutilisable.
            indicateur = Indicateur.objects.filter(
                type=type_indicateur, valeur=valeur.lower()
            ).first()
            # Pas d'adresse exacte : la plage qui la contient fait verdict.
            # Une plage /16 tient en une ligne au lieu de 65 536.
            if indicateur is None and type_indicateur == Indicateur.Type.IP:
                plage = Plage.contenant(valeur)
                if plage is not None:
                    corps = {
                        "verdict": plage.verdict,
                        "score": round(plage.score, 3),
                        "categories": plage.categories,
                        "sources": sorted(plage.sources.keys()),
                        "vu_le": plage.derniere_vue.isoformat(),
                        "correspondance": {"type": "plage", "cidr": plage.cidr},
                    }
                    cache.set(cle_cache, corps, DUREE_CACHE)
                    return corps
        except Exception:
            # Fail-open : une panne de base ne doit pas bloquer le client.
            logger.exception("reputation: base indisponible, verdict inconnu renvoye")
            return dict(REPONSE_INCONNUE)

        if indicateur is None:
            corps = dict(REPONSE_INCONNUE)
        else:
            corps = {
                "verdict": indicateur.verdict,
                "score": round(indicateur.score, 3),
                "categories": indicateur.categories,
                "sources": sorted(indicateur.sources.keys()),
                "vu_le": indicateur.derniere_vue.isoformat(),
                "fraicheur_jours": indicateur.fraicheur_jours,
                "pays": indicateur.pays or None,
            }

        cache.set(cle_cache, corps, DUREE_CACHE)
        return corps


class SanteView(APIView):
    """GET /v1/sante -- sonde pour la supervision. Sans authentification."""

    authentication_classes = []
    permission_classes = []

    def get(self, request):
        try:
            total = Indicateur.objects.count()
            base = "ok"
        except Exception:
            total, base = 0, "indisponible"
        return Response(
            {"service": "sentinelle", "base": base, "indicateurs": total}
        )
