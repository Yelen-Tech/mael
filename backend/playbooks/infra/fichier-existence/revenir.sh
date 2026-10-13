#!/usr/bin/env bash
# MAEL - playbook infra.fichier-existence (revenir). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
CHEMIN="${1:?usage: revenir.sh <chemin>}"
mael_valider "$CHEMIN" '^/[A-Za-z0-9._/+-]+$' chemin
mael_exiger_root
ETAT=$(mael_chemin_etat infra.fichier-existence "$CHEMIN")
[[ -d "$ETAT" ]] || { echo "Rien a revenir."; exit 0; }
mael_restaurer "$ETAT"
rm -rf -- "$ETAT"
echo "Retour arriere effectue pour ${CHEMIN}."
