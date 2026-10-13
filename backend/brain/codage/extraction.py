"""Lire les fichiers dans la reponse du modele — sans appel d'outil natif.

Meme choix que le terminal (voir _extraire_bloc) : un petit modele rate
l'appel d'outil quand le prompt grossit, mais il sait ecrire un bloc de code.
On lui demande :

    ```html fichier=index.html
    ...
    ```

Et on tolere ce que les modeles ecrivent en vrai, sans le demander :
    ```html:index.html            (forme courte)
    **index.html** / ### index.html / Fichier : index.html   (ligne avant le bloc)
    <!-- index.html --> / // script.js / # app.py               (1re ligne du bloc)

Un bloc sans nom recoit le nom par defaut de son langage (index.html,
style.css, script.js, main.py) — une seule fois : deux blocs anonymes du meme
langage, c'est une ambiguite, et on la signale au lieu de choisir.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_BLOC = re.compile(r"(?ms)^```[ \t]*([^\n`]*)\n(.*?)^```[ \t]*$")
_NOM = r"([\w./-]+\.[A-Za-z0-9]{1,8})"
_ENTETE_NOM = re.compile(
    rf"(?:fichier|file|chemin|path)\s*[=:]\s*[\"']?{_NOM}", re.I)
_ENTETE_COURT = re.compile(rf"^[\w+-]*:{_NOM}$")
_AVANT = re.compile(
    rf"(?im)^\s*(?:#+\s*|\*\*|`|(?:fichier|file)\s*:\s*)*`?{_NOM}`?\**\s*:?\s*$")
_PREMIERE = re.compile(
    rf"^\s*(?:<!--\s*{_NOM}\s*-->|/[/*]\s*{_NOM}\s*(?:\*/)?|#\s*{_NOM})\s*$")

PAR_DEFAUT = {
    "html": "index.html", "htm": "index.html",
    "css": "style.css",
    "js": "script.js", "javascript": "script.js",
    "py": "main.py", "python": "main.py",
}
# Blocs qui ne sont pas des fichiers du projet : sorties, commandes.
_PAS_UN_FICHIER = {"bash", "sh", "shell", "console", "text", "txt",
                   "powershell", "ps1", "cmd", "output", "sortie"}


@dataclass
class Extraction:
    fichiers: dict[str, str] = field(default_factory=dict)
    ambiguites: list[str] = field(default_factory=list)


def extraire(texte: str) -> Extraction:
    resultat = Extraction()
    anonymes_vus: set[str] = set()
    for m in _BLOC.finditer(texte):
        entete, contenu = m.group(1).strip(), m.group(2)
        langage = entete.split()[0].split(":")[0].lower() if entete else ""
        nom = None

        trouve = _ENTETE_NOM.search(entete) or _ENTETE_COURT.match(entete)
        if trouve:
            nom = trouve.group(1)
        if nom is None:
            # Derniere ligne non vide avant le bloc.
            avant = texte[:m.start()].rstrip().splitlines()[-1:] or [""]
            t = _AVANT.match(avant[0])
            if t:
                nom = t.group(1)
        if nom is None:
            lignes = contenu.splitlines()
            p = _PREMIERE.match(lignes[0]) if lignes else None
            if p:
                nom = next(g for g in p.groups() if g)
        if nom is None:
            if langage in _PAS_UN_FICHIER:
                continue
            nom = PAR_DEFAUT.get(langage)
            if nom is None:
                continue
            if nom in anonymes_vus:
                resultat.ambiguites.append(
                    f"deux blocs {langage} sans nom de fichier")
                continue
            anonymes_vus.add(nom)

        # Seul le prefixe « ./ » est retire. Surtout pas lstrip("./") : il
        # changerait « ../x » en « x » et « .env » en « env » — une evasion
        # corrigee en silence au lieu d'etre refusee par l'espace.
        nom = nom.strip()
        while nom.startswith("./"):
            nom = nom[2:]
        if nom in resultat.fichiers:
            # Le modele a reecrit le meme fichier : la derniere version gagne,
            # c'est celle qu'il a « finie ».
            resultat.ambiguites.append(f"{nom} ecrit deux fois (derniere "
                                       "version gardee)")
        resultat.fichiers[nom] = _sans_etiquette(contenu, nom).rstrip() + "\n"
    return resultat


def _sans_etiquette(contenu: str, nom: str) -> str:
    """La 1re ligne « <!-- script.js --> » / « // app.js » qui ne fait que
    nommer le fichier sert a l'extraction, pas au code : on la retire
    (sixieme essai reel : un commentaire HTML en tete d'un fichier .js)."""
    lignes = contenu.split("\n")
    p = _PREMIERE.match(lignes[0]) if lignes else None
    if p:
        etiquette = next(g for g in p.groups() if g)
        if etiquette.split("/")[-1] == nom.split("/")[-1]:
            return "\n".join(lignes[1:])
    return contenu
