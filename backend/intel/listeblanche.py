"""Liste blanche : ce qu'on ne signalera jamais comme malveillant.

Pourquoi ce fichier existe : un faux positif sur 8.8.8.8 fait couper le DNS
d'un client. Un faux positif sur les plages de Cloudflare ou de Microsoft
lui coupe son site ou sa messagerie. Un produit de securite qui casse la
production du client est pire qu'aucun produit.

Les flux publics contiennent regulierement ce genre d'entrees -- une IP de
resolveur public signalee parce qu'elle apparait dans une requete d'attaque,
un domaine d'hebergeur signale pour un seul de ses clients. La liste blanche
est le dernier filet avant le verdict.

Elle prime sur toutes les sources : une valeur en liste blanche recoit le
verdict « benin », quel que soit son score agrege.
"""
from __future__ import annotations

import ipaddress
from functools import lru_cache

# --- Resolveurs DNS publics : les bloquer coupe Internet au client ---------
RESOLVEURS = [
    "8.8.8.8", "8.8.4.4",              # Google
    "1.1.1.1", "1.0.0.1",              # Cloudflare
    "9.9.9.9", "149.112.112.112",      # Quad9
    "208.67.222.222", "208.67.220.220",  # OpenDNS
    "64.6.64.6", "64.6.65.6",          # Verisign
]

# --- Plages d'infrastructure critique -------------------------------------
# Volontairement restreint : on ne blanchit que ce dont le blocage casse
# immediatement un client. Ce n'est pas une liste d'hebergeurs « de confiance ».
PLAGES = [
    "127.0.0.0/8",        # boucle locale
    "10.0.0.0/8",         # prive
    "172.16.0.0/12",      # prive
    "192.168.0.0/16",     # prive
    "169.254.0.0/16",     # lien-local
    "224.0.0.0/4",        # multidiffusion
    "::1/128",
    "fc00::/7",
    "fe80::/10",
]

# --- Domaines dont le blocage casse un service courant --------------------
DOMAINES = [
    "google.com", "gstatic.com", "googleapis.com", "gmail.com",
    "microsoft.com", "microsoftonline.com", "office.com", "windowsupdate.com",
    "cloudflare.com", "cloudflare-dns.com",
    "apple.com", "icloud.com",
    "amazonaws.com", "cloudfront.net",
    "github.com", "githubusercontent.com",
    "mozilla.org", "letsencrypt.org",
    "whatsapp.com", "facebook.com", "fbcdn.net",
    "orange.bf", "moov-africa.bf", "telecel.bf",  # operateurs locaux
]


@lru_cache(maxsize=1)
def _plages_compilees():
    return [ipaddress.ip_network(p) for p in PLAGES]


@lru_cache(maxsize=1)
def _resolveurs():
    return set(RESOLVEURS)


def est_blanchi(type_indicateur: str, valeur: str) -> bool:
    """Vrai si cette valeur ne doit jamais etre signalee."""
    valeur = valeur.strip().lower()

    if type_indicateur == "ip":
        if valeur in _resolveurs():
            return True
        try:
            adresse = ipaddress.ip_address(valeur)
        except ValueError:
            return False
        return any(adresse in plage for plage in _plages_compilees())

    if type_indicateur == "domaine":
        return any(valeur == d or valeur.endswith("." + d) for d in DOMAINES)

    # Une URL complete n'est JAMAIS blanchie, meme sur un domaine protege.
    #
    # Constate sur les donnees reelles d'URLhaus : les attaquants hebergent
    # massivement leurs charges sur drive.google.com et raw.githubusercontent.com.
    # Bloquer « https://drive.google.com/uc?id=<charge> » ne casse rien chez le
    # client ; bloquer « drive.google.com » lui coupe son Drive. La granularite
    # de l'indicateur decide : le domaine est protege, l'URL precise ne l'est pas.
    return False


def raison(type_indicateur: str, valeur: str) -> str:
    """Message d'explication, pour la piste d'audit et le tableau de bord."""
    if not est_blanchi(type_indicateur, valeur):
        return ""
    if type_indicateur == "ip" and valeur in _resolveurs():
        return "resolveur DNS public : blocage interdit"
    if type_indicateur == "ip":
        return "plage reservee ou privee"
    return "domaine d'infrastructure critique"
