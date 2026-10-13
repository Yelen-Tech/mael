"""Module 7 du noyau d'integrite : isolation seccomp-BPF et namespaces.

Deux questions, et la premiere concerne MAEL lui-meme.

**1. Ce que MAEL lance chez le client est-il enferme ?** MAEL execute des
outils (nuclei, trivy, clamav...) dans des conteneurs, chez des gens qui
nous font confiance. Un outil mal enferme, c'est notre produit qui devient
le probleme. `exigences_conteneur()` relit la ligne `docker run` avant tout
lancement et refuse ce qui manque : seccomp jamais desactive, toutes les
capacites abandonnees, pas de nouveaux privileges, systeme de fichiers en
lecture seule, memoire et processus bornes, et AUCUN espace de noms de
l'hote partage (pid, reseau, ipc, uts, utilisateur) ni socket Docker monte.

**2. Les processus de la machine auditee sont-ils filtres ?** `mesurer()`
lit `Seccomp:` dans /proc/<pid>/status (0 = aucun filtre, 1 = strict,
2 = filtre BPF) et compare les espaces de noms de chaque processus a ceux
du processus 1 : un processus qui n'a ni filtre d'appels systeme ni espace
de noms propre s'execute sans aucune barriere.

Ce que ce module NE prouve PAS : un filtre seccomp existe, il ne dit pas
qu'il est bon (un filtre qui autorise tout compte comme un filtre). Et
l'isolation d'un conteneur repose sur un noyau sain : le module 6 est a
cote pour cela.

Le code juge ; le modele ne voit que le resultat.
"""
from __future__ import annotations

from brain.garde import NIVEAU, classer

# Espaces de noms de l'hote : les partager, c'est ouvrir la porte.
PARTAGES_INTERDITS = ("host",)
OPTIONS_ESPACES = ("--pid", "--network", "--net", "--ipc", "--uts",
                   "--userns", "--cgroupns")

# Ce qu'un conteneur lance par MAEL doit TOUJOURS avoir.
EXIGENCES = (
    ("seccomp", "le filtre d'appels systeme ne doit jamais etre desactive"),
    ("capacites", "toutes les capacites doivent etre abandonnees "
                  "(--cap-drop ALL)"),
    ("privileges", "aucun nouveau privilege (--security-opt "
                   "no-new-privileges)"),
    ("lecture seule", "le systeme de fichiers doit etre en lecture seule "
                      "(--read-only)"),
    ("memoire", "la memoire doit etre bornee (--memory)"),
    ("processus", "le nombre de processus doit etre borne (--pids-limit)"),
    ("espaces de noms", "aucun espace de noms de l'hote partage"),
    ("socket docker", "le socket Docker ne doit jamais etre monte"),
    ("privilegie", "--privileged est interdit"),
)


def exigences_conteneur(argv: list[str]) -> list[str]:
    """Ce qui manque a cette ligne `docker run` ; liste vide = conforme."""
    texte = " ".join(argv)
    manques = []

    if "seccomp=unconfined" in texte:
        manques.append("seccomp : filtre desactive (seccomp=unconfined)")
    if "--privileged" in argv:
        manques.append("privilegie : --privileged est interdit")
    if not _option_valeur(argv, "--cap-drop", "ALL"):
        manques.append("capacites : --cap-drop ALL absent")
    if "no-new-privileges" not in texte:
        manques.append("privileges : --security-opt no-new-privileges absent")
    if "--read-only" not in argv:
        manques.append("lecture seule : --read-only absent")
    if not _option_presente(argv, "--memory"):
        manques.append("memoire : --memory absent")
    if not _option_presente(argv, "--pids-limit"):
        manques.append("processus : --pids-limit absent")
    for option in OPTIONS_ESPACES:
        valeur = _valeur_de(argv, option)
        if valeur in PARTAGES_INTERDITS:
            manques.append(f"espaces de noms : {option}={valeur} partage "
                           "l'espace de l'hote")
    if "docker.sock" in texte:
        manques.append("socket docker : monter /var/run/docker.sock donne "
                       "la machine entiere")
    return manques


def _valeur_de(argv: list[str], option: str) -> str | None:
    """Valeur d'une option, en « --x v » comme en « --x=v ».

    La DERNIERE occurrence gagne, comme chez Docker : sans cela, un
    « --network none » en tete couvrirait un « --network=host » ajoute
    ensuite (trouve par le test, 20/09/2026)."""
    valeur = None
    for i, a in enumerate(argv):
        if a == option and i + 1 < len(argv):
            valeur = argv[i + 1]
        elif a.startswith(option + "="):
            valeur = a.split("=", 1)[1]
    return valeur


def _option_presente(argv: list[str], option: str) -> bool:
    return _valeur_de(argv, option) is not None


def _option_valeur(argv: list[str], option: str, attendu: str) -> bool:
    valeur = _valeur_de(argv, option)
    return valeur is not None and valeur.upper() == attendu.upper()


# --------------------------------------------------------------------------- #
# Mesure sur la machine auditee
# --------------------------------------------------------------------------- #
SECCOMP = {"0": "aucun filtre", "1": "mode strict", "2": "filtre BPF"}


def _lire(machine, commande: str) -> str:
    v = classer(commande)
    if v.niveau is not NIVEAU.LECTURE:
        raise ValueError(f"commande non LECTURE ({v.motif}) : {commande}")
    r = machine.executer(["bash", "-c", commande], racine=True)
    return r.stdout or ""


def mesurer(machine, limite: int = 12) -> dict:
    """Etat du filtrage des appels systeme et des espaces de noms."""
    sortie = _lire(machine,
                   "grep -H '^Seccomp:' /proc/[0-9]*/status 2>/dev/null")
    comptes, sans_filtre = {}, []
    for ligne in sortie.splitlines():
        # « /proc/412/status:Seccomp:	2 » : couper sur l'etiquette, pas sur
        # le premier deux-points (le chemin en contient un).
        chemin, separateur, valeur = ligne.partition(":Seccomp:")
        if not separateur:
            continue
        mode = valeur.strip()
        comptes[mode] = comptes.get(mode, 0) + 1
        if mode == "0":
            pid = chemin.split("/")[2] if chemin.startswith("/proc/") else "?"
            sans_filtre.append(pid)

    noms = []
    for pid in sans_filtre[:limite]:
        nom = _lire(machine, f"cat /proc/{pid}/comm 2>/dev/null").strip()
        noms.append(f"{pid} ({nom or 'inconnu'})")

    espaces = _lire(machine, "ls -l /proc/1/ns 2>/dev/null | awk '{print $9,"
                             " $11}'")
    return {
        "repartition": {SECCOMP.get(m, f"mode {m}"): n
                        for m, n in sorted(comptes.items())},
        "sans_filtre": noms,
        "sans_filtre_total": len(sans_filtre),
        "espaces_de_noms_pid1": [l.strip() for l in espaces.splitlines()
                                 if l.strip()],
    }
