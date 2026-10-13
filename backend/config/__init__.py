"""Le paquet de configuration.

Il charge la file d'attente du serveur -- sauf en profil local, ou celery
n'est pas installe. Ce test se fait sur l'environnement et non sur les
reglages Django : ce fichier est importe AVANT que les reglages existent.
"""
import os

LOCAL = os.environ.get("MAEL_LOCAL", "").strip().lower() in {
    "1", "true", "oui", "on", "yes"}

if LOCAL:
    __all__ = ()
else:
    from .celery import app as celery_app

    __all__ = ("celery_app",)
