"""Reconnaitre l'Ollama de l'utilisateur, et le modele qu'il a DEJA.

MAEL ne telecharge rien et n'impose rien : il s'installe sur une machine ou
Ollama tourne peut-etre deja, avec un ou deux modeles que l'utilisateur a
choisis pour ses propres raisons. Ce module est la couche qui regarde ce qui
est la, avant de parler.

Quatre situations, quatre reponses -- et jamais une trace d'appel Python :

  1. le modele demande est installe -> on l'utilise, sans un mot ;
  2. il est absent, d'autres sont la -> on CHOISIT le meilleur parmi ceux qui
     sont presents, on le dit en une ligne, et on l'enregistre dans
     ~/.mael/reglages.json pour les fois suivantes ;
  3. aucun modele installe -> une phrase, et la commande exacte a copier ;
  4. Ollama n'est pas la du tout -> une phrase, et le lien.

Le classement des modeles est une DONNEE (`modeles_connus.json`), pas du
code : la campagne de mesure (L6) le corrigera en changeant un fichier. La
categorie « refuser » du banc y sert de critere d'EXCLUSION -- un modele qui
laisse passer ce qu'il devait refuser n'est jamais choisi automatiquement,
quel que soit son score ailleurs. Le choix par defaut est une decision de
securite, pas de confort.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from django.conf import settings

from . import reglages

FICHIER_CONNUS = Path(__file__).resolve().parent / "modeles_connus.json"
LIEN_INSTALLATION = "https://ollama.com/download"
CONSEILLE = "qwen2.5:3b"
# Interroger la liste des modeles est instantane quand Ollama est la. Un long
# delai ne sert qu'a faire attendre celui chez qui il n'est pas installe.
DELAI_LISTE = 5


# --------------------------------------------------------------------------- #
# Ce qui peut empecher de demarrer -- dit en francais, jamais en trace d'appel
# --------------------------------------------------------------------------- #
class ProblemeDeModele(RuntimeError):
    """Un obstacle que l'utilisateur peut lever lui-meme.

    Il porte toujours ce qu'il faut faire ensuite : le message n'est pas un
    constat d'echec, c'est une instruction."""

    def __init__(self, titre: str, conseils: list[str] | None = None):
        self.titre = titre
        self.conseils = list(conseils or [])
        super().__init__(self.humain())

    def humain(self) -> str:
        return "\n".join([self.titre, *(f"  {c}" for c in self.conseils)])


class OllamaAbsent(ProblemeDeModele):
    """Rien n'ecoute a l'adresse d'Ollama."""


class AucunModeleInstalle(ProblemeDeModele):
    """Ollama repond, mais il n'a aucun modele utilisable."""


class ModeleImposeAbsent(ProblemeDeModele):
    """Un modele a ete impose explicitement et il n'est pas la.

    On ne lui en substitue PAS un autre : quand quelqu'un nomme un modele
    (banc de mesure, ligne de commande), lui en donner un autre en silence
    fausserait ce qu'il mesure."""


# --------------------------------------------------------------------------- #
# Ce qu'Ollama repond
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Modele:
    nom: str
    octets: int = 0
    famille: str = ""
    parametres: str = ""
    quantification: str = ""

    @property
    def taille(self) -> str:
        return taille_humaine(self.octets)


def taille_humaine(octets: int) -> str:
    if not octets:
        return "?"
    go = octets / 1024 ** 3
    return f"{go:.1f} Go" if go >= 1 else f"{octets / 1024 ** 2:.0f} Mo"


def _depuis_tags(donnees: dict) -> list[Modele]:
    modeles = []
    for brut in donnees.get("models", []) or []:
        nom = (brut.get("name") or brut.get("model") or "").strip()
        if not nom:
            continue
        details = brut.get("details") or {}
        modeles.append(Modele(
            nom=nom,
            octets=int(brut.get("size") or 0),
            famille=str(details.get("family") or ""),
            parametres=str(details.get("parameter_size") or ""),
            quantification=str(details.get("quantization_level") or ""),
        ))
    return sorted(modeles, key=lambda m: m.nom)


def adresse() -> str:
    return str(settings.BRAIN["BASE_URL"]).rstrip("/")


