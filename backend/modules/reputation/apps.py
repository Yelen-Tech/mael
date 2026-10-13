from django.apps import AppConfig


class ReputationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules.reputation"
    label = "reputation"
    verbose_name = "Module Reputation"
