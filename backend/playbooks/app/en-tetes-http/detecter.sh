#!/usr/bin/env bash
# Constate l'etat actuel. NE MODIFIE RIEN. Sortie JSON sur stdout.
set -euo pipefail
DOMAINE="${1:?usage: detecter.sh <domaine>}"

entetes=$(curl -sS -I -L --max-time 15 "https://${DOMAINE}" || true)
present () { grep -qi "^$1:" <<<"$entetes" && echo true || echo false; }

cat <<JSON
{
  "playbook": "app.en-tetes-http",
  "cible": "${DOMAINE}",
  "etat": {
    "content_security_policy":   $(present "content-security-policy"),
    "strict_transport_security": $(present "strict-transport-security"),
    "x_frame_options":           $(present "x-frame-options"),
    "x_content_type_options":    $(present "x-content-type-options"),
    "referrer_policy":           $(present "referrer-policy"),
    "server_divulgue":           $(present "server")
  }
}
JSON
