#!/usr/bin/env bash
# MAEL - playbook infra.module-interdit (revenir). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
MODULE="${1:?usage: revenir.sh <module>}"
mael_valider "$MODULE" '^[a-z0-9_-]+$' module
mael_exiger_root
ETAT=$(mael_chemin_etat infra.module-interdit "$MODULE")
[[ -d "$ETAT" ]] || { echo "Rien a revenir pour ${MODULE}."; exit 0; }
mael_restaurer "$ETAT"
rm -rf -- "$ETAT"
echo "Retour arriere effectue pour ${MODULE}."
