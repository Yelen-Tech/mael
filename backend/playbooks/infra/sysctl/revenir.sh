#!/usr/bin/env bash
# MAEL - playbook infra.sysctl (revenir). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
CLE="${1:?usage: revenir.sh <cle>}"
mael_valider "$CLE" '^[a-z0-9_.-]+$' cle
mael_exiger_root
ETAT=$(mael_chemin_etat infra.sysctl "$CLE")
[[ -d "$ETAT" ]] || { echo "Rien a revenir pour ${CLE}."; exit 0; }
mael_restaurer "$ETAT"
if [[ -s "${ETAT}/avant_runtime" ]]; then
  sysctl -q -w "${CLE}=$(cat "${ETAT}/avant_runtime")" || true
fi
rm -rf -- "$ETAT"
echo "Retour arriere effectue pour ${CLE}."
