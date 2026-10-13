"""Pseudonymisation des identifiants.

Regle absolue de ce module : **Sentinelle ne stocke jamais l'identifiant en
clair.** On analyse les connexions de nos clients ; si nous sommes compromis,
nous ne devons pas livrer la liste de leurs utilisateurs.

Chaque identifiant est transforme en empreinte HMAC-SHA256 avec :
  - un secret serveur (jamais en base, jamais dans le depot)
  - un sel propre a l'organisation

Le sel par organisation empeche deux choses : recouper les utilisateurs d'un
client avec ceux d'un autre, et reutiliser une table precalculee d'un client
sur un autre.

Limite assumee, a dire au client : l'empreinte est deterministe, donc si un
attaquant obtient le secret serveur *et* le sel, il peut tester des
identifiants qu'il devine deja. Elle protege contre le vol de la base, pas
contre une devinette ciblee. C'est le compromis necessaire pour pouvoir
compter les tentatives par compte.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from django.conf import settings


def secret_serveur() -> bytes:
    """Derive du SECRET_KEY. A isoler dans un coffre en production."""
    return hashlib.sha256(
        b"sentinelle-authguard-v1|" + settings.SECRET_KEY.encode()
    ).digest()


def nouveau_sel() -> str:
    return secrets.token_hex(16)


def empreinte(identifiant: str, sel: str) -> str:
    """Empreinte stable d'un identifiant, pour une organisation donnee."""
    normalise = identifiant.strip().lower().encode()
    return hmac.new(
        secret_serveur(), sel.encode() + b"|" + normalise, hashlib.sha256
    ).hexdigest()


def empreinte_appareil(user_agent: str, sel: str) -> str:
    """Empreinte grossiere d'un appareil, a partir du seul agent utilisateur.

    Volontairement grossiere : on veut reconnaitre « meme genre d'appareil »,
    pas pister finement un individu. Une mise a jour de navigateur ne doit
    pas declencher une alerte.
    """
    ua = (user_agent or "").lower()
    famille = "inconnu"
    for marqueur in ("android", "iphone", "ipad", "windows", "macintosh", "linux"):
        if marqueur in ua:
            famille = marqueur
            break
    moteur = "inconnu"
    for marqueur in ("firefox", "edg/", "chrome", "safari", "opr/", "curl", "python"):
        if marqueur in ua:
            moteur = marqueur.rstrip("/")
            break
    brut = f"{famille}|{moteur}"
    return hmac.new(secret_serveur(), sel.encode() + b"|ua|" + brut.encode(),
                    hashlib.sha256).hexdigest()[:16]
