"""Profil de comportement d'un compte, sous forme pseudonymisee.

Ce qu'on stocke : « le compte dont l'empreinte est abc123 se connecte
habituellement depuis le Burkina Faso, avec deux appareils connus ».

Ce qu'on ne stocke jamais : l'identifiant, l'adresse de courriel, le nom.
Voir `identite.py` pour le pourquoi.

On ne stocke pas non plus chaque tentative : ce serait une ecriture en base
par tentative de connexion, dans le chemin bloquant. Les compteurs vivent
en Redis ; le profil n'est mis a jour qu'apres un succes, et de facon
asynchrone.
"""
from django.db import models
from django.utils import timezone

from core.models import Organisation

MAX_APPAREILS = 8
MAX_PAYS = 6


class SelOrganisation(models.Model):
    """Sel de pseudonymisation propre a chaque organisation.

    Empeche de recouper les utilisateurs d'un client avec ceux d'un autre.
    """

    organisation = models.OneToOneField(
        Organisation, on_delete=models.CASCADE, related_name="sel_authguard"
    )
    sel = models.CharField(max_length=64)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "sel de pseudonymisation"
        verbose_name_plural = "sels de pseudonymisation"

    def __str__(self):
        return f"sel de {self.organisation.nom}"

    @classmethod
    def pour(cls, organisation) -> str:
        from .identite import nouveau_sel

        objet, _ = cls.objects.get_or_create(
            organisation=organisation, defaults={"sel": nouveau_sel()}
        )
        return objet.sel


class ProfilCompte(models.Model):
    """Ce qui est habituel pour un compte. Sert de reference au signal d'anomalie."""

    id = models.BigAutoField(primary_key=True)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="profils_comptes"
    )
    empreinte = models.CharField(max_length=64, db_index=True)

    appareils_connus = models.JSONField(default=list, blank=True)
    pays_connus = models.JSONField(default=list, blank=True)
    connexions_reussies = models.PositiveIntegerField(default=0)
    premiere_vue = models.DateTimeField(default=timezone.now)
    derniere_reussite = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "profil de compte"
        verbose_name_plural = "profils de comptes"
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "empreinte"], name="profil_unique"
            )
        ]

    def __str__(self):
        return f"{self.empreinte[:12]}… ({self.connexions_reussies} connexions)"

    def enregistrer_succes(self, *, empreinte_appareil: str, pays: str) -> None:
        """Met a jour ce qui est « habituel ». Listes bornees, les plus
        recentes en tete : un appareil abandonne il y a deux ans sort tout seul."""
        if empreinte_appareil:
            appareils = [a for a in self.appareils_connus if a != empreinte_appareil]
            self.appareils_connus = [empreinte_appareil, *appareils][:MAX_APPAREILS]
        if pays:
            pays_liste = [p for p in self.pays_connus if p != pays]
            self.pays_connus = [pays, *pays_liste][:MAX_PAYS]
        self.connexions_reussies += 1
        self.derniere_reussite = timezone.now()
        self.save(
            update_fields=[
                "appareils_connus", "pays_connus",
                "connexions_reussies", "derniere_reussite",
            ]
        )


class MotDePasseCompromis(models.Model):
    """Empreintes SHA-1 de mots de passe apparus dans des fuites.

    Stockage par prefixe pour permettre l'interrogation en anonymat :
    le client envoie les 5 premiers caracteres de l'empreinte, on renvoie
    tous les suffixes de ce prefixe. On n'apprend jamais quel mot de passe
    a ete teste -- c'est le protocole k-anonymat.

    La table est vide au depart : il faut charger un corpus
    (`manage.py charger_mots_de_passe`).
    """

    prefixe = models.CharField(max_length=5, db_index=True)
    suffixe = models.CharField(max_length=35)
    occurrences = models.PositiveIntegerField(
        default=1, help_text="Nombre de fuites ou ce mot de passe apparait"
    )

    class Meta:
        verbose_name = "mot de passe compromis"
        verbose_name_plural = "mots de passe compromis"
        constraints = [
            models.UniqueConstraint(
                fields=["prefixe", "suffixe"], name="empreinte_mdp_unique"
            )
        ]
        indexes = [models.Index(fields=["prefixe"])]

    def __str__(self):
        return f"{self.prefixe}… ({self.occurrences} occurrences)"


class ReseauDeConfiance(models.Model):
    """Reseaux declares par le client ou les signaux agreges par IP sont neutralises.

    Sans cela, un bureau derriere un routeur NAT -- une seule adresse publique
    pour vingt employes -- declencherait en permanence le signal de bourrage
    d'identifiants. Le client declare ses plages de bureau et son VPN, et on
    arrete de compter les comptes distincts derriere ces adresses.

    Ce que ca ne desactive pas : les signaux par *compte* (force brute,
    pulverisation, appareil inconnu, changement de pays). Une attaque depuis
    l'interieur reste detectee.
    """

    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="reseaux_de_confiance"
    )
    cidr = models.CharField(max_length=43, help_text="41.203.10.0/24 ou 41.203.10.5/32")
    libelle = models.CharField(max_length=120, help_text="« Siege Ouaga », « VPN »")
    actif = models.BooleanField(default=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "reseau de confiance"
        verbose_name_plural = "reseaux de confiance"
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "cidr"], name="reseau_confiance_unique"
            )
        ]

    def __str__(self):
        return f"{self.libelle} ({self.cidr})"

    @classmethod
    def couvre(cls, organisation, ip: str) -> bool:
        """Cette adresse est-elle dans un reseau declare par le client."""
        import ipaddress

        try:
            adresse = ipaddress.ip_address(ip)
        except ValueError:
            return False
        for reseau in cls.objects.filter(organisation=organisation, actif=True):
            try:
                if adresse in ipaddress.ip_network(reseau.cidr, strict=False):
                    return True
            except ValueError:
                continue
        return False
