"""Indicateurs de compromission agreges depuis les flux publics.

Plan bloquant : la table est alimentee hors ligne par `intel/`, et lue ici
en O(1) avec cache Redis devant. Aucun appel reseau pendant la requete client.
"""
from django.db import models
from django.utils import timezone


class Indicateur(models.Model):
    class Type(models.TextChoices):
        IP = "ip", "Adresse IP"
        DOMAINE = "domaine", "Domaine"
        URL = "url", "URL"
        EMPREINTE = "empreinte", "Empreinte de fichier"

    class Verdict(models.TextChoices):
        MALVEILLANT = "malveillant", "Malveillant"
        SUSPECT = "suspect", "Suspect"
        INCONNU = "inconnu", "Inconnu"
        BENIN = "benin", "Benin (liste blanche)"

    id = models.BigAutoField(primary_key=True)
    type = models.CharField(max_length=12, choices=Type.choices, db_index=True)
    valeur = models.CharField(max_length=512)

    score = models.FloatField(default=0.0, help_text="0 = inoffensif, 1 = certain")
    verdict = models.CharField(
        max_length=12, choices=Verdict.choices, default=Verdict.INCONNU
    )
    categories = models.JSONField(
        default=list, blank=True, help_text="scan, bruteforce, c2, hameconnage…"
    )
    sources = models.JSONField(
        default=dict, blank=True, help_text="{nom_du_flux: score_brut}"
    )

    premiere_vue = models.DateTimeField(default=timezone.now)
    derniere_vue = models.DateTimeField(default=timezone.now, db_index=True)
    pays = models.CharField(max_length=2, blank=True)
    asn = models.CharField(max_length=40, blank=True)

    class Meta:
        verbose_name = "indicateur"
        verbose_name_plural = "indicateurs"
        constraints = [
            models.UniqueConstraint(
                fields=["type", "valeur"], name="indicateur_unique"
            )
        ]
        indexes = [models.Index(fields=["type", "valeur"])]

    def __str__(self):
        return f"{self.valeur} · {self.verdict} ({self.score:.2f})"

    def save(self, *args, **kwargs):
        # Toutes les valeurs sont stockees en minuscules : la lecture du plan
        # bloquant fait un « exact » qui doit pouvoir utiliser l'index.
        self.valeur = self.valeur.strip().lower()
        return super().save(*args, **kwargs)

    @property
    def fraicheur_jours(self) -> int:
        return (timezone.now() - self.derniere_vue).days


class Flux(models.Model):
    """Etat de sante d'un flux de renseignement. Un flux muet est un flux mort."""

    nom = models.CharField(max_length=60, unique=True)
    url = models.URLField(blank=True)
    actif = models.BooleanField(default=True)
    poids = models.FloatField(
        default=1.0, help_text="Confiance accordee a ce flux dans le score agrege"
    )
    derniere_collecte = models.DateTimeField(null=True, blank=True)
    dernier_nombre = models.PositiveIntegerField(default=0)
    derniere_erreur = models.TextField(blank=True)

    class Meta:
        verbose_name = "flux de renseignement"
        verbose_name_plural = "flux de renseignement"
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class Plage(models.Model):
    """Plage d'adresses malveillante (CIDR), interrogeable par appartenance.

    Spamhaus DROP et d'autres flux publient des plages entieres, pas des
    adresses. Les stocker comme une chaine « 45.13.0.0/24 » les rend
    inutilisables : un client demande « 45.13.1.9 », pas la plage.

    On stocke donc les bornes en entiers et on interroge par encadrement,
    ce qui utilise l'index sur `debut`. Une plage /16 pese une ligne au
    lieu de 65 536.
    """

    id = models.BigAutoField(primary_key=True)
    cidr = models.CharField(max_length=43)
    version = models.PositiveSmallIntegerField(default=4, help_text="4 ou 6")
    debut = models.DecimalField(max_digits=39, decimal_places=0, db_index=True)
    fin = models.DecimalField(max_digits=39, decimal_places=0)

    score = models.FloatField(default=0.0)
    verdict = models.CharField(
        max_length=12, choices=Indicateur.Verdict.choices,
        default=Indicateur.Verdict.INCONNU,
    )
    categories = models.JSONField(default=list, blank=True)
    sources = models.JSONField(default=dict, blank=True)
    derniere_vue = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "plage malveillante"
        verbose_name_plural = "plages malveillantes"
        constraints = [
            models.UniqueConstraint(fields=["cidr"], name="plage_unique"),
        ]
        indexes = [models.Index(fields=["version", "debut", "fin"])]

    def __str__(self):
        return f"{self.cidr} · {self.verdict} ({self.score:.2f})"

    @staticmethod
    def bornes(cidr: str) -> tuple[int, int, int] | None:
        """(version, premiere adresse, derniere adresse) en entiers."""
        import ipaddress

        try:
            reseau = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            return None
        return reseau.version, int(reseau[0]), int(reseau[-1])

    @classmethod
    def contenant(cls, adresse: str):
        """Plage la plus specifique contenant cette adresse, ou None."""
        import ipaddress

        try:
            ip = ipaddress.ip_address(adresse)
        except ValueError:
            return None
        valeur = int(ip)
        return (
            cls.objects.filter(version=ip.version, debut__lte=valeur, fin__gte=valeur)
            # La plage la plus etroite est la plus pertinente. Entre deux
            # plages emboitees contenant la meme adresse, elle a un debut
            # plus grand ET une fin plus petite -- « -debut » seul laisse
            # 45.13.0.0/16 et 45.13.0.0/24 a egalite.
            .order_by("-debut", "fin")
            .first()
        )
