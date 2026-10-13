#!/usr/bin/env bash
# MAEL - playbook infra.paquet-installer (appliquer). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SIMULATION=0
[[ "${1:-}" == "--simulation" ]] && { SIMULATION=1; shift; }
PAQUET="${1:?usage: appliquer.sh [--simulation] <paquet>}"
mael_valider "$PAQUET" '^[a-z0-9][a-z0-9+.-]*( [a-z0-9][a-z0-9+.-]*)*$' paquet
installe() { dpkg-query -W -f='${Status}' "$PAQUET" 2>/dev/null | grep -q "ok installed"; }
installe && { echo "Deja installe : ${PAQUET}."; exit 0; }
if [[ $SIMULATION -eq 1 ]]; then
  mael_simulation
  echo "apt-get install -y ${PAQUET}"
  apt-get -s install "$PAQUET" 2>/dev/null | grep '^Inst ' || true
  exit 0
fi
mael_exiger_root
ETAT=$(mael_etat infra.paquet-installer "$PAQUET")
touch "${ETAT}/installe_par_mael"
DEBIAN_FRONTEND=noninteractive apt-get install -y "$PAQUET"
echo "Installe : ${PAQUET}."
