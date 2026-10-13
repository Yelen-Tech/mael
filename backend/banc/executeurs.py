"""Executeurs du banc d'essai (point 4, partie A).

Un EXECUTEUR lance une commande sur un systeme de test et rend le resultat.
Deux implementations :

  ExecuteurDocker   -- conteneur jetable par image (le vrai banc, quand
                       Docker fonctionnera) ;
  ExecuteurFactice  -- sorties preenregistrees, journalise les commandes
                       recues : c'est lui qui teste tout le reste du banc
                       sans Docker.

Regles (consignes de l'architecte, 19/09/2026) :
  - argv est une LISTE, jamais une chaine de shell cote Python ; la commande
    d'une fiche est passee comme UN argument a `bash -c` dans le conteneur ;
  - conteneur jetable nomme mael-banc-<uuid>, suppression garantie ;
  - aucun volume monte depuis l'hote, pas de --privileged, reseau coupe
    (--network none) sauf pour l'installation des paquets ;
  - rien n'est execute sur l'hote en root.
"""
from __future__ import annotations

import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Resultat:
    """Sortie d'une commande executee sur le systeme de test."""
    code: int
    stdout: str = ""
    stderr: str = ""
    duree_ms: int = 0


class Executeur:
    """Interface unique. argv : liste d'arguments (jamais de shell cote
    Python). racine=True : executer en root dans le conteneur."""

    def executer(self, argv: list[str], racine: bool = True,
                 delai: int | None = None) -> Resultat:
        """delai : secondes accordees a CETTE commande (None = delai par
        defaut de l'executeur). Une commande qui balaye tout le disque
        (find /) en demande plus qu'une lecture de fichier."""
        raise NotImplementedError

    def copier(self, source: Path, destination: str) -> None:
        """Copie un fichier ou dossier de l'hote vers le systeme de test."""
        raise NotImplementedError

    def __enter__(self) -> "Executeur":
        return self

    def __exit__(self, *exc) -> None:
        pass


class ExecuteurDocker(Executeur):
    """Conteneur jetable par image. Necessite Docker (bloque au 19/09/2026).

    Le conteneur est cree au `__enter__` et DETRUIT au `__exit__`, quoi
    qu'il arrive (docker rm -f). Le reseau est coupe par defaut ; passer
    reseau=True uniquement pour l'etape d'installation des paquets.
    """

    def __init__(self, image: str, reseau: bool = False, delai: int = 120,
                 options: tuple[str, ...] = (), prefixe: str = "mael-banc"):
        """options : arguments de `docker run` en plus (ex. le plafond de
        memoire de l'atelier de code : --memory 512m --cpus 1)."""
        self.image = image
        self.reseau = reseau
        self.delai = delai
        self.options = tuple(options)
        self.nom = f"{prefixe}-{uuid.uuid4().hex[:12]}"
        self._pret = False

    def _docker(self, args: list[str],
                delai: int | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["docker", *args], capture_output=True,
                              text=True, timeout=delai or self.delai,
                              check=False)

    def __enter__(self) -> "ExecuteurDocker":
        args = ["run", "-d", "--name", self.nom, *self.options]
        if not self.reseau:
            args += ["--network", "none"]
        # sleep infinity : le conteneur vit le temps du banc, les commandes
        # arrivent par docker exec.
        proc = self._docker([*args, self.image, "sleep", "infinity"])
        if proc.returncode != 0:
            raise RuntimeError(f"docker run a echoue : {proc.stderr.strip()}")
        self._pret = True
        return self

    def __exit__(self, *exc) -> None:
        if self._pret:
            self._docker(["rm", "-f", self.nom])   # destruction garantie
            self._pret = False

    def executer(self, argv: list[str], racine: bool = True,
                 delai: int | None = None) -> Resultat:
        if not self._pret:
            raise RuntimeError("executeur hors conteneur (utiliser with)")
        commande = ["exec", f"--user={'0' if racine else '65534'}",
                    self.nom, *argv]
        debut = time.perf_counter()
        try:
            proc = self._docker(commande, delai=delai)
        except subprocess.TimeoutExpired:
            # Une commande lente (find / sur une machine lente) ne doit pas
            # faire tomber tout le banc : 124 = delai depasse (comme timeout).
            return Resultat(124, "", f"delai depasse ({delai or self.delai} s)",
                            int((time.perf_counter() - debut) * 1000))
        return Resultat(proc.returncode, proc.stdout or "", proc.stderr or "",
                        int((time.perf_counter() - debut) * 1000))

    def copier(self, source: Path, destination: str) -> None:
        """docker cp, la seule entree de fichiers (aucun volume monte).

        Le dossier d'accueil est cree d'abord : `docker cp` refuse une
        destination dont le parent n'existe pas (premier passage reel du
        banc des playbooks, 20/09/2026)."""
        parent = destination.rsplit("/", 1)[0] or "/"
        self._docker(["exec", "--user=0", self.nom, "mkdir", "-p", parent])
        proc = self._docker(["cp", str(source), f"{self.nom}:{destination}"])
        if proc.returncode != 0:
            raise RuntimeError(f"docker cp a echoue : {proc.stderr.strip()}")


