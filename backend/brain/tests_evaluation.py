"""Garde-fou de progression de la recuperation.

Deux jeux : REFERENCE (sert a regler la recherche, donc optimiste) et
CONTROLE (jamais utilise pour regler : mesure honnete). Les planchers ne
doivent que MONTER : relever les valeurs quand la recherche s'ameliore.
    python -m brain.bibliotheque.evaluation [--controle]
"""
from brain.bibliotheque import evaluation

# Historique (17/09/2026)
#   depart, mots-cles a plat        : reference top1 31/52, top2 41/52, MRR 0.70
#   etape 3 (index FTS5+aiguillage) : reference top1 50/52, top2 52/52, MRR 0.98
#                                     controle  top1 22/30, top2 28/30, MRR 0.84
#   bugs « routeur » + chemins pointes: reference top1 53/55, top2 55/55, MRR 0.98
#                                     controle  top1 23/30, top2 29/30, MRR 0.87
#   Faiblesse connue laissee au controle : un synonyme d'un seul mot trop
#   gourmand (« routeur » -> ip_forward) masque « sollicitations de routeur ».
# 18/09/2026 -- couverture (461 -> 556 fiches : audit, PAM, sudo, partitions) :
#   2 questions de controle battues par les nouvelles fiches -> deplacees en
#   reference ; 4 questions neuves (zones couvertes) ecrites avant mesure.
#   controle mesure UNE fois avant retouche : top1 25/32, top2 31/32, MRR 0.88
#   (planchers = cette mesure) ; apres lexique : 26/32, 31/32, 0.89.
#   reference (57 q.) apres lexique  : top1 55/57, top2 57/57, MRR 0.98
# 18/09/2026 -- recettes (556 -> 616 fiches importees : comptes, sessions,
#   expiration, sudo) : 1 question de controle battue (« journal dedie » ->
#   groupe dedie de sudo) -> reference ; 4 neuves ecrites avant mesure.
#   controle mesure UNE fois : top1 28/35, top2 33/35, MRR 0.88. Nouvel
#   echec laisse visible : « sessions shell inactives » -> fiches SSH avant
#   TMOUT (rang 3).
#   reference (58 q.) : top1 56/58, top2 58/58, MRR 0.98
# 18/09/2026 -- 3e vague (616 -> 678 fiches importees : auditd.conf, regles
#   d'audit composites, fichiers systeme, journalisation, pare-feu) :
#   « transfert de paquets entre interfaces » battue par la fiche wifi ->
#   reference ; 4 questions neuves ecrites avant mesure (toutes en tete).
#   controle mesure UNE fois : top1 31/38, top2 36/38, MRR 0.89.
#   reference (59 q.) : top1 57/59, top2 59/59, MRR 0.98
# 18/09/2026 -- fin des regles sans gabarit (678 -> 735 fiches importees) :
#   controle inchange (non retouche) : top1 32/38, top2 36/38, MRR 0.90.
#   reference : 3 questions battues par de nouvelles fiches (dont 1 par des
#   fiches plus precises, ajoutees aux attendues) ; synonyme « installe ».
#   -> top1 58/59, top2 59/59, MRR 0.99
# 19/09/2026 -- theme cryptographie (3 fiches manuelles : cles d'hote SSH,
#   echange de cles hybride post-quantique, certificats TLS locaux) ;
#   4 questions neuves ecrites avant mesure, controle mesure UNE fois :
#   top1 35/42, top2 39/42, MRR 0.89 (planchers = cette mesure). Echec
#   laisse visible : « certificat signe en SHA-1 » -> fiches de signature
#   des modules noyau avant la fiche TLS (rang 3).
#   reference inchangee : top1 58/59, top2 59/59, MRR 0.99.
PLANCHERS = {
    "reference": {"fichier": evaluation.FICHIER, "top1": 58, "top2": 59, "mrr": 0.99},
    "controle": {"fichier": evaluation.FICHIER_CONTROLE, "top1": 35, "top2": 39, "mrr": 0.89},
}


def _verifier(nom):
    p = PLANCHERS[nom]
    jeu = evaluation.charger(p["fichier"])
    assert evaluation.fiches_inconnues(jeu) == []
    mesure = evaluation.mesurer(jeu)
    n = len(mesure.resultats)
    assert not [r.question for r in mesure.resultats if r.invalide]
    texte = evaluation.rapport(mesure)
    assert round(mesure.top1 * n) >= p["top1"], texte
    assert round(mesure.top2 * n) >= p["top2"], texte
    assert mesure.mrr >= p["mrr"] - 0.005, texte


def test_jeu_de_reference_ne_regresse_pas():
    _verifier("reference")


def test_jeu_de_controle_ne_regresse_pas():
    _verifier("controle")
