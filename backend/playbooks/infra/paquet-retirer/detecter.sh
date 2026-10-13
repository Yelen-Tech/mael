#!/usr/bin/env bash
# MAEL - playbook infra.paquet-retirer (detecter). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
PAQUET="${1:?usage: detecter.sh <paquet>}"
mael_valider "$PAQUET" '^[a-z0-9][a-z0-9+.-]*( [a-z0-9][a-z0-9+.-]*)*$' paquet
dpkg-query -W -f='${binary:Package} ${Status} ${Version}\n' "$PAQUET" 2>/dev/null || echo "$PAQUET non installe"
