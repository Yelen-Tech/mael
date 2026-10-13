#!/usr/bin/env bash
# MAEL - playbook infra.fichiers-motif (detecter). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
DOSSIER="${1:?usage: detecter.sh <dossier>}"
mael_valider "$DOSSIER" '^/[A-Za-z0-9._/+-]*$' dossier
find "$DOSSIER" -maxdepth 1 -printf '%m %u %g %p\n' 2>/dev/null | head -50
