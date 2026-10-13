#!/usr/bin/env bash
# MAEL - playbook infra.montage-option (verifier). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
POINT="${1:?usage: verifier.sh <point> <option>}"
OPTION="${2:?option manquante}"
mael_valider "$POINT" '^/[A-Za-z0-9._/-]*$' point
if findmnt -kn -o OPTIONS "$POINT" | tr ',' '\n' | grep -qx "$OPTION"; then
  echo "Conforme : ${OPTION} actif sur ${POINT}."; exit 0
fi
echo "Non conforme : ${OPTION} absent de ${POINT}." >&2
exit 1
