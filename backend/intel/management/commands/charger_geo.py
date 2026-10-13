"""python manage.py charger_geo [--ipv6] [--url URL] [--etat]

Charge la table adresse -> pays, utilisee par le signal de voyage impossible.

Source par defaut : le projet ip-location-db, jeu « geo-whois-asn-country »,
sous licence libre (CC0). Derive des enregistrements WHOIS et des annonces
BGP, precis au pays. Format CSV : debut,fin,pays -- les bornes sont deja des
entiers, ce qui correspond exactement a notre stockage.

Licence libre = redistribuable, donc utilisable dans le paquet « sur site »
telecharge par un client. C'est ce qui l'a fait preferer a MaxMind.
"""
import csv
import io

import httpx
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from intel.geo import couverture
from intel.models import PlageGeo

BASE = "https://cdn.jsdelivr.net/npm/@ip-location-db/geo-whois-asn-country/"
URL_IPV4 = BASE + "geo-whois-asn-country-ipv4-num.csv"
URL_IPV6 = BASE + "geo-whois-asn-country-ipv6-num.csv"

LOT = 20_000


class Command(BaseCommand):
    help = "Charge la table de geolocalisation adresse -> pays."

    def add_arguments(self, parseur):
        parseur.add_argument("--ipv6", action="store_true",
                             help="Charge aussi les plages IPv6.")
        parseur.add_argument("--url", help="Source CSV « debut,fin,pays ».")
        parseur.add_argument("--etat", action="store_true",
                             help="Affiche l'etat de la table et sort.")
        parseur.add_argument("--vider", action="store_true")

    def handle(self, *args, **options):
        if options["etat"]:
            etat = couverture()
            self.stdout.write(f"  plages          : {etat['plages']}")
            self.stdout.write(f"  pays distincts  : {etat['pays_distincts']}")
            if not etat["chargee"]:
                self.stdout.write(self.style.WARNING(
                    "  table vide : le signal de voyage impossible ne peut pas "
                    "resoudre les pays lui-meme."
                ))
            return

        if options["vider"]:
            supprimes = PlageGeo.objects.all().delete()[0]
            self.stdout.write(f"  table videe ({supprimes} lignes)")

        sources = [(4, options["url"] or URL_IPV4)]
        if options["ipv6"] and not options["url"]:
            sources.append((6, URL_IPV6))

        total = 0
        for version, url in sources:
            self.stdout.write(f"  IPv{version} : {url.split('/')[-1]}")
            total += self._charger(version, url)

        etat = couverture()
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{total} plages chargees. En base : {etat['plages']} plages, "
            f"{etat['pays_distincts']} pays."
        ))

    # ---------------------------------------------------------------- internes
    def _charger(self, version, url):
        try:
            with httpx.Client(timeout=300, follow_redirects=True) as client:
                reponse = client.get(url)
                reponse.raise_for_status()
        except httpx.HTTPError as exc:
            raise CommandError(f"telechargement impossible : {exc}") from exc

        maintenant = timezone.now()
        tampon, total = [], 0

        for ligne in csv.reader(io.StringIO(reponse.text)):
            if len(ligne) < 3:
                continue
            try:
                debut, fin = int(ligne[0]), int(ligne[1])
            except ValueError:
                continue  # ligne d'en-tete ou malformee
            pays = ligne[2].strip().upper()[:2]
            if not pays:
                continue

            tampon.append(PlageGeo(
                version=version, debut=debut, fin=fin,
                pays=pays, mise_a_jour=maintenant,
            ))
            total += 1

            if len(tampon) >= LOT:
                self._ecrire(tampon)
                tampon.clear()
                self.stdout.write(f"\r    {total:>9d} plages", ending="")
                self.stdout.flush()

        if tampon:
            self._ecrire(tampon)
        self.stdout.write("")
        return total

    @staticmethod
    @transaction.atomic
    def _ecrire(tampon):
        PlageGeo.objects.bulk_create(tampon, batch_size=LOT)
