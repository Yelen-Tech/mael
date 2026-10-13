#!/usr/bin/env bash
# MAEL - playbook infra.fichier-existence (appliquer). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SIMULATION=0
[[ "${1:-}" == "--simulation" ]] && { SIMULATION=1; shift; }
CHEMIN="${1:?usage: appliquer.sh [--simulation] <chemin> <present|absent>}"
ETAT_VOULU="${2:?etat manquant}"
mael_valider "$CHEMIN" '^/[A-Za-z0-9._/+-]+$' chemin
mael_valider "$ETAT_VOULU" '^(present|absent)$' etat
if [[ "$ETAT_VOULU" == present && -e "$CHEMIN" ]] || [[ "$ETAT_VOULU" == absent && ! -e "$CHEMIN" ]]; then
  echo "Deja conforme : ${CHEMIN} ${ETAT_VOULU}."; exit 0
fi
if [[ $SIMULATION -eq 1 ]]; then
  mael_simulation
  if [[ "$ETAT_VOULU" == present ]]; then echo "creer ${CHEMIN} (0640, root:root)"; else echo "supprimer ${CHEMIN} (sauvegarde gardee)"; fi
  exit 0
fi
mael_exiger_root
ETAT=$(mael_etat infra.fichier-existence "$CHEMIN")
mael_sauvegarder "$ETAT" "$CHEMIN"
if [[ "$ETAT_VOULU" == present ]]; then
  touch "$CHEMIN"; chmod 0640 "$CHEMIN"; chown root:root "$CHEMIN"
else
  rm -f -- "$CHEMIN"
fi
echo "Applique : ${CHEMIN} ${ETAT_VOULU}."
