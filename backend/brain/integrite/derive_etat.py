"""Module 8 du noyau d'integrite : controle de derive d'etat.

Une machine durcie le jour de la livraison ne le reste pas : un paquet
s'ajoute, un port s'ouvre, un compte apparait, un binaire prend le bit
SUID. Ce module prend un ETAT date -- une photographie de ce qui compte --
et compare deux photographies pour dire ce qui a bouge, et si c'est grave.

Ce qui entre dans la photographie (neuf rubriques, toutes en LECTURE) :

    paquets     nom et version de chaque paquet installe
    fichiers    empreinte sha256 de chaque fichier de /etc
    comptes     /etc/passwd reduit a l'essentiel (nom, uid, gid, shell)
    groupes     /etc/group
    ecoute      sockets en ecoute (protocole, adresse, port, programme)
    suid        fichiers SUID/SGID de la partition racine
    services    unites systemd activees
    taches      taches planifiees (cron, /etc/cron*)
    noyau       version, modules charges, /etc/ld.so.preload

La gravite n'est pas la meme partout, et c'est tout l'interet :
un compte d'UID 0 qui apparait, un binaire SUID de plus ou un preload
global qui change sont GRAVES ; un port qui s'ouvre, un paquet, un service
ou une tache planifiee sont A VERIFIER ; les fichiers de /etc changent tout
le temps (y compris par MAEL lui-meme) et sont simplement comptes.

Ce que ce module NE prouve PAS : il compare ce qu'on lui a demande de
regarder. Une porte derobee qui ne touche ni aux paquets, ni aux comptes,
ni aux ports, ni a /etc lui echappe -- d'ou les modules 4 et 6 a cote.

Le code juge ; le modele ne voit que le resultat.
"""
from __future__ import annotations

from datetime import datetime, timezone

from brain.garde import NIVEAU, classer

# Un balayage de la partition racine n'a pas le meme temps qu'un cat.
DELAI_BALAYAGE = 900

RUBRIQUES = {
    "paquets": ("dpkg-query -W -f='${Package} ${Version}\\n' 2>/dev/null"
                " || rpm -qa 2>/dev/null", None),
    "fichiers": ("find /etc -xdev -type f -exec sha256sum {} + 2>/dev/null"
                 " | sort -k2", DELAI_BALAYAGE),
    "comptes": ("cut -d: -f1,3,4,7 /etc/passwd 2>/dev/null | sort", None),
    "groupes": ("cut -d: -f1,3 /etc/group 2>/dev/null | sort", None),
    "ecoute": ("ss -lntupH 2>/dev/null | awk '{print $1, $5, $7}' | sort",
               None),
    "suid": ("find / -xdev \\( -perm -4000 -o -perm -2000 \\) -type f "
             "-print 2>/dev/null | sort", DELAI_BALAYAGE),
    "services": ("systemctl list-unit-files --state=enabled --no-legend "
                 "--no-pager 2>/dev/null | awk '{print $1}' | sort", None),
    "taches": ("cat /etc/crontab /etc/cron.d/* 2>/dev/null | "
               "grep -vE '^[[:space:]]*(#|$)' | sort", None),
    "noyau": ("uname -sr 2>/dev/null; lsmod 2>/dev/null | awk 'NR>1"
              " {print $1}' | sort; cat /etc/ld.so.preload 2>/dev/null",
              None),
}

# Rubriques ou une APPARITION est grave par elle-meme.
GRAVE_A_L_APPARITION = {"suid"}

# Rubriques dont chaque ligne est « empreinte<espaces>chemin » : on compare
# par CHEMIN, sinon un fichier modifie apparait deux fois (une disparition
# et une apparition) et personne ne lit ca (essai reel du 20/09/2026).
RUBRIQUES_PAR_CHEMIN = {"fichiers"}

GRAVE, A_VERIFIER, INFORMATION = "grave", "a verifier", "information"

_GRAVITE = {
    "suid": GRAVE,
    "comptes": A_VERIFIER,       # releve a GRAVE si l'UID est 0
    "groupes": A_VERIFIER,
    "ecoute": A_VERIFIER,
    "paquets": A_VERIFIER,
    "services": A_VERIFIER,
    "taches": A_VERIFIER,
    "noyau": A_VERIFIER,         # releve a GRAVE si ld.so.preload bouge
    "fichiers": INFORMATION,
}


def _lire(machine, commande: str, delai: int | None = None) -> str:
    """Une lecture sur la machine, garde-fou d'abord."""
    v = classer(commande)
    if v.niveau is not NIVEAU.LECTURE:
        raise ValueError(f"commande non LECTURE ({v.motif}) : {commande}")
    r = machine.executer(["bash", "-c", commande], racine=True, delai=delai)
    return r.stdout or ""


