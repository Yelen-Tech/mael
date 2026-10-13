#!/usr/bin/env bash
# MAEL - playbook infra.fichier-proprietaire (appliquer). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SIMULATION=0
[[ "${1:-}" == "--simulation" ]] && { SIMULATION=1; shift; }
CHEMIN="${1:?usage: appliquer.sh [--simulation] <chemin> <proprietaire>}"
VOULU="${2:?proprietaire manquant}"
mael_valider "$CHEMIN" '^/[A-Za-z0-9._/+-]+$' chemin
mael_valider "$VOULU" '^[a-z_][a-z0-9_-]*$' proprietaire
[[ -e "$CHEMIN" ]] || { echo "Absent : ${CHEMIN} (rien a faire)."; exit 0; }
ACTUEL=$(stat -c '%U' "$CHEMIN")
DEJA=0; [[ "$ACTUEL" == "$VOULU" ]] && DEJA=1
if [[ $SIMULATION -eq 1 ]]; then
  mael_simulation
  if [[ $DEJA -eq 1 ]]; then echo "deja conforme : ${CHEMIN} (${ACTUEL})"; else echo "chown ${VOULU} ${CHEMIN} (actuel : ${ACTUEL})"; fi
  exit 0
fi
[[ $DEJA -eq 1 ]] && { echo "Deja conforme : ${CHEMIN} (${ACTUEL})."; exit 0; }
mael_exiger_root
ETAT=$(mael_etat infra.fichier-proprietaire "$CHEMIN")
[[ -f "${ETAT}/avant" ]] || printf '%s\n' "$ACTUEL" > "${ETAT}/avant"
chown "$VOULU" "$CHEMIN"
echo "Applique : chown ${VOULU} ${CHEMIN} (avant : ${ACTUEL})."
