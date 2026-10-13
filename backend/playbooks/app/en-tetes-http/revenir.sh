#!/usr/bin/env bash
# Retour arriere complet. Doit toujours reussir, meme applique deux fois.
set -euo pipefail
DOMAINE="${1:?usage: revenir.sh <domaine>}"
[[ $EUID -eq 0 ]] || { echo "Ce playbook exige les droits root." >&2; exit 2; }

CIBLE="/etc/nginx/snippets/sentinelle-entetes.conf"
SAUVEGARDE="/etc/nginx/snippets/.sentinelle-entetes.conf.avant"
CONFIG_SITE="/etc/nginx/sites-enabled/${DOMAINE}"

if [[ -f "${SAUVEGARDE}" ]]; then
  mv "${SAUVEGARDE}" "${CIBLE}"
else
  rm -f "${CIBLE}"
fi
[[ -f "${CONFIG_SITE}.sentinelle-avant" ]] && mv "${CONFIG_SITE}.sentinelle-avant" "${CONFIG_SITE}"

nginx -t && nginx -s reload
echo "Retour arriere effectue sur ${DOMAINE}."
