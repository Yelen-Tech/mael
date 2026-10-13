#!/usr/bin/env bash
# MAEL - playbook infra.service-activer (appliquer). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SIMULATION=0
[[ "${1:-}" == "--simulation" ]] && { SIMULATION=1; shift; }
SERVICE="${1:?usage: appliquer.sh [--simulation] <service>}"
mael_valider "$SERVICE" '^[A-Za-z0-9@_.-]+$' service
U="${SERVICE}"; [[ "$U" == *.timer || "$U" == *.socket ]] || U="${U}.service"
DEMARRAGE=$(systemctl is-enabled "$U" 2>/dev/null || true)
EXECUTION=$(systemctl is-active "$U" 2>/dev/null || true)
if [[ $SIMULATION -eq 1 ]]; then
  mael_simulation
  echo "etat actuel : ${DEMARRAGE:-absent} / ${EXECUTION}"
  echo "systemctl unmask ${U} ; systemctl start ${U} ; systemctl enable ${U}"
  exit 0
fi
mael_exiger_root
ETAT=$(mael_etat infra.service-activer "$SERVICE")
[[ -f "${ETAT}/avant" ]] || printf '%s %s\n' "${DEMARRAGE:-absent}" "$EXECUTION" > "${ETAT}/avant"
systemctl unmask "$U"
systemctl start "$U"
systemctl enable "$U"
echo "Active : ${U}."
