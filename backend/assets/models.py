"""Actifs declares par le client, et la preuve qu'ils lui appartiennent.

`Actif.preuve_verifiee_le` est le champ le plus important du schema.
Scanner une cible sans autorisation ecrite est un delit : aucun outil
d'inspection ne s'execute si la preuve n'est pas valide.
"""
import secrets
import uuid

from django.db import models
from django.utils import timezone

from core.models import Organisation

VALIDITE_PREUVE_JOURS = 365


class Actif(models.Model):
    class Type(models.TextChoices):
        DOMAINE = "domaine", "Domaine"
        IP = "ip", "Adresse IP"
        PLAGE_IP = "plage_ip", "Plage d'adresses"
        HOTE = "hote", "Machine (via agent)"

    class Preuve(models.TextChoices):
        DNS_TXT = "dns_txt", "Enregistrement DNS TXT"
        FICHIER_HTTP = "fichier_http", "Fichier depose a la racine du site"
        MANDAT_SIGNE = "mandat_signe", "Mandat signe (televerse)"
        AGENT = "agent", "Agent installe et authentifie"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="actifs"
    )
    type = models.CharField(max_length=12, choices=Type.choices)
    valeur = models.CharField(max_length=253, help_text="exemple.bf, 41.x.x.x, …")
    libelle = models.CharField(max_length=200, blank=True)

    # --- la preuve de propriete ---
    methode_preuve = models.CharField(
        max_length=20, choices=Preuve.choices, blank=True
    )
    jeton_preuve = models.CharField(
        max_length=64, blank=True, help_text="Valeur a publier par le client"
    )
    preuve_verifiee_le = models.DateTimeField(null=True, blank=True)
    mandat = models.FileField(upload_to="mandats/", blank=True)

    surveille = models.BooleanField(
        default=False, help_text="Inclus dans les scans periodiques"
    )
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "actif"
        verbose_name_plural = "actifs"
        ordering = ["organisation", "valeur"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "type", "valeur"], name="actif_unique"
            )
        ]

    def __str__(self):
        return f"{self.valeur} ({self.get_type_display()})"

    # ------------------------------------------------------------ preuve
    def nouveau_jeton(self) -> str:
        self.jeton_preuve = "sentinelle-verif=" + secrets.token_hex(16)
        self.preuve_verifiee_le = None
        self.save(update_fields=["jeton_preuve", "preuve_verifiee_le"])
        return self.jeton_preuve

    @property
    def preuve_valide(self) -> bool:
        if not self.preuve_verifiee_le:
            return False
        age = timezone.now() - self.preuve_verifiee_le
        return age.days < VALIDITE_PREUVE_JOURS

    def exiger_preuve(self):
        """Appele par chaque adaptateur d'outil avant execution."""
        if not self.preuve_valide:
            raise PermissionError(
                f"Propriete de « {self.valeur} » non prouvee ou expiree. "
                "Aucune inspection autorisee."
            )


class ActifManquant(PermissionError):
    """La cible demandee n'appartient a aucun actif prouve de l'organisation."""


def resoudre_cible(organisation, cible: str) -> Actif:
    """Traduit une chaine en actif prouve, ou refuse.

    C'est le seul point d'entree autorise pour les outils d'inspection.
    """
    actif = Actif.objects.filter(organisation=organisation, valeur=cible).first()
    if actif is None:
        # un sous-domaine est couvert par son domaine parent prouve
        for candidat in Actif.objects.filter(
            organisation=organisation, type=Actif.Type.DOMAINE
        ):
            if cible == candidat.valeur or cible.endswith("." + candidat.valeur):
                actif = candidat
                break
    if actif is None:
        raise ActifManquant(
            f"« {cible} » n'est pas un actif declare de cette organisation."
        )
    actif.exiger_preuve()
    return actif
