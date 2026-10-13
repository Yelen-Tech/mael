#!/usr/bin/env bash
# MAEL - playbook infra.audit-regles (revenir). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
REGLES="${1:?usage: revenir.sh <regles>}"
mael_valider "$REGLES" '^-[wa] [A-Za-z0-9/_.,=!<>:-]+( [A-Za-z0-9/_.,=!<>:-]+)*( \| -[wa] [A-Za-z0-9/_.,=!<>:-]+( [A-Za-z0-9/_.,=!<>:-]+)*)*$' regles
mael_exiger_root
ETAT=$(mael_chemin_etat infra.audit-regles "$REGLES")
[[ -d "$ETAT" ]] || { echo "Rien a revenir."; exit 0; }
mael_restaurer "$ETAT"
rm -rf -- "$ETAT"
augenrules --load || echo "Rechargement impossible (redemarrer si -e 2)." >&2
echo "Retour arriere effectue (regles d'audit)."