def photographier(machine, systeme: str = "") -> dict:
    """L'etat date de la machine : une photographie, pas un jugement."""
    etat = {"date": datetime.now(timezone.utc).isoformat(),
            "systeme": systeme, "rubriques": {}}
    for nom, (commande, delai) in RUBRIQUES.items():
        lignes = [l.rstrip() for l in _lire(machine, commande, delai)
                  .splitlines() if l.strip()]
        etat["rubriques"][nom] = lignes
    return etat


def _gravite(rubrique: str, ligne: str, apparu: bool) -> str:
    """La gravite depend de CE QUI bouge, pas seulement de la rubrique."""
    if rubrique == "comptes" and apparu:
        champs = ligne.split(":")
        if len(champs) > 1 and champs[1].strip() == "0":
            return GRAVE                      # un second root
    if rubrique == "noyau" and "ld.so.preload" not in ligne:
        if ligne.startswith("/"):             # contenu du preload
            return GRAVE
    if rubrique in GRAVE_A_L_APPARITION:
        # un SUID qui DISPARAIT est un durcissement, pas une alerte : la
        # gravite tient au sens du mouvement, pas a la rubrique seule
        return GRAVE if apparu else A_VERIFIER
    return _GRAVITE.get(rubrique, A_VERIFIER)


def _par_chemin(lignes: list[str]) -> dict[str, str]:
    """« empreinte  /chemin » -> {chemin: empreinte}."""
    table = {}
    for ligne in lignes:
        parties = ligne.split(None, 1)
        if len(parties) == 2:
            table[parties[1].strip()] = parties[0]
    return table


def comparer(avant: dict, apres: dict, detail_max: int = 20) -> dict:
    """Ce qui a bouge entre deux photographies, range par gravite."""
    mouvements = []
    for rubrique in RUBRIQUES:
        if rubrique in RUBRIQUES_PAR_CHEMIN:
            ancien = _par_chemin(avant["rubriques"].get(rubrique, []))
            nouveau = _par_chemin(apres["rubriques"].get(rubrique, []))
            modifies = sorted(c for c in set(ancien) & set(nouveau)
                              if ancien[c] != nouveau[c])
            for sens, chemins in (("apparu", sorted(set(nouveau) - set(ancien))),
                                  ("disparu", sorted(set(ancien) - set(nouveau))),
                                  ("modifie", modifies)):
                for chemin in chemins[:detail_max]:
                    mouvements.append({"rubrique": rubrique, "sens": sens,
                                       "ligne": chemin,
                                       "gravite": _GRAVITE[rubrique]})
                if len(chemins) > detail_max:
                    mouvements.append({
                        "rubrique": rubrique, "sens": "reste",
                        "ligne": f"{len(chemins) - detail_max} autre(s) "
                                 f"fichier(s) {sens}(s)",
                        "gravite": INFORMATION})
            continue
        anciennes = set(avant["rubriques"].get(rubrique, []))
        nouvelles = set(apres["rubriques"].get(rubrique, []))
        apparus = sorted(nouvelles - anciennes)
        disparus = sorted(anciennes - nouvelles)
        for ligne in apparus[:detail_max]:
            mouvements.append({"rubrique": rubrique, "sens": "apparu",
                               "ligne": ligne,
                               "gravite": _gravite(rubrique, ligne, True)})
        for ligne in disparus[:detail_max]:
            mouvements.append({"rubrique": rubrique, "sens": "disparu",
                               "ligne": ligne,
                               "gravite": _gravite(rubrique, ligne, False)})
        reste = max(0, len(apparus) - detail_max) + max(
            0, len(disparus) - detail_max)
        if reste:
            mouvements.append({"rubrique": rubrique, "sens": "reste",
                               "ligne": f"{reste} autre(s) mouvement(s) non "
                                        "detaille(s)",
                               "gravite": INFORMATION})
    return {
        "avant": avant.get("date"), "apres": apres.get("date"),
        "mouvements": mouvements,
        "graves": [m for m in mouvements if m["gravite"] == GRAVE],
        "a_verifier": [m for m in mouvements if m["gravite"] == A_VERIFIER],
        "stable": not mouvements,
    }


def resumer(comparaison: dict) -> list[str]:
    """Une ligne par mouvement, lisible par un humain presse."""
    if comparaison["stable"]:
        return ["etat identique : aucune derive"]
    marque = {GRAVE: "GRAVE", A_VERIFIER: "a verifier",
              INFORMATION: "information"}
    fleche = {"apparu": "+", "disparu": "-", "modifie": "~", "reste": "…"}
    return [f"[{marque[m['gravite']]}] {m['rubrique']} "
            f"{fleche[m['sens']]} {m['ligne']}"
            for m in comparaison["mouvements"]]
