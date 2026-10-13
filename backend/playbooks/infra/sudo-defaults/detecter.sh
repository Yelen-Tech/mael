#!/usr/bin/env bash
# MAEL - playbook infra.sudo-defaults (detecter). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
OPTION="${1:?usage: detecter.sh <option>}"
mael_valider "$OPTION" '^[a-z_]+$' option
grep -HRs "^[[:space:]]*Defaults.*${OPTION}" /etc/sudoers /etc/sudoers.d/ || echo "${OPTION} non defini"
