"""Module 4 du noyau d'integrite : integrite des binaires de la machine.

Trois questions posees a la machine auditee (jamais a l'hote de MAEL) :

  1. le gestionnaire de paquets est-il d'accord avec le disque ?
     `dpkg -V` (Debian/Ubuntu) ou `rpm -Va` (RHEL/SUSE) signale tout fichier
     dont l'empreinte, les droits ou le proprietaire ont change depuis
     l'installation ;
  2. les binaires sensibles ont-ils bouge entre deux passages ?
     `sha256sum` d'une liste courte (sudo, sshd, ps, ls, systemd...) compare
     a un releve date ;
  3. y a-t-il, dans les repertoires de binaires, des fichiers qu'aucun paquet
     ne revendique ? (implant depose a cote des vrais binaires)

Ce que ce module NE prouve PAS, et qui est ecrit ici pour qu'on ne le vende
pas : la base de dpkg est un fichier comme un autre, un attaquant root peut
la reecrire, et un releve d'empreintes ne vaut que si le premier passage a
eu lieu sur une machine saine. Ce module detecte l'ordinaire (binaire
remplace, droits eleves, implant pose a cote), pas un adversaire qui tenait
la machine avant la premiere mesure.

Le code juge ; le modele ne voit que le resultat.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from brain.garde import NIVEAU, classer

# --------------------------------------------------------------------------- #
# Commandes (toutes en LECTURE : verifie par le garde-fou avant execution)
# --------------------------------------------------------------------------- #

VERIFICATION = {
    "debian": ["dpkg", "-V"],
    "rhel": ["rpm", "-Va"],
    "suse": ["rpm", "-Va"],
}

# Fichiers revendiques par les paquets (une ligne par fichier, espace en tete).
FICHIERS_CONNUS = ["dpkg-query", "-W", "-f=${db-fsys:Files}\n"]

# Detournements declares (dpkg-divert) : un fichier officiellement remplace
# par un autre. Les images Docker s'en servent (man, initctl) ; un intrus
# aussi, d'ou une categorie a part plutot qu'un silence.
DETOURNEMENTS = ["dpkg-divert", "--list"]

# Repertoires ou un fichier n'a rien a faire s'il n'appartient a aucun paquet.
DOSSIERS_BINAIRES = ("/usr/bin", "/usr/sbin", "/usr/local/bin",
                     "/usr/local/sbin", "/bin", "/sbin")

# Binaires qu'un intrus remplace en premier : les commandes d'administration
# et celles qui SERVENT A LE VOIR (ls, ps, ss, last...).
BINAIRES_SENSIBLES = (
    "/usr/bin/sudo", "/usr/bin/su", "/usr/bin/passwd", "/usr/bin/login",
    "/usr/sbin/sshd", "/usr/bin/ssh", "/usr/bin/bash", "/usr/bin/dash",
    "/usr/lib/systemd/systemd", "/usr/bin/systemctl", "/usr/bin/dpkg",
    "/usr/bin/apt", "/usr/bin/crontab", "/usr/sbin/cron",
    "/usr/bin/ls", "/usr/bin/ps", "/usr/bin/ss", "/usr/bin/netstat",
    "/usr/bin/find", "/usr/bin/who", "/usr/bin/last", "/usr/bin/top",
    "/usr/bin/curl", "/usr/bin/wget", "/usr/bin/python3",
)

# Ce que les images et les machines minces retirent legitimement : la
# documentation. `dpkg -V` la signale « missing » par milliers sur une image
# Docker ; ce n'est pas une atteinte a l'integrite (constate le 20/09/2026).
BRUIT = ("/usr/share/doc/", "/usr/share/man/", "/usr/share/info/",
         "/usr/share/locale/", "/usr/share/help/",
         # caches et journaux : vides ou purges par construction, ils ne
         # disent rien de l'integrite des programmes
         "/var/lib/apt/lists/", "/var/cache/", "/var/log/")

_SENS = {"5": "empreinte differente du paquet", "S": "taille differente",
         "M": "droits differents", "U": "proprietaire different",
         "G": "groupe different", "T": "date differente",
         "L": "lien symbolique different", "D": "peripherique different",
         "P": "capacites differentes"}

_RE_LIGNE = re.compile(r"^(?P<drapeaux>\S{9})\s+(?:(?P<conf>c)\s+)?"
                       r"(?P<fichier>/\S.*)$")
_RE_MANQUANT = re.compile(r"^missing\s+(?:(?P<conf>c)\s+)?(?P<fichier>/\S.*)$")
_RE_DETOUR = re.compile(r"^(?P<local>local )?diversion of (?P<origine>\S+) "
                        r"to (?P<remplacement>\S+)(?: by (?P<paquet>\S+))?$")


@dataclass(frozen=True)
class Modification:
    """Un fichier que le gestionnaire de paquets ne reconnait plus."""
    fichier: str
    drapeaux: str
    conffile: bool
    quoi: tuple[str, ...]
    grave: bool

    def __str__(self) -> str:
        quoi = ", ".join(self.quoi) or self.drapeaux
        marque = "GRAVE " if self.grave else ""
        return (f"{marque}{self.fichier} : {quoi}"
                + (" (fichier de configuration)" if self.conffile else ""))


def _lecture(machine, argv: list[str]) -> tuple[int, str]:
    """Execute une commande de LECTURE sur la machine ; rend (code, stdout).

    Le garde-fou passe avant, comme partout ailleurs : ce noyau ne modifie
    jamais la machine qu'il mesure."""
    commande = " ".join(argv)
    v = classer(commande)
    if v.niveau is not NIVEAU.LECTURE:
        raise ValueError(f"commande non LECTURE ({v.motif}) : {commande}")
    r = machine.executer(argv, racine=True)
    return r.code, (r.stdout or "")


