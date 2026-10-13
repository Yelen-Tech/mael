"""CLI des connaissances.

Sans argument : rapport de validation de toutes les fiches (via schema).
Avec des mots : recherche et affiche chaque fiche trouvee en compact.

    python -m brain.connaissances
    python -m brain.connaissances debordement tampon
"""
import sys

from . import recuperer
from .schema import rapport


def _compact(c) -> str:
    lignes = [f"== {c.nom} ({c.id}, {c.etat}) ==", c.resume, "Securite :"]
    for p in c.securite:
        lignes.append(f"  [{p['gravite']}] {p['titre']}")
        lignes.append(f"      risque  : {p['risque']}")
        lignes.append(f"      conseil : {p['conseil']}")
    lignes.append("Sources :")
    for s in c.sources:
        lignes.append(f"  - {s['titre']} : {s['url']}")
    return "\n".join(lignes)


def main(argv: list[str]) -> int:
    for flux in (sys.stdout,):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if not argv:
        nb_err, texte = rapport()
        print(texte)
        return 1 if nb_err else 0
    requete = " ".join(argv)
    trouvees = recuperer(requete)
    if not trouvees:
        print(f"Aucune connaissance pour « {requete} ».")
        return 0
    for c in trouvees:
        print(_compact(c))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
