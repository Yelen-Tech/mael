#!/usr/bin/env bash
# MAEL - playbook infra.paquet-retirer (revenir). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
PAQUET="${1:?usage: revenir.sh <paquet>}"
mael_valider "$PAQUET" '^[a-z0-9][a-z0-9+.-]*( [a-z0-9][a-z0-9+.-]*)*$' paquet
mael_exiger_root
ETAT=$(mael_chemin_etat infra.paquet-retirer "$PAQUET")
[[ -d "$ETAT" ]] || { echo "Rien a revenir pour ${PAQUET}."; exit 0; }
while IFS='=' read -r p v; do
  [[ -n "$p" ]] || continue
  DEBIAN_FRONTEND=noninteractive apt-get install -y "${p}=${v}" \
    || DEBIAN_FRONTEND=noninteractive apt-get install -y "$p"
done < "${ETAT}/versions"
rm -rf -- "$ETAT"
echo "Retour arriere effectue pour ${PAQUET}."
