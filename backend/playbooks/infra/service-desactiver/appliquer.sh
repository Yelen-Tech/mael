#!/usr/bin/env bash
# MAEL - playbook infra.service-desactiver (appliquer). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SIMULATION=0
[[ "${1:-}" == "--simulation" ]] && { SIMULATION=1; shift; }
SERVICE="${1:?usage: appliquer.sh [--simulation] <service>}"
mael_valider "$SERVICE" '^[A-Za-z0-9@_.-]+$' service
U="${SERVICE}"; [[ "$U" == *.timer || "$U" == *.socket ]] || U="${U}.service"
DEMARRAGE=$(systemctl is-enabled "$U" 2>/dev/null || true)
EXECUTION=$(systemctl is-active "$U" 2>/dev/null || true)
[[ -z "$DEMARRAGE" ]] && { echo "Service absent : ${U} (rien a faire)."; exit 0; }
SOCKET=0; systemctl -q list-unit-files "${SERVICE}.socket" >/dev/null 2>&1 && SOCKET=1
if [[ $SIMULATION -eq 1 ]]; then
  mael_simulation
  echo "etat actuel : ${DEMARRAGE} / ${EXECUTION}"
  echo "systemctl stop ${U} ; systemctl disable ${U} ; systemctl mask ${U}"
  [[ $SOCKET -eq 1 ]] && echo "systemctl stop ${SERVICE}.socket ; systemctl mask ${SERVICE}.socket"
  exit 0
fi
mael_exiger_root
ETAT=$(mael_etat infra.service-desactiver "$SERVICE")
[[ -f "${ETAT}/avant" ]] || printf '%s %s\n' "$DEMARRAGE" "$EXECUTION" > "${ETAT}/avant"
[[ $SOCKET -eq 1 && ! -f "${ETAT}/socket" ]] && \
  printf '%s %s\n' "$(systemctl is-enabled "${SERVICE}.socket" 2>/dev/null || true)" \
    "$(systemctl is-active "${SERVICE}.socket" 2>/dev/null || true)" > "${ETAT}/socket"
systemctl stop "$U" || true
systemctl disable "$U" || true
systemctl mask "$U"
if [[ $SOCKET -eq 1 ]]; then
  systemctl stop "${SERVICE}.socket" || true
  systemctl mask "${SERVICE}.socket"
fi
systemctl reset-failed "$U" 2>/dev/null || true
echo "Desactive : ${U}."
