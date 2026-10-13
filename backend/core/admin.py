from django.contrib import admin

from .models import AuditLog, Organisation, User


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ("nom", "secteur", "formule", "actif", "cree_le")
    list_filter = ("formule", "actif")
    search_fields = ("nom",)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "email", "organisation", "role", "is_active")
    list_filter = ("role", "organisation")
    search_fields = ("username", "email")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("horodatage", "acteur", "action", "cible", "organisation")
    list_filter = ("action", "organisation")
    search_fields = ("acteur", "cible")
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
