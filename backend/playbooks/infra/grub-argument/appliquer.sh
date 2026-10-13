#!/usr/bin/env bash
# MAEL - playbook infra.grub-argument (appliquer). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SIMULATION=0
[[ "${1:-}" == "--simulation" ]] && { SIMULATION=1; shift; }
ARG="${1:?usage: appliquer.sh [--simulation] <argument> <ajouter|retirer>}"
ACTION="${2:?action manquante}"
mael_valider "$ARG" '^[A-Za-z0-9_.,=:-]+( [A-Za-z0-9_.,=:-]+)*$' argument
mael_valider "$ACTION" '^(ajouter|retirer)$' action
F=/etc/default/grub
[[ -f "$F" ]] || { echo "Refus : ${F} absent (autre chargeur ?)." >&2; exit 5; }
ACTUEL=$(sed -n 's/^GRUB_CMDLINE_LINUX="\(.*\)"$/\1/p' "$F" | head -1)
NOUVEAU=" ${ACTUEL} "
for a in $ARG; do
  nom="${a%%=*}"
  NOUVEAU=$(printf '%s' "$NOUVEAU" | sed -E "s/ ${nom}(=[^ ]*)? / /g")
  [[ "$ACTION" == ajouter ]] && NOUVEAU="${NOUVEAU} ${a} "
done
NOUVEAU=$(echo $NOUVEAU)
if [[ $SIMULATION -eq 1 ]]; then
  mael_simulation
  echo "GRUB_CMDLINE_LINUX actuel  : \"${ACTUEL}\""
  echo "GRUB_CMDLINE_LINUX nouveau : \"${NOUVEAU}\""
  echo "puis : update-grub ; effet au prochain redemarrage"
  exit 0
fi
mael_exiger_root
ETAT=$(mael_etat infra.grub-argument "$ARG")
mael_sauvegarder "$ETAT" "$F"
if grep -q '^GRUB_CMDLINE_LINUX=' "$F"; then
  sed -i "s|^GRUB_CMDLINE_LINUX=.*|GRUB_CMDLINE_LINUX=\"${NOUVEAU}\"|" "$F"
else
  printf 'GRUB_CMDLINE_LINUX="%s"\n' "$NOUVEAU" >> "$F"
fi
if ! (update-grub 2>/dev/null || grub-mkconfig -o /boot/grub/grub.cfg); then
  echo "Regeneration de GRUB impossible : retour arriere." >&2
  "$(dirname "$0")/revenir.sh" "$ARG"
  exit 3
fi
echo "Applique (${ACTION}) : ${ARG} ; redemarrage necessaire."
