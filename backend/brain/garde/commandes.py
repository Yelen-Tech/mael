"""Classement de securite des commandes shell (garde-fou 1).

Trois niveaux, decides par des regles ecrites -- jamais par le modele :

  LECTURE      -- n'ecrit rien, ne change rien. S'execute sans demander.
  MODIFICATION -- change l'etat d'une machine. Exige une validation humaine.
  INTERDIT     -- destructeur, offensif, ou hors perimetre. Bloque, meme si
                  l'utilisateur dit oui.

Principe de prudence : dans le doute, on classe vers le HAUT (une commande
inconnue est traitee comme MODIFICATION, jamais comme LECTURE). Une IA qui se
trompe doit se tromper du cote sur.

Ce module ne fait AUCUN appel reseau et n'importe rien de lourd : il doit
rester instantanement testable, y compris sans Django.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from enum import Enum


class NIVEAU(str, Enum):
    LECTURE = "lecture"
    MODIFICATION = "modification"
    INTERDIT = "interdit"


@dataclass
class Verdict:
    niveau: NIVEAU
    binaire: str
    motif: str
    # Regles precises qui ont declenche ce niveau (pour le journal et l'UI).
    signaux: list[str] = field(default_factory=list)

    @property
    def auto(self) -> bool:
        """Peut s'executer sans demander ?"""
        return self.niveau is NIVEAU.LECTURE

    @property
    def bloque(self) -> bool:
        return self.niveau is NIVEAU.INTERDIT


# --------------------------------------------------------------------------- #
# Listes de reference. Volontairement explicites : on prefere une liste longue
# et relisible a une regex maligne que personne ne saura auditer.
# --------------------------------------------------------------------------- #

# Binaires purement consultatifs. Ne modifient jamais la machine.
LECTURE_SEULE = {
    # inspection systeme
    "ls", "cat", "less", "more", "head", "tail", "stat", "file", "wc",
    "find", "locate", "tree", "readlink", "realpath", "basename", "dirname",
    "pwd", "whoami", "id", "groups", "hostname", "uname", "uptime", "date",
    "df", "du", "free", "lsblk", "lscpu", "lsusb", "lspci", "mount",
    "ps", "top", "htop", "pstree", "lsof", "who", "w", "last",
    "env", "printenv", "echo", "which", "type", "history",
    # reseau (lecture)
    "ip", "ifconfig", "ss", "netstat", "route", "arp", "ping", "traceroute",
    "tracepath", "mtr", "dig", "nslookup", "host", "whois", "getent",
    "nc", "ncat", "curl", "wget", "openssl", "nmap",
    # inspection de services / journaux
    "systemctl", "service", "journalctl", "dmesg", "logread",
    # paquets (lecture)
    "dpkg", "rpm", "apt", "apt-get", "yum", "dnf", "pacman", "pip", "pip3",
    "npm", "snap",
    # utilisateurs / droits (lecture)
    "getfacl", "sudo", "namei",
    # web / securite (lecture)
    "grep", "egrep", "fgrep", "awk", "sed", "sort", "uniq", "cut", "tr",
    "diff", "cmp", "md5sum", "sha256sum", "sha1sum", "b2sum",
    "jq", "xmllint", "base64", "xxd", "hexdump", "strings",
    "gpg", "keytool",
    # conteneurs / cloud (lecture)
    "docker", "kubectl", "podman", "git",
    # durcissement Linux (ANSSI / CIS) : consultation
    "getenforce", "sestatus", "aa-status", "apparmor_status", "lsmod",
    "modinfo", "lastlog", "lastb", "findmnt", "apt-cache", "dpkg-query",
    "ausearch", "aureport", "loginctl", "lsattr", "timedatectl",
    "hostnamectl", "dpkg-divert",
    # builtin shell : lit une ligne sur l'entree standard (boucles while read)
    "read",
}

