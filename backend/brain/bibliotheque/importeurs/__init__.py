"""Importeurs : transforment des sources publiques en fiches v2 (etape 2.4.3).

Principe (decision du 17/09/2026, option a) : les FAITS viennent de la source
(regle, parametre, valeur attendue, gravite, numeros CIS/ANSSI) ; les
COMMANDES de lecture viennent de gabarits ecrits et verifies par nous, un par
type de regle. Rien n'est genere par un modele. Toute fiche produite passe par
`schema.valider` (garde-fou compris) et sort en `brouillon` : elle n'est
« verifiee » qu'apres relecture humaine.
"""
