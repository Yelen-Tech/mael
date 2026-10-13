"""Ce que la machine de l'utilisateur peut porter.

MAEL s'installe aussi bien sur un portable de bureau a 8 Go que sur une tour
a 128 Go avec une carte graphique. Le meme code doit servir les deux : celui
qui n'a qu'un petit modele ne doit jamais recevoir un choix qui fera ramer sa
machine, et celui qui a mieux que nos modeles doit s'en servir.

D'ou ce module : il mesure la memoire REELLE, sans aucune dependance
supplementaire (l'installation locale doit rester legere -- chantier L2), et
sans rien envoyer nulle part. Trois systemes, trois lectures :

  Linux   /proc/meminfo
  Windows GlobalMemoryStatusEx (ctypes, pas de paquet a installer)
  macOS   sysctl hw.memsize

La carte graphique, elle, se demande a `nvidia-smi` s'il est la. Absent, ce
n'est pas une erreur : la plupart des utilisateurs n'en ont pas, et Ollama
tourne tres bien sur le processeur.
"""
from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass

GO = 1024 ** 3


def _octets_lisibles(octets: int) -> str:
    if not octets:
        return "?"
    return f"{octets / GO:.1f} Go"


# --------------------------------------------------------------------------- #
# Memoire vive
# --------------------------------------------------------------------------- #
def _meminfo_linux() -> tuple[int, int]:
    total = dispo = 0
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for ligne in f:
                cle, _, reste = ligne.partition(":")
                if cle == "MemTotal":
                    total = int(reste.split()[0]) * 1024
                elif cle == "MemAvailable":
                    dispo = int(reste.split()[0]) * 1024
                if total and dispo:
                    break
    except (OSError, ValueError, IndexError):
        return 0, 0
    return total, dispo or total


def _memoire_windows() -> tuple[int, int]:
    import ctypes

    class _Etat(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    etat = _Etat()
    etat.dwLength = ctypes.sizeof(_Etat)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(etat)):
            return 0, 0
    except (AttributeError, OSError):
        return 0, 0
    return int(etat.ullTotalPhys), int(etat.ullAvailPhys)