def _normaliser(chemin: str) -> str:
    """/bin/ls et /usr/bin/ls sont le meme fichier depuis la fusion de /usr."""
    for court in ("/bin/", "/sbin/", "/lib/", "/lib64/"):
        if chemin.startswith(court):
            return "/usr" + chemin
    return chemin


def _du_bruit(chemin: str) -> bool:
    return chemin.startswith(BRUIT)


def modifications(machine, famille: str = "debian") -> list[Modification]:
    """Fichiers que le gestionnaire de paquets ne reconnait plus.

    La documentation retiree (images minces) n'est pas comptee. Un fichier de
    configuration modifie n'est PAS grave : c'est le travail normal d'un
    durcissement, y compris celui de MAEL. Un binaire dont l'empreinte a
    change, lui, l'est."""
    argv = VERIFICATION.get(famille)
    if argv is None:
        raise ValueError(f"famille inconnue : {famille}")
    code, sortie = _lecture(machine, argv)
    if code not in (0, 1):
        raise RuntimeError(f"{' '.join(argv)} a echoue (code {code})")

    trouvees = []
    for ligne in sortie.splitlines():
        ligne = ligne.rstrip()
        if not ligne:
            continue
        m = _RE_MANQUANT.match(ligne)
        if m:
            fichier = m.group("fichier")
            if _du_bruit(fichier):
                continue
            conf = bool(m.group("conf"))
            trouvees.append(Modification(fichier, "missing", conf,
                                         ("fichier absent du disque",),
                                         grave=not conf))
            continue
        m = _RE_LIGNE.match(ligne)
        if not m:
            continue
        fichier = m.group("fichier")
        if _du_bruit(fichier):
            continue
        drapeaux = m.group("drapeaux")
        conf = bool(m.group("conf"))
        quoi = tuple(_SENS[d] for d in drapeaux if d in _SENS)
        grave = (("5" in drapeaux or "M" in drapeaux or "U" in drapeaux)
                 and not conf)
        trouvees.append(Modification(fichier, drapeaux, conf, quoi, grave))
    return trouvees


