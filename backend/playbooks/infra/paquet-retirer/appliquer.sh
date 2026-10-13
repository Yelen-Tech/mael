#!/usr/bin/env bash
# MAEL - playbook infra.paquet-retirer (appliquer). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SIMULATION=0
[[ "${1:-}" == "--simulation" ]] && { SIMULATION=1; shift; }
PAQUET="${1:?usage: appliquer.sh [--simulation] <paquet>}"
mael_valider "$PAQUET" '^[a-z0-9][a-z0-9+.-]*( [a-z0-9][a-z0-9+.-]*)*$' paquet
INSTALLES=()
for p in $PAQUET; do
  dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "ok installed" && INSTALLES+=("$p")
done
[[ ${#INSTALLES[@]} -eq 0 ]] && { echo "Deja absent : ${PAQUET}."; exit 0; }
PAQUET="${INSTALLES[*]}"
PLAN=$(apt-get -s remove ${PAQUET} 2>/dev/null | grep '^Remv ' || true)
if [[ $SIMULATION -eq 1 ]]; then
  mael_simulation
  echo "apt-get remove -y ${PAQUET}"
  echo "${PLAN:-(plan indisponible)}"
  exit 0
fi
mael_exiger_root
if [[ $(grep -c '^Remv ' <<<"$PLAN") -gt ${#INSTALLES[@]} ]]; then
  echo "Refus : le retrait emporterait d'autres paquets :" >&2
  echo "$PLAN" >&2
  exit 4
fi
ETAT=$(mael_etat infra.paquet-retirer "$PAQUET")
for p in "${INSTALLES[@]}"; do
  printf '%s=%s\n' "$p" "$(dpkg-query -W -f='${Version}' "$p")" >> "${ETAT}/versions"
done
DEBIAN_FRONTEND=noninteractive apt-get remove -y "${INSTALLES[@]}"
echo "Retire : ${PAQUET}."
