#!/usr/bin/env bash
# MAEL - playbook infra.ssh-directive (revenir). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
DIRECTIVE="${1:?usage: revenir.sh <directive>}"
mael_valider "$DIRECTIVE" '^[A-Za-z]+$' directive
mael_exiger_root
ETAT=$(mael_chemin_etat infra.ssh-directive "$DIRECTIVE")
[[ -d "$ETAT" ]] || { echo "Rien a revenir pour ${DIRECTIVE}."; exit 0; }
mael_restaurer "$ETAT"
rm -rf -- "$ETAT"
if sshd -t; then
  systemctl reload ssh 2>/dev/null || systemctl reload sshd || true
fi
echo "Retour arriere effectue pour ${DIRECTIVE}."
