#!/usr/bin/env bash
# MAEL - playbook infra.cle-valeur (appliquer). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SIMULATION=0
[[ "${1:-}" == "--simulation" ]] && { SIMULATION=1; shift; }
FICHIER="${1:?usage: appliquer.sh [--simulation] <fichier> <cle> <valeur> <format>}"
CLE="${2:?cle manquante}"
VALEUR="${3-}"
FORMAT="${4:?format manquant}"
mael_valider "$FICHIER" '^/(etc|root)/[A-Za-z0-9._/-]+$' fichier
mael_valider "$CLE" '^\$?[A-Za-z_][A-Za-z0-9_-]*$' cle
mael_valider "$VALEUR" "^[A-Za-z0-9@,._:/+=|-]*( [A-Za-z0-9@,._:/+=|-]+)*$" valeur
mael_valider "$FORMAT" '^(egal|egal_espaces|espace|cle_seule|readonly)$' format
CLE_RE="${CLE//\$/\\\$}"
MOTIF="^[[:space:]]*(export[[:space:]]+|readonly[[:space:]]+)?${CLE_RE}([[:space:]]|=|$)"
case "$FORMAT" in
  egal) LIGNE="${CLE}=${VALEUR}" ;;
  egal_espaces) LIGNE="${CLE} = ${VALEUR}" ;;
  espace) LIGNE="${CLE} ${VALEUR}" ;;
  cle_seule) LIGNE="${CLE}" ;;
  readonly) LIGNE="readonly ${CLE}=${VALEUR}" ;;
esac
if [[ $SIMULATION -eq 1 ]]; then
  mael_simulation
  echo "fichier : ${FICHIER}"
  grep -Es "$MOTIF" "$FICHIER" | sed 's/^/remplacer : /' || true
  echo "ligne voulue : ${LIGNE}"
  [[ "$FORMAT" == readonly ]] && echo "et : export ${CLE}"
  exit 0
fi
mael_exiger_root
ETAT=$(mael_etat infra.cle-valeur "${FICHIER}:${CLE}")
mael_sauvegarder "$ETAT" "$FICHIER"
mkdir -p "$(dirname "$FICHIER")"
touch "$FICHIER"
if grep -Eqs "$MOTIF" "$FICHIER"; then
  # remplace chaque ligne active de CLE (comme bash_replace_or_append)
  awk -v motif="$MOTIF" -v ligne="$LIGNE" '$0 ~ motif && !fait {print ligne; fait=1; next} $0 ~ motif {next} {print}' "$FICHIER" > "${FICHIER}.mael"
  cat "${FICHIER}.mael" > "$FICHIER" && rm -f "${FICHIER}.mael"
else
  printf '\n# MAEL (infra.cle-valeur)\n%s\n' "$LIGNE" >> "$FICHIER"
fi
if [[ "$FORMAT" == readonly ]] && ! grep -Eqs "^[[:space:]]*export[[:space:]]+${CLE_RE}[[:space:]]*$" "$FICHIER"; then
  printf 'export %s\n' "$CLE" >> "$FICHIER"
fi
echo "Applique : ${LIGNE} (${FICHIER})."
