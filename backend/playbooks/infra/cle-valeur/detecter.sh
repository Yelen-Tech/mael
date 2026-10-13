#!/usr/bin/env bash
# MAEL - playbook infra.cle-valeur (detecter). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
FICHIER="${1:?usage: detecter.sh <fichier>}"
mael_valider "$FICHIER" '^/(etc|root)/[A-Za-z0-9._/-]+$' fichier
[[ -f "$FICHIER" ]] || { echo "${FICHIER} absent"; exit 0; }
grep -v '^[[:space:]]*#' "$FICHIER" | grep -v '^[[:space:]]*$' | head -50
