#!/usr/bin/env bash
# MAEL - playbook infra.fichier-droits (appliquer). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SIMULATION=0
[[ "${1:-}" == "--simulation" ]] && { SIMULATION=1; shift; }
CHEMIN="${1:?usage: appliquer.sh [--simulation] <chemin> <mode>}"
VOULU="${2:?mode manquant}"
mael_valider "$CHEMIN" '^/[A-Za-z0-9._/+-]+$' chemin
mael_valider "$VOULU" '^[0-7]{3,4}$' mode
[[ -e "$CHEMIN" ]] || { echo "Absent : ${CHEMIN} (rien a faire)."; exit 0; }
ACTUEL=$(stat -c '%a' "$CHEMIN")
DEJA=0; (( (8#$ACTUEL & ~8#$VOULU) == 0 )) && DEJA=1
# On RETIRE les bits en trop, on n'en ajoute jamais (0604 -> 0600, pas 0640).
NOUVEAU=$(printf '%04o' $(( 8#$ACTUEL & 8#$VOULU )))
if [[ $SIMULATION -eq 1 ]]; then
  mael_simulation
  if [[ $DEJA -eq 1 ]]; then echo "deja conforme : ${CHEMIN} (${ACTUEL})"; else echo "chmod ${NOUVEAU} ${CHEMIN} (actuel : ${ACTUEL}, au plus ${VOULU})"; fi
  exit 0
fi
[[ $DEJA -eq 1 ]] && { echo "Deja conforme : ${CHEMIN} (${ACTUEL})."; exit 0; }
mael_exiger_root
ETAT=$(mael_etat infra.fichier-droits "$CHEMIN")
[[ -f "${ETAT}/avant" ]] || printf '%s\n' "$ACTUEL" > "${ETAT}/avant"
chmod "$NOUVEAU" "$CHEMIN"
echo "Applique : chmod ${NOUVEAU} ${CHEMIN} (avant : ${ACTUEL})."
