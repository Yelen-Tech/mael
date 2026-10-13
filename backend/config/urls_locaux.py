"""Aucune adresse : MAEL local ne sert rien sur le reseau.

Django exige un ROOT_URLCONF et verifie les adresses au demarrage de chaque
commande. En local, l'admin, l'API et le tableau de bord ne sont pas
installes : leur laisser `config.urls` ferait tomber le terminal sur un
« No installed app with label 'admin' » -- une trace d'appel Python en plein
demarrage, exactement ce que L1 interdit.

Cette liste vide dit la meme chose que le virage du 21/09 : l'outil local
n'ouvre aucun port.
"""
urlpatterns: list = []
