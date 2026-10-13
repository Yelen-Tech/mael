#!/usr/bin/env bash
# MAEL - playbook infra.fichier-proprietaire (verifier). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
CHEMIN="${1:?usage: verifier.sh <chemin> <proprietaire>}"
VOULU="${2:?proprietaire manquant}"
mael_valider "$CHEMIN" '^/[A-Za-z0-9._/+-]+$' chemin
[[ -e "$CHEMIN" ]] || { echo "Absent : ${CHEMIN}."; exit 0; }
ACTUEL=$(stat -c '%U' "$CHEMIN")
DEJA=0; [[ "$ACTUEL" == "$VOULU" ]] && DEJA=1
if [[ $DEJA -eq 1 ]]; then echo "Conforme : ${CHEMIN} (${ACTUEL})."; exit 0; fi
echo "Non conforme : ${CHEMIN} (${ACTUEL}, attendu ${VOULU})." >&2
exit 1
