#!/usr/bin/env bash
# MAEL - playbook infra.ssh-directive (detecter). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
DIRECTIVE="${1:?usage: detecter.sh <directive>}"
mael_valider "$DIRECTIVE" '^[A-Za-z]+$' directive
grep -HRis "^[[:space:]]*${DIRECTIVE}[[:space:]]" /etc/ssh/sshd_config /etc/ssh/sshd_config.d/ || echo "non definie (defaut)"
sshd -T 2>/dev/null | grep -i "^${DIRECTIVE} " || echo "sshd -T : droits root requis"
