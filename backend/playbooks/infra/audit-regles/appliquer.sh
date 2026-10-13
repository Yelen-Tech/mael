#!/usr/bin/env bash
# MAEL - playbook infra.audit-regles (appliquer). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SIMULATION=0
[[ "${1:-}" == "--simulation" ]] && { SIMULATION=1; shift; }
REGLES="${1:?usage: appliquer.sh [--simulation] <regles>}"
mael_valider "$REGLES" '^-[wa] [A-Za-z0-9/_.,=!<>:-]+( [A-Za-z0-9/_.,=!<>:-]+)*( \| -[wa] [A-Za-z0-9/_.,=!<>:-]+( [A-Za-z0-9/_.,=!<>:-]+)*)*$' regles
CIBLE=/etc/audit/rules.d/60-mael.rules
IFS='|' read -r -a LISTE <<<"$REGLES"
if [[ $SIMULATION -eq 1 ]]; then
  mael_simulation
  for r in "${LISTE[@]}"; do echo "ajouter a ${CIBLE} : $(echo "$r" | sed 's/^ *//;s/ *$//')"; done
  echo "puis : augenrules --load"
  exit 0
fi
mael_exiger_root
command -v augenrules >/dev/null || { echo "auditd absent (augenrules introuvable)." >&2; exit 4; }
ETAT=$(mael_etat infra.audit-regles "$REGLES")
mael_sauvegarder "$ETAT" "$CIBLE"
touch "$CIBLE"
chmod 0640 "$CIBLE"
for r in "${LISTE[@]}"; do
  r=$(echo "$r" | sed 's/^ *//;s/ *$//')
  grep -qxF -- "$r" "$CIBLE" || printf '%s\n' "$r" >> "$CIBLE"
done
if ! augenrules --load; then
  echo "Chargement des regles impossible (configuration immuable -e 2 ?) : retour arriere." >&2
  "$(dirname "$0")/revenir.sh" "$REGLES"
  exit 3
fi
echo "Applique : ${#LISTE[@]} regle(s) dans ${CIBLE}."
