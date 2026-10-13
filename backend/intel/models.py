"""Donnees de reference collectees : geolocalisation des adresses.

Meme motif que `reputation.Plage` : les jeux de donnees publient des plages,
on stocke les bornes en entiers et on interroge par encadrement indexe.
Une plage /16 tient en une ligne au lieu de 65 536.

Source utilisee : le projet ip-location-db, qui publie des jeux de donnees
sous licence libre, derives des enregistrements WHOIS et des annonces BGP.
Precision au pays -- suffisant pour le signal de voyage impossible.

Pourquoi pas MaxMind : leur base gratuite exige un compte et une cle, et sa
licence encadre la redistribution. Impossible a mettre dans un paquet
« sur site » telecharge par le client. Le resolveur est remplacable
(`intel/geo.py`), donc un client qui a une licence MaxMind peut la brancher.
"""
from django.db import models
from django.utils import timezone


class PlageGeo(models.Model):
    """Plage d'adresses -> pays."""

    id = models.BigAutoField(primary_key=True)
    version = models.PositiveSmallIntegerField(default=4)
    debut = models.DecimalField(max_digits=39, decimal_places=0, db_index=True)
    fin = models.DecimalField(max_digits=39, decimal_places=0)
    pays = models.CharField(max_length=2, db_index=True)
    mise_a_jour = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "plage geographique"
        verbose_name_plural = "plages geographiques"
        indexes = [models.Index(fields=["version", "debut", "fin"])]

    def __str__(self):
        return f"{self.debut}-{self.fin} -> {self.pays}"
