"""« mael code » : l'atelier de code, dans la norme.

    mael code "une page d'accueil pour une boulangerie" --dossier site
        le modele ecrit, les juges controlent, le modele corrige ;
    mael code --relire --dossier mon-projet
        juger un projet existant (sans modele, sans rien ecrire) ;
    mael code "un site de 4 pages ..." --chantier --dossier site
        grande demande : plan, puis un fichier a la fois (memoire courte),
        juges a chaque tache, finition sur tout le projet ;
    mael code --reprendre --dossier site
        reprendre un chantier interrompu a la premiere tache non finie ;
    mael code --corriger --dossier mon-projet
        juger, puis faire corriger les fichiers fautifs (originaux
        sauvegardes dans mon-projet/.mael/sauvegardes/).
    mael code --ticket ticket.md --dossier un-depot
        DEPOT EXISTANT : localiser, reproduire le ticket par un test,
        corriger, verifier avant / apres (correctif dans
        un-depot/.mael/correctif.diff, bilan dans .mael/BILAN-TICKET.md).

Code de sortie : 0 si conforme, 2 s'il reste des defauts bloquants — pour
qu'un script ou une CI puisse s'en servir tel quel.
"""
from __future__ import annotations

import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from brain import modeles
from brain.codage.atelier import Atelier, rendre_bilan
from brain.codage.espace import Espace


