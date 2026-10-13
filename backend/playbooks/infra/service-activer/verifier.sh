#!/usr/bin/env bash
# MAEL - playbook infra.service-activer (verifier). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SERVICE="${1:?usage: verifier.sh <service>}"
mael_valider "$SERVICE" '^[A-Za-z0-9@_.-]+$' service
U="${SERVICE}"; [[ "$U" == *.timer || "$U" == *.socket ]] || U="${U}.service"
D=$(systemctl is-enabled "$U" 2>/dev/null || true)
E=$(systemctl is-active "$U" 2>/dev/null || true)
if [[ "$D" == enabled && "$E" == active ]]; then
  echo "Conforme : ${SERVICE} enabled / active."; exit 0
fi
echo "Non conforme : ${SERVICE} ${D:-absent} / ${E}." >&2
exit 1
