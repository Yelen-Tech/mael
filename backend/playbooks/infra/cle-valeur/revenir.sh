#!/usr/bin/env bash
# MAEL - playbook infra.cle-valeur (revenir). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
FICHIER="${1:?usage: revenir.sh <fichier> <cle>}"
CLE="${2:?cle manquante}"
mael_valider "$FICHIER" '^/(etc|root)/[A-Za-z0-9._/-]+$' fichier
mael_valider "$CLE" '^\$?[A-Za-z_][A-Za-z0-9_-]*$' cle
mael_exiger_root
ETAT=$(mael_chemin_etat infra.cle-valeur "${FICHIER}:${CLE}")
[[ -d "$ETAT" ]] || { echo "Rien a revenir pour ${CLE}."; exit 0; }
mael_restaurer "$ETAT"
rm -rf -- "$ETAT"
echo "Retour arriere effectue pour ${CLE} (${FICHIER})."
