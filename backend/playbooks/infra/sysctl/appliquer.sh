#!/usr/bin/env bash
# MAEL - playbook infra.sysctl (appliquer). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SIMULATION=0
[[ "${1:-}" == "--simulation" ]] && { SIMULATION=1; shift; }
CLE="${1:?usage: appliquer.sh [--simulation] <cle> <valeur>}"
VALEUR="${2:?valeur manquante}"
mael_valider "$CLE" '^[a-z0-9_.-]+$' cle
mael_valider "$VALEUR" '^[0-9 ]+$' valeur
MOTIF="^[[:space:]]*${CLE//./\\.}[[:space:]]*="
AUTRES=()
for f in /etc/sysctl.d/*.conf /run/sysctl.d/*.conf /usr/local/lib/sysctl.d/*.conf /etc/ufw/sysctl.conf; do
  [[ -f "$f" ]] || continue
  [[ "$(readlink -f "$f")" == "/etc/sysctl.conf" ]] && continue
  grep -qs "$MOTIF" "$f" && AUTRES+=("$f")
done

if [[ $SIMULATION -eq 1 ]]; then
  mael_simulation
  for f in "${AUTRES[@]}"; do echo "commenter dans $f : $(grep -s "$MOTIF" "$f" | tr '\n' ' ')"; done
  echo "ecrire dans /etc/sysctl.conf : ${CLE} = ${VALEUR}"
  echo "appliquer a chaud : sysctl -q -w ${CLE}=\"${VALEUR}\""
  exit 0
fi

mael_exiger_root
ETAT=$(mael_etat infra.sysctl "$CLE")
[[ -f "${ETAT}/avant_runtime" ]] || sysctl -n "$CLE" > "${ETAT}/avant_runtime" 2>/dev/null || true
for f in "${AUTRES[@]}"; do
  mael_sauvegarder "$ETAT" "$f"
  sed -i --follow-symlinks "s/${MOTIF}/# &/" "$f"
done
mael_sauvegarder "$ETAT" /etc/sysctl.conf
touch /etc/sysctl.conf
if grep -qs "$MOTIF" /etc/sysctl.conf; then
  sed -i "s/${MOTIF}.*/${CLE} = ${VALEUR}/" /etc/sysctl.conf
else
  printf '\n# MAEL (infra.sysctl)\n%s = %s\n' "$CLE" "$VALEUR" >> /etc/sysctl.conf
fi
if ! sysctl -q -w "${CLE}=${VALEUR}"; then
  echo "sysctl -w a echoue : retour arriere automatique." >&2
  "$(dirname "$0")/revenir.sh" "$CLE"
  exit 3
fi
echo "Applique : ${CLE} = ${VALEUR} (actif et persistant)."
