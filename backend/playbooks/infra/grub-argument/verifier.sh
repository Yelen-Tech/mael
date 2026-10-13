#!/usr/bin/env bash
# MAEL - playbook infra.grub-argument (verifier). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
ARG="${1:?usage: verifier.sh <argument> <action>}"
ACTION="${2:?action manquante}"
mael_valider "$ARG" '^[A-Za-z0-9_.,=:-]+( [A-Za-z0-9_.,=:-]+)*$' argument
LIGNE=" $(sed -n 's/^GRUB_CMDLINE_LINUX="\(.*\)"$/\1/p' /etc/default/grub | head -1) "
for a in $ARG; do
  if [[ "$ACTION" == ajouter && "$LIGNE" != *" ${a} "* ]]; then echo "Non conforme : ${a} absent." >&2; exit 1; fi
  if [[ "$ACTION" == retirer && "$LIGNE" =~ \ ${a%%=*}(=|\ ) ]]; then echo "Non conforme : ${a} present." >&2; exit 1; fi
done
echo "Conforme (configuration persistante ; effet au redemarrage)."
