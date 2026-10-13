"""Taches de facturation."""
from celery import shared_task

from . import journal


@shared_task(name="billing.tasks.vider_journal")
def vider_journal() -> dict:
    """Transfere le tampon Redis vers la base. Toutes les 10 s."""
    return {"ecrites": journal.vider(), "en_attente": journal.en_attente()}


@shared_task(name="billing.tasks.reconcilier_quotas")
def reconcilier_quotas() -> dict:
    """Recale les compteurs rapides sur la base. Une fois par heure.

    Le compteur Redis peut deriver (perte du tampon, expiration). La base
    reste la verite pour la facturation.
    """
    from .models import Quota

    journal.vider()  # d'abord tout ecrire, sinon on recale sur un retard
    recales = 0
    for quota in Quota.objects.all().iterator():
        journal.reconcilier_quota(quota.organisation_id, quota.module)
        recales += 1
    return {"quotas_recales": recales}