def lister(base: str | None = None, delai: int = DELAI_LISTE) -> list[Modele]:
    """Les modeles reellement installes. Leve OllamaAbsent si personne ne
    repond -- c'est une situation normale, pas une anomalie."""
    base = (base or adresse()).rstrip("/")
    # Cette requete est de la plomberie : elle n'a pas a s'afficher dans la
    # sortie de MAEL, entre la banniere et la premiere phrase.
    journal = logging.getLogger("httpx")
    niveau = journal.level
    journal.setLevel(logging.WARNING)
    try:
        with httpx.Client(timeout=delai) as client:
            rep = client.get(f"{base}/api/tags")
            rep.raise_for_status()
            donnees = rep.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OllamaAbsent(
            f"Ollama ne repond pas sur {base} ({type(exc).__name__}).",
            [f"Installer Ollama : {LIEN_INSTALLATION}",
             "Puis le lancer :  ollama serve",
             "S'il tourne ailleurs : BRAIN_BASE_URL=http://..."],
        ) from None
    finally:
        journal.setLevel(niveau)
    if not isinstance(donnees, dict):
        raise OllamaAbsent(f"Reponse inattendue d'Ollama sur {base}.",
                           ["Verifier qu'il s'agit bien d'un serveur Ollama."])
    return _depuis_tags(donnees)


# --------------------------------------------------------------------------- #
# Ce que MAEL sait des modeles (donnees relisibles, pas du code)
# --------------------------------------------------------------------------- #
_connus: dict | None = None

DEFAUTS_CONNUS = {
    "categories_milliards": [3, 7, 13, 27, 70],
    "mesures": [],
    "preferes": [CONSEILLE],
    "exclus": [],
    "exclus_pourquoi": {},
    "particularites": {},
    "non_conversationnels": ["embed", "rerank", "minilm"],
    "marge_memoire_octets": 1610612736,
    "conseille_si_rien": CONSEILLE,
}


def connus(recharger: bool = False) -> dict:
    """Le fichier de connaissances des modeles. Abime ou absent, MAEL demarre
    quand meme : on retombe sur un minimum sur, jamais sur une exception."""
    global _connus
    if _connus is not None and not recharger:
        return _connus
    valeurs = dict(DEFAUTS_CONNUS)
    try:
        brut = json.loads(FICHIER_CONNUS.read_text(encoding="utf-8"))
        if isinstance(brut, dict):
            for cle in DEFAUTS_CONNUS:
                if cle in brut:
                    valeurs[cle] = brut[cle]
    except (OSError, json.JSONDecodeError):
        pass
    _connus = valeurs
    return valeurs


# --------------------------------------------------------------------------- #
# Reconnaitre un modele sous ses variantes
# --------------------------------------------------------------------------- #
def _famille(nom: str) -> str:
    return nom.split(":", 1)[0].strip().lower()


def _etiquette(nom: str) -> str:
    morceaux = nom.split(":", 1)
    return morceaux[1].strip().lower() if len(morceaux) > 1 else ""


def correspond(demande: str, installe: str) -> bool:
    """« qwen2.5:3b » demande, « qwen2.5:3b-instruct-q4_K_M » installe : c'est
    le meme modele, quantifie. « mistral:7b » demande, « mistral:latest »
    installe : c'est celui qu'Ollama pose par defaut, donc le meme aussi.
    En revanche 3b et 7b ne se remplacent jamais l'un l'autre."""
    demande, installe = demande.strip().lower(), installe.strip().lower()
    if not demande or not installe:
        return False
    if demande == installe:
        return True
    if _famille(demande) != _famille(installe):
        return False
    vise, pose = _etiquette(demande), _etiquette(installe)
    if not vise or vise == pose:
        return True
    if pose in ("", "latest"):
        return True
    return pose.startswith(vise + "-") or pose.startswith(vise + "_")


def trouver(demande: str, disponibles: list[Modele]) -> Modele | None:
    """Le modele demande parmi ceux qui sont la : d'abord au nom exact, sinon
    par variante. L'exact d'abord, pour qu'une variante ne vole jamais la
    place du nom ecrit."""
    for m in disponibles:
        if m.nom.strip().lower() == demande.strip().lower():
            return m
    for m in disponibles:
        if correspond(demande, m.nom):
            return m
    return None


def est_exclu(nom: str, savoir: dict | None = None) -> bool:
    savoir = savoir or connus()
    return any(correspond(x, nom) for x in savoir.get("exclus", []))


def sait_dialoguer(nom: str, savoir: dict | None = None) -> bool:
    savoir = savoir or connus()
    minuscule = nom.lower()
    return not any(motif.lower() in minuscule
                   for motif in savoir.get("non_conversationnels", []))


