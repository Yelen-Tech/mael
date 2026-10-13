#!/usr/bin/env bash
# MAEL - playbook infra.service-desactiver (revenir). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SERVICE="${1:?usage: revenir.sh <service>}"
mael_valider "$SERVICE" '^[A-Za-z0-9@_.-]+$' service
U="${SERVICE}"; [[ "$U" == *.timer || "$U" == *.socket ]] || U="${U}.service"
mael_exiger_root
ETAT=$(mael_chemin_etat infra.service-desactiver "$SERVICE")
[[ -f "${ETAT}/avant" ]] || { echo "Rien a revenir pour ${SERVICE}."; exit 0; }
read -r D E < "${ETAT}/avant"
systemctl unmask "$U" || true
[[ "$D" == masked ]] && systemctl mask "$U"
[[ "$D" =~ ^enabled ]] && systemctl enable "$U"
[[ "$E" == active ]] && systemctl start "$U"
if [[ -f "${ETAT}/socket" ]]; then
  read -r SD SE < "${ETAT}/socket"
  systemctl unmask "${SERVICE}.socket" || true
  [[ "$SD" =~ ^enabled ]] && systemctl enable "${SERVICE}.socket"
  [[ "$SE" == active ]] && systemctl start "${SERVICE}.socket"
fi
rm -rf -- "$ETAT"
echo "Retour arriere effectue pour ${U}."