class ExecuteurFactice(Executeur):
    """Sorties preenregistrees + journal des commandes recues.

    reponses : dict commande -> (code, stdout, stderr). La cle est la
    commande telle que passee a `bash -c` (UN seul argument). Une commande
    inconnue rend 127 (commande introuvable), comme un vrai conteneur sans
    le binaire.
    """

    def __init__(self, reponses: dict[str, tuple[int, str, str]] | None = None):
        self.reponses = dict(reponses or {})
        self.journal: list[tuple[list[str], bool]] = []   # (argv, racine)
        self.delais: list[int] = []      # delais propres demandes (non None)
        self.copies: list[tuple[str, str]] = []           # (source, dest)

    def executer(self, argv: list[str], racine: bool = True,
                 delai: int | None = None) -> Resultat:
        self.journal.append((list(argv), racine))
        if delai is not None:
            self.delais.append(delai)
        if argv[:2] == ["bash", "-c"] and len(argv) == 3:
            cmd = argv[2]
            if cmd in self.reponses:
                code, out, err = self.reponses[cmd]
                return Resultat(code, out, err)
            return Resultat(127, "", f"bash: commande inconnue : {cmd[:60]}")
        return Resultat(0, "", "")     # hors bash -c : succes silencieux

    def copier(self, source: Path, destination: str) -> None:
        self.copies.append((str(source), destination))


