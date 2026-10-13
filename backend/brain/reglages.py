"""Reglages de MAEL : ce que l'utilisateur choisit une fois pour toutes.

Jusqu'ici tout passait par des options de ligne de commande : il fallait les
retaper a chaque session. Les reglages sont maintenant ecrits dans un fichier
de l'utilisateur et relus au demarrage.

Trois regles :

  1. **l'ordre de priorite est fixe** : option de la ligne de commande >
     reglage enregistre > valeur par defaut. Ce qu'on tape maintenant gagne
     toujours sur ce qu'on a enregistre avant ;
  2. **rien d'inconnu n'entre** : chaque reglage est declare ici, avec son
     type et ses valeurs acceptees. Un fichier abime ou bricole ne peut pas
     faire demarrer MAEL dans un etat impossible -- on revient au defaut et
     on le DIT ;
  3. **aucun secret** : ce fichier ne contient que des preferences
     d'affichage et de conduite. Ni cle d'API, ni mot de passe, ni jeton.
     Une cle d'abonnement se range ailleurs, chiffree (etape 4 du plan).

Fichier : ~/.mael/reglages.json (MAEL_DOSSIER pour le deplacer).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Reglage:
    """Un reglage : ce qu'il vaut, ce qu'il accepte, ce qu'il veut dire."""
    defaut: object
    explication: str
    valeurs: tuple | None = None        # None = libre (texte)
    type_: type = str

    def valider(self, valeur):
        """Rend la valeur convertie, ou leve ValueError avec de quoi
        comprendre."""
        if self.type_ is bool:
            if isinstance(valeur, bool):
                return valeur
            texte = str(valeur).strip().lower()
            if texte in {"oui", "vrai", "1", "on", "true"}:
                return True
            if texte in {"non", "faux", "0", "off", "false"}:
                return False
            raise ValueError("attendu : oui ou non")
        if self.type_ is int:
            try:
                return int(valeur)
            except (TypeError, ValueError):
                raise ValueError("attendu : un nombre entier") from None
        valeur = str(valeur).strip()
        if self.valeurs and valeur not in self.valeurs:
            raise ValueError("attendu : " + ", ".join(self.valeurs))
        return valeur


def _profil_par_defaut() -> str:
    """Profil conseille par la machine. Jamais une exception : si la mesure
    echoue, on garde l'ancien defaut."""
    try:
        from . import machine
        return machine.profil_conseille()
    except Exception:            # noqa: BLE001 -- un reglage ne bloque rien
        return "complet"


CONNUS: dict[str, Reglage] = {
    "theme": Reglage("sombre", "couleurs du terminal",
                     ("sombre", "clair"), str),
    "couleurs": Reglage(True, "afficher les couleurs (non = texte brut)",
                        None, bool),
    "largeur_max": Reglage(100, "largeur maximale du texte, en colonnes",
                           None, int),
    # Le defaut depend de la MACHINE : sur un portable sans carte graphique,
    # le profil complet quadruple le temps de reponse (130 s -> 295 s, mesure
    # du 22/09). Un defaut fixe servait la machine du developpeur, pas celle
    # de l'utilisateur. Voir brain/machine.py.
    "profil": Reglage(_profil_par_defaut(),
                      "etendue du mode d'emploi envoye au modele",
                      ("court", "complet"), str),
    # Ces deux valeurs etaient les defauts des options de la ligne de
    # commande : les changer en passant aux reglages aurait modifie ce que
    # MAEL mesure, en silence. On les reprend telles quelles.
    "role": Reglage("expert", "role de modele utilise par defaut", None, str),
    # Vide = MAEL regarde ce qui est installe chez l'utilisateur et choisit
    # (brain/modeles.py). Rempli = ce nom-la gagne sur le defaut du code.
    "modele": Reglage("", "modele Ollama a utiliser (vide = choix automatique)",
                      None, str),
    "niveau": Reglage("1:intermediaire",
                      "niveau d'exigence des fiches (ex. « 2:renforce », "
                      "« tout »)", None, str),
    "perimetre": Reglage("", "perimetre d'audit par defaut", None, str),
    "executer": Reglage(False, "executer reellement les commandes de lecture",
                        None, bool),
    "details": Reglage(True, "afficher les lignes techniques (modele, duree, "
                             "jetons)", None, bool),
    "attente": Reglage(True, "indicateur d'activite pendant que le modele "
                             "reflechit", None, bool),
    "animation": Reglage(True, "orbe 3D anime pendant la reflexion, banniere "
                               "animee au demarrage (non = indicateur simple)",
                         None, bool),
    "interface": Reglage(True, "ecran plein : conversation qui defile, barre "
                               "de saisie fixe en bas (non = mode classique)",
                         None, bool),
    "historique": Reglage(True, "se souvenir des lignes tapees d'une session "
                                "a l'autre", None, bool),
}


