"""La boucle de l'atelier : savoir -> ecriture -> juges -> correction -> bilan.

    F = f0 . (1 - k) . (1 - v)^n        (doc 15, la loi de MAEL)

    k : le savoir donne AVANT d'ecrire (consignes de norme, gabarits) ;
    v : les juges APRES (juges.py) ;
    n : les tours de correction, bornes (TOURS_MAX).

Le prompt systeme est FIGE pour toute la session : il ne contient ni l'etat
ni la demande. Ollama garde donc sa lecture en cache d'un tour a l'autre
(gain mesure le 22/09 : ~28 s par question sur la machine visee). Tout ce
qui change passe dans les messages.

Deux portes :
    ecrire(...)   la demande devient des fichiers jugés ;
    assister(...) un projet existant est juge, puis corrige SI on le demande.
Le bilan ne dit « conforme » que si aucun defaut bloquant ne reste, et il
liste toujours ce que les juges n'ont PAS pu verifier.
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from typing import Callable

from . import demande as fidelite
from . import juges, reparation
from .espace import CheminRefuse, Espace
from .extraction import extraire
from .juges import GRAVITE, Defaut
from .remedes import remede

TOURS_MAX = 3            # au-dela, le gain est faible et l'attente longue
DEFAUTS_PAR_RELANCE = 12  # un petit modele noye sous 40 defauts n'en corrige aucun

SYSTEME = """Tu es MAEL, atelier de code. Tu ecris du code complet, juste et sur.

FORMAT OBLIGATOIRE — chaque fichier dans son propre bloc, nom en en-tete :
```html fichier=index.html
...contenu COMPLET du fichier...
```
Jamais de « ... », jamais « reste du code » : un fichier est ecrit en entier.
Chemins relatifs uniquement (index.html, css/style.css, js/app.js).

NORMES (des juges automatiques les verifient ; chaque ecart te sera renvoye) :
- HTML : <!DOCTYPE html>, <html lang="fr">, <meta charset="utf-8">,
  <meta name="viewport" content="width=device-width, initial-scale=1">,
  <title>, un seul <h1>, un <main>, titres sans niveau saute.
- Accessibilite (WCAG 2.2) : alt sur chaque <img> ; chaque champ a un
  <label for> ; liens et boutons ont un texte ; focus visible ; zoom permis.
- Securite (OWASP) : aucun secret dans le code ; pas d'eval ; pas
  d'innerHTML avec des donnees (textContent) ; pas de onclick= (utiliser
  addEventListener) ; https ; mot de passe en method="post" ; SQL toujours
  parametre ; pas de shell=True.
- Tout fichier reference (css, js, image) doit exister ou etre ecrit.

