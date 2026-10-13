#!/usr/bin/env bash
# MAEL - playbook infra.montage-option (detecter). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
POINT="${1:?usage: detecter.sh <point>}"
mael_valider "$POINT" '^/[A-Za-z0-9._/-]*$' point
findmnt -kn "$POINT" || echo "${POINT} : pas de montage separe"
grep -E "[[:space:]]${POINT}[[:space:]]" /etc/fstab || echo "${POINT} absent de /etc/fstab"
