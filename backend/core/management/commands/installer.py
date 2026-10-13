"""« mael installer » : le moteur de MAEL et son modele, en une commande.

    mael installer                 montre le plan, demande l'accord, installe
    mael installer --oui           sans question (serveur, script)
    mael installer --plan          montre seulement ce qui serait fait
    mael installer --cpu|--cuda    impose l'acceleration (defaut : detectee)
    mael installer --moteur-seul   llama.cpp sans le modele (ou --modele-seul)

Le modele installe, MAEL-Coder, est Qwen3-Coder-30B-A3B-Instruct
(Apache-2.0) compresse : la commande le dit avant de telecharger, et pose sa
carte a cote du fichier (voir brain/installation.py).
"""
from __future__ import annotations

import sys
import time

from django.core.management.base import BaseCommand, CommandError

from brain import installation as inst


class Command(BaseCommand):
    help = "Installer le moteur de MAEL (llama.cpp) et son modele."

    def add_arguments(self, parser):
        parser.add_argument("--oui", action="store_true",
                            help="ne pas demander l'accord")
        parser.add_argument("--plan", action="store_true",
                            help="montrer ce qui serait fait, sans rien faire")
        acc = parser.add_mutually_exclusive_group()
        acc.add_argument("--cpu", action="store_true")
        acc.add_argument("--cuda", action="store_true")
        part = parser.add_mutually_exclusive_group()
        part.add_argument("--moteur-seul", action="store_true")
        part.add_argument("--modele-seul", action="store_true")
        parser.add_argument("--modele", default=inst.DEFAUT,
                            choices=sorted(inst.CATALOGUE))

    def handle(self, *args, **o):
        for flux in (sys.stdout, sys.stderr):
            try:
                flux.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass
        try:
            plan = inst.preparer(
                o["modele"], "cuda" if o["cuda"] else "cpu" if o["cpu"]
                else "", moteur=not o["modele_seul"],
                modele=not o["moteur_seul"])
        except inst.InstallationImpossible as e:
            raise CommandError(str(e)) from None
        self.stdout.write("\n".join(plan.lignes()))
        if plan.a_telecharger == 0:
            self.stdout.write("Tout est deja installe.")
            return
        if o["plan"]:
            return
        if not o["oui"]:
            try:
                rep = input("Installer ? [o/N] ").strip().lower()
            except EOFError:
                rep = ""
            if rep not in {"o", "oui", "y", "yes"}:
                self.stdout.write("Rien n'a ete telecharge.")
                return
        derniere = [0.0]

        def progression(nom, fait, total):
            if time.monotonic() - derniere[0] > 2 or fait >= total:
                derniere[0] = time.monotonic()
                self.stdout.write(f"\r  {nom[:48]:48} {100 * fait / total:5.1f} %",
                                  ending="")
                self.stdout.flush()
        try:
            etat = inst.installer(plan, progression=progression)
        except inst.InstallationImpossible as e:
            raise CommandError(str(e)) from None
        except OSError as e:
            raise CommandError(
                f"coupure ou disque : {e}. Relancer `mael installer` : le "
                "telechargement reprend ou il s'est arrete.") from None
        except KeyboardInterrupt:
            raise CommandError("interrompu. Relancer `mael installer` : le "
                               "telechargement reprendra.") from None
        self.stdout.write("")
        self.stdout.write(f"Installe : moteur {etat.get('moteur', '-')}, "
                          f"modele {etat.get('modele', '-')}.")
        if etat.get("modele"):
            self.stdout.write("MAEL s'en sert desormais (BRAIN_BACKEND="
                              "llamacpp). Carte du modele : "
                              f"{plan.dossier / 'modeles' / 'MAEL-Coder.md'}")
