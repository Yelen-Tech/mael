#!/usr/bin/env bash
# MAEL - playbook infra.module-interdit (detecter). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
MODULE="${1:?usage: detecter.sh <module>}"
mael_valider "$MODULE" '^[a-z0-9_-]+$' module
grep -Hs "$MODULE" /etc/modprobe.d/*.conf || echo "aucune interdiction"
lsmod | grep -w "$MODULE" || echo "non charge"
