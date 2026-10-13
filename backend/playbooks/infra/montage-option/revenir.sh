#!/usr/bin/env bash
# MAEL - playbook infra.montage-option (revenir). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
POINT="${1:?usage: revenir.sh <point> <option>}"
OPTION="${2:?option manquante}"
mael_valider "$POINT" '^/[A-Za-z0-9._/-]*$' point
mael_exiger_root
ETAT=$(mael_chemin_etat infra.montage-option "${POINT}:${OPTION}")
[[ -d "$ETAT" ]] || { echo "Rien a revenir."; exit 0; }
mael_restaurer "$ETAT"
rm -rf -- "$ETAT"
mount -o remount "$POINT" || true
echo "Retour arriere effectue pour ${POINT}."