# Sous-commandes qui, pour un binaire par ailleurs consultatif, ECRIVENT.
# Ex : `systemctl status` lit, `systemctl restart` modifie.
SOUS_COMMANDES_MODIFIANTES = {
    "systemctl": {"start", "stop", "restart", "reload", "enable", "disable",
                  "mask", "unmask", "set-property", "kill", "isolate",
                  "daemon-reload", "edit"},
    "service": {"start", "stop", "restart", "reload", "force-reload"},
    "apt": {"install", "remove", "purge", "upgrade", "full-upgrade",
            "autoremove", "dist-upgrade"},
    "apt-get": {"install", "remove", "purge", "upgrade", "dist-upgrade",
                "autoremove"},
    "yum": {"install", "remove", "erase", "update", "upgrade", "downgrade"},
    "dnf": {"install", "remove", "erase", "update", "upgrade", "downgrade"},
    "pacman": {"-S", "-R", "-U", "-Syu"},
    "dpkg": {"-i", "--install", "-r", "--remove", "-P", "--purge"},
    # dpkg-divert --list consulte ; --add/--remove/--rename detournent un
    # fichier, c'est-a-dire modifient la machine (module 4, 20/09/2026)
    "dpkg-divert": {"--add", "--remove", "--rename"},
    "rpm": {"-i", "-U", "-e", "--install", "--upgrade", "--erase"},
    "pip": {"install", "uninstall"},
    "pip3": {"install", "uninstall"},
    "npm": {"install", "uninstall", "update", "i", "ci"},
    "snap": {"install", "remove", "refresh"},
    "docker": {"run", "rm", "rmi", "stop", "kill", "exec", "build", "push",
               "pull", "create", "start", "restart", "prune", "system"},
    "kubectl": {"apply", "delete", "create", "edit", "patch", "scale",
                "replace", "drain", "cordon", "rollout"},
    "git": {"push", "reset", "clean", "checkout", "rebase", "commit",
            "merge", "pull", "fetch"},
    # Un ip/ss en lecture, mais `ip ... add/del/set` modifie.
    "ip": {"add", "del", "set", "delete", "flush", "change", "replace"},
    "timedatectl": {"set-time", "set-timezone", "set-local-rtc", "set-ntp"},
    "hostnamectl": {"set-hostname", "hostname", "set-icon-name",
                    "set-chassis", "set-deployment", "set-location",
                    "icon-name", "chassis", "deployment", "location"},
}

# Binaires en lecture UNIQUEMENT pour une liste blanche de sous-commandes :
# toute autre sous-commande (connue ou non) modifie. Plus sur qu'une liste
# noire pour des outils de securite (pare-feu, anti-force-brute).
LECTURE_SI_SOUS_COMMANDE = {
    "ufw": {"status", "show", "version"},
    "nft": {"list"},
    "fail2ban-client": {"status", "get", "ping", "version", "banned",
                        "-h", "--help", "-V"},
    # `ssh -Q` interroge les algorithmes connus localement, sans connexion ;
    # toute autre invocation ouvre une connexion -> validation.
    "ssh": {"-Q"},
}

# Options qui font ECRIRE un binaire par ailleurs consultatif.
# Correspondance exacte ; pour une option longue (--x), le prefixe suffit
# (--vacuum-size=1G) ; `lettres` = options courtes groupees (-sSo contient o).
ECRITURE_PAR_OPTION = {
    "sed": {"exact": {"--in-place"}, "prefixe": ["-i", "--in-place"],
            "lettres": {"i"}},
    "find": {"exact": {"-delete", "-exec", "-execdir", "-ok", "-okdir",
                       "-fprint", "-fprint0", "-fprintf", "-fls"}},
    "curl": {"exact": {"--output", "--remote-name", "--remote-name-all",
                       "--upload-file", "--data", "--data-binary",
                       "--data-raw", "--data-urlencode", "--form",
                       "--output-dir", "--create-dirs"},
             "lettres": {"o", "O", "T", "d", "F"}},
    "openssl": {"exact": {"-out", "-keyout"}},
    "journalctl": {"prefixe": ["--vacuum-", "--rotate", "--flush", "--sync",
                               "--relinquish-var", "--setup-keys"]},
    "dmesg": {"exact": {"-C", "--clear", "-c", "--read-clear", "-n",
                        "--console-level", "-D", "-E"}},
    "date": {"exact": {"-s", "--set"}, "prefixe": ["--set"]},
}

