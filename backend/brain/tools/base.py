"""Socle des outils embarques.

Le modele n'execute jamais un binaire. Il appelle un *adaptateur*, qui :

  1. verifie le perimetre     -- la cible appartient a un actif prouve du client
  2. valide les parametres    -- schema strict, pas de chaine libre vers un shell
  3. execute dans un conteneur -- jetable, sans reseau hote, sans volume, avec delai
  4. normalise la sortie      -- chaque outil rend le meme format d'observation
  5. journalise               -- qui, quoi, quand, pour quel client

Aucun outil n'ecrit jamais sur un systeme client. L'ecriture passe
exclusivement par les playbooks, avec validation humaine.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from django.conf import settings

logger = logging.getLogger("sentinelle.audit")


class OutilRefuse(PermissionError):
    """Le perimetre interdit cette execution. Jamais reessaye."""


class OutilEchoue(RuntimeError):
    """L'outil s'est mal termine. Peut etre reessaye."""


@dataclass
class Observation:
    """Format unique de sortie, quel que soit l'outil.

    C'est ce que le cerveau lit. Il ne voit jamais la sortie brute d'un
    binaire : uniquement des constats normalises et ancrables.
    """

    outil: str
    cible: str
    constats: list[dict] = field(default_factory=list)
    brut: str = ""
    duree_ms: int = 0
    code_sortie: int = 0

    def ajouter(self, *, code: str, gravite: str, resume: str, **details):
        """gravite : critique | elevee | moyenne | faible | info"""
        self.constats.append(
            {"code": code, "gravite": gravite, "resume": resume, "details": details}
        )

    @property
    def pire_gravite(self) -> str:
        ordre = ["critique", "elevee", "moyenne", "faible", "info"]
        presentes = {c["gravite"] for c in self.constats}
        return next((g for g in ordre if g in presentes), "info")

    def pour_le_modele(self) -> dict:
        """Ce que le modele recoit : les constats, jamais la sortie brute.

        La sortie brute contient du texte controle par l'attaquant
        (banniere de service, nom de fichier, en-tete HTTP). Elle reste
        en base pour l'analyste humain et n'entre pas dans le prompt.
        """
        return {
            "outil": self.outil,
            "cible": self.cible,
            "constats": self.constats,
            "pire_gravite": self.pire_gravite,
        }


# Image figee par empreinte : images.lock associe chaque nom d'image a une
# reference image@sha256:... (A_RESOUDRE tant que Docker n'a pas pu la
# resoudre — voir banc/resoudre_empreintes.py).
IMAGES_LOCK = Path(__file__).with_name("images.lock")


def image_figee(image: str, lock: Path = IMAGES_LOCK) -> str:
    """Reference @sha256 utilisable pour `image`. Refuse toute image non
    figee : `:latest`, absence de digest, absence du verrou.

    OutilRefuse si l'image n'est pas epinglee (decision de securite) ;
    OutilEchoue si l'epingle existe mais n'est pas resolue (A_RESOUDRE :
    il faut Docker pour la renseigner, pas une erreur de configuration).
    """
    if not image:
        raise OutilEchoue("aucune image declaree.")
    if image.endswith(":latest"):
        raise OutilRefuse(f"{image} : « latest » est interdit, epingler "
                          f"par @sha256 (images.lock).")
    if "@sha256:" in image:
        if image.endswith("A_RESOUDRE"):
            raise OutilEchoue(f"{image} : empreinte a resoudre "
                              f"(banc/resoudre_empreintes.py).")
        return image
    verrou = {}
    if lock.exists():
        verrou = json.loads(lock.read_text(encoding="utf-8"))
    epinglee = verrou.get(image) or verrou.get(image.split(":", 1)[0])
    if not epinglee:
        raise OutilRefuse(f"{image} : absente d'images.lock, execution "
                          f"refusee (une image non figee n'est pas lancee).")
    return image_figee(epinglee, lock)     # A_RESOUDRE ou digest final


# Outils LOCAUX (19/09/2026) : ils lisent un dossier de la machine auditee,
# monte en LECTURE SEULE dans le conteneur (jamais d'ecriture). Le chemin est
# valide ici : absolu, sans « .. », hors pseudo-systemes de fichiers, sans
# caractere qui casserait la syntaxe de --mount.
CIBLE_CONTENEUR = "/cible"
_INTERDITS_LOCAUX = ("/proc", "/sys", "/dev", "/run")
_RE_CHEMIN = re.compile(r"^(?:[A-Za-z]:)?[/\\][^,\n\r\x00]*$")


def chemin_local_valide(chemin: str) -> str:
    """Chemin de la machine auditee autorise pour un outil local, sinon
    OutilRefuse. Rend le chemin normalise (barres obliques)."""
    c = (chemin or "").strip().replace("\\", "/")
    if not _RE_CHEMIN.match(c):
        raise OutilRefuse(f"chemin « {chemin} » refuse : absolu attendu, "
                          f"sans virgule ni retour a la ligne.")
    parties = [p for p in c.split("/") if p]
    if ".." in parties:
        raise OutilRefuse(f"chemin « {chemin} » refuse : « .. » interdit.")
    posix = "/" + "/".join(parties[1:] if re.match(r"^[A-Za-z]:$", parties[0] if parties else "") else parties)
    if any(posix == i or posix.startswith(i + "/") for i in _INTERDITS_LOCAUX):
        raise OutilRefuse(f"chemin « {chemin} » refuse : pseudo-systeme de "
                          f"fichiers ({posix}).")
    return c


class Outil:
    """Classe de base. Un sous-classe par outil embarque."""

    nom: ClassVar[str] = ""
    description: ClassVar[str] = ""
    # Schema JSON des parametres, expose tel quel au modele.
    schema: ClassVar[dict] = {"type": "object", "properties": {}, "required": []}
    # Image figee. `latest` est interdit en production : on epingle un digest.
    image: ClassVar[str] = ""
    # Si vrai, la cible doit correspondre a un actif dont la propriete est prouvee.
    exige_preuve: ClassVar[bool] = True
    # Un outil de lecture ne modifie rien. Il n'existe pas d'outil d'ecriture.
    lecture_seule: ClassVar[bool] = True
    delai: ClassVar[int] = 300
    # « reseau » : la cible est un actif prouve du client (domaine, IP).
    # « locale » : la cible est un dossier de la machine auditee, monte en
    # lecture seule sur /cible ; aucune preuve d'actif, chemin valide.
    portee: ClassVar[str] = "reseau"
    # Reseau du conteneur : « bridge » (sortie possible, hote inaccessible)
    # ou « none » (outil local qui n'a besoin de rien telecharger).
    reseau: ClassVar[str] = "bridge"
    # Repertoires en memoire, seuls endroits ecrivables (cache d'une base de
    # vulnerabilites...) : le conteneur reste --read-only.
    tmpfs: ClassVar[dict[str, str]] = {}      # chemin -> taille (ex. "1g")
    # Point d'entree impose (image dont le point d'entree par defaut lance un
    # demon, ex. clamav).
    entrypoint: ClassVar[str] = ""
    memoire: ClassVar[str] = "1g"
    # Codes de sortie qui signifient « l'outil a bien travaille ». Tout
    # autre code leve OutilEchoue : un scan qui echoue ne doit JAMAIS passer
    # pour un resultat propre (Trivy en echec rendait « 0 faille »,
    # 19/09/2026).
    codes_succes: ClassVar[frozenset[int]] = frozenset({0})
    # Volumes Docker NOMMES (jamais un chemin de l'hote) : nom -> point de
    # montage. Sert aux bases de donnees des outils (base de vulnerabilites
    # de Trivy), telechargees une fois par la preparation.
    volumes: ClassVar[dict[str, str]] = {}
    # Variables d'environnement du conteneur (jamais un secret : seulement
    # de quoi rediriger un outil vers un chemin inscriptible, ex. TMPDIR).
    env: ClassVar[dict[str, str]] = {}

    # ------------------------------------------------------------ a redefinir
    def commande(self, **params) -> list[str]:
        """Arguments passes a l'image. Liste, jamais une chaine de shell."""
        raise NotImplementedError

    def analyser(self, sortie: str, obs: Observation) -> None:
        """Traduit la sortie brute en constats normalises."""
        raise NotImplementedError

    # ------------------------------------------------------------ orchestration
    def executer(self, *, organisation, cible: str, **params) -> Observation:
        debut = time.perf_counter()
        self._verifier_perimetre(organisation, cible)

        obs = Observation(outil=self.nom, cible=cible)
        montage = None
        if self.portee == "locale":
            montage = chemin_local_valide(cible)
            cible_outil = CIBLE_CONTENEUR
        else:
            cible_outil = cible
        try:
            sortie, code = self._lancer(self.commande(cible=cible_outil, **params),
                                        montage=montage)
            obs.brut, obs.code_sortie = sortie[:200_000], code
            if code not in self.codes_succes:
                raise OutilEchoue(f"code de sortie {code} : "
                                  f"{sortie.strip()[-400:]}")
            self.analyser(sortie, obs)
        except OutilRefuse:
            raise
        except subprocess.TimeoutExpired:
            limite = min(self.delai, settings.OUTILS["TIMEOUT"])
            raise OutilEchoue(f"{self.nom} : delai de {limite} s depasse "
                              f"(image non preparee ? python -m brain.tools "
                              f"--preparer).")
        except Exception as exc:  # noqa: BLE001
            raise OutilEchoue(f"{self.nom} : {exc}") from exc
        finally:
            obs.duree_ms = int((time.perf_counter() - debut) * 1000)
            logger.info(
                "outil=%s organisation=%s cible=%s constats=%d duree=%dms",
                self.nom,
                getattr(organisation, "id", "-"),
                cible,
                len(obs.constats),
                obs.duree_ms,
            )
        return obs

    # ------------------------------------------------------------ garde-fous
    def _verifier_perimetre(self, organisation, cible: str) -> None:
        if self.portee == "locale":
            chemin_local_valide(cible)          # leve OutilRefuse sinon
            return
        if not self.exige_preuve:
            return
        if organisation is None:
            raise OutilRefuse("Aucune organisation : execution refusee.")
        # Import tardif : evite un cycle au chargement des applications.
        from assets.models import ActifManquant, resoudre_cible

        try:
            resoudre_cible(organisation, cible)
        except (ActifManquant, PermissionError) as exc:
            raise OutilRefuse(str(exc)) from exc

    def arguments_docker(self, image: str, args: list[str],
                         montage: str | None = None) -> list[str]:
        """Ligne docker complete (separee pour etre testee sans Docker)."""
        commande = [
            "docker", "run", "--rm",
            "--network", self.reseau,     # bridge : hote inaccessible ; none
            "--read-only",                # aucune ecriture dans le conteneur
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--memory", self.memoire,
            "--pids-limit", "256",
        ]
        for chemin, taille in self.tmpfs.items():
            commande += ["--tmpfs", f"{chemin}:rw,noexec,nosuid,size={taille}"]
        for cle, valeur in self.env.items():
            commande += ["--env", f"{cle}={valeur}"]
        if montage:
            # --mount (et non -v) : pas d'analyse des « : » du chemin.
            commande += ["--mount", f"type=bind,source={montage},"
                                    f"target={CIBLE_CONTENEUR},readonly"]
        for volume, cible in self.volumes.items():
            commande += ["--mount", f"type=volume,source={volume},"
                                    f"target={cible}"]
        if self.entrypoint:
            commande += ["--entrypoint", self.entrypoint]
        return [*commande, image, *args]

    def _lancer(self, args: list[str], montage: str | None = None
                ) -> tuple[str, int]:
        runtime = settings.OUTILS["RUNTIME"]
        delai = min(self.delai, settings.OUTILS["TIMEOUT"])

        if runtime == "docker":
            if not self.image:
                raise OutilEchoue(f"{self.nom} : aucune image declaree.")
            image = image_figee(self.image)     # refuse :latest et non figee
            commande = self.arguments_docker(image, args, montage)
            # Module 7 du noyau d'integrite : l'isolation se VERIFIE avant
            # chaque lancement, elle ne se suppose pas. Un conteneur mal
            # enferme chez un client, c'est notre produit qui devient le
            # probleme (Claude, 20/09/2026).
            from brain.integrite.isolation import exigences_conteneur
            manques = exigences_conteneur(commande)
            if manques:
                raise OutilRefuse(f"{self.nom} : isolation insuffisante — "
                                  + " ; ".join(manques))
        else:
            # Mode local : uniquement pour le developpement.
            binaire = args[0]
            if shutil.which(binaire) is None:
                raise OutilEchoue(f"{binaire} absent du PATH (mode local).")
            commande = args

        proc = subprocess.run(  # noqa: S603 -- liste d'arguments, jamais shell=True
            commande, capture_output=True, timeout=delai, check=False,
            # Sortie d'un outil : elle contient ce qu'elle veut. Lue en
            # cp1252 (defaut Windows), un seul octet inattendu fait tomber
            # le fil de lecture et la sortie est PERDUE -- donc le garde-fou
            # qui cherche « failed to » dedans ne voit plus rien (22/09).
            text=True, encoding="utf-8", errors="replace"
        )
        return (proc.stdout or "") + (proc.stderr or ""), proc.returncode


