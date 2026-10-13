#!/usr/bin/env bash
# MAEL - playbook infra.audit-regles (detecter). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
REGLES="${1:?usage: detecter.sh <regles>}"
mael_valider "$REGLES" '^-[wa] [A-Za-z0-9/_.,=!<>:-]+( [A-Za-z0-9/_.,=!<>:-]+)*( \| -[wa] [A-Za-z0-9/_.,=!<>:-]+( [A-Za-z0-9/_.,=!<>:-]+)*)*$' regles
auditctl -l 2>/dev/null | head -100 || echo "auditctl -l : droits root requis"
