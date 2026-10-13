"""python manage.py collecter [--flux nom] [--sans-cle] [--sante] [--decroissance]

Collecte manuelle, pour le developpement et le diagnostic. En production
c'est la tache Celery qui appelle le meme code.
"""
from django.core.management.base import BaseCommand

from intel.agregation import appliquer_decroissance, integrer, sante_des_flux
from intel.feeds import PAR_NOM, SANS_CLE, TOUS


class Command(BaseCommand):
    help = "Collecte les flux de renseignement et met a jour les indicateurs."

    def add_arguments(self, parseur):
        parseur.add_argument(
            "--flux", action="append", default=[],
            help="Nom d'un flux precis (repetable). Par defaut : tous.",
        )
        parseur.add_argument(
            "--sans-cle", action="store_true",
            help="Seulement les flux ne demandant aucune cle d'API.",
        )
        parseur.add_argument(
            "--sante", action="store_true", help="Affiche l'etat des flux et sort."
        )
        parseur.add_argument(
            "--decroissance", action="store_true",
            help="Applique la decroissance par age et sort.",
        )

    def handle(self, *args, **options):
        if options["sante"]:
            return self._sante()
        if options["decroissance"]:
            restants = appliquer_decroissance()
            self.stdout.write(
                self.style.SUCCESS(f"Decroissance appliquee. Malveillants : {restants}")
            )
            return

        if options["flux"]:
            inconnus = [n for n in options["flux"] if n not in PAR_NOM]
            if inconnus:
                self.stderr.write(
                    self.style.ERROR(
                        f"Flux inconnus : {inconnus}. Connus : {sorted(PAR_NOM)}"
                    )
                )
                return
            classes = [PAR_NOM[n] for n in options["flux"]]
        elif options["sans_cle"]:
            classes = SANS_CLE
        else:
            classes = TOUS

        total = {"crees": 0, "mis_a_jour": 0, "blanchis": 0}
        for classe in classes:
            collecteur = classe()
            self.stdout.write(f"  {collecteur.nom:16s} ", ending="")
            self.stdout.flush()

            enregistrements, erreur = collecteur.collecter()
            if erreur:
                style = self.style.WARNING if "cle" in erreur else self.style.ERROR
                self.stdout.write(style(erreur))
                continue

            resultat = integrer(collecteur.nom, enregistrements)
            total["crees"] += resultat.crees
            total["mis_a_jour"] += resultat.mis_a_jour
            total["blanchis"] += resultat.blanchis
            self.stdout.write(
                self.style.SUCCESS(f"{len(enregistrements):>7d} recus  |  {resultat}")
            )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Total : {total['crees']} crees, {total['mis_a_jour']} mis a jour, "
                f"{total['blanchis']} blanchis par la liste blanche"
            )
        )

    def _sante(self):
        lignes = sante_des_flux()
        if not lignes:
            self.stdout.write("Aucun flux enregistre. Lancez une collecte d'abord.")
            return
        self.stdout.write(f"{'FLUX':16s} {'STATUT':14s} {'RECU':>8s}  DERNIERE")
        for e in lignes:
            style = {
                "ok": self.style.SUCCESS,
                "en erreur": self.style.ERROR,
                "silencieux": self.style.WARNING,
            }.get(e["statut"], self.style.NOTICE)
            quand = (
                e["derniere_collecte"].strftime("%Y-%m-%d %H:%M")
                if e["derniere_collecte"] else "-"
            )
            statut = style(f"{e['statut']:14s}")
            self.stdout.write(
                f"{e['flux']:16s} {statut} {e['dernier_nombre']:>8d}  {quand}"
            )
            if e["erreur"]:
                self.stdout.write(f"{'':16s} -> {e['erreur'][:100]}")
