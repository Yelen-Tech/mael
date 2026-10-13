#!/usr/bin/env bash
# MAEL - playbook infra.fichier-existence (detecter). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
CHEMIN="${1:?usage: detecter.sh <chemin>}"
mael_valider "$CHEMIN" '^/[A-Za-z0-9._/+-]+$' chemin
stat -c '%a %U %G %n' "$CHEMIN" 2>/dev/null || echo "${CHEMIN} absent"
