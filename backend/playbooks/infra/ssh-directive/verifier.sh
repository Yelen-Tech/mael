#!/usr/bin/env bash
# MAEL - playbook infra.ssh-directive (verifier). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
DIRECTIVE="${1:?usage: verifier.sh <directive> <valeur>}"
VALEUR="${2:?valeur manquante}"
mael_valider "$DIRECTIVE" '^[A-Za-z]+$' directive
bas=$(printf '%s' "$DIRECTIVE" | tr 'A-Z' 'a-z')
lu=$(sshd -T 2>/dev/null | awk -v k="$bas" '$1 == k {sub(/^[^ ]+ /, ""); print; exit}')
if [[ -n "$lu" && "${lu,,}" == "${VALEUR,,}" ]]; then
  echo "Conforme : ${DIRECTIVE} ${lu}."; exit 0
fi
echo "Non conforme : ${DIRECTIVE} = ${lu:-? (sshd -T exige root)} (attendu ${VALEUR})." >&2
exit 1
