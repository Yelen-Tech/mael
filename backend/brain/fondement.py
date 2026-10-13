"""Un constat est-il fonde sur une observation ? (le code decide)

Vu en direct le 17/09/2026 : qwen2.5:3b a affirme « PermitRootLogin = yes,
critique » sans avoir lance une seule commande. Un audit qui invente ses
constats ne vaut rien. Regle :

  FONDE     -- il existe au moins une PREUVE liee au sujet du constat :
               une commande reellement executee, ou une preuve deposee par
               l'humain (/preuve). Lien = meme fiche de la bibliotheque, ou
               un terme technique commun (permitrootlogin, sshd, 5432...).
  NON FONDE -- aucune preuve, ou aucune preuve sur ce sujet. Le constat est
               garde comme HYPOTHESE : il ne fait pas avancer l'audit et le
               modele est renvoye observer.

Limite assumee : « fonde » veut dire « une observation sur le sujet existe »,
pas « la conclusion est juste ». Lire la sortie reste le travail du modele et
de l'humain.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Callable

from brain import bibliotheque
from brain.bibliotheque.verification import verifier

# Mots trop generaux pour lier un constat a une commande.
_GENERIQUES = {
    "commande", "directive", "valeur", "fichier", "fichiers", "present",
    "presente", "absent", "absente", "active", "actif", "etat", "prend",
    "etre", "cette", "celle", "dans", "avec", "pour", "sans", "plus",
    "moins", "tous", "tout", "toute", "toutes", "peut", "doit", "mettre",
    "risque", "gravite", "action", "constat", "critique", "elevee", "moyenne",
    "faible", "serveur", "service", "systeme", "machine", "configuration",
    "acces", "securite", "attaque", "attaques", "autres", "formes",
    # utilitaires et bruit de ligne de commande
    "sudo", "grep", "egrep", "tail", "head", "sort", "uniq", "echo", "null",
    "pager", "since", "hours", "print", "true", "false",
}


def _normaliser(texte: str) -> str:
    texte = unicodedata.normalize("NFD", (texte or "").lower())
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


def termes(texte: str) -> set[str]:
    """Termes techniques : mots de 4+ caracteres non generiques, et nombres
    de 2 a 5 chiffres (ports) -- les nombres ne sont pris que dans un texte
    court et intentionnel (constat, commande), jamais dans une sortie."""
    bas = _normaliser(texte)
    mots = {m for m in re.findall(r"[a-z][a-z0-9]{3,}", bas)
            if m not in _GENERIQUES}
    nombres = set(re.findall(r"(?<![\d.])\d{2,5}(?![\d.])", bas))
    return mots | nombres


def _fiches_du_texte(texte: str) -> set[str]:
    return {f.id for f in bibliotheque.chercher(texte, n=2)}


def juger(texte_constat: str, commandes_executees: list[str],
          preuves_humaines: list[str]) -> tuple[bool, str]:
    """(fonde, motif lisible)."""
    if not commandes_executees and not preuves_humaines:
        return False, "aucune observation executee dans cet audit"

    fiches_constat = _fiches_du_texte(texte_constat)
    termes_constat = termes(texte_constat)

    for cmd in commandes_executees:
        communes = fiches_constat & set(verifier(cmd).fiches)
        if communes:
            return True, f"observe par « {cmd} » (fiche {sorted(communes)[0]})"
        if termes_constat & termes(cmd):
            return True, f"observe par « {cmd} »"

    for preuve in preuves_humaines:
        if (termes_constat & termes(preuve)
                or fiches_constat & _fiches_du_texte(preuve)):
            return True, "preuve deposee par l'humain"

    n = len(commandes_executees)
    return False, (f"aucune observation sur ce sujet ({n} commande(s) "
                   f"executee(s), sans rapport)")


def juge_pour(memoire) -> Callable[[str], tuple[bool, str]]:
    """Juge lie a un audit : relit ses commandes executees et ses preuves au
    moment de l'appel (elles evoluent pendant la session)."""
    def _juge(texte: str) -> tuple[bool, str]:
        executees = [c.commande for c in memoire.commandes if c.executee]
        return juger(texte, executees, list(memoire.preuves))
    return _juge