# Binaires qui MODIFIENT sauf si une option de lecture est presente et
# qu'aucune option d'ecriture ne l'accompagne.
LECTURE_SAUF_ECRITURE = {
    "iptables": ({"-S", "-L", "--list", "--list-rules", "-nL", "-vnL",
                  "-nvL", "-Ln", "-Lnv"},
                 {"-A", "-I", "-D", "-R", "-F", "-X", "-N", "-P", "-Z", "-E",
                  "--append", "--insert", "--delete", "--replace", "--flush",
                  "--delete-chain", "--new-chain", "--policy", "--zero",
                  "--rename-chain"}),
    "firewall-cmd": ({"--list-all", "--list-all-zones", "--state",
                      "--get-active-zones", "--get-default-zone",
                      "--list-services", "--list-ports", "--list-rich-rules",
                      "--get-zones", "--query-service", "--query-port"},
                     {"--add-", "--remove-", "--set-", "--reload",
                      "--complete-reload", "--new-", "--delete-", "--change-",
                      "--runtime-to-permanent", "--lockdown-", "--panic-"}),
    "sysctl": ({"-a", "--all", "-n", "-e", "-N", "--values", "--names"},
               {"-w", "--write", "-p", "--load", "--system", "-f"}),
    "crontab": ({"-l"}, {"-e", "-r", "-i"}),
    "auditctl": ({"-l", "-s"}, {"-D", "-a", "-A", "-d", "-w", "-W", "-e",
                               "-b", "-f", "-r", "-R", "--reset-lost"}),
    "chage": ({"-l", "--list"}, {"-d", "-E", "-I", "-m", "-M", "-W",
                                 "--lastday", "--expiredate", "--inactive",
                                 "--mindays", "--maxdays", "--warndays"}),
    "passwd": ({"-S", "--status"}, {"-d", "-l", "-u", "-e", "-x", "-n",
                                    "-w", "-i", "--delete", "--lock",
                                    "--unlock", "--expire"}),
    "ssh-keygen": ({"-l", "-lf", "-lv", "-lvf", "-F", "-L", "-y"},
                   {"-R", "-t", "-b", "-N", "-p", "-c", "-s", "-A", "-i",
                    "-e"}),
}
LECTURE_SAUF_ECRITURE["ip6tables"] = LECTURE_SAUF_ECRITURE["iptables"]

# Mots-cles de shell. En tete de segment ils ne sont pas des binaires :
# `do echo x` -> on classe `echo x` ; `for p in a b` -> rien a executer.
_MOTS_SHELL = {"do", "then", "else", "elif", "done", "fi", "{", "}", "!",
               "if", "while", "until", "time"}
_ENTETES_SANS_COMMANDE = {"for", "case", "select", "esac", "in"}

# Binaires qui MODIFIENT toujours (pas de mode lecture pertinent ici).
MODIFICATION_TOUJOURS = {
    "cp", "mv", "mkdir", "rmdir", "touch", "ln", "install",
    "chmod", "chown", "chgrp", "setfacl", "umask",
    "useradd", "usermod", "userdel", "groupadd", "groupdel",
    "adduser", "deluser", "gpasswd",
    "ip6tables",
    "at", "modprobe", "insmod", "rmmod",
    "mkfs", "fdisk", "parted", "swapon", "swapoff", "fsck",
    "ln", "rsync", "scp", "sftp", "tee", "patch",
    "kill", "killall", "pkill", "renice", "nice",
    "certbot", "update-ca-certificates", "ssh-copy-id",
    "make", "cmake", "gcc", "cargo",
}

