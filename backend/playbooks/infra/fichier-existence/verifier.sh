#!/usr/bin/env bash
# MAEL - playbook infra.fichier-existence (verifier). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
CHEMIN="${1:?usage: verifier.sh <chemin> <etat>}"
ETAT_VOULU="${2:?etat manquant}"
mael_valider "$CHEMIN" '^/[A-Za-z0-9._/+-]+$' chemin
if [[ "$ETAT_VOULU" == present && -e "$CHEMIN" ]] || [[ "$ETAT_VOULU" == absent && ! -e "$CHEMIN" ]]; then
  echo "Conforme : ${CHEMIN} ${ETAT_VOULU}."; exit 0
fi
echo "Non conforme : ${CHEMIN}." >&2
exit 1
