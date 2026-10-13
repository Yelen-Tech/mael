#!/usr/bin/env bash
# MAEL - playbook infra.cle-valeur (verifier). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
FICHIER="${1:?usage: verifier.sh <fichier> <cle> <valeur> <format>}"
CLE="${2:?cle manquante}"
VALEUR="${3-}"
FORMAT="${4:?format manquant}"
mael_valider "$FICHIER" '^/(etc|root)/[A-Za-z0-9._/-]+$' fichier
mael_valider "$CLE" '^\$?[A-Za-z_][A-Za-z0-9_-]*$' cle
case "$FORMAT" in
  egal) LIGNE="${CLE}=${VALEUR}" ;;
  egal_espaces) LIGNE="${CLE} = ${VALEUR}" ;;
  espace) LIGNE="${CLE} ${VALEUR}" ;;
  cle_seule) LIGNE="${CLE}" ;;
  readonly) LIGNE="readonly ${CLE}=${VALEUR}" ;;
esac
if grep -qxF "$LIGNE" "$FICHIER" 2>/dev/null; then
  echo "Conforme : ${LIGNE}."; exit 0
fi
echo "Non conforme : « ${LIGNE} » absent de ${FICHIER}." >&2
exit 1