# Motifs formellement interdits. Bloques meme sur validation humaine.
# Chaque entree : (regex, motif lisible).
INTERDITS = [
    (r"\brm\s+(-[a-zA-Z]*\s+)*(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)",
     "rm -rf : suppression recursive forcee"),
    (r"\brm\b.*\s/(\s|$)", "rm ciblant la racine /"),
    (r":\s*\(\s*\)\s*\{.*\|.*&.*\}", "fork bomb"),
    (r"\bmkfs\b", "formatage de systeme de fichiers"),
    (r"\bdd\b.*\bof=/dev/(sd|nvme|hd|mapper)", "dd ecrit sur un disque brut"),
    (r">\s*/dev/(sd|nvme|hd)", "ecriture directe sur un disque"),
    (r"\bshred\b", "effacement securise (destructif)"),
    (r"\bwipefs\b", "effacement de signatures de FS"),
    (r"\b(shutdown|reboot|halt|poweroff|init\s+0|init\s+6)\b",
     "arret ou redemarrage de la machine"),
    (r"\bchmod\s+(-[a-zA-Z]*\s+)*(0*777|a\+rwx)\b.*\s/(\s|$)",
     "chmod 777 sur la racine"),
    (r"\bchown\b.*\s/(\s|$)", "chown sur la racine"),
    # Effacement / falsification de traces = sabotage d'audit.
    (r">\s*/var/log/", "troncature d'un journal systeme"),
    (r"\brm\b.*/var/log/", "suppression de journaux systeme"),
    (r"\b(history\s+-c|unset\s+HISTFILE|export\s+HISTFILE=/dev/null)\b",
     "effacement de l'historique shell"),
    (r"\bauditctl\s+-D\b", "desactivation de l'audit systeme"),
    # Exfiltration / porte derobee grossiere.
    (r"\bnc\b.*\s-e\b", "netcat avec -e : shell distant"),
    (r"\bncat\b.*--exec", "ncat --exec : shell distant"),
    (r"/dev/tcp/", "redirection reseau bash brute (canal cache)"),
    (r"\bcurl\b.*\|\s*(sudo\s+)?(ba)?sh\b", "curl | sh : execution de code non verifie"),
    (r"\bwget\b.*\|\s*(sudo\s+)?(ba)?sh\b", "wget | sh : execution de code non verifie"),
    # Cassage de mots de passe / attaque active = hors mandat d'audit defensif.
    (r"\b(hydra|medusa|john|hashcat|patator|crackmapexec|responder)\b",
     "outil d'attaque active de mots de passe"),
    (r"\bnmap\b.*\bscript=.*(exploit|brute|dos)\b",
     "scripts nmap offensifs (exploit/brute/dos)"),
    (r"\bmsfconsole\b|\bmetasploit\b", "framework d'exploitation"),
]

# Binaires en lecture SEULEMENT si un drapeau de test/vidage est present
# (ex. `sshd -T` lit la config effective ; `sshd` seul demarre le service).
LECTURE_SI_DRAPEAU = {
    "sshd": {"-t", "-T"},
    "nginx": {"-t", "-T"},
    "apachectl": {"-t", "-S"},
    "apache2ctl": {"-t", "-S", "configtest"},
    "named-checkconf": {""},   # toujours lecture
}

# Elevation de privileges : ne change pas le niveau a elle seule, mais on la
# signale toujours -- une commande de LECTURE precedee de sudo reste lecture,
# une MODIFICATION en sudo est un signal fort a afficher.
_PREFIXES = {"sudo", "doas", "time", "nice", "ionice", "nohup", "env",
             "command", "builtin", "exec", "watch", "xargs"}