# --------------------------------------------------------------------- registre
class Registre:
    """Catalogue des outils. Source unique pour le modele et pour les tests."""

    def __init__(self):
        self._outils: dict[str, Outil] = {}

    def inscrire(self, classe: type[Outil]) -> type[Outil]:
        if not classe.nom:
            raise ValueError(f"{classe.__name__} doit declarer un nom.")
        self._outils[classe.nom] = classe()
        return classe

    def __getitem__(self, nom: str) -> Outil:
        if nom not in self._outils:
            raise OutilRefuse(f"Outil « {nom} » inconnu.")
        return self._outils[nom]

    def noms(self) -> list[str]:
        return sorted(self._outils)

    def definitions(self, *, seulement: list[str] | None = None) -> list[dict]:
        """Definitions de fonctions donnees au modele.

        Le modele ne voit que les outils qu'on lui autorise pour cette tache.
        Un outil absent de la liste est inappelable, pas seulement decourage.
        """
        choisis = seulement or self.noms()
        return [
            {
                "type": "function",
                "function": {
                    "name": o.nom,
                    "description": o.description,
                    "parameters": o.schema,
                },
            }
            for nom, o in self._outils.items()
            if nom in choisis
        ]

    def appeler(self, nom: str, *, organisation, arguments: dict | str) -> dict:
        """Point d'entree unique depuis la boucle du cerveau."""
        if isinstance(arguments, str):
            # Les modeles echappent le JSON differemment : toujours parser.
            arguments = json.loads(arguments)
        outil = self[nom]
        cible = arguments.pop("cible", "")
        obs = outil.executer(organisation=organisation, cible=cible, **arguments)
        return obs.pour_le_modele()


registre = Registre()