def _memoire_macos() -> tuple[int, int]:
    try:
        sortie = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                capture_output=True, text=True, timeout=3)
        total = int(sortie.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0, 0
    # Pas de MemAvailable simple sur macOS : on reste prudent et on compte
    # les trois quarts de la memoire installee comme utilisables.
    return total, int(total * 0.75)


def memoire() -> tuple[int, int]:
    """(totale, disponible) en octets. (0, 0) si on ne sait pas lire."""
    systeme = platform.system()
    if systeme == "Linux":
        return _meminfo_linux()
    if systeme == "Windows":
        return _memoire_windows()
    if systeme == "Darwin":
        return _memoire_macos()
    return 0, 0


# --------------------------------------------------------------------------- #
# Carte graphique (facultative)
# --------------------------------------------------------------------------- #
def carte_graphique() -> tuple[str, int] | None:
    """(nom, memoire video) si nvidia-smi repond. Rien sinon -- ce n'est pas
    une anomalie : Ollama tourne sur le processeur."""
    try:
        sortie = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if sortie.returncode != 0 or not sortie.stdout.strip():
        return None
    premiere = sortie.stdout.strip().splitlines()[0]
    nom, _, mib = premiere.partition(",")
    try:
        return nom.strip(), int(float(mib.strip())) * 1024 * 1024
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Ce qu'on en retient
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Capacite:
    """Ce que la machine peut porter, et jusqu'ou on la pousse.

    Deux seuils plutot qu'un : « a l'aise » et « au plus juste ». Entre les
    deux, un modele tourne mais fait souffrir la machine : MAEL le prend
    quand il n'y a rien de mieux, et le DIT.

    Les deux seuils se calculent sur la memoire INSTALLEE autant que sur la
    memoire libre : le systeme rend ses caches quand un programme demande de
    la place. Ne compter que le libre de l'instant declarerait « trop gros »
    un modele que l'utilisateur fait tourner tous les jours."""
    ram_totale: int = 0
    ram_libre: int = 0
    vram: int = 0
    gpu: str = ""
    fraction_confortable: float = 0.6
    fraction_serree: float = 0.9

    @property
    def a_l_aise(self) -> int:
        """Ce qui tient sans faire souffrir la machine."""
        return max(self.ram_libre, self.vram,
                   int(self.ram_totale * self.fraction_confortable))

    @property
    def au_plus_juste(self) -> int:
        """Ce qui tient en poussant la machine."""
        return max(int(self.ram_totale * self.fraction_serree), self.vram,
                   self.ram_libre)

    @property
    def connue(self) -> bool:
        return bool(self.ram_totale or self.vram)

    def libelle(self) -> str:
        if not self.connue:
            return "machine de capacite inconnue"
        morceaux = [f"{_octets_lisibles(self.ram_totale)} de memoire vive "
                    f"({_octets_lisibles(self.ram_libre)} libres)"]
        if self.vram:
            morceaux.append(f"{self.gpu or 'carte graphique'} "
                            f"{_octets_lisibles(self.vram)}")
        return ", ".join(morceaux)


_capacite: Capacite | None = None


def capacite(recharger: bool = False) -> Capacite:
    """Mesure la machine une fois par processus (lecture instantanee, sauf
    nvidia-smi : quelques dizaines de millisecondes)."""
    global _capacite
    if _capacite is not None and not recharger:
        return _capacite
    totale, libre = memoire()
    gpu = carte_graphique() if os.environ.get("MAEL_SANS_GPU") != "1" else None
    _capacite = Capacite(ram_totale=totale, ram_libre=libre,
                         vram=gpu[1] if gpu else 0, gpu=gpu[0] if gpu else "")
    return _capacite


def oublier() -> None:
    global _capacite
    _capacite = None


_ansi_actif: bool | None = None


def activer_sequences_ansi() -> bool:
    """Windows : demander a la console d'INTERPRETER les couleurs.

    Ailleurs, un terminal affiche les sequences ANSI sans qu'on demande rien.
    La console Windows, elle, les imprime telles quelles tant qu'on ne lui a
    pas active le « rendu virtuel » -- et l'utilisateur voit alors
    « ←[1;38;5;51mmael › » au lieu d'un titre en couleur, l'orbe laisse des
    debris a l'ecran, l'outil parait casse (friction relevee par le
    responsable pendant l'epreuve L3, 22/09).

    Rend vrai si la console sait desormais afficher les couleurs. Faux si on
    n'a pas pu : l'appelant coupe alors la couleur et tout reste lisible, ce
    qui vaut infiniment mieux qu'un ecran de codes d'echappement."""
    global _ansi_actif
    if _ansi_actif is not None:
        return _ansi_actif
    if platform.system() != "Windows":
        _ansi_actif = True
        return True

    RENDU_VIRTUEL = 0x0004
    SORTIE, ERREUR = -11, -12
    try:
        import ctypes

        noyau = ctypes.windll.kernel32
        obtenu = False
        for flux in (SORTIE, ERREUR):
            poignee = noyau.GetStdHandle(flux)
            if not poignee or poignee == -1:
                continue
            mode = ctypes.c_uint32()
            if not noyau.GetConsoleMode(poignee, ctypes.byref(mode)):
                continue          # pas une console : tube ou fichier
            if mode.value & RENDU_VIRTUEL:
                obtenu = True
            elif noyau.SetConsoleMode(poignee, mode.value | RENDU_VIRTUEL):
                obtenu = True
        _ansi_actif = obtenu
    except (AttributeError, OSError, ValueError):
        _ansi_actif = False
    return _ansi_actif


def profil_conseille(capa: Capacite | None = None) -> str:
    """« court » ou « complet » : la taille du mode d'emploi envoye au modele.

    Ce n'est pas un reglage de confort. Mesure du 22/09 sur un portable de
    8 Go sans carte graphique : 130 s de reponse en profil court, 295 s en
    complet -- pour la MEME question. Sur une machine modeste, le profil
    complet transforme un echange en attente interminable ; sur une machine
    capable, il n'y a aucune raison de s'en priver.

    L'utilisateur garde le dernier mot : ce n'est qu'un defaut, que le
    reglage « profil » et l'option --profil remplacent."""
    capa = capa if capa is not None else capacite()
    if not capa.connue:
        return "complet"
    if capa.vram >= 8 * GO:            # carte graphique digne de ce nom
        return "complet"
    return "court" if capa.ram_totale < 16 * GO else "complet"


def budget_savoir_conseille(capa: Capacite | None = None) -> int:
    """Combien de jetons de savoir on s'autorise a injecter par question.

    Ce budget n'est pas gratuit : il s'ajoute au mode d'emploi et le modele
    doit tout RELIRE a chaque question. Mesure du 22/09 sur le portable vise
    (8 Go, sans carte graphique) : environ **26 jetons lus par seconde**,
    soit quatre secondes par centaine de jetons. Un budget de 700 jetons,
    c'est donc 27 secondes d'attente ajoutees a chaque question.

    Sur une machine capable, la question ne se pose pas : plus de savoir
    verifie, c'est moins d'invention. Sur une petite machine, c'est le choix
    entre un peu moins de contexte et une conversation deux fois plus
    rapide -- et une reponse qui arrive est plus utile qu'une reponse
    complete qui n'arrive pas."""
    capa = capa if capa is not None else capacite()
    if not capa.connue or capa.vram >= 8 * GO:
        return 1200
    if capa.ram_totale >= 16 * GO:
        return 700
    return 250


def contexte_conseille(capa: Capacite | None = None) -> int:
    """Taille de contexte (num_ctx) que cette machine supporte sans souffrir.

    Le contexte se paie deux fois : en memoire (le cache des jetons est
    alloue d'avance) et en temps (chaque jeton du prompt est relu a chaque
    question). Sur un portable de 8 Go, 8192 prend de la place que le modele
    n'a deja pas, pour une conversation qui atteint rarement 2 000 jetons.

    4096 en dessous de 16 Go sans carte graphique, 8192 sinon."""
    capa = capa if capa is not None else capacite()
    if not capa.connue or capa.vram >= 8 * GO:
        return 8192
    return 4096 if capa.ram_totale < 16 * GO else 8192


def tient(besoin: int, capa: Capacite | None = None, *,
          serre: bool = False) -> bool:
    """Est-ce que ce besoin de memoire tient sur cette machine ?

    Capacite inconnue : on repond oui. Mieux vaut laisser tourner (l'utilisateur
    verra bien) que refuser un modele sur une mesure qu'on n'a pas su faire."""
    capa = capa if capa is not None else capacite()
    if not capa.connue:
        return True
    return besoin <= (capa.au_plus_juste if serre else capa.a_l_aise)
