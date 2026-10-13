"""Module 6 du noyau d'integrite : infiltration par LD_PRELOAD et hooks.

Avant de remplacer un binaire (ce que le module 4 verrait), un intrus fait
plus simple : il demande a l'editeur de liens de charger SA bibliotheque
avant toutes les autres. Le programme reste intact sur le disque, dpkg est
content, et pourtant `ls` ne montre plus ses fichiers.

Ce module va voir les cinq endroits ou cela se declare :

  1. /etc/ld.so.preload      -- charge dans TOUT programme de la machine ;
  2. l'environnement des processus en cours (LD_PRELOAD, LD_AUDIT) ;
  3. les fichiers ou le systeme declare ses variables (/etc/environment,
     profil du shell, unites systemd) ;
  4. les chemins de bibliotheques ajoutes (ld.so.conf.d) ;
  5. les modules charges dans le noyau (hook de plus bas niveau).

Gravite : un preload GLOBAL ou DECLARE est grave -- c'est rarement
legitime et toujours total. Un LD_PRELOAD dans un processus isole se
verifie (des logiciels honnetes s'en servent), il ne se condamne pas.

Ce que ce module NE prouve PAS : un hook pose dans le noyau lui-meme
(module signe, eBPF) ne se lit pas depuis l'espace utilisateur ; et si la
bibliotheque intruse ment sur les lectures, elle peut se cacher d'elle-meme.
C'est pourquoi il regarde plusieurs endroits independants plutot qu'un seul.

Le code juge ; le modele ne voit que le resultat.
"""
from __future__ import annotations

from dataclasses import dataclass

from brain.garde import NIVEAU, classer

# Repertoires de bibliotheques d'une distribution ordinaire. Tout le reste
# est un ajout, donc quelque chose a expliquer.
CHEMINS_ORDINAIRES = (
    "/lib", "/lib64", "/lib32", "/libx32", "/usr/lib", "/usr/lib64",
    "/usr/lib32", "/usr/libx32", "/usr/local/lib",
)

# La ou un systeme declare ses variables d'environnement.
DECLARATIONS = ("/etc/environment", "/etc/profile", "/etc/profile.d",
                "/etc/systemd/system", "/etc/systemd/user",
                "/lib/systemd/system", "/etc/default",
                "/root/.bashrc", "/root/.profile", "/root/.bash_profile")

GRAVE, A_VERIFIER, TENU = "grave", "a verifier", "tenu"


@dataclass(frozen=True)
class Constat:
    """Ce qui a ete regarde, et ce qui a ete vu."""
    sujet: str
    niveau: str          # GRAVE / A_VERIFIER / TENU
    detail: str

    def __str__(self) -> str:
        marque = {GRAVE: "GRAVE", A_VERIFIER: "a verifier", TENU: "tenu"}
        return f"[{marque[self.niveau]}] {self.sujet} : {self.detail}"


def _lire(machine, commande: str) -> tuple[int, str]:
    """Une lecture sur la machine, passee au garde-fou d'abord.

    La commande est donnee a `bash -c` comme UN argument (motifs /proc/*,
    tubes) : c'est la convention du banc, elle ne fabrique pas de shell
    cote Python."""
    v = classer(commande)
    if v.niveau is not NIVEAU.LECTURE:
        raise ValueError(f"commande non LECTURE ({v.motif}) : {commande}")
    r = machine.executer(["bash", "-c", commande], racine=True)
    return r.code, (r.stdout or "")


def preload_global(machine) -> Constat:
    """/etc/ld.so.preload : charge dans tout programme, sans exception."""
    code, sortie = _lire(machine, "cat /etc/ld.so.preload 2>/dev/null")
    lignes = [l.strip() for l in sortie.splitlines()
              if l.strip() and not l.strip().startswith("#")]
    if code != 0 or not lignes:
        return Constat("/etc/ld.so.preload", TENU,
                       "absent ou vide (c'est l'etat normal)")
    return Constat("/etc/ld.so.preload", GRAVE,
                   "charge dans TOUS les programmes : " + ", ".join(lignes))


