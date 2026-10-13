"""Socle multi-entreprise : organisation, utilisateur, piste d'audit.

Reprend le modele de FinControl. Regle absolue : toute donnee metier porte
une cle vers Organisation, et tout acces est filtre dessus au niveau du
gestionnaire de requetes -- jamais dans les vues.
"""
import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class Organisation(models.Model):
    """Le client. Racine du cloisonnement."""

    class Formule(models.TextChoices):
        DECOUVERTE = "decouverte", "Decouverte (gratuite)"
        ESSENTIEL = "essentiel", "Essentiel"
        PRO = "pro", "Pro"
        SUR_SITE = "sur_site", "Sur site (auto-heberge)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nom = models.CharField(max_length=200)
    secteur = models.CharField(max_length=120, blank=True)
    formule = models.CharField(
        max_length=20, choices=Formule.choices, default=Formule.DECOUVERTE
    )
    contact_incident = models.EmailField(
        blank=True, help_text="Adresse alertee en cas d'incident critique"
    )
    telephone_incident = models.CharField(max_length=40, blank=True)
    actif = models.BooleanField(default=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "organisation"
        verbose_name_plural = "organisations"
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class User(AbstractUser):
    """Acces humain au tableau de bord."""

    class Role(models.TextChoices):
        ADMIN = "admin", "Administrateur"
        ANALYSTE = "analyste", "Analyste"
        LECTEUR = "lecteur", "Lecteur"

    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="utilisateurs",
        null=True,
        blank=True,
        help_text="Vide = personnel Sentinelle (acces transverse)",
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.LECTEUR)

    class Meta:
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"

    @property
    def est_interne(self) -> bool:
        """Personnel Sentinelle, pas un client."""
        return self.organisation_id is None

    def peut_valider_playbook(self) -> bool:
        """Appliquer un playbook chez un client est une action humaine."""
        return self.role in {self.Role.ADMIN, self.Role.ANALYSTE}


class AuditLog(models.Model):
    """Piste d'audit en ecriture seule. Jamais modifiee, jamais supprimee."""

    id = models.BigAutoField(primary_key=True)
    horodatage = models.DateTimeField(auto_now_add=True, db_index=True)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.PROTECT, null=True, blank=True
    )
    acteur = models.CharField(
        max_length=200, help_text="Utilisateur, cle d'API, tache, ou « cerveau »"
    )
    action = models.CharField(max_length=120, db_index=True)
    cible = models.CharField(max_length=500, blank=True)
    details = models.JSONField(default=dict, blank=True)
    ip_source = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = "entree d'audit"
        verbose_name_plural = "piste d'audit"
        ordering = ["-horodatage"]
        indexes = [models.Index(fields=["organisation", "-horodatage"])]

    def __str__(self):
        return f"{self.horodatage:%Y-%m-%d %H:%M} {self.acteur} {self.action}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("La piste d'audit est en ecriture seule.")
        return super().save(*args, **kwargs)

    @classmethod
    def tracer(cls, *, acteur, action, organisation=None, cible="", ip=None, **details):
        return cls.objects.create(
            acteur=str(acteur),
            action=action,
            organisation=organisation,
            cible=cible[:500],
            ip_source=ip,
            details=details,
        )
