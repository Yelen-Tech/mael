#!/usr/bin/env bash
# MAEL - playbook infra.audit-regles (verifier). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
REGLES="${1:?usage: verifier.sh <regles>}"
mael_valider "$REGLES" '^-[wa] [A-Za-z0-9/_.,=!<>:-]+( [A-Za-z0-9/_.,=!<>:-]+)*( \| -[wa] [A-Za-z0-9/_.,=!<>:-]+( [A-Za-z0-9/_.,=!<>:-]+)*)*$' regles
IFS='|' read -r -a LISTE <<<"$REGLES"
manque=0
for r in "${LISTE[@]}"; do
  r=$(echo "$r" | sed 's/^ *//;s/ *$//')
  grep -qxF -- "$r" /etc/audit/rules.d/60-mael.rules 2>/dev/null || { echo "absente : $r" >&2; manque=1; }
done
[[ $manque -eq 0 ]] && { echo "Conforme : regles persistantes presentes."; exit 0; }
exit 1