def _binaire_reel(jetons: list[str]) -> tuple[str, list[str]]:
    """Saute les prefixes (sudo, env VAR=val, time...) pour trouver le vrai
    binaire et ses arguments."""
    i = 0
    while i < len(jetons):
        j = jetons[i]
        # env/export sous forme VAR=valeur
        if "=" in j and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", j):
            i += 1
            continue
        if j in _PREFIXES:
            i += 1
            # sudo -u user, nice -n 10 : sauter un eventuel drapeau + valeur
            while i < len(jetons) and jetons[i].startswith("-"):
                i += 2 if jetons[i] in {"-u", "-n", "-g"} else 1
            continue
        return j, jetons[i + 1:]
    return "", []


def _premiere_sous_commande(args: list[str]) -> str | None:
    """Premier argument non-drapeau : la sous-commande (install, restart...)."""
    for a in args:
        if a.startswith("-"):
            # Pour pacman/dpkg/rpm, le drapeau EST la sous-commande.
            return a
        return a
    return None


_CHERCHEURS = {"grep", "egrep", "fgrep", "zgrep", "rg"}
# Un programme awk qui peut EXECUTER (system(), getline depuis une commande,
# print vers une commande) reste juge tel quel : `awk 'BEGIN{system(
# "shutdown")}'` arrete la machine.
_AWK_EXECUTE = re.compile(r"system\s*\(|getline|\|\s*[\"']|[\"']\s*\||\|&")
_GUILLEMETS = re.compile(r"'[^']*'|\"[^\"]*\"")


def _sans_motifs_de_recherche(commande: str) -> str:
    """Les chaines entre guillemets qui ne sont que des MOTIFS lus par grep
    (ou un programme awk incapable d'executer) remplacees par ''."""
    # decoupage HORS guillemets : '/shutdown|halt/' est un seul motif
    morceaux, courant, quote = [], "", ""
    for ch in commande:
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch in ";|&":
            morceaux += [courant, ch]
            courant = ""
            continue
        courant += ch
    morceaux.append(courant)
    for k, seg in enumerate(morceaux):
        mots = seg.split()
        if not mots:
            continue
        binaire, _ = _binaire_reel(mots)
        binaire = binaire.rsplit("/", 1)[-1]
        if binaire in _CHERCHEURS:
            morceaux[k] = _GUILLEMETS.sub("''", seg)
        elif binaire in {"awk", "gawk", "mawk", "nawk"}:
            morceaux[k] = _GUILLEMETS.sub(
                lambda m: m.group(0) if _AWK_EXECUTE.search(m.group(0))
                else "''", seg)
    return "".join(morceaux)


