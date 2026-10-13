"""Banc d'essai Linux de MAEL (point 4).

Prouve que les fiches et les playbooks fonctionnent VRAIMENT sur Ubuntu
22.04, Ubuntu 24.04 et Debian 12 — aujourd'hui avec l'executeur factice,
demain tel quel avec Docker.

  executeurs.py  -- interface + ExecuteurDocker + ExecuteurFactice (A)
  images/        -- Dockerfiles par systeme, empreintes figees (B)
  resoudre_empreintes.py -- renseigne les @sha256 le jour ou Docker marche
  fiches.py      -- execute les commandes observer, le code juge (C)
  playbooks.py   -- aller-retour complet des playbooks (D)

CLI : python -m banc.fiches --image ubuntu2204 [--theme X]
      python -m banc.playbooks --image ubuntu2204
      python -m banc.resoudre_empreintes
"""
