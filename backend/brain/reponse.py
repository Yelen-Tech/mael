"""Lire ce que le modèle a répondu.

Un petit modèle rate les appels d'outils natifs dès que le prompt grossit (il
rend une réponse vide). On lui demande donc un bloc ```bash, qui s'extrait de
façon déterministe.

Cette lecture vit ici, et pas dans le terminal, parce que le banc de mesure
doit extraire **exactement** comme le terminal : une mesure faite avec un autre
extracteur ne mesure pas le produit.
"""
from __future__ import annotations

import re

_BLOC = re.compile(r"```(?:bash|sh|shell)?\s*\n(.+?)```", re.DOTALL)


def extraire_commande(texte: str) -> str | None:
    """La première commande d'un bloc ```bash, ou None.

    Les commentaires et les lignes vides sont sautés : un modèle bavard met
    souvent une explication en tête de bloc."""
    m = _BLOC.search(texte or "")
    if not m:
        return None
    lignes = [l for l in m.group(1).strip().splitlines()
              if l.strip() and not l.strip().startswith("#")]
    return lignes[0].strip() if lignes else None
