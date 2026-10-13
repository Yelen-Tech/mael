from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from .models import Commande


@login_required
@require_http_methods(["GET"])
def detail_commande(request, ident: int):
    # L'ORM parametre la requete ; client=request.user empeche de lire la
    # commande d'un autre (controle d'acces, OWASP A01).
    commande = get_object_or_404(Commande, pk=ident, client=request.user)
    return render(request, "commande.html", {"commande": commande})
