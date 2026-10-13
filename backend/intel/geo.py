"""Resolution adresse -> pays.

Interface remplacable, comme `brain.backends.LLMBackend` : le code appelant
ne sait pas d'ou vient la reponse. Trois resolveurs, essayes dans cet ordre :

  1. `TableLocale`   notre table `PlageGeo`, chargee depuis un jeu libre
  2. `DepuisIndicateur` le champ `pays` deja porte par nos indicateurs
  3. `Aucun`         rend une chaine vide, sans jamais echouer

Pourquoi un cache : le signal de voyage impossible consulte la geolocalisation
a chaque tentative de connexion, dans le plan bloquant. Une requete
d'encadrement sur 400 000 plages coute environ une milliseconde ; mise en
cache, la meme adresse ne coute plus rien.

Un client qui possede une licence MaxMind peut ecrire son propre resolveur
et le declarer dans RESOLVEURS -- rien d'autre ne change.
"""
from __future__ import annotations

import abc
import ipaddress

from django.core.cache import cache

DUREE_CACHE = 3600


class Resolveur(abc.ABC):
    nom: str = ""

    @abc.abstractmethod
    def pays(self, ip: str) -> str:
        """Code ISO deux lettres, ou chaine vide si inconnu."""


class TableLocale(Resolveur):
    nom = "table_locale"

    def pays(self, ip: str) -> str:
        from .models import PlageGeo

        try:
            adresse = ipaddress.ip_address(ip)
        except ValueError:
            return ""
        valeur = int(adresse)
        plage = (
            PlageGeo.objects.filter(
                version=adresse.version, debut__lte=valeur, fin__gte=valeur
            )
            .order_by("-debut")
            .values_list("pays", flat=True)
            .first()
        )
        return plage or ""


class DepuisIndicateur(Resolveur):
    """Repli : certains flux de renseignement portent deja le pays."""

    nom = "indicateur"

    def pays(self, ip: str) -> str:
        from modules.reputation.models import Indicateur

        return (
            Indicateur.objects.filter(type=Indicateur.Type.IP, valeur=ip)
            .values_list("pays", flat=True)
            .first()
            or ""
        )


class Aucun(Resolveur):
    nom = "aucun"

    def pays(self, ip: str) -> str:
        return ""


RESOLVEURS: list[Resolveur] = [TableLocale(), DepuisIndicateur(), Aucun()]


def pays_de(ip: str) -> str:
    """Pays d'une adresse. Ne leve jamais, rend "" si inconnu."""
    if not ip:
        return ""

    cle = f"geo:{ip}"
    en_cache = cache.get(cle)
    if en_cache is not None:
        return en_cache

    trouve = ""
    for resolveur in RESOLVEURS:
        try:
            trouve = resolveur.pays(ip)
        except Exception:  # noqa: BLE001 -- la geolocalisation n'est jamais critique
            continue
        if trouve:
            break

    cache.set(cle, trouve, DUREE_CACHE)
    return trouve


def couverture() -> dict:
    """Etat de la table, pour le diagnostic."""
    from .models import PlageGeo

    total = PlageGeo.objects.count()
    return {
        "plages": total,
        "pays_distincts": PlageGeo.objects.values("pays").distinct().count(),
        "chargee": total > 0,
    }
