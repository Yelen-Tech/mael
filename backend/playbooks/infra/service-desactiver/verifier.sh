#!/usr/bin/env bash
# MAEL - playbook infra.service-desactiver (verifier). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SERVICE="${1:?usage: verifier.sh <service>}"
mael_valider "$SERVICE" '^[A-Za-z0-9@_.-]+$' service
U="${SERVICE}"; [[ "$U" == *.timer || "$U" == *.socket ]] || U="${U}.service"
D=$(systemctl is-enabled "$U" 2>/dev/null || true)
E=$(systemctl is-active "$U" 2>/dev/null || true)
if [[ "$D" =~ ^(enabled|enabled-runtime)$ || "$E" == active ]]; then
  echo "Non conforme : ${SERVICE} ${D} / ${E}." >&2; exit 1
fi
echo "Conforme : ${SERVICE} ${D:-absent} / ${E}."
