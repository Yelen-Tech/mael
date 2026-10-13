#!/usr/bin/env bash
# MAEL - playbook infra.sudo-defaults (verifier). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
OPTION="${1:?usage: verifier.sh <option> [valeur]}"
VALEUR="${2-}"
mael_valider "$OPTION" '^[a-z_]+$' option
LIGNE="Defaults ${OPTION}${VALEUR:+=${VALEUR}}"
if grep -qxF "$LIGNE" /etc/sudoers.d/60-mael 2>/dev/null && visudo -qc >/dev/null 2>&1; then
  echo "Conforme : ${LIGNE}."; exit 0
fi
echo "Non conforme : ${LIGNE} absent (ou sudoers illisible sans root)." >&2
exit 1
