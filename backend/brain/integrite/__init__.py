"""Noyau d'integrite de MAEL (document « NOUVEAU POINT LE NOYEAU »).

Pilier transverse, a cote du mode d'emploi, du garde-fou (censure) et de la
bibliotheque. Quatre modules realisables sans Linux :

  merkle.py      modules 1+5 — scellement de la bibliotheque, arbre de Merkle
  coherence.py   module 9    — solveur de coherence fiches <-> playbooks
  invariants.py  module 3    — invariants verifies en continu par le code
  entropie.py    module 2    — entropie de Shannon (contenu injecte/obscurci)

  binaires.py    module 4    — integrite des binaires de la machine mesuree
                               (dpkg -V / rpm -Va, empreintes, intrus)
  infiltration.py module 6   — LD_PRELOAD, LD_AUDIT, chemins et modules
  isolation.py   module 7    — seccomp-BPF et espaces de noms : le contrat
                               d'enfermement des conteneurs de MAEL, verifie
                               avant CHAQUE lancement d'outil
  derive_etat.py module 8    — photographie datee d'une machine (9 rubriques)
                               et comparaison de deux photographies

Les 9 modules du document sont faits.

CLI : python -m brain.integrite [--sceller|--merkle|--coherence|--invariants|--entropie]
      python -m brain.integrite --binaires     [--image mael-banc-ubuntu2204]
      python -m brain.integrite --infiltration [--image ...]
      python -m brain.integrite --isolation    [--image ...]
      python -m brain.integrite --etat         [--image ...]
                                [--enregistrer etat.json | --comparer etat.json]
"""