def milliards(m: Modele) -> float:
    """Taille du modele en milliards de parametres.

    Ollama la donne (« 8.0B ») ; quand il ne la donne pas, on l'estime sur le
    poids du fichier -- un modele quantifie en 4 bits pese environ 0,6 Go par
    milliard de parametres. L'estimation n'a pas besoin d'etre juste au
    dixieme : elle ne sert qu'a ranger le modele dans une categorie."""
    brut = (m.parametres or "").strip().upper().rstrip("B")
    try:
        valeur = float(brut)
    except ValueError:
        valeur = 0.0
    if valeur > 0:
        return valeur
    return round((m.octets / 1024 ** 3) / 0.6, 1) if m.octets else 0.0


def categorie(m: Modele, savoir: dict | None = None) -> int:
    """Categorie de capacite (0 = le plus petit).

    On compare par categorie et non au dixieme de milliard : entre un 8b et
    un 9b, la difference ne se voit pas, alors qu'entre un 3b et un 30b elle
    saute aux yeux. A l'interieur d'une categorie, c'est ce qu'on CONNAIT du
    modele qui tranche."""
    savoir = savoir or connus()
    bornes = savoir.get("categories_milliards", [3, 7, 13, 27, 70])
    taille = milliards(m)
    rang = 0
    for borne in bornes:
        if taille >= borne:
            rang += 1
    return rang


def est_mesure(nom: str, savoir: dict | None = None) -> bool:
    """Ce modele est-il reellement passe au banc ?"""
    savoir = savoir or connus()
    return any(correspond(x, nom) for x in savoir.get("mesures", []))


def besoin_memoire(m: Modele, savoir: dict | None = None) -> int:
    """Memoire qu'il faut pour le faire tourner : son fichier, plus la place
    du contexte et du programme."""
    savoir = savoir or connus()
    return m.octets + int(savoir.get("marge_memoire_octets") or 0)


def particularite(nom: str, savoir: dict | None = None) -> str:
    savoir = savoir or connus()
    minuscule = nom.lower()
    for motif, phrase in (savoir.get("particularites") or {}).items():
        if motif.lower() in minuscule:
            return phrase
    return ""


@dataclass
class Choix:
    """Le modele retenu, et ce qu'il faut en dire a l'utilisateur."""
    modele: Modele
    notes: list[str] = field(default_factory=list)


def _rang(m: Modele, savoir: dict) -> tuple:
    """Ce qui fait qu'un modele passe devant un autre, dans l'ordre :

    1. **sa categorie de capacite** -- un 20b inconnu vaut mieux qu'un 3b que
       nous connaissons bien : la garde de MAEL est dans le code, pas dans le
       modele, donc un modele plus capable ne nous coute rien en surete ;
    2. **le fait qu'on l'ait mesure**, a categorie egale ;
    3. **notre ordre de preference**, a categorie egale ;
    4. le poids du fichier : a taille de modele egale, une quantification
       plus riche vaut mieux."""
    prefs = savoir.get("preferes", [])
    place = next((i for i, p in enumerate(prefs) if correspond(p, m.nom)),
                 len(prefs))
    return (categorie(m, savoir), 1 if est_mesure(m.nom, savoir) else 0,
            -place, m.octets)


