#!/usr/bin/env bash
# MAEL - playbook infra.fichier-groupe (appliquer). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SIMULATION=0
[[ "${1:-}" == "--simulation" ]] && { SIMULATION=1; shift; }
CHEMIN="${1:?usage: appliquer.sh [--simulation] <chemin> <groupe>}"
VOULU="${2:?groupe manquant}"
mael_valider "$CHEMIN" '^/[A-Za-z0-9._/+-]+$' chemin
mael_valider "$VOULU" '^[a-z_][a-z0-9_-]*$' groupe
[[ -e "$CHEMIN" ]] || { echo "Absent : ${CHEMIN} (rien a faire)."; exit 0; }
ACTUEL=$(stat -c '%G' "$CHEMIN")
DEJA=0; [[ "$ACTUEL" == "$VOULU" ]] && DEJA=1
if [[ $SIMULATION -eq 1 ]]; then
  mael_simulation
  if [[ $DEJA -eq 1 ]]; then echo "deja conforme : ${CHEMIN} (${ACTUEL})"; else echo "chgrp ${VOULU} ${CHEMIN} (actuel : ${ACTUEL})"; fi
  exit 0
fi
[[ $DEJA -eq 1 ]] && { echo "Deja conforme : ${CHEMIN} (${ACTUEL})."; exit 0; }
mael_exiger_root
ETAT=$(mael_etat infra.fichier-groupe "$CHEMIN")
[[ -f "${ETAT}/avant" ]] || printf '%s\n' "$ACTUEL" > "${ETAT}/avant"
chgrp "$VOULU" "$CHEMIN"
echo "Applique : chgrp ${VOULU} ${CHEMIN} (avant : ${ACTUEL})."
