"""L'espace de travail : le seul endroit ou l'atelier a le droit d'ecrire.

Un modele qui ecrit « ../../.ssh/authorized_keys » ou « C:/Windows/... » ne
doit rien pouvoir faire. Tout chemin est resolu, puis compare a la racine :
s'il en sort, il est refuse — pas corrige en silence.

Avant d'ecraser un fichier existant, on en garde une copie dans
.mael/sauvegardes/<horodatage>/ : en mode « assister », c'est le code de
l'utilisateur, et une correction ratee doit pouvoir se defaire.
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path, PurePosixPath


class CheminRefuse(ValueError):
    pass


# Ce qu'un modele n'ecrit jamais, meme dans l'espace.
_INTERDITS = {".git", ".mael", ".env", ".ssh"}


class Espace:
    def __init__(self, racine: Path | str):
        self.racine = Path(racine).resolve()
        self.racine.mkdir(parents=True, exist_ok=True)
        self._lot = time.strftime("%Y%m%d-%H%M%S")

    def chemin(self, relatif: str) -> Path:
        brut = relatif.strip().strip("`'\"").replace("\\", "/")
        if not brut or brut.startswith("/") or re.match(r"^[A-Za-z]:", brut):
            raise CheminRefuse(f"chemin absolu refuse : {relatif!r}")
        parties = PurePosixPath(brut).parts
        if ".." in parties:
            raise CheminRefuse(f"remontee de dossier refusee : {relatif!r}")
        if set(parties) & _INTERDITS:
            raise CheminRefuse(f"emplacement protege : {relatif!r}")
        cible = (self.racine / brut).resolve()
        if cible != self.racine and self.racine not in cible.parents:
            raise CheminRefuse(f"sort de l'espace de travail : {relatif!r}")
        return cible

    def lire(self, relatif: str) -> str:
        return self.chemin(relatif).read_text(encoding="utf-8",
                                              errors="replace")

    def ecrire(self, relatif: str, contenu: str, *, fin_de_ligne: str = "\n",
               ligne_finale: bool = True) -> tuple[Path, bool]:
        """Ecrit le fichier. Rend (chemin, etait_deja_la). Sur un depot
        existant, fin_de_ligne et ligne_finale gardent le style du fichier
        (sinon changer 2 lignes d'un fichier en \\r\\n les change toutes)."""
        cible = self.chemin(relatif)
        existait = cible.exists()
        if existait:
            copie = self.racine / ".mael" / "sauvegardes" / self._lot / \
                cible.relative_to(self.racine)
            if not copie.exists():   # la PREMIERE version du lot fait foi
                copie.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cible, copie)
        cible.parent.mkdir(parents=True, exist_ok=True)
        if ligne_finale and not contenu.endswith("\n"):
            contenu += "\n"
        cible.write_text(contenu, encoding="utf-8", newline=fin_de_ligne)
        return cible, existait

    def creer_octets(self, relatif: str, octets: bytes) -> Path:
        """Cree un fichier binaire (image provisoire). Jamais par-dessus un
        fichier existant : FileExistsError."""
        cible = self.chemin(relatif)
        cible.parent.mkdir(parents=True, exist_ok=True)
        with open(cible, "xb") as f:      # « x » : echoue si le fichier existe
            f.write(octets)
        return cible

    def relatif(self, p: Path) -> str:
        return p.relative_to(self.racine).as_posix()
