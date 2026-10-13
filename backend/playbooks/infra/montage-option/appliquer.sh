#!/usr/bin/env bash
# MAEL - playbook infra.montage-option (appliquer). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SIMULATION=0
[[ "${1:-}" == "--simulation" ]] && { SIMULATION=1; shift; }
POINT="${1:?usage: appliquer.sh [--simulation] <point> <option>}"
OPTION="${2:?option manquante}"
mael_valider "$POINT" '^/[A-Za-z0-9._/-]*$' point
mael_valider "$OPTION" '^[a-z_]+$' option
if ! awk -v p="$POINT" '$1 !~ /^#/ && $2 == p {t=1} END{exit !t}' /etc/fstab; then
  echo "Refus : ${POINT} n'est pas declare dans /etc/fstab (partition dediee a creer d'abord)." >&2
  exit 5
fi
if [[ $SIMULATION -eq 1 ]]; then
  mael_simulation
  awk -v p="$POINT" '$1 !~ /^#/ && $2 == p {print "ligne actuelle : " $0}' /etc/fstab
  echo "ajouter ${OPTION} aux options, puis : mount -o remount ${POINT}"
  exit 0
fi
mael_exiger_root
ETAT=$(mael_etat infra.montage-option "${POINT}:${OPTION}")
mael_sauvegarder "$ETAT" /etc/fstab
awk -v p="$POINT" -v o="$OPTION" 'BEGIN{OFS="\t"} $1 !~ /^#/ && $2 == p {n=split($4,x,","); ok=0; for(i=1;i<=n;i++) if(x[i]==o) ok=1; if(!ok) $4=$4","o} {print}' /etc/fstab > /etc/fstab.mael
cat /etc/fstab.mael > /etc/fstab && rm -f /etc/fstab.mael
if ! mount -o remount "$POINT"; then
  echo "Remontage impossible : retour arriere." >&2
  "$(dirname "$0")/revenir.sh" "$POINT" "$OPTION"
  exit 3
fi
echo "Applique : ${OPTION} sur ${POINT}."