def preload_processus(machine, limite: int = 15) -> list[Constat]:
    """LD_PRELOAD / LD_AUDIT dans l'environnement des processus en cours."""
    code, sortie = _lire(
        machine,
        "grep -a -l -s -e LD_PRELOAD -e LD_AUDIT /proc/[0-9]*/environ")
    chemins = [l.strip() for l in sortie.splitlines() if l.strip()]
    if not chemins:
        return [Constat("processus en cours", TENU,
                        "aucun LD_PRELOAD ni LD_AUDIT dans les "
                        "environnements lisibles")]
    constats = []
    for chemin in chemins[:limite]:
        pid = chemin.split("/")[2]
        _, nom = _lire(machine, f"cat /proc/{pid}/comm 2>/dev/null")
        _, valeur = _lire(
            machine,
            f"cat /proc/{pid}/environ 2>/dev/null | tr '\\0' '\\n' "
            "| grep -E '^LD_(PRELOAD|AUDIT)='")
        constats.append(Constat(
            f"processus {pid} ({nom.strip() or 'inconnu'})", A_VERIFIER,
            "; ".join(v.strip() for v in valeur.splitlines() if v.strip())
            or "variable presente, valeur illisible"))
    if len(chemins) > limite:
        constats.append(Constat("processus en cours", A_VERIFIER,
                                f"{len(chemins) - limite} autres processus "
                                "concernes, non detailles ici"))
    return constats


def preload_declare(machine) -> list[Constat]:
    """LD_PRELOAD ecrit dans la configuration du systeme : jamais anodin."""
    cibles = " ".join(DECLARATIONS)
    _, sortie = _lire(
        machine,
        "grep -rsE \"(^|[^A-Z_])(LD_PRELOAD|LD_AUDIT)=\" " + cibles)
    lignes = [l.strip() for l in sortie.splitlines() if l.strip()]
    if not lignes:
        return [Constat("declarations du systeme", TENU,
                        "aucun LD_PRELOAD declare dans la configuration")]
    return [Constat("declaration du systeme", GRAVE, l) for l in lignes[:20]]


def chemins_de_bibliotheques(machine) -> list[Constat]:
    """Repertoires ajoutes a la recherche de bibliotheques (ld.so.conf.d)."""
    _, sortie = _lire(machine,
                      "cat /etc/ld.so.conf /etc/ld.so.conf.d/*.conf "
                      "2>/dev/null")
    ajouts = []
    for ligne in sortie.splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or ligne.startswith("include"):
            continue
        if not ligne.startswith("/"):
            continue
        if not ligne.startswith(CHEMINS_ORDINAIRES):
            ajouts.append(ligne)
    if not ajouts:
        return [Constat("chemins de bibliotheques", TENU,
                        "aucun repertoire hors des emplacements ordinaires")]
    return [Constat("chemin de bibliotheques ajoute", A_VERIFIER, a)
            for a in ajouts]


def modules_noyau(machine) -> list[Constat]:
    """Modules charges dans le noyau : le hook le plus bas, et le plus dur
    a voir depuis l'espace utilisateur.

    Dans un conteneur, `lsmod` montre les modules de l'HOTE : le resultat
    ne dit rien de la machine mesuree. On le dit plutot que de le taire."""
    code, sortie = _lire(machine, "lsmod 2>/dev/null")
    lignes = [l for l in sortie.splitlines()[1:] if l.strip()]
    # Reconnaitre un conteneur : le fichier temoin d'abord (cgroup v2 ne
    # nomme plus docker dans /proc/1/cgroup), la cgroup ensuite.
    # (ls rend 2 des qu'UN des chemins manque : c'est la sortie qui compte,
    # pas le code de retour.)
    _, temoin = _lire(machine, "ls -d /.dockerenv /run/.containerenv "
                               "2>/dev/null")
    _, marque = _lire(machine, "cat /proc/1/cgroup 2>/dev/null | head -3")
    en_conteneur = (bool(temoin.strip()) or "docker" in marque
                    or "containerd" in marque or "lxc" in marque)
    if en_conteneur:
        return [Constat("modules du noyau", A_VERIFIER,
                        f"{len(lignes)} modules vus, mais ce sont ceux de "
                        "l'HOTE : mesure a refaire sur une vraie machine")]
    if code != 0:
        return [Constat("modules du noyau", A_VERIFIER,
                        "lsmod indisponible sur cette machine")]
    noms = sorted(l.split()[0] for l in lignes)
    return [Constat("modules du noyau", TENU,
                    f"{len(noms)} modules charges : {', '.join(noms[:12])}"
                    + (" ..." if len(noms) > 12 else ""))]


def controler(machine) -> dict:
    """Les cinq endroits d'un coup. Rien n'est corrige, tout est dit."""
    constats = [preload_global(machine)]
    constats += preload_processus(machine)
    constats += preload_declare(machine)
    constats += chemins_de_bibliotheques(machine)
    constats += modules_noyau(machine)
    return {
        "constats": [str(c) for c in constats],
        "graves": [str(c) for c in constats if c.niveau == GRAVE],
        "a_verifier": [str(c) for c in constats if c.niveau == A_VERIFIER],
    }
