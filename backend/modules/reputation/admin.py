from django.contrib import admin
from django.utils.html import format_html

from .models import Flux, Indicateur, Plage

COULEURS = {
    "malveillant": "#a02a20",
    "suspect": "#b15715",
    "inconnu": "#65767f",
    "benin": "#336247",
}


def colorer(verdict):
    return format_html(
        '<b style="color:{}">{}</b>', COULEURS.get(verdict, "#000000"), verdict
    )


@admin.register(Indicateur)
class IndicateurAdmin(admin.ModelAdmin):
    list_display = ("valeur", "type", "verdict_colore", "score",
                    "categories", "derniere_vue")
    list_filter = ("type", "verdict", "pays")
    search_fields = ("valeur",)
    readonly_fields = ("premiere_vue",)
    actions = ["marquer_benin"]

    @admin.display(description="verdict", ordering="verdict")
    def verdict_colore(self, obj):
        return colorer(obj.verdict)

    @admin.action(description="Marquer comme benin (faux positif signale)")
    def marquer_benin(self, request, queryset):
        """Un faux positif remonte par un client se corrige ici.

        L'agregation respecte ce choix : `integrer()` ne touche pas aux
        indicateurs deja marques benins, meme si un flux les resignale.
        """
        nombre = queryset.update(verdict=Indicateur.Verdict.BENIN, score=0.0)
        self.message_user(request, f"{nombre} indicateur(s) marque(s) benin(s).")


@admin.register(Plage)
class PlageAdmin(admin.ModelAdmin):
    list_display = ("cidr", "verdict_colore", "score", "adresses", "derniere_vue")
    list_filter = ("verdict", "version")
    search_fields = ("cidr",)

    @admin.display(description="verdict")
    def verdict_colore(self, obj):
        return colorer(obj.verdict)

    @admin.display(description="adresses couvertes")
    def adresses(self, obj):
        return f"{int(obj.fin - obj.debut) + 1:,}".replace(",", " ")


@admin.register(Flux)
class FluxAdmin(admin.ModelAdmin):
    """Le poids se regle ici, sans toucher au code : un flux qui produit trop
    de faux positifs se voit baisser sa confiance dans le score agrege."""

    list_display = ("nom", "actif", "poids", "dernier_nombre",
                    "derniere_collecte", "sante")
    list_editable = ("actif", "poids")
    readonly_fields = ("derniere_collecte", "dernier_nombre", "derniere_erreur")

    @admin.display(description="etat")
    def sante(self, obj):
        if obj.derniere_erreur:
            return format_html(
                '<b style="color:#a02a20">erreur</b> — {}', obj.derniere_erreur[:60]
            )
        if not obj.derniere_collecte:
            return format_html('<span style="color:#65767f">jamais collecte</span>')
        return format_html('<b style="color:#336247">ok</b>')
