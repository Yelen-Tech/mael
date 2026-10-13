#!/usr/bin/env bash
# MAEL - playbook infra.ssh-directive (appliquer). Voir manifest.yaml.
set -euo pipefail
source "$(dirname "$0")/../../_commun/mael.sh"
SIMULATION=0
[[ "${1:-}" == "--simulation" ]] && { SIMULATION=1; shift; }
DIRECTIVE="${1:?usage: appliquer.sh [--simulation] <directive> <valeur>}"
VALEUR="${2:?valeur manquante}"
mael_valider "$DIRECTIVE" '^[A-Za-z]+$' directive
mael_valider "$VALEUR" '^[A-Za-z0-9@,._:/+-]+( [A-Za-z0-9@,._:/+-]+)*$' valeur
PRINCIPAL=/etc/ssh/sshd_config
DOSSIER=/etc/ssh/sshd_config.d
CIBLE="${DOSSIER}/00-mael-durcissement.conf"
MOTIF="^[[:space:]]*${DIRECTIVE}[[:space:]]"
if ! grep -qiE '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/' "$PRINCIPAL" 2>/dev/null; then
  echo "Refus : ${PRINCIPAL} n'inclut pas ${DOSSIER}/*.conf ; correction a faire a la main." >&2
  exit 5
fi
A_NETTOYER=$(grep -lis "$MOTIF" "$PRINCIPAL" "$DOSSIER"/*.conf 2>/dev/null | grep -vx "$CIBLE" || true)
if [[ $SIMULATION -eq 1 ]]; then
  mael_simulation
  for f in $A_NETTOYER; do echo "retirer de $f : $(grep -is "$MOTIF" "$f" | tr '\n' ' ')"; done
  echo "ecrire dans ${CIBLE} : ${DIRECTIVE} ${VALEUR}"
  echo "puis : sshd -t && systemctl reload ssh (retour arriere si sshd -t echoue)"
  exit 0
fi
mael_exiger_root
ETAT=$(mael_etat infra.ssh-directive "$DIRECTIVE")
for f in $A_NETTOYER; do
  mael_sauvegarder "$ETAT" "$f"
  sed -i "/${MOTIF}/Id" "$f"
done
mael_sauvegarder "$ETAT" "$CIBLE"
mkdir -p "$DOSSIER"
touch "$CIBLE"
chmod 0600 "$CIBLE"
sed -i "/${MOTIF}/Id" "$CIBLE"
{ printf '%s %s\n' "$DIRECTIVE" "$VALEUR"; cat "$CIBLE"; } > "${CIBLE}.mael" && mv "${CIBLE}.mael" "$CIBLE"
chmod 0600 "$CIBLE"
if ! sshd -t; then
  echo "Configuration sshd invalide : retour arriere automatique." >&2
  "$(dirname "$0")/revenir.sh" "$DIRECTIVE"
  exit 3
fi
systemctl reload ssh 2>/dev/null || systemctl reload sshd
echo "Applique : ${DIRECTIVE} ${VALEUR} (${CIBLE})."
