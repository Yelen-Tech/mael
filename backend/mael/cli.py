"""La commande « mael ».

    mael                      ouvre le terminal MAEL
    mael modeles              ce qui est installe chez vous, et lequel sert
    mael modeles --utiliser X change de modele
    mael code "..."           ecrire du code, juge contre les normes
    mael code --relire        juger un projet existant
    mael installer            le moteur et son modele, en une commande
    mael audit <dossier>      audit de securite d'un depot
    mael --version

Une seule chose se decide ici : **on demarre en profil local**
(`MAEL_LOCAL=1`). Ni serveur, ni base, ni file d'attente, ni port ouvert --
voir `config/settings.py`. Quelqu'un qui veut le profil serveur passe par
`manage.py`, comme avant.

Aucune trace d'appel Python ne doit sortir d'ici : une erreur prevue est une
phrase et une commande a copier.
"""
from __future__ import annotations

import os
import sys

from . import VERSION

# Les commandes que « mael » expose. Tout le reste de manage.py reste
# accessible par manage.py : ce n'est pas la meme audience.
COMMANDES = {
    "terminal": "ouvrir le terminal MAEL (defaut)",
    "modeles": "voir les modeles Ollama installes, en choisir un",
    "code": "atelier de code : ecrire ou relire, juge contre les normes",
    "installer": "installer le moteur de MAEL et son modele (MAEL-Coder)",
    "audit": "audit de securite d'un depot : secrets, dependances, code",
}
DEFAUT = "terminal"


def _aide() -> str:
    lignes = [f"mael {VERSION} — audit et cybersecurite en terminal, chez vous.",
              "",
              "  mael                      ouvre le terminal",
              "  mael <commande> [options] une commande precise",
              "", "Commandes :"]
    lignes += [f"  {nom:<10s} {quoi}" for nom, quoi in COMMANDES.items()]
    lignes += ["", "  mael <commande> --help    les options d'une commande"]
    return "\n".join(lignes)


def principal(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)

    if arguments and arguments[0] in ("--version", "-V"):
        print(f"mael {VERSION}")
        return 0
    if arguments and arguments[0] in ("--aide", "aide", "-h", "--help"):
        print(_aide())
        return 0

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    # setdefault : quelqu'un qui sait ce qu'il fait peut lancer le terminal
    # contre le profil serveur en posant MAEL_LOCAL=0 lui-meme.
    os.environ.setdefault("MAEL_LOCAL", "1")

    if arguments and arguments[0] in COMMANDES:
        commande, reste = arguments[0], arguments[1:]
    else:
        commande, reste = DEFAUT, arguments

    from django.core.management import execute_from_command_line

    try:
        execute_from_command_line(["mael", commande, *reste])
    except KeyboardInterrupt:
        print()
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
