#!/usr/bin/env bash
# MAEL - playbook infra.sysctl (detecter). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
CLE="${1:?usage: detecter.sh <cle>}"
mael_valider "$CLE" '^[a-z0-9_.-]+$' cle
echo "actif      : $(sysctl -n "$CLE" 2>/dev/null || echo inconnu)"
MOTIF="^[[:space:]]*${CLE//./\\.}[[:space:]]*="
grep -Hs "$MOTIF" /etc/sysctl.conf /etc/sysctl.d/*.conf /run/sysctl.d/*.conf \
  /usr/local/lib/sysctl.d/*.conf /etc/ufw/sysctl.conf || echo "persistant : aucune definition"
