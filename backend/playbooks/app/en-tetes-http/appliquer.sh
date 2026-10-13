#!/usr/bin/env bash
# Idempotent. --simulation affiche le diff sans rien ecrire.
set -euo pipefail

SIMULATION=0
[[ "${1:-}" == "--simulation" ]] && { SIMULATION=1; shift; }

DOMAINE="${1:?usage: appliquer.sh [--simulation] <domaine> [csp] [duree_hsts]}"
CSP="${2:-default-src 'self'; frame-ancestors 'none'}"
HSTS="${3:-31536000}"

CIBLE="/etc/nginx/snippets/sentinelle-entetes.conf"
SAUVEGARDE="/etc/nginx/snippets/.sentinelle-entetes.conf.avant"

BLOC=$(cat <<CONF
# Genere par Sentinelle - playbook app.en-tetes-http
# Retour arriere : revenir.sh ${DOMAINE}
add_header Content-Security-Policy "${CSP}" always;
add_header Strict-Transport-Security "max-age=${HSTS}; includeSubDomains" always;
add_header X-Frame-Options "DENY" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
server_tokens off;
CONF
)

if [[ $SIMULATION -eq 1 ]]; then
  echo "--- SIMULATION : aucune ecriture ---"
  echo "Fichier cible : ${CIBLE}"
  echo "${BLOC}"
  echo "--- puis : nginx -t && nginx -s reload ---"
  exit 0
fi

[[ $EUID -eq 0 ]] || { echo "Ce playbook exige les droits root." >&2; exit 2; }

mkdir -p "$(dirname "${CIBLE}")"
[[ -f "${CIBLE}" ]] && cp -p "${CIBLE}" "${SAUVEGARDE}"
printf '%s\n' "${BLOC}" > "${CIBLE}"

# Le bloc doit etre inclus dans le server{} concerne.
CONFIG_SITE="/etc/nginx/sites-enabled/${DOMAINE}"
if [[ -f "${CONFIG_SITE}" ]] && ! grep -q "sentinelle-entetes.conf" "${CONFIG_SITE}"; then
  cp -p "${CONFIG_SITE}" "${CONFIG_SITE}.sentinelle-avant"
  sed -i "0,/server\s*{/s//server {\n    include snippets\/sentinelle-entetes.conf;/" \
    "${CONFIG_SITE}"
fi

# On ne recharge que si la configuration est valide. Sinon retour arriere immediat.
if ! nginx -t 2>&1; then
  echo "Configuration invalide : retour arriere automatique." >&2
  [[ -f "${SAUVEGARDE}" ]] && mv "${SAUVEGARDE}" "${CIBLE}" || rm -f "${CIBLE}"
  [[ -f "${CONFIG_SITE}.sentinelle-avant" ]] && mv "${CONFIG_SITE}.sentinelle-avant" "${CONFIG_SITE}"
  nginx -t && nginx -s reload
  exit 3
fi

nginx -s reload
echo "Applique sur ${DOMAINE}."
