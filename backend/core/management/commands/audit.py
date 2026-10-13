"""« mael audit <dossier> » : l'audit de securite d'un depot (voir
brain/audit.py).

    mael audit .                       secrets + dependances + code
    mael audit . --sans dependances    sans Trivy
    mael audit . --sortie rapport.md   ou ecrire le rapport

Code de sortie : 0 propre, 1 constat eleve/critique, 2 audit incomplet.
"""
from __future__ import annotations

import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from brain import audit


class Command(BaseCommand):
    help = "Audit de securite d'un depot : secrets, dependances, code."

    def add_arguments(self, parser):
        parser.add_argument("dossier", nargs="?", default=".")
        parser.add_argument("--sans", action="append", default=[],
                            choices=["secrets", "dependances", "code"])
        parser.add_argument("--sortie", default="",
                            help="fichier du rapport (defaut : "
                                 "<dossier>/.mael/AUDIT-SECURITE.md)")

    def handle(self, *args, **o):
        for flux in (sys.stdout, sys.stderr):
            try:
                flux.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass
        dossier = Path(o["dossier"]).resolve()
        if not dossier.is_dir():
            raise CommandError(f"{dossier} n'est pas un dossier")
        regards = tuple(g for g in ("secrets", "dependances", "code")
                        if g not in o["sans"])
        self.stdout.write(f"Audit de {dossier} : {', '.join(regards)}...")
        r = audit.auditer(dossier, regards)
        sortie = Path(o["sortie"]) if o["sortie"] else \
            dossier / ".mael" / "AUDIT-SECURITE.md"
        sortie.parent.mkdir(parents=True, exist_ok=True)
        sortie.write_text(audit.en_markdown(r), encoding="utf-8")
        for g in audit.ORDRE:
            if r.compte(g):
                self.stdout.write(f"  {g:9} {r.compte(g)}")
        for g, pourquoi in r.non_verifie.items():
            self.stdout.write(f"  NON VERIFIE {audit.NOMS[g]} : {pourquoi}")
        self.stdout.write(f"Rapport : {sortie}")
        sys.exit(r.code_sortie)
