from django.contrib import admin

from .models import PlageGeo


@admin.register(PlageGeo)
class PlageGeoAdmin(admin.ModelAdmin):
    list_display = ("pays", "version", "debut", "fin", "mise_a_jour")
    list_filter = ("pays", "version")
    search_fields = ("pays",)

    def has_add_permission(self, request):
        """La table se charge par manage.py charger_geo."""
        return False
