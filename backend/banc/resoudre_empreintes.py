"""Renseigne les empreintes @sha256 des images du banc (point 4, partie B).

Les Dockerfiles de banc/images/ et le verrou des outils embarques
(brain/tools/images.lock) portent `@sha256:A_RESOUDRE` : l'empreinte ne
s'obtient qu'avec Docker. Le jour ou Docker fonctionne :

    python -m banc.resoudre_empreintes

Pour chaque reference, interroge le registre (`docker buildx imagetools
inspect`) et reecrit les fichiers. Echoue sans rien modifier si une
empreinte est introuvable. Aucun autre appel reseau.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

BANC = Path(__file__).resolve().parent
IMAGES = BANC / "images"
LOCK_OUTILS = BANC.parent / "brain" / "tools" / "images.lock"

# reference de base -> Dockerfile a reecrire
DOCKERFILES = {
    "ubuntu:22.04": IMAGES / "Dockerfile.ubuntu2204",
    "ubuntu:24.04": IMAGES / "Dockerfile.ubuntu2404",
    "debian:12": IMAGES / "Dockerfile.debian12",
}

_A_RESOUDRE = "A_RESOUDRE"


def _empreinte(reference: str) -> str:
    """Digest sha256 de la reference sur le registre, via Docker."""
    proc = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", reference],
        capture_output=True, text=True, timeout=120, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"imagetools inspect {reference} : "
                           f"{proc.stderr.strip()}")
    m = re.search(r"sha256:[0-9a-f]{64}", proc.stdout)
    if not m:
        raise RuntimeError(f"digest introuvable pour {reference}")
    return m.group(0)


def main() -> int:
    # 1) Dockerfiles du banc
    for reference, dockerfile in DOCKERFILES.items():
        texte = dockerfile.read_text(encoding="utf-8")
        # Une image deja epinglee ne bouge plus : re-resoudre a chaque
        # lancement changeait l'image de base en silence (Claude, 19/09).
        if f"{reference}@sha256:" in texte and _A_RESOUDRE not in texte:
            continue
        digest = _empreinte(reference)
        nouveau = re.sub(rf"{re.escape(reference)}@sha256:[A-Za-z0-9_]+",
                         f"{reference}@{digest}", texte)
        if nouveau == texte and f"{reference}@" not in texte:
            nouveau = texte.replace(f"FROM {reference}",
                                    f"FROM {reference}@{digest}", 1)
        dockerfile.write_text(nouveau, encoding="utf-8")
        print(f"{dockerfile.name} : {reference}@{digest[:19]}…")

    # 2) Verrou des outils embarques
    if LOCK_OUTILS.exists():
        verrou = json.loads(LOCK_OUTILS.read_text(encoding="utf-8"))
        for nom, image in verrou.items():
            if image.endswith(_A_RESOUDRE):
                base = image.split("@", 1)[0]
                verrou[nom] = f"{base}@{_empreinte(base)}"
                print(f"images.lock : {nom} -> {verrou[nom][:40]}…")
        LOCK_OUTILS.write_text(json.dumps(verrou, indent=1, sort_keys=True)
                               + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
