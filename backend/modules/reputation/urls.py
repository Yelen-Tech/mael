from django.urls import path

from .views import ReputationView, SanteView

urlpatterns = [
    path("reputation", ReputationView.as_view(), name="reputation"),
    path("sante", SanteView.as_view(), name="sante"),
]
