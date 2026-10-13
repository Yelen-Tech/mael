#!/usr/bin/env bash
# MAEL - playbook infra.sysctl (verifier). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
CLE="${1:?usage: verifier.sh <cle> <valeur>}"
VALEUR="${2:?valeur manquante}"
mael_valider "$CLE" '^[a-z0-9_.-]+$' cle
actif=$(sysctl -n "$CLE" 2>/dev/null | tr -s '[:space:]' ' ' | sed 's/ $//')
voulu=$(printf '%s' "$VALEUR" | tr -s '[:space:]' ' ')
MOTIF="^[[:space:]]*${CLE//./\\.}[[:space:]]*="
if [[ "$actif" == "$voulu" ]] && grep -qs "$MOTIF" /etc/sysctl.conf; then
  echo "Conforme : ${CLE} = ${actif}."
  exit 0
fi
echo "Non conforme : ${CLE} = ${actif:-?} (attendu ${voulu})." >&2
exit 1
