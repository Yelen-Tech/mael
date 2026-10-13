from django.contrib import admin
from django.utils.html import format_html

from .models import Actif


@admin.register(Actif)
class ActifAdmin(admin.ModelAdmin):
    list_display = ("valeur", "type", "organisation", "etat_preuve", "surveille")
    list_filter = ("type", "surveille", "methode_preuve", "organisation")
    search_fields = ("valeur", "libelle")
    readonly_fields = ("jeton_preuve", "cree_le")
    actions = ["generer_jeton"]

    @admin.display(description="preuve de propriete")
    def etat_preuve(self, obj):
        if obj.preuve_valide:
            return format_html(
                '<b style="color:#336247">valide</b> ({})',
                obj.get_methode_preuve_display(),
            )
        if obj.preuve_verifiee_le:
            return format_html('<b style="color:#b15715">expiree</b>')
        return format_html(
            '<b style="color:#a02a20">absente</b> — aucune inspection possible'
        )

    @admin.action(description="Generer un nouveau jeton de verification")
    def generer_jeton(self, request, queryset):
        for actif in queryset:
            actif.nouveau_jeton()
        self.message_user(
            request,
            f"{queryset.count()} jeton(s) genere(s). Le client doit publier la "
            "valeur, puis la verification peut etre lancee.",
        )
