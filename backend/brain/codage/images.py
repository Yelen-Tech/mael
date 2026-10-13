"""Images de remplacement : une page qui appelle une photo absente.

Un modele qui ecrit du code ne peut pas produire une photo (premier essai
reel du chantier, 07/10/2026 : images/croissant.jpg, images/gateau.jpg).
Decision du responsable (option A) : MAEL cree lui-meme une image NEUTRE
au bon chemin, pour que le site soit complet et s'affiche ; le bilan liste
ces images comme PROVISOIRES, a remplacer par les vraies. Rien n'est cache.

Rigueur :
  - le fichier est dans le VRAI format de son extension (un .jpg contient
    un JPEG, pas un PNG renomme) ; Pillow (HPND, licence permissive) s'il
    est installe ; sans lui, seuls .png et .svg sont fabriques (en Python
    pur) et le bilan dit pourquoi les autres manquent ;
  - la taille vient des attributs width/height de la balise s'ils existent,
    sinon 800 x 600 ; bornee a 2 000 px ;
  - jamais par-dessus un fichier existant ; jamais hors de l'espace ;
  - teinte grise neutre et le nom du fichier ecrit dessus : impossible de
    la prendre pour la vraie photo.
"""
from __future__ import annotations

import io
import re
import struct
import zlib
from pathlib import Path

EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif",
              ".bmp", ".ico"}
FOND, TEXTE = (229, 231, 235), (75, 85, 99)       # #e5e7eb / #4b5563
DEFAUT, MAXI = (800, 600), 2_000


def taille_dans_la_balise(ligne: str, lien: str) -> tuple[int, int]:
    """width / height de la balise qui contient `lien` sur cette ligne."""
    m = re.search(r"<[^<>]*" + re.escape(lien) + r"[^<>]*>", ligne)
    balise = m.group(0) if m else ""
    w = re.search(r'\bwidth\s*=\s*["\']?(\d+)', balise)
    h = re.search(r'\bheight\s*=\s*["\']?(\d+)', balise)
    largeur = min(int(w.group(1)), MAXI) if w else DEFAUT[0]
    hauteur = min(int(h.group(1)), MAXI) if h else (
        largeur * DEFAUT[1] // DEFAUT[0] if w else DEFAUT[1])
    return max(largeur, 1), max(hauteur, 1)


def _svg(nom: str, l: int, h: int) -> bytes:
    nom = re.sub(r"[<>&\"']", "", nom)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{l}" '
            f'height="{h}" viewBox="0 0 {l} {h}" role="img" '
            f'aria-label="image provisoire {nom}"><rect width="100%" '
            f'height="100%" fill="#e5e7eb"/><text x="50%" y="50%" '
            f'dominant-baseline="middle" text-anchor="middle" '
            f'font-family="sans-serif" font-size="{max(12, min(l, h) // 12)}"'
            f' fill="#4b5563">image provisoire : {nom}</text></svg>\n'
            ).encode("utf-8")


def _png_pur(l: int, h: int) -> bytes:
    """Un PNG uni, sans bibliotheque (format PNG, RFC 2083)."""
    def morceau(type_, donnees):
        return (struct.pack(">I", len(donnees)) + type_ + donnees
                + struct.pack(">I", zlib.crc32(type_ + donnees) & 0xFFFFFFFF))
    ligne = b"\x00" + bytes(FOND) * l
    return (b"\x89PNG\r\n\x1a\n"
            + morceau(b"IHDR", struct.pack(">IIBBBBB", l, h, 8, 2, 0, 0, 0))
            + morceau(b"IDAT", zlib.compress(ligne * h, 9))
            + morceau(b"IEND", b""))


def fabriquer(nom: str, l: int, h: int) -> tuple[bytes | None, str]:
    """(octets, raison). octets None = format impossible ici (raison dite)."""
    ext = Path(nom).suffix.lower()
    if ext == ".svg":
        return _svg(Path(nom).name, l, h), ""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        if ext == ".png":
            return _png_pur(l, h), ""
        return None, f"format {ext} : Pillow absent (pip install Pillow)"
    image = Image.new("RGB", (l, h), FOND)
    dessin = ImageDraw.Draw(image)
    texte = f"image provisoire : {Path(nom).name}"
    try:
        dessin.text((l / 2, h / 2), texte, fill=TEXTE, anchor="mm")
    except (ValueError, OSError):
        pass                           # tres petite image : sans texte
    formats = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".gif": "GIF",
               ".webp": "WEBP", ".bmp": "BMP", ".ico": "ICO",
               ".avif": "AVIF"}
    sortie = io.BytesIO()
    try:
        image.save(sortie, format=formats[ext])
    except (KeyError, OSError, ValueError) as exc:
        return None, f"format {ext} : non fabrique ({type(exc).__name__})"
    return sortie.getvalue(), ""
