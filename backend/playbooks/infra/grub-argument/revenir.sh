#!/usr/bin/env bash
# MAEL - playbook infra.grub-argument (revenir). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
ARG="${1:?usage: revenir.sh <argument>}"
mael_valider "$ARG" '^[A-Za-z0-9_.,=:-]+( [A-Za-z0-9_.,=:-]+)*$' argument
mael_exiger_root
ETAT=$(mael_chemin_etat infra.grub-argument "$ARG")
[[ -d "$ETAT" ]] || { echo "Rien a revenir pour ${ARG}."; exit 0; }
mael_restaurer "$ETAT"
rm -rf -- "$ETAT"
update-grub 2>/dev/null || grub-mkconfig -o /boot/grub/grub.cfg || true
echo "Retour arriere effectue pour ${ARG}."
