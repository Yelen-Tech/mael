"""Preparation commune des tests du brain : Django est configure UNE fois,
avant tout fichier de test.

Avant le 12/10/2026, seuls deux fichiers (tests_outils, tests_integrite) le
faisaient : un fichier lance seul (tests_modeles.py : 7 echecs) ne marchait
que si l'un d'eux avait ete importe avant — la suite complete passait par
chance d'ordre.
"""
import os

import django
from django.conf import settings

if not settings.configured:            # tests lances hors manage.py
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
