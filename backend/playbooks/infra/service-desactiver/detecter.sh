#!/usr/bin/env bash
# MAEL - playbook infra.service-desactiver (detecter). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SERVICE="${1:?usage: detecter.sh <service>}"
mael_valider "$SERVICE" '^[A-Za-z0-9@_.-]+$' service
U="${SERVICE}"; [[ "$U" == *.timer || "$U" == *.socket ]] || U="${U}.service"
echo "demarrage : $(systemctl is-enabled "$U" 2>/dev/null || echo absent)"
echo "execution : $(systemctl is-active "$U" 2>/dev/null || true)"