def choisir(disponibles: list[Modele], savoir: dict | None = None,
            capacite=None) -> Choix | None:
    """Le meilleur candidat parmi CEUX QUI SONT LA, pour CETTE machine.

    MAEL ne suppose jamais que l'utilisateur a nos modeles, et ne suppose pas
    non plus qu'il a notre machine. Deux publics, une seule regle :

      - petite machine : on ne choisit jamais un modele qui ne tient pas dans
        sa memoire ; un gros modele installe mais hors de portee n'est pris
        que s'il n'y a rien d'autre, et on previent que ce sera lent ;
      - machine capable, modeles meilleurs que les notres : ils gagnent. Un
        modele que nous n'avons jamais mesure est utilise et signale comme
        tel -- ce n'est pas un risque de surete, c'est une inconnue de
        qualite, et l'avis de l'utilisateur nous la levera (L5)."""
    savoir = savoir or connus()
    candidats = [m for m in disponibles
                 if sait_dialoguer(m.nom, savoir)
                 and not est_exclu(m.nom, savoir)]
    if not candidats:
        return None

    from . import machine
    capa = capacite if capacite is not None else machine.capacite()

    a_l_aise = [m for m in candidats
                if machine.tient(besoin_memoire(m, savoir), capa)]
    serres = [m for m in candidats
              if m not in a_l_aise
              and machine.tient(besoin_memoire(m, savoir), capa, serre=True)]

    notes: list[str] = []
    if a_l_aise:
        retenus = a_l_aise
    elif serres:
        retenus, notes = serres, [
            "Aucun modele installe ne tient a l'aise dans "
            f"{capa.libelle()} : le choix va pousser la machine."]
    else:
        # Rien ne tient : plutot que de refuser de demarrer, on prend le plus
        # petit et on dit la verite. C'est sa machine, c'est son choix.
        petit = min(candidats, key=lambda m: m.octets)
        return Choix(petit, [
            f"« {petit.nom} » ({petit.taille}) depasse ce que cette machine "
            f"peut porter ({capa.libelle()}) : ce sera lent, voire impossible.",
            "Un modele plus petit tiendrait mieux, par exemple :  ollama pull "
            f"{savoir.get('conseille_si_rien', CONSEILLE)}"])

    meilleur = max(retenus, key=lambda m: _rang(m, savoir))
    if not est_mesure(meilleur.nom, savoir):
        notes.append(
            f"« {meilleur.nom} » n'a jamais ete mesure par MAEL : la garde "
            "verifie ses commandes comme celles des autres, mais nous ne "
            "savons pas encore ce qu'il vaut. Ton retour nous interesse.")
    trait = particularite(meilleur.nom, savoir)
    if trait:
        notes.append(f"« {meilleur.nom} » : {trait}.")
    return Choix(meilleur, notes)


# --------------------------------------------------------------------------- #
# La resolution : de « ce qui est regle » a « ce qui va reellement tourner »
# --------------------------------------------------------------------------- #
@dataclass
class Resolution:
    nom: str
    modele: Modele | None = None
    origine: str = "defaut"          # reglage | defaut | impose | automatique
    messages: list[str] = field(default_factory=list)
    enregistre: bool = False
    disponibles: list[Modele] = field(default_factory=list)


_resolu: dict[tuple, Resolution] = {}


def oublier() -> None:
    """Vide le cache de resolution (changement de reglage, tests)."""
    _resolu.clear()


def demande(role: str = "expert",
            valeurs: dict | None = None) -> tuple[str, str]:
    """Le modele voulu et d'ou vient ce choix, AVANT de regarder la machine.

    Ordre de priorite, le meme que partout dans MAEL : un modele impose
    maintenant (MODELE_EXACT : banc de mesure, ligne de commande) gagne sur le
    reglage enregistre, qui gagne sur le defaut livre avec le code."""
    valeurs = valeurs if valeurs is not None else reglages.charger()[0]
    regle = str(valeurs.get("modele") or "").strip()
    if regle and not settings.BRAIN.get("MODELE_EXACT", False):
        return regle, "reglage"
    modeles = settings.BRAIN["MODELES"]
    if role not in modeles:
        raise ValueError(
            f"Role de modele « {role} » inconnu. Connus : {sorted(modeles)}")
    return str(modeles[role]), "defaut"


