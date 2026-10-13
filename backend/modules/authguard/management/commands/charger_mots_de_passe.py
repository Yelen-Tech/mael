"""python manage.py charger_mots_de_passe [--source NOM | --url URL | --fichier CHEMIN]

Charge un corpus de mots de passe compromis.

Le clair n'est jamais stocke : on ne garde que le prefixe (5 caracteres) et le
suffixe de l'empreinte SHA-1, ce qui permet l'interrogation en k-anonymat.
Meme si notre base fuit, elle ne contient aucun mot de passe utilisable.

Sources connues (--liste pour les afficher) :
    pwdb-1k / pwdb-10k / pwdb-100k / pwdb-1m    bases de fuites, les plus courants
    xato-100k / xato-1m                          corpus xato, 10 M de mots de passe
    darkweb-10k                                  observes sur le dark web en 2017

Formats de fichier acceptes :
    un mot de passe en clair par ligne              (defaut)
    « SHA1:occurrences » par ligne                  (--deja-hache)
"""
import hashlib

import httpx
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from modules.authguard.models import MotDePasseCompromis

LOT = 10_000
BASE_SECLISTS = (
    "https://raw.githubusercontent.com/danielmiessler/SecLists/master/"
    "Passwords/Common-Credentials/"
)

SOURCES = {
    "pwdb-1k": (BASE_SECLISTS + "Pwdb_top-1000.txt", "8 Ko"),
    "pwdb-10k": (BASE_SECLISTS + "Pwdb_top-10000.txt", "80 Ko"),
    "pwdb-100k": (BASE_SECLISTS + "Pwdb_top-100000.txt", "0,8 Mo"),
    "pwdb-1m": (BASE_SECLISTS + "Pwdb_top-1000000.txt", "8,7 Mo"),
    "xato-100k": (
        BASE_SECLISTS + "xato-net-10-million-passwords-100000.txt", "0,8 Mo"),
    "xato-1m": (
        BASE_SECLISTS + "xato-net-10-million-passwords-1000000.txt", "8,6 Mo"),
    "darkweb-10k": (BASE_SECLISTS + "darkweb2017_top-10000.txt", "83 Ko"),
}


class Command(BaseCommand):
    help = "Charge un corpus de mots de passe compromis (prefixe/suffixe SHA-1)."

    def add_arguments(self, parseur):
        parseur.add_argument("--source", choices=sorted(SOURCES))
        parseur.add_argument("--url")
        parseur.add_argument("--fichier")
        parseur.add_argument("--liste", action="store_true",
                             help="Affiche les sources connues et sort.")
        parseur.add_argument("--deja-hache", action="store_true",
                             help="Le fichier contient « SHA1:occurrences ».")
        parseur.add_argument("--limite", type=int, default=0)
        parseur.add_argument("--vider", action="store_true",
                             help="Vide la table avant de charger.")

    def handle(self, *args, **options):
        if options["liste"]:
            self.stdout.write(f"{'SOURCE':14s} {'TAILLE':>8s}  URL")
            for nom, (url, taille) in sorted(SOURCES.items()):
                self.stdout.write(f"{nom:14s} {taille:>8s}  {url.split('/')[-1]}")
            return

        cibles = [options[c] for c in ("source", "url", "fichier") if options[c]]
        if len(cibles) != 1:
            raise CommandError(
                "Donnez exactement une origine : --source, --url ou --fichier "
                "(--liste pour voir les sources connues)."
            )

        if options["vider"]:
            supprimes = MotDePasseCompromis.objects.all().delete()[0]
            self.stdout.write(f"  table videe ({supprimes} lignes)")

        if options["fichier"]:
            with open(options["fichier"], encoding="utf-8", errors="ignore") as f:
                total = self._consommer(f, options)
        else:
            url = SOURCES[options["source"]][0] if options["source"] else options["url"]
            self.stdout.write(f"  telechargement : {url.split('/')[-1]}")
            total = self._depuis_url(url, options)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{total} mots de passe traites. Empreintes en base : "
            f"{MotDePasseCompromis.objects.count()}"
        ))

    # ---------------------------------------------------------------- internes
    def _depuis_url(self, url, options):
        with httpx.Client(timeout=300, follow_redirects=True) as client:
            with client.stream("GET", url) as reponse:
                if reponse.status_code >= 400:
                    raise CommandError(
                        f"{reponse.status_code} sur {url} — verifiez l'URL "
                        "(--liste pour les sources connues)."
                    )
                return self._consommer(reponse.iter_lines(), options)

    def _consommer(self, lignes, options):
        deja = options["deja_hache"]
        limite = options["limite"]
        tampon, total = [], 0

        for ligne in lignes:
            if isinstance(ligne, bytes):
                ligne = ligne.decode("utf-8", "ignore")
            ligne = ligne.rstrip("\r\n")
            if not ligne:
                continue

            if deja:
                morceaux = ligne.split(":")
                empreinte = morceaux[0].strip().upper()
                if len(empreinte) != 40:
                    continue
                try:
                    occurrences = int(morceaux[1]) if len(morceaux) > 1 else 1
                except ValueError:
                    occurrences = 1
            else:
                empreinte = hashlib.sha1(ligne.encode()).hexdigest().upper()  # noqa: S324
                # Le rang dans la liste est une mesure de frequence : les
                # premiers sont les plus utilises. On l'inverse grossierement
                # pour que l'API puisse dire « ce mot de passe est tres courant ».
                occurrences = max(1, 1_000_000 - total)

            tampon.append(MotDePasseCompromis(
                prefixe=empreinte[:5], suffixe=empreinte[5:],
                occurrences=occurrences,
            ))
            total += 1

            if len(tampon) >= LOT:
                self._ecrire(tampon)
                tampon.clear()
                self.stdout.write(f"\r  {total:>9d} charges", ending="")
                self.stdout.flush()
            if limite and total >= limite:
                break

        if tampon:
            self._ecrire(tampon)
        return total

    @staticmethod
    @transaction.atomic
    def _ecrire(tampon):
        MotDePasseCompromis.objects.bulk_create(
            tampon, batch_size=LOT, ignore_conflicts=True
        )