class ExecuteurWSL(Executeur):
    """Une VRAIE machine Linux : noyau, systemd, /proc/sys inscriptible.

    Cinq playbooks touchent au noyau ou a systemd. Dans un conteneur,
    /proc/sys est en lecture seule et systemd n'est pas PID 1 : le banc les
    met de cote (« a tester en VM », constate le 20/09/2026). WSL2 fournit
    ce qui manquait -- un vrai noyau, systemd, et les droits root.

    Trois differences avec le conteneur, dites franchement :

      1. **il n'y a pas d'isolation**. Le playbook modifie REELLEMENT la
         distribution. Le banc applique, verifie, re-mesure, puis annule
         (etape « revenir ») et compare l'empreinte de l'etat au depart :
         une restauration ratee se voit, elle ne se devine pas ;
      2. **rien n'est jetable** : pas de conteneur neuf entre deux
         playbooks. Un playbook qui laisse une trace la laisse pour le
         suivant -- c'est justement ce que la comparaison d'empreinte
         detecte ;
      3. **le reseau de la machine est celui de l'hote.** Aucun playbook du
         banc n'en a besoin ; si l'un en demandait, ce serait a dire.

    Usage : `python -m banc.playbooks --vm Ubuntu` (implique --vraie-machine).
    """

    def __init__(self, distribution: str = "Ubuntu", delai: int = 180):
        self.distribution = distribution
        self.delai = delai

    # -- WSL parle en UTF-16 pour SES messages, en UTF-8 pour la sortie du
    # programme lance. On lit donc des octets et on decode nous-memes.
    @staticmethod
    def _propre(flux: bytes) -> str:
        texte = flux.decode("utf-8", errors="replace")
        # « wsl: Failed to start the systemd user session... » revient a
        # chaque appel et n'appartient pas au resultat de la commande.
        return "\n".join(l for l in texte.splitlines()
                         if not l.startswith("wsl: ")).strip("\n")

    def _wsl(self, args: list[str], racine: bool,
             delai: int | None) -> subprocess.CompletedProcess:
        # --exec, et surtout PAS « -- » : sans lui, wsl.exe fait passer la
        # commande par un shell de connexion qui la relit avant nous. « $ »
        # et « \ » y disparaissent : `dpkg-query -f='${Status}'` arrivait
        # vide, et la re-mesure declarait absent un paquet installe (faux
        # verdict decouvert au premier banc sur machine reelle, 22/09).
        prefixe = ["wsl.exe", "-d", self.distribution, "-u", "root", "--exec"]
        if not racine:
            # Meme identite que dans le conteneur (65534 = nobody), sans
            # dependre de l'existence d'un shell pour cet utilisateur.
            args = ["setpriv", "--reuid=65534", "--regid=65534",
                    "--clear-groups", *args]
        return subprocess.run([*prefixe, *args], capture_output=True,
                              timeout=delai or self.delai, check=False)

    def executer(self, argv: list[str], racine: bool = True,
                 delai: int | None = None) -> Resultat:
        debut = time.perf_counter()
        try:
            proc = self._wsl(list(argv), racine, delai)
        except subprocess.TimeoutExpired:
            return Resultat(124, "", f"delai depasse ({delai or self.delai} s)",
                            int((time.perf_counter() - debut) * 1000))
        except FileNotFoundError:
            return Resultat(127, "", "wsl.exe introuvable sur cette machine",
                            int((time.perf_counter() - debut) * 1000))
        return Resultat(proc.returncode, self._propre(proc.stdout),
                        self._propre(proc.stderr),
                        int((time.perf_counter() - debut) * 1000))

    @staticmethod
    def _chemin_linux(source: Path) -> str:
        """Un chemin Windows tel que WSL le voit : le lecteur C devient
        /mnt/c, et les separateurs deviennent des barres obliques.

        La conversion se fait ICI et pas avec `wslpath` : wsl.exe reassemble
        la ligne de commande, et les barres obliques inverses d'un chemin
        Windows n'y survivent pas (elles sont mangees comme des echappements
        — constate au premier passage du banc sur machine reelle, 22/09)."""
        chemin = Path(source).resolve()
        lecteur = chemin.drive.rstrip(":").lower()
        if not lecteur:
            return chemin.as_posix()          # deja un chemin Unix
        reste = chemin.as_posix()[len(chemin.drive):]
        return f"/mnt/{lecteur}{reste}"

    def copier(self, source: Path, destination: str) -> None:
        """Copie depuis l'hote Windows : WSL voit le disque sous /mnt."""
        cote_linux = self._chemin_linux(source)
        vu = self.executer(["test", "-e", cote_linux])
        if vu.code != 0:
            raise RuntimeError(
                f"{source} est invisible depuis {self.distribution} "
                f"(cherche en {cote_linux}). Le montage automatique des "
                f"disques Windows est-il actif dans cette distribution ?")
        parent = destination.rsplit("/", 1)[0] or "/"
        self.executer(["mkdir", "-p", parent])
        r = self.executer(["cp", "-r", cote_linux, destination])
        if r.code != 0:
            raise RuntimeError(f"copie vers {destination} a echoue : {r.stderr}")

    def systeme(self) -> str:
        """« ubuntu:26.04 » : de quoi filtrer les fiches comme pour une image.

        On lit le fichier et on l'analyse ICI plutot que de demander au shell
        de le faire : wsl.exe reassemble la ligne de commande a sa facon, et
        une substitution de variable n'y survit pas toujours."""
        r = self.executer(["cat", "/etc/os-release"])
        champs = {}
        for ligne in r.stdout.splitlines():
            cle, _, valeur = ligne.partition("=")
            champs[cle.strip()] = valeur.strip().strip('"')
        identifiant = champs.get("ID", "")
        version = champs.get("VERSION_ID", "")
        return f"{identifiant}:{version}" if identifiant and version else "inconnu"
