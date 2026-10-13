#!/usr/bin/env bash
# MAEL - playbook infra.fichiers-motif (revenir). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
DOSSIER="${1:?usage: revenir.sh <dossier> <regex> <nature>}"
REGEX="${2:?}"; NATURE="${3:?}"
mael_valider "$DOSSIER" '^/[A-Za-z0-9._/+-]*$' dossier
mael_valider "$REGEX" '^[][A-Za-z0-9._/^$*+?|(){}~\\-]+$' regex
mael_valider "$NATURE" '^(droits|proprietaire|groupe)$' nature
mael_exiger_root
ETAT=$(mael_chemin_etat infra.fichiers-motif "${DOSSIER}:${REGEX}:${NATURE}")
[[ -f "${ETAT}/avant" ]] || { echo "Rien a revenir."; exit 0; }
while read -r mode proprio groupe chemin; do
  [[ -e "$chemin" ]] || continue
  chmod "$mode" "$chemin"; chown "$proprio" "$chemin"; chgrp "$groupe" "$chemin"
done < "${ETAT}/avant"
rm -rf -- "$ETAT"
echo "Retour arriere effectue."
