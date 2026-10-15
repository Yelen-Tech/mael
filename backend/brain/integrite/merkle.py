"""Modules 1 + 5 du noyau d'integrite : scellement de la bibliotheque.

Meme philosophie que playbooks/sceau.json, etendue a TOUTE la bibliotheque :
chaque fiche est hachee (SHA-256, fins de ligne normalisees) et les
empreintes forment les feuilles d'un ARBRE DE MERKLE dont la racine engage
toute la bibliotheque en une seule valeur.

Pourquoi un arbre et pas une liste plate :
  - une seule valeur a publier/comparer (paquet « sur site », journal) ;
  - preuve d'appartenance d'une fiche en O(log n) : preuve(chemin) rend le
    chemin de hachage, verifier_preuve() le controle sans le sceau complet.

Construction (relecture 19/09/2026, Yelen Tech) : separation de domaine a la
RFC 6962 -- feuille = H(0x00 || chemin || 0x00 || empreinte du contenu),
noeud = H(0x01 || gauche || droite) ; un noeud impair remonte tel quel.
Sans cela : un noeud interne passait pour une fiche dans verifier_preuve,
et la duplication de la derniere feuille donnait la MEME racine a deux
bibliotheques differentes ([a, b, c] et [a, b, c, c'], cf. CVE-2012-2459).

Le sceau DETECTE, il ne verrouille pas : la relecture quotidienne modifie
les fiches. On re-scelle apres une relecture assumee :

    python -m brain.integrite --sceller     # re-ecrire le sceau
    python -m brain.integrite --merkle      # etat : racine, modifications
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

RACINE_BIBLIOTHEQUE = Path(__file__).resolve().parents[1] / "bibliotheque"
FICHES = RACINE_BIBLIOTHEQUE / "fiches"
SCEAU = RACINE_BIBLIOTHEQUE / "sceau.json"


def _empreinte(chemin: Path) -> str:
    """SHA-256 du contenu, fins de ligne normalisees (comme les playbooks)."""
    return hashlib.sha256(chemin.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _h(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def _feuille(chemin: str, empreinte: str) -> str:
    """Noeud feuille : lie le NOM de la fiche a son contenu (prefixe 0x00)."""
    return _h("\x00" + chemin + "\x00" + empreinte)


def _noeud(gauche: str, droite: str) -> str:
    """Noeud interne (prefixe 0x01) : jamais confondable avec une feuille."""
    return _h("\x01" + gauche + droite)


def noeuds_feuilles(f: dict[str, str]) -> list[str]:
    """Noeuds feuilles dans l'ordre canonique (chemins tries)."""
    return [_feuille(c, f[c]) for c in sorted(f)]


def feuilles() -> dict[str, str]:
    """chemin relatif -> empreinte, pour chaque fiche de la bibliotheque."""
    # as_posix : le chemin entre dans l'arbre ; avec str(), il valait
    # « a\b.yaml » sous Windows et « a/b.yaml » sous Linux — racine
    # differente, bibliotheque « alteree » chez tout utilisateur Linux
    # (CI sur Linux vierge, 12/10/2026).
    return {c.relative_to(FICHES).as_posix(): _empreinte(c)
            for c in sorted(FICHES.rglob("*.yaml"))}


def _monter(niveau: list[str]) -> list[str]:
    """Niveau superieur : couples haches, noeud impair remonte tel quel."""
    haut = [_noeud(niveau[i], niveau[i + 1])
            for i in range(0, len(niveau) - 1, 2)]
    if len(niveau) % 2:
        haut.append(niveau[-1])
    return haut


def racine_merkle(noeuds: list[str]) -> str:
    """Racine de l'arbre a partir des NOEUDS FEUILLES (noeuds_feuilles()).
    L'ordre est significatif (chemins tries). Liste vide -> empreinte du
    vide (documente)."""
    if not noeuds:
        return _h("")
    niveau = list(noeuds)
    while len(niveau) > 1:
        niveau = _monter(niveau)
    return niveau[0]


def calculer() -> dict:
    """Sceau calcule sur l'etat actuel : {racine, feuilles, cree_le}."""
    f = feuilles()
    return {"cree_le": date.today().isoformat(),
            "racine": racine_merkle(noeuds_feuilles(f)),
            "feuilles": f}


def sceller() -> dict:
    """Ecrit le sceau de l'etat actuel. A faire APRES relecture assumee."""
    sceau = calculer()
    SCEAU.write_text(json.dumps(sceau, indent=1, sort_keys=True) + "\n",
                     encoding="utf-8")
    return sceau


def controler() -> list[str]:
    """Ecarts entre le sceau et l'etat reel (vide = bibliotheque intacte)."""
    if not SCEAU.exists():
        return ["sceau.json absent : bibliotheque non scellee"]
    sceau = json.loads(SCEAU.read_text(encoding="utf-8"))
    attendues, reelles = sceau.get("feuilles", {}), feuilles()
    ecarts = []
    for chemin, emp in sorted(attendues.items()):
        if chemin not in reelles:
            ecarts.append(f"{chemin} : fiche manquante")
        elif reelles[chemin] != emp:
            ecarts.append(f"{chemin} : fiche modifiee")
    for chemin in sorted(set(reelles) - set(attendues)):
        ecarts.append(f"{chemin} : fiche ajoutee hors sceau")
    if not ecarts and sceau.get("racine") != racine_merkle(noeuds_feuilles(reelles)):
        ecarts.append("racine de Merkle incoherente avec les feuilles du sceau")
    return ecarts


# --------------------------------------------------------------------------- #
# Preuves d'appartenance (chemin de Merkle)
# --------------------------------------------------------------------------- #
def preuve(chemin: str, feuilles_sceau: dict[str, str] | None = None
           ) -> list[tuple[str, str]]:
    """Chemin de hachage d'une fiche : [(direction, empreinte_du_frere)...],
    de la feuille vers la racine. direction = « g » (frere a gauche) ou « d »."""
    f = feuilles_sceau if feuilles_sceau is not None else feuilles()
    if chemin not in f:
        raise KeyError(f"{chemin} : fiche inconnue")
    cles = sorted(f)
    niveau = noeuds_feuilles(f)
    index = cles.index(chemin)
    chemin_de_hachage = []
    while len(niveau) > 1:
        frere = index + 1 if index % 2 == 0 else index - 1
        if frere < len(niveau):             # noeud impair : pas de frere
            chemin_de_hachage.append(("d" if index % 2 == 0 else "g",
                                      niveau[frere]))
        index //= 2
        niveau = _monter(niveau)
    return chemin_de_hachage


def verifier_preuve(chemin: str, empreinte_feuille: str,
                    chemin_de_hachage: list[tuple[str, str]],
                    racine: str) -> bool:
    """Vrai si la preuve relie la fiche (chemin + empreinte de son
    contenu) a la racine attendue."""
    courant = _feuille(chemin, empreinte_feuille)
    for direction, frere in chemin_de_hachage:
        courant = (_noeud(frere, courant) if direction == "g"
                   else _noeud(courant, frere))
    return courant == racine