def resoudre(role: str = "expert", *, souhaite: str | None = None,
             valeurs: dict | None = None,
             disponibles: list[Modele] | None = None,
             enregistrer: bool = True, exiger_exact: bool | None = None,
             base: str | None = None, capacite=None) -> Resolution:
    """Le coeur de L1. Rend ce qui va tourner, ou leve un ProblemeDeModele
    dont le message dit quoi faire.

    Le resultat est retenu pour la duree du processus : une fois le modele
    reconnu, une coupure d'Ollama plus tard dans la session ne doit pas
    rejouer ce dialogue -- c'est l'appel au modele qui se plaindra, a sa
    place."""
    valeurs = valeurs if valeurs is not None else reglages.charger()[0]
    if souhaite:
        voulu, origine = souhaite, "impose"
    else:
        voulu, origine = demande(role, valeurs)
    if exiger_exact is None:
        exiger_exact = bool(settings.BRAIN.get("MODELE_EXACT", False))

    cle = (role, voulu, base or adresse(), exiger_exact)
    if disponibles is None and cle in _resolu:
        return _resolu[cle]

    presents = lister(base) if disponibles is None else list(disponibles)
    savoir = connus()

    if not presents:
        raise AucunModeleInstalle(
            "Ollama repond, mais aucun modele n'est installe.",
            ["Installer celui que MAEL conseille :  ollama pull "
             f"{savoir.get('conseille_si_rien', CONSEILLE)}",
             "Puis relancer MAEL."],
        )

    trouve = trouver(voulu, presents)
    if trouve is not None:
        resolution = Resolution(nom=trouve.nom, modele=trouve, origine=origine,
                                disponibles=presents)
        if trouve.nom.strip().lower() != voulu.strip().lower():
            resolution.messages.append(
                f"« {voulu} » n'est pas installe sous ce nom exact : "
                f"« {trouve.nom} » est la meme famille et sert a sa place.")
        from . import machine
        # la capacite DONNEE sert aussi ici (avant le 12/10, l'avertissement
        # relisait la vraie machine : test faux sur une CI de 3,8 Go)
        capa = capacite if capacite is not None else machine.capacite()
        if not machine.tient(besoin_memoire(trouve, savoir), capa, serre=True):
            # On ne remplace PAS son choix : on le previent. C'est sa machine.
            resolution.messages.append(
                f"« {trouve.nom} » ({trouve.taille}) est gros pour cette "
                f"machine ({capa.libelle()}) : attends-toi a "
                "des reponses lentes.")
        if est_exclu(trouve.nom, savoir):
            pourquoi = savoir.get("exclus_pourquoi", {}).get(trouve.nom, "")
            resolution.messages.append(
                "ATTENTION : ce modele a echoue la categorie « refuser » du "
                "banc de mesure" + (f" ({pourquoi})" if pourquoi else "") +
                ". Il sert parce qu'il est demande explicitement ; MAEL ne "
                "l'aurait pas choisi.")
        if disponibles is None:
            _resolu[cle] = resolution
        return resolution

    if exiger_exact:
        raise ModeleImposeAbsent(
            f"Le modele demande « {voulu} » n'est pas installe.",
            [f"L'installer :  ollama pull {voulu}",
             "Installes : " + ", ".join(m.nom for m in presents)],
        )

    choix = choisir(presents, savoir, capacite=capacite)
    if choix is None:
        raison = ("aucun des modeles installes ne sait dialoguer, ou tous ont "
                  "ete ecartes par le banc de mesure")
        raise AucunModeleInstalle(
            f"Aucun modele utilisable ({raison}).",
            ["Installes : " + ", ".join(m.nom for m in presents),
             "Installer celui que MAEL conseille :  ollama pull "
             f"{savoir.get('conseille_si_rien', CONSEILLE)}"],
        )

    retenu = choix.modele
    resolution = Resolution(nom=retenu.nom, modele=retenu,
                            origine="automatique", disponibles=presents)
    resolution.messages.append(
        f"« {voulu} » n'est pas installe : MAEL prend « {retenu.nom} » "
        f"({retenu.taille}), le meilleur parmi ceux qui sont la.")
    resolution.messages.extend(choix.notes)
    if enregistrer:
        nouvelles = dict(valeurs)
        nouvelles["modele"] = retenu.nom
        try:
            chemin = reglages.enregistrer(nouvelles)
            resolution.enregistre = True
            resolution.messages.append(
                f"Choix enregistre dans {chemin} "
                "(« mael modeles » pour en changer).")
        except OSError as exc:
            resolution.messages.append(
                f"Choix non enregistre ({exc}) : il sera refait au prochain "
                "demarrage.")
    if disponibles is None:
        _resolu[cle] = resolution
    return resolution


# --------------------------------------------------------------------------- #
# Affichage : « mael modeles »
# --------------------------------------------------------------------------- #
def prechauffer(modele: str, systeme: str = "", base: str | None = None):
    """Charger le modele pendant que l'utilisateur lit l'ecran d'accueil.

    Mesure du 22/09 sur le portable vise (8 Go, sans carte graphique) :

        modele froid  : 25,7 s de chargement + 27,7 s pour lire le mode
                        d'emploi = presque une minute avant le premier mot ;
        modele chaud  : 0,2 s + 0,1 s = **4 secondes** pour la meme question.

    Tout ce temps est paye AVANT que l'utilisateur ait fini de taper sa
    premiere question -- a condition de s'y prendre pendant qu'il lit. D'ou
    ce prechauffage : un appel minuscule (un seul jeton demande) lance dans
    un fil de l'ombre des l'ouverture du terminal. Si `systeme` est fourni,
    le mode d'emploi est envoye aussi : Ollama garde alors la lecture du
    prompt, et la premiere vraie question ne la repaie pas.

    Rien n'en depend : c'est une avance prise, pas une etape. Toute erreur
    est avalee -- au pire, la premiere question coutera ce qu'elle coutait
    avant."""
    import threading

    adresse_ollama = (base or adresse()).rstrip("/")
    duree = settings.BRAIN.get("GARDER_EN_MEMOIRE", "30m")
    contexte = settings.BRAIN.get("NUM_CTX", 8192)

    def _chauffer():
        messages = []
        if systeme:
            messages.append({"role": "system", "content": systeme})
        messages.append({"role": "user", "content": "."})
        try:
            with httpx.Client(timeout=httpx.Timeout(600, connect=5)) as client:
                client.post(f"{adresse_ollama}/api/chat", json={
                    "model": modele, "stream": False, "keep_alive": duree,
                    "messages": messages,
                    "options": {"temperature": 0.1, "num_ctx": contexte,
                                # On ne veut pas de reponse : juste que le
                                # modele soit la, et le prompt deja lu.
                                "num_predict": 1},
                })
        except Exception:            # noqa: BLE001 -- une avance, pas une etape
            pass

    fil = threading.Thread(target=_chauffer, daemon=True,
                           name="mael-prechauffage")
    fil.start()
    return fil


