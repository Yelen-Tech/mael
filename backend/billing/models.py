"""Cles d'API, quotas, comptage d'usage.

Une cle n'est jamais stockee en clair : on garde son empreinte SHA-256 et
un prefixe lisible pour que le client puisse l'identifier dans son tableau
de bord sans qu'on puisse la lui reafficher.
"""
import hashlib
import secrets
import uuid

from django.db import models
from django.utils import timezone

from core.models import Organisation

PREFIXE = "sk_sent_"


def _empreinte(cle_en_clair: str) -> str:
    return hashlib.sha256(cle_en_clair.encode()).hexdigest()


class Module(models.TextChoices):
    """Les services vendus. La portee d'une cle est une liste de ces valeurs."""

    REPUTATION = "reputation", "Reputation"
    AUTHGUARD = "authguard", "Securite des connexions"
    SURFACE = "surface", "Surface exposee"
    LOGS = "logs", "Journaux"
    AIGUARD = "aiguard", "Garde IA"


class ApiKey(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="cles"
    )
    libelle = models.CharField(max_length=120, help_text="« Production », « Recette »…")
    prefixe = models.CharField(max_length=24, db_index=True)
    empreinte = models.CharField(max_length=64, unique=True)
    portee = models.JSONField(
        default=list, help_text="Liste de modules autorises pour cette cle"
    )
    ip_autorisees = models.JSONField(
        default=list, blank=True, help_text="Vide = pas de restriction d'IP"
    )
    active = models.BooleanField(default=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    derniere_utilisation = models.DateTimeField(null=True, blank=True)
    rotation_due_le = models.DateField(
        null=True, blank=True, help_text="Rappel de rotation"
    )

    class Meta:
        verbose_name = "cle d'API"
        verbose_name_plural = "cles d'API"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"{self.organisation.nom} · {self.libelle} ({self.prefixe}…)"

    @classmethod
    def generer(cls, *, organisation, libelle, portee, **extra):
        """Cree une cle et renvoie (objet, cle_en_clair).

        La cle en clair n'existe qu'ici. On ne peut plus jamais la retrouver.
        """
        brut = PREFIXE + secrets.token_urlsafe(32)
        obj = cls.objects.create(
            organisation=organisation,
            libelle=libelle,
            portee=list(portee),
            prefixe=brut[: len(PREFIXE) + 6],
            empreinte=_empreinte(brut),
            **extra,
        )
        return obj, brut

    @classmethod
    def resoudre(cls, cle_en_clair: str):
        """Retrouve une cle active depuis sa valeur en clair, ou None."""
        if not cle_en_clair or not cle_en_clair.startswith(PREFIXE):
            return None
        return (
            cls.objects.select_related("organisation")
            .filter(empreinte=_empreinte(cle_en_clair), active=True)
            .first()
        )

    def couvre(self, module: str) -> bool:
        return module in self.portee

    def ip_permise(self, ip: str | None) -> bool:
        if not self.ip_autorisees:
            return True
        return ip in self.ip_autorisees


class Quota(models.Model):
    """Plafond mensuel par module. Une ligne par (organisation, module)."""

    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="quotas"
    )
    module = models.CharField(max_length=20, choices=Module.choices)
    plafond_mensuel = models.PositiveIntegerField(default=1000)
    depassement_autorise = models.BooleanField(
        default=False, help_text="Si faux, on refuse au-dela du plafond"
    )

    class Meta:
        verbose_name = "quota"
        verbose_name_plural = "quotas"
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "module"], name="quota_unique_par_module"
            )
        ]

    def __str__(self):
        return f"{self.organisation.nom} · {self.module} · {self.plafond_mensuel}/mois"

    def consommation_du_mois(self, *, rapide: bool = False) -> int:
        """`rapide` : lit le compteur Redis, sans toucher la base.

        Utilise par le plan bloquant. Retombe sur le comptage en base si
        Redis n'est pas disponible (developpement).
        """
        if rapide:
            from . import journal

            valeur = journal.consommation(self.organisation_id, self.module)
            if valeur >= 0:
                return valeur

        debut = timezone.now().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        return ApiCall.objects.filter(
            organisation=self.organisation, module=self.module, horodatage__gte=debut
        ).count()

    def depasse(self, *, rapide: bool = False) -> bool:
        return self.consommation_du_mois(rapide=rapide) >= self.plafond_mensuel


class ApiCall(models.Model):
    """Journal d'appel : facturation et piste d'audit a la fois."""

    id = models.BigAutoField(primary_key=True)
    horodatage = models.DateTimeField(auto_now_add=True, db_index=True)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="appels"
    )
    cle = models.ForeignKey(
        ApiKey, on_delete=models.SET_NULL, null=True, related_name="appels"
    )
    module = models.CharField(max_length=20, db_index=True)
    cible = models.CharField(max_length=500, blank=True)
    verdict = models.CharField(max_length=40, blank=True)
    score = models.FloatField(null=True, blank=True)
    latence_ms = models.PositiveIntegerField(null=True, blank=True)
    code_http = models.PositiveSmallIntegerField(default=200)
    ip_source = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = "appel d'API"
        verbose_name_plural = "appels d'API"
        ordering = ["-horodatage"]
        indexes = [
            models.Index(fields=["organisation", "module", "-horodatage"]),
        ]

    def __str__(self):
        return f"{self.horodatage:%H:%M:%S} {self.module} {self.cible} -> {self.verdict}"
