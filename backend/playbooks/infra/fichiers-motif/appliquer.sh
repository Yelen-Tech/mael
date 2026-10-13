#!/usr/bin/env bash
# MAEL - playbook infra.fichiers-motif (appliquer). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SIMULATION=0
[[ "${1:-}" == "--simulation" ]] && { SIMULATION=1; shift; }
DOSSIER="${1:?usage: appliquer.sh [--simulation] <dossier> <regex> <nature> <valeur> <recursif> [exclure]}"
REGEX="${2:?regex manquante}"; NATURE="${3:?nature}"; VALEUR="${4:?valeur}"; RECURSIF="${5:?recursif}"
EXCLURE="${6:-}"
mael_valider "$DOSSIER" '^/[A-Za-z0-9._/+-]*$' dossier
mael_valider "$REGEX" '^[][A-Za-z0-9._/^$*+?|(){}~\\-]+$' regex
mael_valider "$NATURE" '^(droits|proprietaire|groupe)$' nature
mael_valider "$VALEUR" '^([0-7]{3,4}|[a-z_][a-z0-9_-]*)$' valeur
mael_valider "$RECURSIF" '^(oui|non)$' recursif
mael_valider "$EXCLURE" '^([][A-Za-z0-9._*?-]+(,[][A-Za-z0-9._*?-]+)*)?$' exclure
PROF=(); [[ "$RECURSIF" == non ]] && PROF=(-maxdepth 1)
# Fichiers exclus par la source (noms, jokers de find -name) : ils ont leur
# propre exigence (ex. wtmp en 0664) et ne doivent jamais etre touches ici.
EXC=(); IFS=',' read -ra MOTIFS <<< "$EXCLURE"
for m in "${MOTIFS[@]}"; do EXC+=(! -name "$m"); done
mapfile -t CIBLES < <(find "$DOSSIER" "${PROF[@]}" -type f -regextype posix-extended -regex "$REGEX" "${EXC[@]}" 2>/dev/null)
A_FAIRE=()
for f in "${CIBLES[@]}"; do
  case "$NATURE" in
    droits) (( (8#$(stat -c %a "$f") & ~8#$VALEUR) != 0 )) && A_FAIRE+=("$f") ;;
    proprietaire) [[ "$(stat -c %U "$f")" != "$VALEUR" ]] && A_FAIRE+=("$f") ;;
    groupe) [[ "$(stat -c %G "$f")" != "$VALEUR" ]] && A_FAIRE+=("$f") ;;
  esac
done
CMD=$(case "$NATURE" in droits) echo chmod;; proprietaire) echo chown;; groupe) echo chgrp;; esac)
# Droits : on RETIRE les bits en trop, on n'en ajoute jamais (0604 -> 0600,
# pas 0640).
cible() {
  if [[ "$NATURE" == droits ]]; then
    printf '%04o' $(( 8#$(stat -c %a "$1") & 8#$VALEUR ))
  else
    printf '%s' "$VALEUR"
  fi
}
if [[ $SIMULATION -eq 1 ]]; then
  mael_simulation
  echo "${#CIBLES[@]} fichier(s) correspondant(s), ${#A_FAIRE[@]} a corriger :"
  for f in "${A_FAIRE[@]}"; do echo "  ${CMD} $(cible "$f") ${f} (actuel : $(stat -c '%a %U %G' "$f"))"; done
  exit 0
fi
[[ ${#A_FAIRE[@]} -eq 0 ]] && { echo "Deja conforme."; exit 0; }
mael_exiger_root
ETAT=$(mael_etat infra.fichiers-motif "${DOSSIER}:${REGEX}:${NATURE}")
for f in "${A_FAIRE[@]}"; do
  grep -qF -- " ${f}" "${ETAT}/avant" 2>/dev/null || stat -c '%a %U %G %n' "$f" >> "${ETAT}/avant"
  "$CMD" "$(cible "$f")" "$f"
done
echo "Applique : ${CMD} (${VALEUR}) sur ${#A_FAIRE[@]} fichier(s)."
