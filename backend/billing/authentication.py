"""Authentification par cle d'API et garde de portee/quota.

Plan bloquant : ce code tourne devant chaque appel client. Il doit rester
en dessous de quelques millisecondes -- aucune requete reseau, aucun modele.
"""
import time

from rest_framework import authentication, exceptions, permissions

from . import journal
from .models import ApiKey, Quota

ENTETE = "HTTP_X_API_KEY"


def ip_client(request) -> str | None:
    transmise = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if transmise:
        return transmise.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class PorteurDeCle:
    """Identite non humaine. DRF veut un objet avec is_authenticated."""

    is_authenticated = True

    def __init__(self, cle: ApiKey):
        self.cle = cle
        self.organisation = cle.organisation
        self.organisation_id = cle.organisation_id

    def __str__(self):
        return f"cle:{self.cle.prefixe}"


class ApiKeyAuthentication(authentication.BaseAuthentication):
    """En-tete `X-API-Key: sk_sent_...`."""

    def authenticate(self, request):
        brut = request.META.get(ENTETE)
        if not brut:
            return None  # laisse la main a JWT pour le tableau de bord

        cle = ApiKey.resoudre(brut)
        if cle is None:
            raise exceptions.AuthenticationFailed("Cle d'API inconnue ou revoquee.")

        if not cle.organisation.actif:
            raise exceptions.AuthenticationFailed("Organisation suspendue.")

        if not cle.ip_permise(ip_client(request)):
            raise exceptions.AuthenticationFailed(
                "Cette cle n'est pas autorisee depuis cette adresse IP."
            )

        return PorteurDeCle(cle), cle


class PorteeModule(permissions.BasePermission):
    """La vue declare `module = "reputation"` ; on verifie portee puis quota."""

    message = "Cette cle ne couvre pas ce module."

    def has_permission(self, request, view):
        porteur = getattr(request, "user", None)

        # Refus par defaut : une identite absente n'est jamais autorisee.
        if porteur is None or not getattr(porteur, "is_authenticated", False):
            self.message = "Cle d'API requise (en-tete X-API-Key)."
            return False

        module = getattr(view, "module", None)
        if module is None:
            return True

        if not isinstance(porteur, PorteurDeCle):
            return True  # acces humain authentifie : gere par les roles

        if not porteur.cle.couvre(module):
            return False

        quota = Quota.objects.filter(
            organisation=porteur.organisation, module=module
        ).first()
        if quota and quota.depasse(rapide=True) and not quota.depassement_autorise:
            self.message = (
                f"Quota mensuel atteint pour « {module} » "
                f"({quota.plafond_mensuel} appels)."
            )
            return False

        journal.incrementer_quota(porteur.organisation_id, module)
        return True


class JournaliseAppel:
    """Melange pour les vues du plan bloquant : mesure et journalise.

    A utiliser via `with self.journal(request, cible=...) as j:` puis
    `j.verdict = ...`. Le journal est ecrit meme en cas d'exception.
    """

    module: str = ""

    class _Mesure:
        def __init__(self, vue, request, cible):
            self.vue, self.request, self.cible = vue, request, cible
            self.verdict, self.score, self.code = "", None, 200

        def __enter__(self):
            self.debut = time.perf_counter()
            return self

        def __exit__(self, exc_type, exc, tb):
            porteur = getattr(self.request, "user", None)
            organisation = getattr(porteur, "organisation", None)
            if organisation is None:
                return False
            cle = getattr(porteur, "cle", None)
            # Empilage en memoire, pas d'ecriture en base ici : voir
            # billing/journal.py pour la mesure qui justifie ce choix.
            journal.empiler(
                organisation_id=str(organisation.id),
                cle_id=str(cle.id) if cle else None,
                module=self.vue.module,
                cible=str(self.cible)[:500],
                verdict=self.verdict if exc is None else "erreur",
                score=self.score,
                latence_ms=int((time.perf_counter() - self.debut) * 1000),
                code_http=500 if exc else self.code,
                ip_source=ip_client(self.request),
            )
            return False

    def journal(self, request, *, cible=""):
        return self._Mesure(self, request, cible)
