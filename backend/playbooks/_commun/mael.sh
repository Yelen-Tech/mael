#!/usr/bin/env bash
# Bibliotheque commune des playbooks MAEL -- sourcee, jamais executee seule.
#
# Regles communes (README, « Les playbooks ») :
#   detecter.sh  constate, ne modifie rien
#   appliquer.sh idempotent, --simulation, retour arriere auto si invalide
#   verifier.sh  code 0 = conforme
#   revenir.sh   retour arriere complet, rejouable
#
# L'etat avant correction est garde dans $MAEL_ETAT_RACINE/<playbook>/<cle>/ :
# fichiers sauvegardes (arborescence d'origine sous sauvegarde/), fichiers
# crees (liste crees), valeurs precedentes (fichiers texte). revenir.sh le
# relit puis l'efface.

MAEL_ETAT_RACINE="${MAEL_ETAT_RACINE:-/var/lib/mael/playbooks}"

mael_exiger_root() {
  [[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Ce playbook exige les droits root." >&2; exit 2; }
}

# mael_valider VALEUR MOTIF NOM : refuse tout parametre hors motif (pas
# d'espace de commande possible : les scripts ne font jamais d'eval).
mael_valider() {
  [[ "$1" =~ $2 ]] || { echo "Parametre $3 invalide : '$1'" >&2; exit 64; }
}

# mael_etat PLAYBOOK CLE -> repertoire d'etat (cree, 0700)
mael_etat() {
  local cle
  cle=$(printf '%s' "$2" | tr -c 'A-Za-z0-9._-' '_')
  local d="${MAEL_ETAT_RACINE}/$1/${cle}"
  mkdir -p "$d"
  chmod 0700 "$d"
  printf '%s\n' "$d"
}

# mael_chemin_etat PLAYBOOK CLE -> chemin, sans rien creer (revenir.sh)
mael_chemin_etat() {
  local cle
  cle=$(printf '%s' "$2" | tr -c 'A-Za-z0-9._-' '_')
  printf '%s\n' "${MAEL_ETAT_RACINE}/$1/${cle}"
}

# mael_sauvegarder ETAT FICHIER : garde la version d'origine une seule fois
# (une 2e application ne doit pas ecraser l'original).
mael_sauvegarder() {
  local etat="$1" f="$2"
  if [[ -e "${etat}/sauvegarde${f}" ]] || grep -qxF "$f" "${etat}/crees" 2>/dev/null; then
    return 0
  fi
  if [[ -e "$f" ]]; then
    mkdir -p "${etat}/sauvegarde$(dirname "$f")"
    cp -p "$f" "${etat}/sauvegarde${f}"
  else
    printf '%s\n' "$f" >> "${etat}/crees"
  fi
}

# mael_restaurer ETAT : remet les fichiers sauvegardes, supprime les crees.
mael_restaurer() {
  local etat="$1" f
  if [[ -d "${etat}/sauvegarde" ]]; then
    while IFS= read -r -d '' f; do
      cp -p "$f" "${f#"${etat}/sauvegarde"}"
    done < <(find "${etat}/sauvegarde" -type f -print0)
  fi
  if [[ -f "${etat}/crees" ]]; then
    while IFS= read -r f; do
      [[ -n "$f" ]] && rm -f -- "$f"
    done < "${etat}/crees"
  fi
}

mael_simulation() {
  echo "--- SIMULATION : aucune ecriture ---"
}