def expliquer_echec(exc: Exception, modele: str = "",
                    profil: str = "") -> str:
    """Pourquoi l'appel au modele a echoue, et quoi faire.

    « injoignable » est faux dans le cas le plus frequent chez l'utilisateur
    vise : le modele est la, il est LENT. Le dire correctement, c'est la
    difference entre quelqu'un qui recommence autrement et quelqu'un qui
    desinstalle (friction n° 1 de l'epreuve L3, 22/09)."""
    from . import machine

    nom = f"« {modele} » " if modele else "le modele "
    if isinstance(exc, httpx.ReadTimeout | httpx.WriteTimeout | httpx.PoolTimeout):
        conseils = [
            "Ce n'est pas une panne : il calcule encore quand le delai tombe.",
            "Laisser plus de temps :  BRAIN_TIMEOUT=1200  (secondes)",
        ]
        if profil != "court":
            conseils.append("Alleger ce qu'on lui envoie :  mael --profil court"
                            "  (deux fois moins d'attente)")
        conseils.append("Ou prendre un modele plus petit :  mael modeles")
        return "\n".join([f"{nom}a depasse le delai de reponse.", *
                          (f"  {c}" for c in conseils)])
    if isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout):
        return OllamaAbsent(
            f"Ollama ne repond plus sur {adresse()}.",
            ["Verifier qu'il tourne toujours :  ollama serve"],
        ).humain()
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
        return "\n".join([
            f"Ollama ne connait pas {nom.strip()}.",
            f"  L'installer :  ollama pull {modele}" if modele else
            "  Voir ce qui est installe :  mael modeles"])
    details = f"{type(exc).__name__}: {exc}".strip()
    quoi = machine.capacite().libelle()
    return (f"Echec de l'appel au modele ({details}).\n"
            f"  Machine : {quoi}\n"
            "  Si cela se reproduit, dites-le nous avec cette ligne.")


def decrire(disponibles: list[Modele], actif: str = "",
            savoir: dict | None = None, capacite=None) -> list[str]:
    """Une ligne par modele installe : celui qui sert est marque, ce qui ne
    tient pas sur cette machine le dit, ce que MAEL ne choisira jamais tout
    seul le dit aussi, et pourquoi."""
    savoir = savoir or connus()
    from . import machine
    capa = capacite if capacite is not None else machine.capacite()
    lignes = []
    for m in disponibles:
        marque = ">" if actif and correspond(actif, m.nom) else " "
        notes = []
        if not sait_dialoguer(m.nom, savoir):
            notes.append("ne dialogue pas (vectorisation)")
        if est_exclu(m.nom, savoir):
            pourquoi = savoir.get("exclus_pourquoi", {}).get(m.nom, "")
            notes.append("ecarte par le banc"
                         + (f" : {pourquoi}" if pourquoi else ""))
        besoin = besoin_memoire(m, savoir)
        if not machine.tient(besoin, capa, serre=True):
            notes.append("trop gros pour cette machine")
        elif not machine.tient(besoin, capa):
            notes.append("tient tout juste")
        if est_mesure(m.nom, savoir):
            notes.append("mesure par MAEL")
        details = " ".join(x for x in (m.parametres, m.quantification) if x)
        fin = f"  [{'; '.join(notes)}]" if notes else ""
        lignes.append(f" {marque} {m.nom:<32} {m.taille:>8}  {details}{fin}")
    return lignes
