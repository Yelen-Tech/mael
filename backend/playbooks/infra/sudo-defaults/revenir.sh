#!/usr/bin/env bash
# MAEL - playbook infra.sudo-defaults (revenir). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
OPTION="${1:?usage: revenir.sh <option>}"
mael_valider "$OPTION" '^[a-z_]+$' option
mael_exiger_root
ETAT=$(mael_chemin_etat infra.sudo-defaults "$OPTION")
[[ -d "$ETAT" ]] || { echo "Rien a revenir pour ${OPTION}."; exit 0; }
mael_restaurer "$ETAT"
rm -rf -- "$ETAT"
visudo -qc >/dev/null || echo "ATTENTION : sudoers invalide apres retour arriere." >&2
echo "Retour arriere effectue pour ${OPTION}."
