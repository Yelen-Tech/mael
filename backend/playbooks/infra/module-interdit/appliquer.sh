#!/usr/bin/env bash
# MAEL - playbook infra.module-interdit (appliquer). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SIMULATION=0
[[ "${1:-}" == "--simulation" ]] && { SIMULATION=1; shift; }
MODULE="${1:?usage: appliquer.sh [--simulation] <module>}"
mael_valider "$MODULE" '^[a-z0-9_-]+$' module
F="/etc/modprobe.d/${MODULE}.conf"
if [[ $SIMULATION -eq 1 ]]; then
  mael_simulation
  echo "dans ${F} : install ${MODULE} /bin/false ; blacklist ${MODULE}"
  exit 0
fi
mael_exiger_root
ETAT=$(mael_etat infra.module-interdit "$MODULE")
mael_sauvegarder "$ETAT" "$F"
if grep -qs "^install ${MODULE}" "$F"; then
  sed -i "s#^install ${MODULE}.*#install ${MODULE} /bin/false#" "$F"
else
  printf '\n# Disable per security requirements (MAEL)\ninstall %s /bin/false\n' "$MODULE" >> "$F"
fi
grep -qs "^blacklist ${MODULE}$" "$F" || echo "blacklist ${MODULE}" >> "$F"
echo "Applique : ${MODULE} interdit (${F})."
