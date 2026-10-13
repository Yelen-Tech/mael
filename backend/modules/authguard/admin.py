from django.contrib import admin

from .models import (
    MotDePasseCompromis,
    ProfilCompte,
    ReseauDeConfiance,
    SelOrganisation,
)


@admin.register(ReseauDeConfiance)
class ReseauDeConfianceAdmin(admin.ModelAdmin):
    """Le reglage le plus important pour un client d'entreprise.

    Sans lui, son siege derriere un routeur NAT -- une adresse publique pour
    vingt postes -- est signale en permanence comme du bourrage d'identifiants.
    """

    list_display = ("libelle", "cidr", "organisation", "actif", "cree_le")
    list_filter = ("actif", "organisation")
    search_fields = ("libelle", "cidr")


@admin.register(ProfilCompte)
class ProfilCompteAdmin(admin.ModelAdmin):
    list_display = ("empreinte_courte", "organisation", "connexions_reussies",
                    "pays_connus", "nombre_appareils", "derniere_reussite")
    list_filter = ("organisation",)
    search_fields = ("empreinte",)
    readonly_fields = [f.name for f in ProfilCompte._meta.fields]

    @admin.display(description="empreinte (aucun identifiant en clair)")
    def empreinte_courte(self, obj):
        return f"{obj.empreinte[:16]}…"

    @admin.display(description="appareils connus")
    def nombre_appareils(self, obj):
        return len(obj.appareils_connus)

    def has_add_permission(self, request):
        return False


@admin.register(MotDePasseCompromis)
class MotDePasseCompromisAdmin(admin.ModelAdmin):
    list_display = ("prefixe", "suffixe", "occurrences")
    search_fields = ("prefixe",)

    def has_add_permission(self, request):
        """Le corpus se charge par manage.py charger_mots_de_passe."""
        return False


@admin.register(SelOrganisation)
class SelOrganisationAdmin(admin.ModelAdmin):
    list_display = ("organisation", "cree_le")
    # Le sel sert a pseudonymiser : il ne doit jamais s'afficher, meme a un
    # administrateur. Le voir, avec le secret serveur, permettrait de tester
    # des identifiants devines.
    exclude = ("sel",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
