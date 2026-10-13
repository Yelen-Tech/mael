#!/usr/bin/env bash
# MAEL - playbook infra.grub-argument (detecter). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
ARG="${1:?usage: detecter.sh <argument>}"
mael_valider "$ARG" '^[A-Za-z0-9_.,=:-]+( [A-Za-z0-9_.,=:-]+)*$' argument
echo "en cours : $(cat /proc/cmdline)"
grep -E '^GRUB_CMDLINE_LINUX' /etc/default/grub || echo "GRUB_CMDLINE_LINUX absent"
