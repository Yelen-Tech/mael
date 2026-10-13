"""« mael modeles » : voir ce qui est installe, et changer de modele.

Trois usages, trois lignes :

    mael modeles                      ce qui est installe, et lequel sert
    mael modeles --utiliser mistral   fixe le modele (enregistre)
    mael modeles --auto               rend le choix a MAEL

Aucune trace d'appel Python ne doit sortir d'ici : quand Ollama n'est pas la
ou qu'aucun modele n'est installe, on affiche la phrase et la commande a
copier, et on s'arrete (code de sortie 1).
"""
from __future__ import annotations

import sys

from django.core.management.base import BaseCommand, CommandError

from brain import machine, modeles, reglages


class Command(BaseCommand):
    help = "Modeles Ollama installes : les voir, en choisir un."

    def add_arguments(self, parser):
        parser.add_argument("--utiliser", default=None, metavar="NOM",
                            help="modele a utiliser desormais (enregistre "
                                 "dans ~/.mael/reglages.json)")
        parser.add_argument("--auto", action="store_true",
                            help="oublier le choix enregistre : MAEL choisit "
                                 "de nouveau tout seul")
        parser.add_argument("--adresse", default=None,
                            help="adresse d'Ollama (defaut : celle des "
                                 "reglages du projet)")

    def handle(self, *args, **opts):
        # Console Windows en cp1252 : meme precaution que le terminal, sinon
        # un simple tiret cadratin sort en caractere de remplacement.
        for flux in (sys.stdout, sys.stderr):
            try:
                flux.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass
        valeurs, plaintes = reglages.charger()
        for plainte in plaintes:
            self.stderr.write(f"  ! reglages : {plainte}")

        try:
            installes = modeles.lister(opts.get("adresse"))
        except modeles.ProblemeDeModele as souci:
            raise CommandError(souci.humain()) from None

        if opts.get("auto"):
            return self._auto(valeurs, installes)
        if opts.get("utiliser"):
            return self._utiliser(valeurs, installes, opts["utiliser"])
        return self._montrer(valeurs, installes)

    # ------------------------------------------------------------------ voir
    def _montrer(self, valeurs, installes):
        if not installes:
            savoir = modeles.connus()
            raise CommandError(
                "Ollama repond, mais aucun modele n'est installe.\n"
                f"  Installer celui que MAEL conseille :  ollama pull "
                f"{savoir.get('conseille_si_rien', modeles.CONSEILLE)}")

        # Ce que MAEL prendrait maintenant, sans rien enregistrer : la
        # commande MONTRE l'etat, elle ne le change pas.
        try:
            resolution = modeles.resoudre(
                valeurs.get("role", "expert"), valeurs=valeurs,
                disponibles=installes, enregistrer=False)
            actif, origine, messages = (resolution.nom, resolution.origine,
                                        resolution.messages)
        except modeles.ProblemeDeModele as souci:
            actif, origine, messages = "", "", [souci.humain()]

        self.stdout.write(f"\nOllama  : {modeles.adresse()}   "
                          f"({len(installes)} modele(s) installe(s))")
        self.stdout.write(f"Machine : {machine.capacite().libelle()}\n")
        for ligne in modeles.decrire(installes, actif):
            self.stdout.write(ligne)

        explication = {
            "reglage": "choisi par toi (reglage « modele »)",
            "defaut": "defaut livre avec MAEL",
            "automatique": "choisi par MAEL faute du modele demande",
            "impose": "impose pour cette execution",
        }.get(origine, "")
        if actif:
            self.stdout.write(f"\nEn service : {actif}"
                              + (f"  — {explication}" if explication else ""))
        for message in messages:
            self.stdout.write(f"  {message}")
        self.stdout.write("\n  mael modeles --utiliser <nom>   pour en changer"
                          "\n  mael modeles --auto             pour rendre le "
                          "choix a MAEL\n")

    # --------------------------------------------------------------- changer
    def _utiliser(self, valeurs, installes, demande):
        trouve = modeles.trouver(demande, installes)
        if trouve is None:
            raise CommandError(
                f"« {demande} » n'est pas installe.\n"
                "  Installes : "
                + ", ".join(m.nom for m in installes) +
                f"\n  Pour l'installer :  ollama pull {demande}")
        if not modeles.sait_dialoguer(trouve.nom):
            raise CommandError(
                f"« {trouve.nom} » ne sait pas dialoguer (modele de "
                "vectorisation) : MAEL ne peut rien en faire.")
        valeurs = dict(valeurs)
        valeurs["modele"] = trouve.nom
        chemin = reglages.enregistrer(valeurs)
        modeles.oublier()
        self.stdout.write(f"Modele : {trouve.nom} ({trouve.taille}) — "
                          f"enregistre dans {chemin}")
        if modeles.est_exclu(trouve.nom):
            pourquoi = modeles.connus().get("exclus_pourquoi", {}).get(
                trouve.nom, "")
            self.stderr.write(
                "  ! ce modele a echoue la categorie « refuser » du banc de "
                "mesure" + (f" ({pourquoi})" if pourquoi else "") +
                " : MAEL ne l'aurait pas choisi tout seul.")

    def _auto(self, valeurs, installes):
        valeurs = dict(valeurs)
        valeurs["modele"] = ""
        reglages.enregistrer(valeurs)
        modeles.oublier()
        try:
            resolution = modeles.resoudre(
                valeurs.get("role", "expert"), valeurs=valeurs,
                disponibles=installes, enregistrer=False)
        except modeles.ProblemeDeModele as souci:
            raise CommandError(souci.humain()) from None
        self.stdout.write("Choix rendu a MAEL. Au prochain demarrage : "
                          f"{resolution.nom}")
