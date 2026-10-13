"""Les LEVIERS : ce que MAEL sait changer en lui-meme apres une relecture.

3e essai reel de la relecture (08/10/2026) : les lecons acceptees par le
juge restaient des bonnes intentions (« assure-toi que les consignes sont
suivies ») — vraies, mais rien a appliquer : le modele avait deja ces
consignes. Une lecon est donc desormais le CHOIX d'un levier dans ce
catalogue : une action precise du programme de MAEL ou de ses consignes,
que l'etape « appliquer » sait mettre en oeuvre, et que la relance des
missions peut verifier.

C'est toujours MAEL (le modele) qui choisit le levier, d'apres les faits ;
le catalogue borne seulement ce qui est applicable. Quand aucun levier ne
convient, il le dit (« AUCUN ») et propose le sien : c'est un levier
MANQUANT, note pour le responsable, jamais applique en silence.

Un levier agit soit sur une CONSIGNE (le texte envoye au modele), soit sur
le PROGRAMME de MAEL (lecteur du plan, criteres, reparations sans modele).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Levier:
    id: str
    origine: str                  # consigne | programme : ce qu'il change
    action: str                   # ce que MAEL fera, une phrase
    familles: tuple[str, ...]     # les faiblesses qu'il peut corriger


CATALOGUE: tuple[Levier, ...] = (
    # --- liens, menu, ressources : criteres ecrits mais non tenus
    Levier("rappel-criteres-en-fin", "consigne",
           "rappeler, a la FIN de la consigne d'une tache, la liste exacte "
           "des criteres (liens, feuille de style, script) a tenir",
           ("lien-navigation-manquant", "ressource-non-chargee",
            "structure-de-page")),
    Levier("menu-commun-a-recopier", "consigne",
           "donner a chaque page le bloc <nav> exact du menu commun, avec "
           "les liens vers toutes les pages du plan, a recopier tel quel",
           ("lien-navigation-manquant",)),
    Levier("reparer-liens-du-menu", "programme",
           "ajouter moi-meme (sans modele) dans le <nav> d'une page les "
           "liens manquants vers les pages du plan",
           ("lien-navigation-manquant",)),
    Levier("reparer-ressources-du-head", "programme",
           "ajouter moi-meme (sans modele) dans le <head> le <link> ou le "
           "<script> du plan qui manque",
           ("ressource-non-chargee",)),
    # --- en-tete et pied de page traites comme des pages
    Levier("fragments-sans-criteres-de-page", "programme",
           "ne plus exiger <main>, <h1> ni le menu complet d'un morceau de "
           "page (header.html, footer.html, nav.html)",
           ("fragment-traite-en-page",)),
    Levier("plan-sans-fragments", "consigne",
           "dire au chef de chantier qu'un en-tete ou un pied de page n'est "
           "pas un fichier a part : il s'ecrit dans chaque page",
           ("fragment-traite-en-page",)),
    # --- le plan
    Levier("plan-chemins-tolerants", "programme",
           "faire accepter au lecteur du plan un chemin qui commence par "
           "« / », en retirant ce « / »",
           ("plan-illisible",)),
    Levier("plan-chemins-relatifs", "consigne",
           "ecrire dans la consigne du plan : chemins relatifs, jamais de "
           "« / » au debut",
           ("plan-illisible",)),
    Levier("plan-selon-la-demande", "consigne",
           "ne plus pousser le plan vers des pages HTML quand la demande est "
           "une API ou un programme sans pages",
           ("plan-illisible",)),
    # --- fichier jamais ecrit (ecriture coupee)
    Levier("ecrire-en-plusieurs-fois", "programme",
           "ecrire un fichier coupe parce que trop long en plusieurs "
           "parties, puis les assembler",
           ("fichier-du-plan-jamais-ecrit",)),
    Levier("fichier-court-demande", "consigne",
           "demander, pour un fichier deja coupe, une version courte (nombre "
           "de lignes limite, l'essentiel d'abord)",
           ("fichier-du-plan-jamais-ecrit",)),
    Levier("feuille-de-secours", "programme",
           "ecrire moi-meme une feuille de style minimale et juste quand "
           "celle du modele echoue, pour que les pages ne soient pas cassees",
           ("fichier-du-plan-jamais-ecrit",)),
    # --- liens vers des fichiers inexistants
    Levier("liens-du-plan-seulement", "consigne",
           "ecrire dans la consigne : un lien interne ne vise qu'un fichier "
           "du plan (liste donnee)",
           ("lien-casse",)),
    Levier("reparer-lien-hors-plan", "programme",
           "retirer moi-meme (sans modele) un lien interne qui ne vise aucun "
           "fichier du plan ni du projet",
           ("lien-casse",)),
    # --- accessibilite
    Levier("palette-mesuree", "consigne",
           "donner a la tache CSS des couleurs deja mesurees (contraste 4,5:1 "
           "au moins), liens dans le texte soulignes",
           ("contraste",)),
    Levier("reparer-liens-soulignes", "programme",
           "souligner moi-meme les liens places dans un texte quand leur "
           "couleur seule ne suffit pas a les distinguer",
           ("contraste",)),
    Levier("cibles-24px-dans-la-consigne", "consigne",
           "ecrire dans la consigne CSS : boutons et liens d'au moins 24 px "
           "de haut et de large",
           ("cible-trop-petite",)),
    Levier("reparer-cibles-24px", "programme",
           "ajouter moi-meme a la feuille de style une taille minimale de "
           "24 px aux boutons et aux liens",
           ("cible-trop-petite",)),
    # --- angles morts du navigateur (angles_morts.py) : MAEL les corrige
    Levier("reessayer-page-expiree", "programme",
           "donner une seconde chance, delai double, a une page qui depasse "
           "son delai d'ouverture dans le navigateur",
           ("page-expiree",)),
    Levier("budget-selon-les-pages", "programme",
           "adapter le temps du navigateur au nombre de pages (60 s par "
           "page, 10 min au plus) au lieu de 120 s pour tout le projet",
           ("pages-hors-budget",)),
    # --- scripts
    Levier("ids-des-pages-au-script", "consigne",
           "donner au script la liste exacte des id presents dans les pages, "
           "et lui interdire d'en viser d'autres",
           ("script-plante",)),
    Levier("script-garde-ses-elements", "consigne",
           "exiger du script qu'il verifie chaque element trouve avant de "
           "s'en servir (sinon il s'arrete sans erreur)",
           ("script-plante",)),
)

PAR_ID = {l.id: l for l in CATALOGUE}
AUCUN = "AUCUN"


def pour(famille: str) -> list[Levier]:
    """Les leviers proposes au modele pour cette faiblesse."""
    return [l for l in CATALOGUE if famille in l.familles]


def en_texte(leviers: list[Levier]) -> str:
    return "\n".join(f"{i}. {l.id} ({l.origine}) : {l.action}"
                     for i, l in enumerate(leviers, 1))


# ------------------------------------------------- l'etape APPLIQUER
# Les leviers mis en oeuvre a ce jour. Un levier accepte mais pas encore
# programme reste « en attente » : la verification le dit, sans le compter.
APPLIQUES = {"liens-du-plan-seulement", "palette-mesuree",
             "cibles-24px-dans-la-consigne", "ecrire-en-plusieurs-fois",
             "reessayer-page-expiree", "budget-selon-les-pages",
             # Programmes le 09/10 (examen : solutions connues non appliquees)
             # et toujours actifs : ce sont des reparations sures.
             "reparer-ressources-du-head", "reparer-liens-du-menu",
             "reparer-lien-hors-plan", "reparer-cibles-24px"}

# Couleurs MESUREES (bac_a_sable.contraste, 08/10/2026) : WCAG 4,5:1 exige.
PALETTE = (("texte", "#1f2937", "#ffffff", 14.68),
           ("liens", "#1d4ed8", "#ffffff", 6.70),
           ("boutons (texte sur fond)", "#ffffff", "#1d4ed8", 6.70),
           ("texte secondaire", "#4b5563", "#ffffff", 7.56),
           ("texte sur fond clair #f3f4f6", "#1f2937", "#f3f4f6", 13.34))


def retenus(chemin: Path, etats: set[str]) -> set[str]:
    """Les leviers de lecons.yaml dont l'etat est dans `etats`, et que MAEL
    sait deja appliquer."""
    try:
        donnees = yaml.safe_load(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return set()
    return {l.get("levier", "") for l in (donnees or {}).get("lecons", [])
            if l.get("etat") in etats} & APPLIQUES


def consignes(actifs: set[str], fichier: str, pages: list[str]
              ) -> list[tuple[str, str]]:
    """(levier, texte) a ajouter a la consigne d'une tache, selon le type
    de son fichier. Seuls les leviers ACTIFS (lecons retenues) parlent."""
    ext = fichier.rsplit(".", 1)[-1].lower()
    out = []
    if "liens-du-plan-seulement" in actifs and ext in {"html", "htm"}:
        out.append(("liens-du-plan-seulement",
                    "un lien interne (href) ne vise QUE l'un de ces "
                    f"fichiers : {', '.join(pages)}. Aucune autre page "
                    "(pas de /mentions-legales, /produits, /contact…). Un "
                    "lien externe (https://, mailto:, tel:) reste permis."))
    if ext == "css":
        if "palette-mesuree" in actifs:
            out.append(("palette-mesuree",
                        "utilise ces couleurs, deja mesurees : "
                        + " ; ".join(f"{n} {c} sur {f} ({r:.1f}:1)"
                                     for n, c, f, r in PALETTE)
                        + ". Les liens places dans un texte sont soulignes "
                          "(text-decoration: underline)."))
        if "cibles-24px-dans-la-consigne" in actifs:
            out.append(("cibles-24px-dans-la-consigne",
                        "chaque bouton, lien de menu et champ de formulaire "
                        "fait au moins 24 px de haut et de large : "
                        "min-height: 24px; min-width: 24px; (ou un padding "
                        "qui l'assure)."))
    return out


# ------------------------------- les regles TOUJOURS donnees (09/10/2026)
# Examen des 100 missions : douze leviers etaient au catalogue, choisis par
# la relecture, mais jamais programmes — le defaut revenait (script qui vise
# #services absent, pied de page juge comme une page...). Les leviers
# « consigne » ci-dessous sont desormais TOUJOURS donnes au modele : ce sont
# des faits du projet (pages, id, criteres), pas des preferences.
TOUJOURS = {"rappel-criteres-en-fin", "menu-commun-a-recopier",
            "ids-des-pages-au-script", "script-garde-ses-elements",
            "fichier-court-demande", "plan-sans-fragments",
            "plan-chemins-relatifs", "plan-selon-la-demande",
            "plan-chemins-tolerants", "fragments-sans-criteres-de-page",
            "feuille-de-secours", "reparer-liens-soulignes"}
APPLIQUES |= TOUJOURS
LIGNES_MAX = {".css": 150, ".js": 120, ".mjs": 120}


def _nom_de_page(page: str) -> str:
    stem = Path(page).stem
    if stem.lower() in {"index", "accueil", "home"}:
        return "Accueil"
    return stem.replace("-", " ").replace("_", " ").strip().capitalize()


def menu_commun(fichier: str, pages: list[str]) -> str:
    """Le bloc <nav> exact, liens relatifs depuis `fichier`."""
    import posixpath
    ici = posixpath.dirname(fichier) or "."
    items = "".join(
        f'<li><a href="{posixpath.relpath(p, ici)}"'
        + (' aria-current="page"' if p == fichier else "")
        + f">{_nom_de_page(p)}</a></li>" for p in pages)
    return f'<nav aria-label="Menu principal"><ul>{items}</ul></nav>'


def regles(fichier: str, pages: list[str], ids: list[str],
           criteres: list[str]) -> list[tuple[str, str]]:
    """(levier, texte) des regles toujours donnees pour CE fichier."""
    ext = Path(fichier).suffix.lower()
    out = []
    if ext in {".html", ".htm", ".php"} and len(pages) >= 2:
        out.append(("menu-commun-a-recopier",
                    "recopie TEL QUEL ce menu commun dans le <header> : "
                    + menu_commun(fichier, pages)))
    if ext in {".js", ".mjs"}:
        out.append(("ids-des-pages-au-script",
                    "les id presents dans les pages sont : "
                    + (", ".join(f"#{i}" for i in ids) or "(aucun)")
                    + ". Ne vise AUCUN autre id."))
        out.append(("script-garde-ses-elements",
                    "verifie chaque element avant de t'en servir : "
                    "const el = document.getElementById('x'); "
                    "if (!el) return;"))
    if ext in LIGNES_MAX:
        out.append(("fichier-court-demande",
                    f"fichier COURT : {LIGNES_MAX[ext]} lignes au plus, "
                    "l'essentiel d'abord, et ferme le bloc avec ```"))
    if criteres:
        out.append(("rappel-criteres-en-fin",
                    "AVANT de fermer le bloc, verifie que tu tiens : "
                    + " ; ".join(criteres)))
    return out


def lire(reponse: str, proposes: list[Levier]) -> str:
    """Le levier choisi : son id, un numero de la liste, ou AUCUN ; ""
    s'il n'est pas reconnu."""
    r = reponse.strip().strip("`*«» .").lower()
    if not r:
        return ""
    if r.startswith(AUCUN.lower()):
        return AUCUN
    if r.split(".")[0].split()[0].isdigit():
        n = int(r.split(".")[0].split()[0])
        return proposes[n - 1].id if 1 <= n <= len(proposes) else ""
    return next((l.id for l in proposes if l.id in r),
                next((l.id for l in CATALOGUE if l.id in r), ""))
