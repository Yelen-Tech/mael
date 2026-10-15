"""Schema des fiches de connaissances (etape 2 du plan : les langages).

Les connaissances sont du savoir GENERAL (caracteristiques d'un langage,
pieges de securite classiques), PAS des fiches de controle : pas de
commandes, pas d'evaluation. Le schema est donc propre a ce module, dans le
meme esprit que brain.bibliotheque.schema : c'est le CODE qui refuse une
fiche douteuse avant qu'elle n'atteigne le modele.

    valider(donnees, chemin) -> (erreurs, avertissements)

- ERREUR : la fiche est ecartee au chargement.
- AVERTISSEMENT : la fiche est chargee mais imparfaite (liste de travail).

Rapport de toutes les connaissances :
    python -m brain.connaissances.schema
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

SCHEMA_ACTUEL = 1

# Familles de connaissances (plan de developpement) : « langage » (etape 2), puis les
# familles scientifiques et humaines des etapes 3 a 6.
FAMILLES = {"langage", "mathematiques", "physique", "chimie",
            "histoire-geographie", "astronomie"}
ETATS = {"brouillon", "verifie", "obsolete"}
GRAVITES = {"info", "moyenne", "elevee", "critique"}

_RE_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _texte(donnees: dict, cle: str, erreurs: list[str], ou: str = "") -> None:
    v = donnees.get(cle)
    if not isinstance(v, str) or not v.strip():
        erreurs.append(f"{ou}champ « {cle} » manquant ou vide")


def valider(donnees: dict, chemin: Path | None = None,
            ) -> tuple[list[str], list[str]]:
    """Rend (erreurs, avertissements). Aucune erreur = fiche chargeable."""
    erreurs: list[str] = []
    avert: list[str] = []
    if not isinstance(donnees, dict):
        return ["la fiche n'est pas un objet YAML"], []

    # --- identite ---------------------------------------------------------
    fid = donnees.get("id")
    if not isinstance(fid, str) or not _RE_ID.match(fid or ""):
        erreurs.append("« id » manquant ou invalide (minuscules-et-tirets)")
    elif chemin is not None and chemin.stem != fid:
        erreurs.append(f"l'id « {fid} » ne correspond pas au fichier "
                       f"« {chemin.name} »")
    if donnees.get("schema") != SCHEMA_ACTUEL:
        erreurs.append(f"« schema » doit valoir {SCHEMA_ACTUEL}")
    _texte(donnees, "nom", erreurs)
    resume = donnees.get("resume")
    if not isinstance(resume, str) or not resume.strip():
        erreurs.append("champ « resume » manquant ou vide")
    elif len(resume) > 300:
        erreurs.append("« resume » depasse 300 caracteres")
    if donnees.get("famille") not in FAMILLES:
        erreurs.append(f"famille « {donnees.get('famille')} » inconnue "
                       f"(attendu : {', '.join(sorted(FAMILLES))})")

    # --- cycle de vie -----------------------------------------------------
    if not isinstance(donnees.get("version"), int) or donnees["version"] < 1:
        erreurs.append("« version » doit etre un entier >= 1")
    etat = donnees.get("etat")
    if etat not in ETATS:
        erreurs.append(f"etat « {etat} » inconnu "
                       f"({', '.join(sorted(ETATS))})")
    verifie_le = donnees.get("verifie_le")
    if verifie_le is not None:
        try:
            jour = (verifie_le if isinstance(verifie_le, date)
                    else date.fromisoformat(str(verifie_le)))
            if jour > date.today():
                erreurs.append("« verifie_le » est dans le futur")
        except ValueError:
            erreurs.append("« verifie_le » doit etre une date AAAA-MM-JJ")
        if etat != "verifie":
            avert.append("« verifie_le » present sans etat « verifie »")
    elif etat == "verifie":
        erreurs.append("une fiche « verifie » doit dater sa relecture "
                       "(verifie_le)")

    # --- retrouvabilite ---------------------------------------------------
    mots_cles = donnees.get("mots_cles")
    if (not isinstance(mots_cles, list) or not mots_cles
            or not all(isinstance(m, str) and m.strip() for m in mots_cles)):
        erreurs.append("« mots_cles » doit etre une liste non vide de textes")

    # --- caracteristiques -------------------------------------------------
    carac = donnees.get("caracteristiques")
    if not isinstance(carac, dict):
        erreurs.append("« caracteristiques » doit etre un dictionnaire")
    elif donnees.get("famille") == "langage":
        # Un langage se decrit toujours de la meme facon : comparabilite.
        paradigmes = carac.get("paradigmes")
        if (not isinstance(paradigmes, list) or not paradigmes
                or not all(isinstance(p, str) and p.strip()
                           for p in paradigmes)):
            erreurs.append("caracteristiques : « paradigmes » doit etre une "
                           "liste non vide de textes")
        for cle in ("typage", "execution", "memoire"):
            _texte(carac, cle, erreurs, ou="caracteristiques : ")
    else:
        # Autres familles : au moins trois notions cle -> texte.
        notions = [(k, v) for k, v in carac.items()
                   if isinstance(k, str) and isinstance(v, str)
                   and k.strip() and v.strip()]
        if len(notions) < 3:
            erreurs.append("caracteristiques : au moins trois notions "
                           "cle -> texte")

    # --- points de securite -----------------------------------------------
    # Pour les familles hors « langage », ce sont les points de vigilance :
    # pieges classiques du sujet et consequences pratiques en informatique
    # (titre, risque, conseil, gravite = criticite de l'erreur).
    securite = donnees.get("securite")
    if not isinstance(securite, list) or not securite:
        erreurs.append("« securite » : au moins un point de securite")
        securite = []
    for i, point in enumerate(securite, 1):
        ou = f"securite #{i} : "
        if not isinstance(point, dict):
            erreurs.append(f"{ou}doit etre un dictionnaire")
            continue
        for cle in ("titre", "risque", "conseil"):
            _texte(point, cle, erreurs, ou=ou)
        if point.get("gravite") not in GRAVITES:
            erreurs.append(f"{ou}gravite « {point.get('gravite')} » inconnue "
                           f"({', '.join(sorted(GRAVITES))})")

    # --- sources ----------------------------------------------------------
    sources = donnees.get("sources")
    if not isinstance(sources, list) or not sources:
        erreurs.append("« sources » : au moins une source officielle")
        sources = []
    for i, source in enumerate(sources, 1):
        ou = f"source #{i} : "
        if not isinstance(source, dict):
            erreurs.append(f"{ou}doit etre un dictionnaire")
            continue
        _texte(source, "titre", erreurs, ou=ou)
        url = source.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            erreurs.append(f"{ou}« url » doit commencer par https://")

    return erreurs, avert


def _dossier() -> Path:
    """Racine des connaissances ; un sous-dossier par famille
    (`langages/`, puis les autres familles du plan)."""
    return Path(__file__).resolve().parent


def rapport() -> tuple[int, str]:
    """Valide toutes les connaissances : (nb erreurs, texte du rapport)."""
    import yaml

    lignes, nb_err, nb_fiches, par_etat, ids = [], 0, 0, {}, {}
    for chemin in sorted(_dossier().rglob("*.yaml")):
        nb_fiches += 1
        try:
            donnees = yaml.safe_load(chemin.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            erreurs, avert, donnees = [f"YAML illisible : {exc}"], [], None
        else:
            erreurs, avert = valider(donnees, chemin)
            fid = (donnees or {}).get("id") if isinstance(donnees, dict) \
                else None
            if fid is not None:
                if fid in ids:
                    erreurs.append(f"id en double avec {ids[fid]}")
                ids[fid] = chemin.name
        etat = ((donnees or {}).get("etat", "?")
                if isinstance(donnees, dict) else "illisible")
        par_etat[etat] = par_etat.get(etat, 0) + 1
        nb_err += len(erreurs)
        lignes.append(f"{chemin.name} : {'ECARTEE' if erreurs else 'ok'}")
        lignes += [f"   ERREUR  {e}" for e in erreurs]
        lignes += [f"   a faire {a}" for a in avert]
    compte = ", ".join(f"{e} : {n}" for e, n in sorted(par_etat.items()))
    lignes.append(f"\n{nb_fiches} fiche(s) ({compte}), {nb_err} erreur(s)")
    return nb_err, "\n".join(lignes)


if __name__ == "__main__":
    import sys

    for flux in (sys.stdout,):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    nb_err, texte = rapport()
    print(texte)
    sys.exit(1 if nb_err else 0)