def classer(commande: str) -> Verdict:
    """Classe une ligne de commande shell. Point d'entree unique.

    On analyse chaque segment separe par un operateur de shell (`;`, `&&`,
    `||`, `|`). Le verdict global prend le niveau le plus eleve rencontre :
    un pipeline est aussi dangereux que son maillon le plus dangereux.
    """
    commande = (commande or "").strip()
    if not commande:
        return Verdict(NIVEAU.LECTURE, "", "commande vide")

    # 1) Interdits : on teste la ligne entiere d'abord (les motifs destructeurs
    #    traversent souvent les operateurs de shell). Les MOTIFS DE RECHERCHE
    #    (grep 'shutdown', awk '/halt/') ne s'executent pas : on les retire
    #    avant ce test (faux positif signale par Kimi, 13/10/2026).
    bas = _sans_motifs_de_recherche(commande.lower())
    for motif, raison in INTERDITS:
        if re.search(motif, bas):
            return Verdict(NIVEAU.INTERDIT, "", raison, signaux=[motif])

    # 1 bis) Substitutions `$(...)`, `...`, <(...), >(...) : du code execute
    #    DANS la commande. Chacune est classee comme une commande a part
    #    entiere ; la ligne vaut le pire. Sans ca, `echo $(rm x)` passait
    #    pour une lecture.
    internes, exterieur = _extraire_substitutions(commande)
    if internes is None:
        return Verdict(NIVEAU.MODIFICATION, "", "substitution de commande "
                       "non analysable", signaux=["substitution"])
    if internes:
        pire_interne = Verdict(NIVEAU.LECTURE, "", "")
        for interne in internes:
            v = classer(interne)
            if _rang(v.niveau) > _rang(pire_interne.niveau):
                pire_interne = v
        v_ext = classer(exterieur)
        if _rang(pire_interne.niveau) > _rang(v_ext.niveau):
            pire_interne.motif = f"dans une substitution : {pire_interne.motif}"
            return pire_interne
        return v_ext

    # 2) Decoupage en segments executables -- en respectant les guillemets.
    #    Un `|` d'alternation grep (« (a|b) » entre quotes) n'est PAS un
    #    operateur de shell ; un decoupage naif par regex le casserait.
    try:
        lex = shlex.shlex(commande, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        jetons_tous = list(lex)
    except ValueError:
        # Guillemets non fermes, etc. : on ne prend aucun risque.
        return Verdict(NIVEAU.MODIFICATION, "", "commande non analysable",
                       signaux=["shlex"])

    operateurs = {";", "|", "||", "&&", "&"}
    segments: list[list[str]] = [[]]
    for t in jetons_tous:
        if t in operateurs:
            segments.append([])
        elif t in {"(", ")"}:
            continue           # groupement de shell : on ignore la parenthese
        else:
            segments[-1].append(t)

    pire = Verdict(NIVEAU.LECTURE, "", "aucun segment modifiant")
    for jetons in segments:
        while jetons and jetons[0] in _MOTS_SHELL:
            jetons = jetons[1:]
        if not jetons or jetons[0] in _ENTETES_SANS_COMMANDE:
            continue   # `for p in a b` : une liste de mots, rien n'est lance
        binaire, args = _binaire_reel(jetons)
        v = _classer_segment(binaire, args)
        if _rang(v.niveau) > _rang(pire.niveau):
            pire = v
    return pire


def _ecrit_un_fichier(args: list[str]) -> bool:
    """Vrai si un `>`/`>>` vise un vrai fichier. Une redirection vers /dev/null
    (ex. `2>/dev/null`) ne change rien : ce n'est pas une ecriture."""
    for i, a in enumerate(args):
        if a in {">", ">>"}:
            cible = args[i + 1] if i + 1 < len(args) else ""
            if cible not in {"/dev/null", "/dev/zero"}:
                return True
    return False


def _classer_segment(binaire: str, args: list[str]) -> Verdict:
    base = binaire.rsplit("/", 1)[-1]  # /usr/bin/systemctl -> systemctl

    if not base:
        return Verdict(NIVEAU.MODIFICATION, base, "binaire indetermine")

    # Redirection en ecriture vers un vrai fichier (pas /dev/null) ?
    ecrit_fichier = _ecrit_un_fichier(args)

    # Test/vidage de configuration : lecture (ex. sshd -T, nginx -t).
    if base in LECTURE_SI_DRAPEAU:
        drapeaux = LECTURE_SI_DRAPEAU[base]
        if "" in drapeaux or any(a in drapeaux for a in args):
            if not ecrit_fichier:
                return Verdict(NIVEAU.LECTURE, base,
                               f"{base} en test/vidage de configuration")

    ecriture = _ecriture_par_option(base, args)
    if ecriture:
        return Verdict(NIVEAU.MODIFICATION, base, ecriture,
                       signaux=["option-ecriture"])

    if base in LECTURE_SI_SOUS_COMMANDE:
        sc = _premiere_sous_commande(args)
        if sc in LECTURE_SI_SOUS_COMMANDE[base] and not ecrit_fichier:
            return Verdict(NIVEAU.LECTURE, base, f"{base} {sc} : consultation")
        return Verdict(NIVEAU.MODIFICATION, base,
                       f"{base} {sc or ''} : sous-commande non reconnue "
                       f"comme lecture".replace("  ", " "), signaux=[str(sc)])

    if base in LECTURE_SAUF_ECRITURE:
        lectures, ecritures = LECTURE_SAUF_ECRITURE[base]
        if _a_une_option(args, ecritures):
            return Verdict(NIVEAU.MODIFICATION, base,
                           f"{base} avec une option d'ecriture")
        if base == "sysctl":
            # sysctl net.ipv4.ip_forward lit ; sysctl cle=valeur ecrit.
            if any("=" in a for a in args if not a.startswith("-")):
                return Verdict(NIVEAU.MODIFICATION, base,
                               "sysctl cle=valeur modifie le noyau")
            if not ecrit_fichier and (args and (
                    _a_une_option(args, lectures)
                    or any(not a.startswith("-") for a in args))):
                return Verdict(NIVEAU.LECTURE, base, "sysctl en lecture")
        elif _a_une_option(args, lectures) and not ecrit_fichier:
            return Verdict(NIVEAU.LECTURE, base, f"{base} en consultation")
        return Verdict(NIVEAU.MODIFICATION, base,
                       f"{base} sans option de lecture : validation requise")

    if base in MODIFICATION_TOUJOURS:
        return Verdict(NIVEAU.MODIFICATION, base,
                       f"{base} modifie l'etat de la machine")

    if base in SOUS_COMMANDES_MODIFIANTES:
        sc = _premiere_sous_commande(args)
        if sc and sc in SOUS_COMMANDES_MODIFIANTES[base]:
            return Verdict(NIVEAU.MODIFICATION, base,
                           f"{base} {sc} modifie l'etat", signaux=[sc])
        # sous-commande de lecture (status, list, show...) -> lecture
        if ecrit_fichier:
            return Verdict(NIVEAU.MODIFICATION, base,
                           "redirection en ecriture (>)", signaux=[">"])
        return Verdict(NIVEAU.LECTURE, base, f"{base} en consultation")

    if base in LECTURE_SEULE:
        if ecrit_fichier:
            return Verdict(NIVEAU.MODIFICATION, base,
                           "redirection en ecriture (>)", signaux=[">"])
        return Verdict(NIVEAU.LECTURE, base, f"{base} : lecture seule")

    # Inconnu -> prudence : traite comme une modification a valider.
    return Verdict(NIVEAU.MODIFICATION, base,
                   f"binaire inconnu ({base}) : validation requise",
                   signaux=["inconnu"])


def _a_une_option(args: list[str], options: set[str]) -> bool:
    """Vrai si un argument correspond : exact, ou par prefixe pour les
    entrees terminees par '-' (--add-) ou les options longues (--x=val)."""
    for a in args:
        nom = a.split("=", 1)[0]
        for o in options:
            if nom == o or (o.endswith("-") and o.startswith("--")
                            and nom.startswith(o)):
                return True
    return False


def _find_exec_ecrit(args: list[str]) -> str | None:
    r"""`find -exec CMD ... ;` : c'est la CHARGE UTILE qui decide.

    `find /etc -type f -exec sha256sum {} +` lit la machine ; `find / -exec
    rm {} \;` la detruit. Refuser les deux, c'est interdire une empreinte
    de configuration ; accepter les deux, c'est ouvrir une porte. On classe
    donc la commande lancee, avec le meme garde-fou (Claude, 20/09/2026)."""
    for i, a in enumerate(args):
        if a not in {"-exec", "-execdir", "-ok", "-okdir"}:
            continue
        charge = []
        for b in args[i + 1:]:
            if b in {";", "\\;", "+"}:
                break
            charge.append(b)
        if not charge:
            return f"find {a} sans commande : forme inattendue"
        if any(c in {"-exec", "-execdir", "-ok", "-okdir"} for c in charge):
            return f"find {a} imbrique : jamais juge automatiquement"
        commande = " ".join(charge).replace("{}", "/chemin/trouve")
        v = classer(commande)
        if v.niveau is not NIVEAU.LECTURE:
            return (f"find {a} lance « {commande[:40]} » : "
                    f"{v.niveau.value}")
    return None


def _ecriture_par_option(base: str, args: list[str]) -> str | None:
    """Motif si une option fait ecrire un binaire consultatif, sinon None."""
    if base == "find":
        motif = _find_exec_ecrit(args)
        if motif:
            return motif
        # -exec dont la charge utile LIT : ce n'est pas une ecriture, les
        # autres options de find (-delete, -fprint...) restent jugees.
        args = [a for a in args
                if a not in {"-exec", "-execdir", "-ok", "-okdir"}]
    regles = ECRITURE_PAR_OPTION.get(base)
    if regles:
        for a in args:
            nom = a.split("=", 1)[0]
            if nom in regles.get("exact", set()):
                return f"{base} {nom} ecrit sur la machine"
            if any(a.startswith(p) for p in regles.get("prefixe", [])):
                return f"{base} {a} ecrit sur la machine"
            lettres = regles.get("lettres")
            if lettres and re.fullmatch(r"-[A-Za-z]+", a) and set(a[1:]) & lettres:
                return f"{base} {a} ecrit sur la machine"
    if base == "wget":
        # wget ecrit un fichier par defaut ; lecture seulement vers la sortie
        # standard (-O -, -qO-) ou en simple verification (--spider).
        vers_sortie = any(
            a in {"--spider", "-O-", "-qO-", "--output-document=-"}
            or (a in {"-O", "-qO", "--output-document"}
                and i + 1 < len(args) and args[i + 1] == "-")
            for i, a in enumerate(args))
        if not vers_sortie:
            return "wget telecharge un fichier sur la machine"
    if base in {"awk", "gawk", "mawk", "nawk"}:
        programme = " ".join(a for a in args if not a.startswith("-"))
        if re.search(r"\bsystem\s*\(|\|\s*\"|>\s*\"|\|&", programme):
            return f"{base} lance une commande ou ecrit un fichier"
    if base in {"mount", "hostname"}:
        if any(not a.startswith("-") for a in args):
            return f"{base} avec argument modifie la machine"
    return None


def _extraire_substitutions(commande: str) -> tuple[list[str] | None, str]:
    """Isole le contenu des $(...), <(...), >(...) et `...` (hors apostrophes,
    ou le shell ne les evalue pas). Rend (contenus, ligne ou chaque
    substitution est remplacee par un mot neutre). None si mal fermee."""
    internes: list[str] = []
    sortie: list[str] = []
    i, n = 0, len(commande)
    dans_apostrophe = False
    while i < n:
        c = commande[i]
        if c == "'" and not dans_apostrophe:
            fin = commande.find("'", i + 1)
            if fin == -1:
                return None, commande
            sortie.append(commande[i:fin + 1])
            i = fin + 1
            continue
        if c == "\\" and i + 1 < n:
            sortie.append(commande[i:i + 2])
            i += 2
            continue
        if c in "$<>" and i + 1 < n and commande[i + 1] == "(":
            if c == "$" and i + 2 < n and commande[i + 2] == "(":
                # $(( calcul arithmetique )) : pas une commande
                fin = commande.find("))", i + 3)
                if fin == -1:
                    return None, commande
                sortie.append("0")
                i = fin + 2
                continue
            profondeur, j = 1, i + 2
            while j < n and profondeur:
                if commande[j] == "(":
                    profondeur += 1
                elif commande[j] == ")":
                    profondeur -= 1
                j += 1
            if profondeur:
                return None, commande
            internes.append(commande[i + 2:j - 1])
            sortie.append("SUBST")
            i = j
            continue
        if c == "`":
            fin = commande.find("`", i + 1)
            if fin == -1:
                return None, commande
            internes.append(commande[i + 1:fin])
            sortie.append("SUBST")
            i = fin + 1
            continue
        sortie.append(c)
        i += 1
    return internes, "".join(sortie)


def _rang(n: NIVEAU) -> int:
    return {NIVEAU.LECTURE: 0, NIVEAU.MODIFICATION: 1, NIVEAU.INTERDIT: 2}[n]
