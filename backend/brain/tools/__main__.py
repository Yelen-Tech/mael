"""Etat et preparation des outils embarques.

    python -m brain.tools              # liste : outil, image figee, presente ?
    python -m brain.tools --preparer   # telecharge a l'avance les images figees

Pourquoi preparer : le premier lancement d'un outil telecharge son image ;
sur une machine lente, ce telechargement depasse a lui seul le delai de
l'outil (constate le 19/09/2026 : gitleaks, 3 min 25 de telechargement).
Sur site, les images preparees sont celles qu'on exporte (docker save).
"""
from __future__ import annotations

import json
import subprocess
import sys

from .base import IMAGES_LOCK


def _presente(reference: str) -> bool:
    r = subprocess.run(["docker", "image", "inspect", reference],
                       capture_output=True, check=False,
                       text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0


def _preparer_bases(verrou: dict) -> int:
    """Bases de donnees des outils (volume nomme), telechargees une fois."""
    from . import registre
    echecs = 0
    for nom in registre.noms():
        outil = registre[nom]
        prep = getattr(outil, "PREPARATION", None)
        if not prep:
            continue
        reference = verrou.get(outil.image, "")
        ligne = ["docker", "run", "--rm", "--network", "bridge",
                 "--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
        for volume, cible in outil.volumes.items():
            ligne += ["--mount", f"type=volume,source={volume},target={cible}"]
        print(f"  base de {nom} : mise a jour...", flush=True)
        # La sortie d'un outil est lue en UTF-8, pas dans l'encodage de la
        # console : un octet inattendu ferait tomber le fil de lecture, et le
        # garde-fou « failed to » ci-dessous ne verrait plus rien (22/09).
        r = subprocess.run([*ligne, reference, *prep], capture_output=True,
                           check=False, text=True, encoding="utf-8",
                           errors="replace")
        # Un code 0 ne suffit pas : nuclei rend 0 apres avoir ecrit
        # « failed to update nuclei templates » (telechargement expire).
        # Une base non telechargee doit se voir ICI, pas au premier scan
        # d'un client (20/09/2026).
        sortie = (r.stdout or "") + (r.stderr or "")
        ok = r.returncode == 0 and "failed to" not in sortie.lower()

        # Et surtout : on VERIFIE que la base est la. nuclei a rendu 0, sans
        # message d'erreur, en n'ecrivant aucun modele (20/09/2026) ; dire
        # « prete » sur la foi d'un code de sortie, c'est decouvrir le
        # probleme chez le client. La verification tourne dans l'image de
        # l'outil, reseau coupe, et doit rendre quelque chose.
        controle = getattr(outil, "VERIFICATION", None)
        if ok and controle:
            ligne_v = ["docker", "run", "--rm", "--network", "none",
                       "--cap-drop", "ALL", "--security-opt",
                       "no-new-privileges"]
            for volume, cible in outil.volumes.items():
                ligne_v += ["--mount",
                            f"type=volume,source={volume},target={cible}"]
            v = subprocess.run([*ligne_v, reference, *controle],
                               capture_output=True, check=False, text=True,
                               encoding="utf-8", errors="replace")
            contenu = (v.stdout or "") + (v.stderr or "")
            # Un code 0 et trois lignes de banniere ne prouvent RIEN : nuclei
            # affiche « Listing available nuclei templates » meme quand il
            # n'en a aucun. Chaque outil dit donc ce qu'il faut VOIR dans la
            # sortie pour que sa base soit consideree presente.
            attendu = getattr(outil, "VERIFICATION_ATTENDU", "")
            if v.returncode != 0 or attendu not in contenu:
                ok = False
                sortie += ("\n  verification : la base est absente du "
                           "volume (sortie : "
                           f"{contenu.strip()[:200] or 'vide'})")
        print(f"  base de {nom} : {'prete' if ok else 'ECHEC'}")
        if not ok:
            print(f"    {sortie.strip()[-300:]}")
            echecs += 1
    return echecs


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    verrou = json.loads(IMAGES_LOCK.read_text(encoding="utf-8"))
    preparer = "--preparer" in argv
    manquantes = 0
    for nom, reference in sorted(verrou.items()):
        if reference.endswith("A_RESOUDRE"):
            print(f"  {nom:28} empreinte a resoudre (banc.resoudre_empreintes)")
            manquantes += 1
            continue
        present = _presente(reference)
        if not present and preparer:
            print(f"  {nom:28} telechargement...", flush=True)
            r = subprocess.run(["docker", "pull", "-q", reference],
                               capture_output=True, check=False, text=True,
                               encoding="utf-8", errors="replace")
            present = r.returncode == 0
            if not present:
                print(f"    echec : {r.stderr.strip()[:200]}")
        print(f"  {nom:28} {'presente' if present else 'ABSENTE'}")
        manquantes += 0 if present else 1
    if preparer:
        manquantes += _preparer_bases(verrou)
    return 1 if manquantes else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
