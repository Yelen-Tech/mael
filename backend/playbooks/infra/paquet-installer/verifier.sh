#!/usr/bin/env bash
# MAEL - playbook infra.paquet-installer (verifier). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
PAQUET="${1:?usage: verifier.sh <paquet>}"
mael_valider "$PAQUET" '^[a-z0-9][a-z0-9+.-]*( [a-z0-9][a-z0-9+.-]*)*$' paquet
if dpkg-query -W -f='${Status}' "$PAQUET" 2>/dev/null | grep -q "ok installed"; then
  echo "Conforme : ${PAQUET} installe."; exit 0
fi
echo "Non conforme : ${PAQUET} absent." >&2
exit 1
