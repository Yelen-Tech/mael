"""Banc de mesure du MODÈLE : ce qu'il répond, jugé par du code.

Jusqu'ici on mesurait la RECHERCHE de fiches (`bibliotheque.evaluation` :
top1, top2, MRR). On ne mesurait pas ce que le modèle **fait** de ces fiches.
C'est ce trou que ce paquet comble — et c'est le seul moyen de savoir si un
modèle plus gros améliore le produit, ou si on paie du GPU pour rien.

    python -m brain.bench                      # le modèle configuré
    python -m brain.bench --modele qwen2.5:14b
    python -m brain.bench --base http://127.0.0.1:11434   # GPU loué, par tunnel
    python -m brain.bench --comparer resultats/*.json

Quatre choses sont mesurées, toutes par du code, jamais à l'appréciation :

  1. **observer**  — le modèle propose-t-il la bonne commande de LECTURE ?
     (motif attendu, et le garde-fou doit la classer « lecture »)
  2. **refuser**   — refuse-t-il ce qui doit l'être, sans proposer la commande ?
  3. **fonder**    — s'abstient-il d'affirmer un constat sans observation ?
     (juge : `brain.fondement`, le même que le terminal)
  4. **tenir**     — la commande proposée est-elle reconnue par les fiches ?
     (`bibliotheque.verification`, le même que le terminal)

Aucun de ces quatre points ne demande de lire la réponse « au jugé ». Une
mesure qu'un humain doit interpréter n'est pas une mesure.
"""
