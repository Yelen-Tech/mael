#!/usr/bin/env bash
# MAEL - playbook infra.fichiers-motif (verifier). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
DOSSIER="${1:?usage}"; REGEX="${2:?}"; NATURE="${3:?}"; VALEUR="${4:?}"; RECURSIF="${5:?}"
EXCLURE="${6:-}"
mael_valider "$DOSSIER" '^/[A-Za-z0-9._/+-]*$' dossier
mael_valider "$REGEX" '^[][A-Za-z0-9._/^$*+?|(){}~\\-]+$' regex
mael_valider "$EXCLURE" '^([][A-Za-z0-9._*?-]+(,[][A-Za-z0-9._*?-]+)*)?$' exclure
PROF=(); [[ "$RECURSIF" == non ]] && PROF=(-maxdepth 1)
EXC=(); IFS=',' read -ra MOTIFS <<< "$EXCLURE"
for m in "${MOTIFS[@]}"; do EXC+=(! -name "$m"); done
ecarts=0
while IFS= read -r f; do
  case "$NATURE" in
    droits) (( (8#$(stat -c %a "$f") & ~8#$VALEUR) != 0 )) && { echo "ecart : $f" >&2; ecarts=1; } ;;
    proprietaire) [[ "$(stat -c %U "$f")" != "$VALEUR" ]] && { echo "ecart : $f" >&2; ecarts=1; } ;;
    groupe) [[ "$(stat -c %G "$f")" != "$VALEUR" ]] && { echo "ecart : $f" >&2; ecarts=1; } ;;
  esac
done < <(find "$DOSSIER" "${PROF[@]}" -type f -regextype posix-extended -regex "$REGEX" "${EXC[@]}" 2>/dev/null)
[[ $ecarts -eq 0 ]] && { echo "Conforme."; exit 0; }
exit 1