def dossier() -> Path:
    """Dossier des reglages : ~/.mael, ou MAEL_DOSSIER s'il est defini."""
    force = os.environ.get("MAEL_DOSSIER")
    return Path(force) if force else Path.home() / ".mael"


def fichier() -> Path:
    return dossier() / "reglages.json"


def defauts() -> dict:
    return {nom: r.defaut for nom, r in CONNUS.items()}


def charger(chemin: Path | None = None) -> tuple[dict, list[str]]:
    """Rend (reglages, avertissements). Jamais d'exception : un fichier
    illisible ne doit pas empecher MAEL de demarrer -- il doit se PLAINDRE
    et repartir sur les valeurs par defaut."""
    chemin = chemin or fichier()
    valeurs, plaintes = defauts(), []
    if not chemin.exists():
        return valeurs, plaintes
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return valeurs, [f"{chemin} illisible ({exc}) : valeurs par defaut"]
    if not isinstance(brut, dict):
        return valeurs, [f"{chemin} : contenu inattendu, valeurs par defaut"]
    for nom, valeur in brut.items():
        reglage = CONNUS.get(nom)
        if reglage is None:
            plaintes.append(f"reglage inconnu ignore : « {nom} »")
            continue
        try:
            valeurs[nom] = reglage.valider(valeur)
        except ValueError as exc:
            plaintes.append(f"« {nom} » : {exc} — valeur par defaut gardee")
    return valeurs, plaintes


def enregistrer(valeurs: dict, chemin: Path | None = None) -> Path:
    """Ecrit les reglages connus (les autres sont ignores, pas recopies)."""
    chemin = chemin or fichier()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    propres = {nom: valeurs[nom] for nom in CONNUS if nom in valeurs}
    chemin.write_text(json.dumps(propres, ensure_ascii=False, indent=1) + "\n",
                      encoding="utf-8")
    return chemin


def appliquer_options(valeurs: dict, options: dict) -> dict:
    """Ligne de commande par-dessus les reglages enregistres.

    Une option absente ou laissee a sa valeur neutre ne doit PAS ecraser un
    reglage enregistre : sinon enregistrer un reglage ne servirait a rien."""
    resultat = dict(valeurs)
    for nom, valeur in options.items():
        if nom not in CONNUS or valeur in (None, "", False):
            continue
        try:
            resultat[nom] = CONNUS[nom].valider(valeur)
        except ValueError:
            continue
    return resultat


def decrire(valeurs: dict) -> list[str]:
    """Une ligne par reglage : nom, valeur, explication. Pour /parametres."""
    lignes = []
    for nom, reglage in CONNUS.items():
        valeur = valeurs.get(nom, reglage.defaut)
        if isinstance(valeur, bool):
            affichee = "oui" if valeur else "non"
        else:
            affichee = str(valeur) if str(valeur) else "—"
        choix = f" ({', '.join(reglage.valeurs)})" if reglage.valeurs else ""
        lignes.append(f"{nom:12s} {affichee:<10s} {reglage.explication}{choix}")
    return lignes


def modifier(valeurs: dict, nom: str, valeur: str) -> tuple[dict, str]:
    """Change un reglage ; rend (reglages, message pour l'humain)."""
    reglage = CONNUS.get(nom)
    if reglage is None:
        proches = [c for c in CONNUS if c.startswith(nom[:3])]
        piste = f" Peut-etre : {', '.join(proches)}." if proches else ""
        return valeurs, f"reglage inconnu : « {nom} ».{piste}"
    try:
        convertie = reglage.valider(valeur)
    except ValueError as exc:
        return valeurs, f"« {nom} » : {exc}"
    nouveaux = dict(valeurs)
    nouveaux[nom] = convertie
    affichee = ("oui" if convertie else "non") if isinstance(convertie, bool) \
        else convertie
    return nouveaux, f"{nom} = {affichee}"
