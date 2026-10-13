#!/usr/bin/env bash
# MAEL - playbook infra.module-interdit (verifier). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
MODULE="${1:?usage: verifier.sh <module>}"
mael_valider "$MODULE" '^[a-z0-9_-]+$' module
F="/etc/modprobe.d/${MODULE}.conf"
if grep -qs "^install ${MODULE} /bin/false" "$F" && grep -qs "^blacklist ${MODULE}$" "$F"; then
  echo "Conforme : ${MODULE} interdit."; exit 0
fi
echo "Non conforme : ${MODULE} chargeable." >&2
exit 1
