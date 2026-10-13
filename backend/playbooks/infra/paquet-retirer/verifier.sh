#!/usr/bin/env bash
# MAEL - playbook infra.paquet-retirer (verifier). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
PAQUET="${1:?usage: verifier.sh <paquet>}"
mael_valider "$PAQUET" '^[a-z0-9][a-z0-9+.-]*( [a-z0-9][a-z0-9+.-]*)*$' paquet
for p in $PAQUET; do
  if dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "ok installed"; then
    echo "Non conforme : ${p} est installe." >&2; exit 1
  fi
done
echo "Conforme : ${PAQUET} absent."
