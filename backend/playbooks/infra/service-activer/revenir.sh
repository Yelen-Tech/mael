#!/usr/bin/env bash
# MAEL - playbook infra.service-activer (revenir). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SERVICE="${1:?usage: revenir.sh <service>}"
mael_valider "$SERVICE" '^[A-Za-z0-9@_.-]+$' service
U="${SERVICE}"; [[ "$U" == *.timer || "$U" == *.socket ]] || U="${U}.service"
mael_exiger_root
ETAT=$(mael_chemin_etat infra.service-activer "$SERVICE")
[[ -f "${ETAT}/avant" ]] || { echo "Rien a revenir pour ${SERVICE}."; exit 0; }
read -r D E < "${ETAT}/avant"
[[ "$E" == active ]] || systemctl stop "$U" || true
[[ "$D" =~ ^enabled ]] || systemctl disable "$U" || true
[[ "$D" == masked ]] && systemctl mask "$U"
rm -rf -- "$ETAT"
echo "Retour arriere effectue pour ${U}."
