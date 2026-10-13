from django.contrib import admin

from .models import ApiCall, ApiKey, Quota


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("libelle", "organisation", "prefixe", "portee",
                    "active", "derniere_utilisation", "rotation_due_le")
    list_filter = ("active", "organisation")
    search_fields = ("libelle", "prefixe")
    # L'empreinte ne doit jamais etre modifiable a la main, et la cle en clair
    # n'existe qu'a la creation : elle n'est nulle part reaffichable.
    readonly_fields = ("prefixe", "empreinte", "cree_le", "derniere_utilisation")

    def has_add_permission(self, request):
        """Une cle se cree par ApiKey.generer(), qui rend la valeur en clair une
        seule fois. La creer ici produirait une cle inutilisable par le client."""
        return False


@admin.register(Quota)
class QuotaAdmin(admin.ModelAdmin):
    list_display = ("organisation", "module", "plafond_mensuel",
                    "consommation_affichee", "depassement_autorise")
    list_filter = ("module", "depassement_autorise")

    @admin.display(description="consomme ce mois")
    def consommation_affichee(self, obj):
        return f"{obj.consommation_du_mois()} / {obj.plafond_mensuel}"


@admin.register(ApiCall)
class ApiCallAdmin(admin.ModelAdmin):
    list_display = ("horodatage", "organisation", "module", "cible",
                    "verdict", "latence_ms", "code_http")
    list_filter = ("module", "verdict", "organisation")
    search_fields = ("cible",)
    date_hierarchy = "horodatage"
    readonly_fields = [f.name for f in ApiCall._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
