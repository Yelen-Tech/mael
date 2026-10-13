#!/usr/bin/env bash
# MAEL - playbook infra.sudo-defaults (appliquer). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SIMULATION=0
[[ "${1:-}" == "--simulation" ]] && { SIMULATION=1; shift; }
OPTION="${1:?usage: appliquer.sh [--simulation] <option> [valeur]}"
VALEUR="${2-}"
mael_valider "$OPTION" '^[a-z_]+$' option
mael_valider "$VALEUR" '^[A-Za-z0-9._/-]*$' valeur
CIBLE=/etc/sudoers.d/60-mael
LIGNE="Defaults ${OPTION}${VALEUR:+=${VALEUR}}"
if [[ $SIMULATION -eq 1 ]]; then
  mael_simulation
  echo "ecrire dans ${CIBLE} : ${LIGNE}"
  echo "puis : visudo -c (retour arriere si invalide)"
  exit 0
fi
mael_exiger_root
ETAT=$(mael_etat infra.sudo-defaults "$OPTION")
mael_sauvegarder "$ETAT" "$CIBLE"
touch "$CIBLE"
chmod 0440 "$CIBLE"
sed -i "/^Defaults[[:space:]]\+!\?${OPTION}\([=[:space:]]\|$\)/d" "$CIBLE"
printf '%s\n' "$LIGNE" >> "$CIBLE"
if ! visudo -qc >/dev/null; then
  echo "sudoers invalide : retour arriere automatique." >&2
  "$(dirname "$0")/revenir.sh" "$OPTION"
  exit 3
fi
echo "Applique : ${LIGNE} (${CIBLE})."
