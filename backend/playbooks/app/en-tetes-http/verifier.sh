#!/usr/bin/env bash
# Confirme que le changement est bien en place. Code 0 = conforme.
set -euo pipefail
DOMAINE="${1:?usage: verifier.sh <domaine>}"

entetes=$(curl -sS -I -L --max-time 15 "https://${DOMAINE}")
manquants=()
for e in content-security-policy strict-transport-security x-frame-options \
         x-content-type-options referrer-policy; do
  grep -qi "^${e}:" <<<"$entetes" || manquants+=("$e")
done

if [[ ${#manquants[@]} -eq 0 ]]; then
  echo "Conforme : tous les en-tetes attendus sont presents."
  exit 0
fi
printf 'Non conforme. En-tetes manquants : %s\n' "${manquants[*]}" >&2
exit 1