class Command(BaseCommand):
    help = "Atelier de code : ecrire ou relire du code, juge contre les normes."

    def add_arguments(self, parser):
        parser.add_argument("demande", nargs="*",
                            help="ce qu'il faut ecrire (entre guillemets)")
        parser.add_argument("--dossier", default=".",
                            help="espace de travail (rien n'est ecrit "
                                 "ailleurs) ; defaut : dossier courant")
        parser.add_argument("--relire", action="store_true",
                            help="juger le projet existant, sans modele")
        parser.add_argument("--corriger", action="store_true",
                            help="juger puis faire corriger les fichiers "
                                 "fautifs")
        parser.add_argument("--chantier", action="store_true",
                            help="grande demande : plan + une tache par "
                                 "fichier (pour les petits modeles)")
        parser.add_argument("--reprendre", action="store_true",
                            help="reprendre le chantier de ce dossier")
        parser.add_argument("--missions", default=None,
                            help="fichier YAML de missions : MAEL les "
                                 "execute une par une dans --dossier, et "
                                 "ecrit JOURNAL.md / RAPPORT.md")
        parser.add_argument("--lecons", default=None,
                            help="avec --missions : appliquer les lecons "
                                 "VALIDEES et PROPOSEES de ce lecons.yaml "
                                 "(un examen avec tout ce que MAEL a appris)")
        parser.add_argument("--se-relire", action="store_true",
                            help="MAEL relit les journaux des missions de "
                                 "--dossier, diagnostique ses echecs et "
                                 "ecrit BILAN-DE-MAEL.md / lecons.yaml")
        parser.add_argument("--verifier-lecons", action="store_true",
                            help="relancer les missions de --dossier avec "
                                 "les lecons proposees, comparer avant / "
                                 "apres, valider ou rejeter chaque lecon")
        parser.add_argument("--rafraichir-savoir", action="store_true",
                            help="verifier EN LIGNE la fraicheur du "
                                 "savoir-faire : sources, dernieres versions "
                                 "des dependances (sans modele)")
        parser.add_argument("--ticket", default=None,
                            help="depot existant : le ticket a traiter "
                                 "(chemin d'un fichier texte, ou le texte)")
        parser.add_argument("--choix", action="store_true",
                            help="avec --ticket : le modele departage les "
                                 "fichiers candidats (en essai)")
        parser.add_argument("--sans-tests", action="store_true",
                            help="avec --ticket : ne pas executer les tests "
                                 "du depot (Docker absent)")
        parser.add_argument("--tours", type=int, default=None,
                            help="tours de correction maximum (defaut 3)")

    def handle(self, *args, **opts):
        for flux in (sys.stdout, sys.stderr):
            try:
                flux.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass
        demande = " ".join(opts["demande"]).strip()
        if not (demande or opts["relire"] or opts["corriger"]
                or opts["reprendre"] or opts["missions"]
                or opts["se_relire"] or opts["verifier_lecons"]
                or opts["rafraichir_savoir"] or opts["ticket"]):
            raise CommandError('Dire quoi faire : mael code "..." , ou '
                               "--relire / --corriger.")
        if opts["rafraichir_savoir"]:
            # Sans modele : sources citees et dernieres versions, en ligne.
            from brain.codage import fraicheur, savoir_faire
            releve = fraicheur.rafraichir(
                sorted({f.url for f in savoir_faire.toutes() if f.url}),
                annoncer=lambda m: self.stdout.write(f"  … {m}"))
            problemes = fraicheur.problemes_hors_ligne(releve)
            self.stdout.write(f"\nsavoir-faire verifie le {releve.date} : "
                              + (f"{len(problemes)} PROBLEME(S)" if problemes
                                 else "a jour"))
            for p in problemes:
                self.stdout.write(f"  - {p}")
            return
        espace = Espace(Path(opts["dossier"]))

        backend = None
        if not opts["relire"]:
            from brain.backends.base import obtenir_backend
            try:
                backend = obtenir_backend()
                nom = backend.modele_pour("codeur")
            except modeles.ProblemeDeModele as souci:
                raise CommandError(souci.humain()) from None
            self.stdout.write(f"modele : {nom}")

        def annoncer(m):
            # Au fil de l'eau, meme quand la sortie est redirigee : une
            # tache dure des minutes, l'utilisateur doit voir ou on en est.
            self.stdout.write(f"  … {m}")
            self.stdout.flush()

        if opts["ticket"]:
            self._ticket(backend, opts)
            return

        if opts["se_relire"]:
            from brain.codage.lecons import BILAN, SeRelire
            familles = SeRelire(backend, Path(opts["dossier"]),
                                annoncer=annoncer).lancer()
            lecons = sum(f.levier not in {"", "AUCUN"} and not f.refus
                         for f in familles)
            self.stdout.write(f"\n{len(familles)} faiblesse(s), {lecons} "
                              f"lecon(s) proposee(s) — voir {BILAN} dans "
                              f"{opts['dossier']}")
            return

        if opts["verifier_lecons"]:
            from brain.codage.verification import RAPPORT_VERIF, Verification
            verdicts = Verification(backend, Path(opts["dossier"]),
                                    savoir=_savoir(),
                                    annoncer=annoncer).lancer()
            for v in verdicts:
                self.stdout.write(f"  {v.levier} : {v.verdict} (vue "
                                  f"{v.avant} -> {v.apres}, a servi "
                                  f"{v.servi} fois)")
            self.stdout.write(f"\nvoir {RAPPORT_VERIF} dans "
                              f"{opts['dossier']}")
            return

        if opts["missions"]:
            from brain.codage.missions import Missions
            appris = None
            if opts["lecons"]:
                from brain.codage.leviers import retenus
                appris = retenus(Path(opts["lecons"]), {"validee",
                                                        "proposee"})
                self.stdout.write("lecons appliquees : "
                                  + (", ".join(sorted(appris)) or "aucune"))
            missions = Missions(backend, Path(opts["dossier"]),
                                Path(opts["missions"]), savoir=_savoir(),
                                annoncer=annoncer, leviers=appris).lancer()
            faites = sum(m.verdict == "CONFORME" for m in missions)
            self.stdout.write(f"\nmissions : {faites}/{len(missions)} "
                              "conformes — voir RAPPORT.md dans "
                              f"{opts['dossier']}")
            return

        if opts["chantier"] or opts["reprendre"]:
            from brain.codage.chantier import Chantier
            chantier = Chantier(backend, espace, savoir=_savoir(),
                                annoncer=annoncer)
            try:
                bilan = (chantier.reprendre() if opts["reprendre"]
                         else chantier.lancer(demande))
            except Exception as exc:  # noqa: BLE001
                raise CommandError(modeles.expliquer_echec(exc)) from None
            self.stdout.write("\n" + rendre_bilan(bilan))
            if bilan.bloquants or not bilan.fichiers:
                sys.exit(2)
            return

        kwargs = {"annoncer": annoncer}
        if opts["tours"]:
            kwargs["tours_max"] = max(1, opts["tours"])
        atelier = Atelier(backend, espace, savoir=_savoir(), **kwargs)

        try:
            if opts["relire"]:
                bilan = atelier.relire()
            elif opts["corriger"]:
                bilan = atelier.corriger(demande)
            else:
                bilan = atelier.ecrire(demande)
        except Exception as exc:  # noqa: BLE001
            # Meme diagnostic que le terminal : lent n'est pas injoignable.
            raise CommandError(modeles.expliquer_echec(exc)) from None

        if bilan.explication:
            self.stdout.write("\n" + bilan.explication)
        self.stdout.write("\n" + rendre_bilan(bilan))
        if bilan.bloquants:
            sys.exit(2)

    def _ticket(self, backend, opts):
        from brain.codage import envergure
        from brain.codage.agent_depot import AgentDepot, rendre
        source = Path(opts["ticket"])
        ticket = (source.read_text(encoding="utf-8", errors="replace")
                  if source.is_file() else opts["ticket"])
        dossier = Path(opts["dossier"])
        # 8 Go : le modele est libere avant chaque passage des tests (Docker)
        decharger = getattr(backend, "decharger", None)
        if decharger is None and hasattr(backend, "relancer"):
            def decharger():                                    # Ollama
                backend.relancer(backend.modele_pour("codeur"))
        agent = AgentDepot(backend, dossier,
                           envergure=envergure.lire(backend),
                           decharger=decharger,
                           executer=not opts["sans_tests"],
                           choix=opts["choix"])
        try:
            bilan = agent.traiter(ticket)
        except Exception as exc:  # noqa: BLE001
            raise CommandError(modeles.expliquer_echec(exc)) from None
        texte = rendre(bilan)
        mael = dossier / ".mael"
        mael.mkdir(parents=True, exist_ok=True)
        (mael / "BILAN-TICKET.md").write_text(texte, encoding="utf-8")
        if bilan.diff:
            (mael / "correctif.diff").write_text(bilan.diff, encoding="utf-8",
                                                 newline="\n")
        self.stdout.write("\n" + texte)
        if bilan.verdict != "resolu-verifie":
            sys.exit(2)


def _savoir():
    """Le savoir donne AVANT d'ecrire (terme k de la loi). Branche ici pour
    que les gabarits et les fiches de normes s'y ajoutent sans toucher a la
    boucle ; vide tant qu'ils n'existent pas."""
    try:
        from brain.codage import normes, savoir
    except ImportError:
        return None

    def avant_d_ecrire(demande: str, fichier: str | None = None) -> str:
        # Les formes justes (gabarits) puis les exigences (fiches de normes).
        # `fichier` (chantier) : seulement des gabarits de ce type.
        morceaux = [savoir.pour_prompt(demande, fichier=fichier),
                    normes.pour_prompt(demande)]
        return "\n\n".join(m for m in morceaux if m)
    return avant_d_ecrire