def empreintes(machine, chemins=BINAIRES_SENSIBLES) -> dict[str, str]:
    """sha256 des binaires presents (les absents ne sont pas inventes)."""
    _, sortie = _lecture(machine, ["sha256sum", "--", *chemins])
    releve = {}
    for ligne in sortie.splitlines():
        parties = ligne.split(None, 1)
        if len(parties) == 2 and len(parties[0]) == 64:
            releve[_normaliser(parties[1].strip())] = parties[0]
    return releve


def derive(reference: dict[str, str], mesure: dict[str, str]) -> list[str]:
    """Ce qui a bouge entre un releve date et la mesure d'aujourd'hui."""
    ecarts = []
    for chemin, empreinte in sorted(reference.items()):
        if chemin not in mesure:
            ecarts.append(f"{chemin} : a DISPARU depuis le releve")
        elif mesure[chemin] != empreinte:
            ecarts.append(f"{chemin} : empreinte CHANGEE "
                          f"({empreinte[:12]} -> {mesure[chemin][:12]})")
    for chemin in sorted(set(mesure) - set(reference)):
        ecarts.append(f"{chemin} : APPARU depuis le releve")
    return ecarts


def detournements(machine) -> dict[str, str]:
    """Fichiers officiellement remplaces par un autre (dpkg-divert).

    C'est une pratique legitime (une image Docker remplace `man` et
    `initctl`) et une technique d'intrus : on la montre, on ne la tait
    pas."""
    code, sortie = _lecture(machine, DETOURNEMENTS)
    if code != 0:
        return {}
    trouves = {}
    for ligne in sortie.splitlines():
        m = _RE_DETOUR.match(ligne.strip())
        if m:
            par = m.group("paquet") or "personne (detournement local)"
            trouves[_normaliser(m.group("origine"))] = (
                f"{m.group('remplacement')} — par {par}")
    return trouves


def sans_paquet(machine, dossiers=DOSSIERS_BINAIRES) -> list[str]:
    """Fichiers des repertoires de binaires qu'aucun paquet ne revendique.

    Deux lectures seulement, et c'est le code qui fait la difference : la
    liste des fichiers connus de dpkg d'un cote, le contenu reel des
    repertoires de l'autre."""
    code, connus = _lecture(machine, FICHIERS_CONNUS)
    if code != 0:
        raise RuntimeError(f"dpkg-query a echoue (code {code})")
    revendiques = {_normaliser(l.strip()) for l in connus.splitlines()
                   if l.strip().startswith("/")}
    # un fichier detourne est revendique, sous son nom d'origine ET sous son
    # nom de remplacement (man -> man.REAL)
    for origine, vers in detournements(machine).items():
        revendiques.add(origine)
        revendiques.add(_normaliser(vers.split(" — ")[0]))
    _, presents = _lecture(machine, ["find", *dossiers, "-maxdepth", "1",
                                     "-type", "f", "-print"])
    intrus = []
    for ligne in presents.splitlines():
        chemin = ligne.strip()
        if chemin.startswith("/") and _normaliser(chemin) not in revendiques:
            intrus.append(chemin)
    return sorted(intrus)


def controler(machine, famille: str = "debian",
              reference: dict[str, str] | None = None) -> dict:
    """Les trois questions d'un coup ; rien n'est corrige, tout est dit."""
    mesure = empreintes(machine)
    mods = modifications(machine, famille)
    debian = famille == "debian"
    return {
        "modifications": [str(m) for m in mods],
        "graves": [str(m) for m in mods if m.grave],
        "empreintes": mesure,
        "derive": derive(reference, mesure) if reference else [],
        "sans_paquet": sans_paquet(machine) if debian else [],
        "detournements": [f"{o} -> {v}" for o, v in
                          sorted(detournements(machine).items())] if debian
        else [],
    }