Quand on te renvoie des defauts : reecris EN ENTIER chaque fichier fautif,
corrige TOUS les defauts listes, ne casse rien d'autre. Explique en une ou
deux phrases maximum, en francais."""


@dataclass
class Tour:
    numero: int
    fichiers: list[str]
    bloquants: int
    conseils: int
    refus: list[str] = field(default_factory=list)
    # Corrections sures appliquees par MAEL lui-meme (reparation.py), sans
    # rappeler le modele.
    reparations: list[str] = field(default_factory=list)
    tache: str = ""             # chantier : le fichier de la tache
    secondes: float = 0.0       # duree de l'appel au modele
    mode: str = ""              # chantier : ecriture / retouche / reecriture


@dataclass
class Bilan:
    racine: str
    tours: list[Tour] = field(default_factory=list)
    defauts: list[Defaut] = field(default_factory=list)
    fichiers: list[str] = field(default_factory=list)
    limites: list[str] = field(default_factory=list)
    explication: str = ""
    arret: str = ""
    plan: list[str] = field(default_factory=list)   # chantier
    # Images creees par MAEL a la place des photos absentes (option A) :
    # a remplacer par les vraies, et le bilan le dit.
    provisoires: list[str] = field(default_factory=list)
    # Ce que MAEL a compris ou decide a la place du developpeur (fautes
    # corrigees, langue, demande vague, contradictions) : a confirmer.
    suppositions: list[str] = field(default_factory=list)
    # Les lecons appliquees (leviers.py) et combien de fois chacune a servi.
    leviers: dict[str, int] = field(default_factory=dict)
    # Le temps passe a juger, et les specialistes appeles (chantier).
    jugement: float = 0.0
    specialistes: dict[str, int] = field(default_factory=dict)
    # Le conseil des professeurs : ses appels (deliberation, doyen).
    appels_conseil: int = 0
    # Le verdict final du conseil sur les juges (conseil_juges.py).
    conseil: str = ""
    # La memoire de travail (memoire.py) : chaque probleme restant et
    # POURQUOI il reste ; et combien ont ete resolus en route.
    memoire: list[str] = field(default_factory=list)
    resolus: int = 0
    # La logistique (logistique.py) : rangement standard et fichiers
    # ecrits par MAEL lui-meme (README, .gitignore...).
    logistique: list[str] = field(default_factory=list)
    # Le chantier par etapes (etapes.py) : ce que chaque etape a livre.
    etapes: list[str] = field(default_factory=list)

    @property
    def bloquants(self) -> list[Defaut]:
        return [d for d in self.defauts if d.gravite is GRAVITE.BLOQUANT]

    @property
    def conforme(self) -> bool:
        return bool(self.fichiers) and not self.bloquants


def _consigne_lien_casse(d: Defaut, fichiers: list[str]) -> str:
    """Un lien casse ne se corrige pas « en general » : le modele ne voit
    pas le dossier. On lui dit QUEL chemin ecrire (premier essai reel du
    07/10/2026 : phi4-mini avait ecrit style.css a la racine pour une page
    qui appelait css/style.css, et n'a pas su corriger seul)."""
    m = re.search(r'="([^"]+)"', d.message)
    if not m:
        return ""
    lien = m.group(1).split("#")[0].split("?")[0]
    dossier = posixpath.dirname(d.fichier)
    cible = posixpath.normpath(posixpath.join(dossier, lien))
    homonymes = [f for f in fichiers
                 if posixpath.basename(f) == posixpath.basename(cible)]
    if homonymes:
        juste = posixpath.relpath(homonymes[0], dossier or ".")
        return (f"  a faire : « {homonymes[0]} » existe deja -> dans "
                f"{d.fichier}, remplace \"{m.group(1)}\" par \"{juste}\"")
    return (f"  a faire : ecris le fichier « {cible} » (ce chemin exact, "
            f"dans un bloc qui porte ce nom), ou retire la balise de "
            f"{d.fichier} si ce fichier n'est pas utile")


def message_correction(defauts: list[Defaut],
                       fichiers: list[str] | None = None) -> str:
    """Le retour des juges au modele : defaut, ligne, norme, ET remede.
    `fichiers` : les fichiers du projet, pour corriger les liens casses."""
    bloquants = [d for d in defauts if d.gravite is GRAVITE.BLOQUANT]
    montres = bloquants[:DEFAUTS_PAR_RELANCE]
    lignes = [f"[juges] {len(bloquants)} defaut(s) bloquant(s). Corrige-les "
              "tous et reecris EN ENTIER chaque fichier concerne."]
    for d in montres:
        r = remede(d.regle)
        lignes.append(f"- {d.fichier} ligne {d.ligne} : {d.message} "
                      f"[{d.norme}]" + (f"\n  forme juste : {r}" if r else ""))
        if d.regle == "fichier-absent" and fichiers is not None:
            consigne = _consigne_lien_casse(d, fichiers)
            if consigne:
                lignes.append(consigne)
    if fichiers is not None and any(d.regle == "fichier-absent"
                                    for d in montres):
        lignes.append("fichiers qui existent dans le projet : "
                      + (", ".join(fichiers) or "aucun"))
    if len(bloquants) > len(montres):
        lignes.append(f"(+ {len(bloquants) - len(montres)} autre(s), "
                      "renvoye(s) au tour suivant)")
    # Le defaut le plus frequent recoit, en plus du remede d'une ligne, la
    # forme juste complete tiree des gabarits : la correction converge en un
    # tour au lieu de trois (terme n de la loi).
    if montres:
        from collections import Counter

        from . import normes, savoir
        for regle, _ in Counter(d.regle for d in montres).most_common():
            exemple = savoir.pour_regle(regle)
            if exemple:
                lignes.append(exemple)
                break
        # Et la raison de la norme pour le defaut le plus frequent : un
        # modele qui comprend POURQUOI ne refait pas la faute ailleurs.
        regle = Counter(d.regle for d in montres).most_common(1)[0][0]
        pourquoi = normes.pour_regle(regle)
        if pourquoi:
            lignes.append(pourquoi)
    return "\n".join(lignes)


def _contenu_projet(espace: Espace, noms: list[str], budget: int = 12_000
                    ) -> str:
    """Les fichiers a corriger, montres au modele, sous un budget en
    caracteres (le contexte d'un petit modele est court)."""
    morceaux, total = [], 0
    for nom in noms:
        try:
            texte = espace.lire(nom)
        except (OSError, CheminRefuse):
            continue
        if total + len(texte) > budget:
            morceaux.append(f"(fichier {nom} trop long pour etre montre "
                            "en entier)")
            continue
        total += len(texte)
        langage = nom.rsplit(".", 1)[-1]
        morceaux.append(f"```{langage} fichier={nom}\n{texte.rstrip()}\n```")
    return "\n\n".join(morceaux)


class Atelier:
    """Une session d'atelier sur un espace. Le moteur (backend) est celui
    du reste de MAEL : on ne parle jamais a un modele par son nom ici."""

    def __init__(self, backend, espace: Espace, *, role: str = "codeur",
                 savoir: Callable[[str], str] | None = None,
                 tours_max: int = TOURS_MAX,
                 annoncer: Callable[[str], None] | None = None,
                 reparer_auto: bool = True):
        self.backend = backend
        self.espace = espace
        self.role = role
        self.savoir = savoir
        self.tours_max = tours_max
        self.annoncer = annoncer or (lambda _m: None)
        self.messages: list[dict] = []
        self.demande = ""        # ce que l'utilisateur a demande (ecrire)
        self.reparer_auto = reparer_auto

    # ------------------------------------------------------------ communs
    def _juger(self) -> tuple[list[Defaut], list[str]]:
        return juges.juger_projet(self.espace.racine)

    def _juger_tour(self, avant) -> tuple[list[Defaut], list[str]]:
        """Les juges, plus la fidelite : rien de perdu pendant ce tour, et
        la demande tenue."""
        defauts, vus = self._juger()
        apres = fidelite.empreinte(self.espace.racine)
        visibles = fidelite.atteignables(self.espace.racine, list(apres))
        return (fidelite.perdus(avant, apres)
                + (fidelite.non_tenues(self.demande, apres, visibles)
                   if self.demande else [])
                + defauts), vus

    def _appliquer(self, texte: str, tour: int) -> Tour:
        ext = extraire(texte)
        ecrits, refus = [], list(ext.ambiguites)
        for nom, contenu in ext.fichiers.items():
            try:
                cible, _ = self.espace.ecrire(nom, contenu)
                ecrits.append(self.espace.relatif(cible))
            except CheminRefuse as exc:
                refus.append(str(exc))
        return Tour(numero=tour, fichiers=ecrits, bloquants=0, conseils=0,
                    refus=refus)

    def _boucler(self, bilan: Bilan, premier_message: str) -> Bilan:
        self.messages.append({"role": "user", "content": premier_message})
        precedents: set = set()
        reparation.nouveau_chantier()            # le bilan parle de CE travail
        for n in range(1, self.tours_max + 1):
            avant = fidelite.empreinte(self.espace.racine)
            self.annoncer(f"tour {n} : le modele ecrit…")
            rep = self.backend.completer(systeme=SYSTEME,
                                         messages=self.messages,
                                         role_modele=self.role)
            self.messages.append({"role": "assistant", "content": rep.texte})
            tour = self._appliquer(rep.texte, n)
            bilan.tours.append(tour)
            if not tour.fichiers:
                bilan.explication = rep.texte.strip()
                bilan.arret = ("le modele n'a ecrit aucun fichier "
                               "reconnaissable" if n == 1 else
                               "le modele n'a rien reecrit")
                break
            bilan.explication = _hors_blocs(rep.texte)
            self.annoncer(f"tour {n} : {len(tour.fichiers)} fichier(s) "
                          "ecrit(s), les juges controlent…")
            defauts, vus = self._juger_tour(avant)
            # Ce que le juge sait corriger exactement, MAEL le corrige
            # lui-meme : un rejugement coute des secondes, un tour de modele
            # des minutes. Deux passes : deux corrections sur une meme ligne
            # se font l'une apres l'autre.
            for _ in range(2 if self.reparer_auto else 0):
                faites = reparation.reparer(self.espace, defauts, vus)
                if not faites:
                    break
                tour.reparations += [str(f) for f in faites]
                bilan.provisoires += [f.fichier for f in faites
                                      if f.provisoire]
                self.annoncer(f"tour {n} : {len(faites)} reparation(s) "
                              "automatique(s), les juges recontrolent…")
                defauts, vus = self._juger_tour(avant)
            tour.bloquants = sum(d.gravite is GRAVITE.BLOQUANT
                                 for d in defauts)
            tour.conseils = len(defauts) - tour.bloquants
            bilan.defauts, bilan.fichiers = defauts, vus
            if tour.bloquants == 0:
                bilan.arret = "aucun defaut bloquant"
                break
            # Le modele ne progresse plus : on arrete au lieu de payer un
            # tour de plus pour le meme resultat. On compare les DEFAUTS, pas
            # leur nombre : corriger un defaut et en faire apparaitre un
            # autre (un style.css enfin ecrit, mais trop pale) est un
            # progres (troisieme essai reel, 07/10/2026).
            presents = {(d.fichier, d.regle, d.message) for d in defauts
                        if d.gravite is GRAVITE.BLOQUANT}
            if n > 1 and precedents <= presents:
                bilan.arret = "le modele ne progresse plus"
                break
            precedents = presents
            retour = message_correction(defauts, vus)
            doubles = [r.split(" ecrit deux fois")[0] for r in tour.refus
                       if "ecrit deux fois" in r]
            if doubles:
                # Chaque fichier en double coute des minutes de generation
                # sur une petite machine (sixieme essai reel).
                retour = (f"[MAEL] tu as ecrit {', '.join(doubles)} deux "
                          "fois dans la meme reponse : ecris chaque fichier "
                          "UNE seule fois, en entier.\n\n" + retour)
            if tour.reparations:
                # Le modele doit VOIR les fichiers repares, sinon il les
                # reecrit de memoire et defait la reparation.
                # (sans les images provisoires : pas du texte a montrer)
                repares = sorted({r.split(":")[0] for r in tour.reparations}
                                 - set(bilan.provisoires))
                retour = ("[MAEL] corrections deja appliquees par MAEL (ne "
                          "les defais pas) :\n"
                          + "\n".join(f"- {r}" for r in tour.reparations)
                          + "\nContenu actuel de ces fichiers :\n"
                          + _contenu_projet(self.espace, repares)
                          + "\n\n" + retour)
            self.messages.append({"role": "user", "content": retour})
        else:
            bilan.arret = f"limite de {self.tours_max} tours atteinte"
        bilan.limites = juges.limites() + reparation.limites()
        return bilan

    # ------------------------------------------------------------- portes
    def ecrire(self, demande: str) -> Bilan:
        """« Fais-moi un site ... » -> fichiers dans l'espace + bilan."""
        bilan = Bilan(racine=str(self.espace.racine))
        self.demande = demande
        contexte = self.savoir(demande) if self.savoir else ""
        existants = [p.relative_to(self.espace.racine).as_posix()
                     for p in juges.fichiers_du_projet(self.espace.racine)]
        message = demande.strip()
        if existants:
            message += ("\n\nFichiers deja presents (ne les reecris que si "
                        "c'est necessaire) : " + ", ".join(existants[:30]))
        if contexte:
            message = f"{contexte}\n\n[demande]\n{message}"
        return self._boucler(bilan, message)

    def relire(self) -> Bilan:
        """Assister, premier temps : juger le projet tel qu'il est. Aucun
        modele, aucune ecriture — marche meme sans Ollama."""
        bilan = Bilan(racine=str(self.espace.racine))
        bilan.defauts, bilan.fichiers = self._juger()
        bilan.limites = juges.limites() + reparation.limites()
        bilan.arret = "relecture seule"
        return bilan

    def corriger(self, consigne: str = "") -> Bilan:
        """Assister, second temps : le modele corrige les fichiers fautifs.
        Les originaux sont sauvegardes par l'espace avant d'etre remplaces."""
        bilan = self.relire()
        if not bilan.bloquants:
            bilan.arret = "rien a corriger : aucun defaut bloquant"
            return bilan
        fautifs = list(dict.fromkeys(d.fichier for d in bilan.bloquants))
        message = (
            (consigne.strip() + "\n\n" if consigne.strip() else "")
            + "Voici les fichiers a corriger :\n\n"
            + _contenu_projet(self.espace, fautifs)
            + "\n\n" + message_correction(bilan.defauts,
                                     bilan.fichiers))
        return self._boucler(Bilan(racine=bilan.racine), message)


def _hors_blocs(texte: str) -> str:
    """L'explication du modele, sans le code (deja ecrit dans les fichiers)."""
    import re
    return re.sub(r"(?ms)^```.*?^```[ \t]*$", "", texte).strip()


def rendre_bilan(bilan: Bilan) -> str:
    """Le bilan en texte pour le terminal. Il ne dit « conforme » que si
    c'est vrai, et il dit toujours ce qui n'a pas ete verifie."""
    l = [f"espace : {bilan.racine}"]
    if bilan.plan:
        l.append("plan :")
        l += [f"  {p}" for p in bilan.plan]
    for t in bilan.tours:
        l.append(f"  tour {t.numero}"
                 + (f" [{t.tache}]" if t.tache else "")
                 + f" : {len(t.fichiers)} fichier(s), "
                 f"{t.bloquants} bloquant(s), {t.conseils} conseil(s)"
                 + (f", {t.secondes:.0f} s" if t.secondes else "")
                 + (f", {t.mode}" if t.mode else ""))
        for r in t.refus:
            l.append(f"    refuse : {r}")
        for r in t.reparations:
            l.append(f"    repare par MAEL : {r}")
    if bilan.fichiers:
        l.append(f"fichiers juges : {', '.join(bilan.fichiers)}")
    if bilan.conforme:
        l.append("VERDICT : conforme aux regles verifiees "
                 f"({len(bilan.defauts)} conseil(s) non bloquant(s))")
    elif bilan.fichiers:
        l.append(f"VERDICT : NON conforme — {len(bilan.bloquants)} "
                 "defaut(s) bloquant(s) restant(s)")
    else:
        l.append("VERDICT : aucun fichier a juger")
    for d in bilan.defauts:
        l.append(f"  {d}")
    if bilan.arret:
        l.append(f"arret : {bilan.arret}")
    if bilan.suppositions:
        l.append("SUPPOSITIONS de MAEL (a confirmer) :")
        l += [f"  - {s}" for s in bilan.suppositions]
    if bilan.provisoires:
        l.append("IMAGES PROVISOIRES a remplacer par les vraies : "
                 + ", ".join(dict.fromkeys(bilan.provisoires)))
    if bilan.limites:
        l.append("non verifie : " + " ; ".join(bilan.limites))
    return "\n".join(l)
