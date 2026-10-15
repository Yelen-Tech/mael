"""Aller-retour complet des playbooks sur machine jetable (point 4, partie D).

Pour chaque playbook, sur un conteneur NEUF :

  empreinte /etc + paquets avant
    -> detecter
    -> appliquer --simulation   (aucun fichier ne doit changer)
    -> appliquer                (la correction reelle)
    -> verifier                 (code 0 = conforme)
    -> re-mesure par la fiche liee (conforme attendu)
    -> revenir                  (retour arriere)
    -> empreintes identiques a l'avant (etat d'origine retrouve)

Garde-fous : le sceau est controle AVANT toute copie des scripts dans le
conteneur ; les arguments viennent de brain.playbooks.arguments() (lui seul
sait quels parametres detecter/revenir recoivent).

    python -m banc.playbooks --image ubuntu2204 [--playbook infra.sysctl]

Les parametres de test sont ceux de la premiere fiche liee au playbook
(champ `parametres` des controles). Un playbook sans fiche liee est signale
« sans parametres de test », pas invente.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from brain import bibliotheque as bib
from brain import playbooks as pb
from brain.bibliotheque import ecarts
from brain.contexte import commande_pour, depuis_declaration
from brain.garde import NIVEAU, classer

from .executeurs import Executeur, ExecuteurDocker, ExecuteurWSL
from .fiches import IMAGES, en_vm

# Snapshot de l'etat a restaurer : /etc (config) + liste des paquets.
# /var/lib/dpkg/status n'est PAS compare (fichier reecrit meme sans
# changement de fond) ; la liste des paquets suffit a prouver le retour.
# Ce qu'un conteneur du banc ne peut pas offrir, reconnu a la sortie REELLE
# du script (jamais a une liste de playbooks ecrite d'avance) : premier
# passage reel des 18 playbooks, 20/09/2026.
HORS_CADRE = (
    ("Unable to locate package", "le banc coupe le reseau : apt ne peut "
     "rien installer (a rejouer sur une machine reliee)"),
    # meme cause, autres mots : Debian 12 repond « has no installation
    # candidate » la ou Ubuntu dit « Unable to locate package »
    ("has no installation candidate", "le banc coupe le reseau : apt n'a "
     "aucun index de paquets (a rejouer sur une machine reliee)"),
    ("Temporary failure resolving", "le banc coupe le reseau : resolution "
     "de noms impossible"),
    ("You must be root to run this program", "sous-systeme d'audit du "
     "noyau : absent d'un conteneur (a tester en VM)"),
    ("Read-only file system", "systeme de fichiers du noyau en lecture "
     "seule dans un conteneur (a tester en VM)"),
)

_COMMANDE_SNAPSHOT = ("find /etc -type f -exec sha256sum {} + 2>/dev/null"
                      " | sort; echo ---; dpkg-query -W 2>/dev/null | sort")


def _snapshot(executeur: Executeur) -> str:
    r = executeur.executer(["bash", "-c", _COMMANDE_SNAPSHOT], racine=True)
    return hashlib.sha256(r.stdout.encode("utf-8")).hexdigest()


def _systemd_refuse(executeur: Executeur, parametres: dict) -> str:
    """systemd refuse-t-il de demarrer cette unite sur CETTE machine ?

    Un service peut etre « enabled » et rester « inactive » parce que le
    noyau ne fournit pas ce qu'il exige : AppArmor compile mais desactive,
    audit absent, securite non chargee. systemd le dit lui-meme
    (ConditionResult=no) et nomme la condition dans son journal.

    Ce n'est pas un playbook faux : c'est une machine qui ne peut pas. Et on
    le CONSTATE en interrogeant systemd, jamais en lisant une liste ecrite
    d'avance (regle posee le 20/09/2026)."""
    service = str(parametres.get("service") or parametres.get("unite") or "")
    service = service.strip()
    if not service:
        return ""
    unite = service if "." in service else f"{service}.service"
    r = executeur.executer(["systemctl", "show", unite, "-p",
                            "ConditionResult", "-p", "LoadState"])
    if "ConditionResult=no" not in (r.stdout or ""):
        return ""
    detail = executeur.executer(
        ["bash", "-c", f"systemctl status {unite} --no-pager 2>&1 "
                       f"| grep -iE 'condition' | head -2"])
    precision = " ".join((detail.stdout or "").split())[:180]
    return ("systemd refuse de demarrer cette unite sur cette machine "
            "(ConditionResult=no)"
            + (f" : {precision}" if precision else ""))


def _fiches_liees(pid: str, avec_parametres: bool = True):
    """(fiche, controle) qui reference ce playbook.

    avec_parametres=False : tous les liens, meme ceux dont le controle ne
    porte pas de parametres -- de quoi distinguer « personne ne cite ce
    playbook » (trou de couverture) de « les parametres viennent du client »
    (un domaine, un certificat : rien a inventer ici)."""
    for f in bib.toutes():
        for c in f.controles:
            if c.playbook == pid and (c.parametres or not avec_parametres):
                yield f, c


def _objets_presents(executeur: Executeur, parametres: dict) -> bool:
    """Les chemins passes en parametre existent-ils sur cette image ?

    Sans cela, le banc « teste » un playbook sur /etc/ipsec.d/ absent de
    l'image : la re-mesure rend « sans objet » et on croit a un echec
    (premier passage reel, 20/09/2026)."""
    for valeur in parametres.values():
        if isinstance(valeur, str) and valeur.startswith("/"):
            chemin = valeur.rstrip("/") or "/"
            if executeur.executer(["test", "-e", chemin],
                                  racine=True).code != 0:
                return False
    return True


def aller_retour(executeur: Executeur, pid: str, systeme: str,
                 vraie_machine: bool = False) -> dict:
    """L'aller-retour complet d'un playbook. Ne leve rien : tout echec est
    consigne dans le resultat (etapes + ecarts).

    vraie_machine=True : le banc tourne sur une VM (noyau et systemd
    reels), donc les playbooks du noyau sont juges comme les autres."""
    resultat = {"playbook": pid, "etapes": [], "ecarts": [], "ok": False,
                "vm": None, "cadre": None}

    def etape(nom, code=0, note=""):
        resultat["etapes"].append({"etape": nom, "code": code, "note": note})

    # 0) sceau avant toute copie
    alteres = pb.controler_sceau(pid)
    if alteres:
        resultat["ecarts"].append(f"sceau rompu : {', '.join(alteres)}")
        return resultat

    liees = [(f, c) for f, c in _fiches_liees(pid)
             if f.etat != "obsolete"]
    if not liees:
        cites = list(_fiches_liees(pid, avec_parametres=False))
        if cites:
            resultat["cadre"] = (
                f"{len(cites)} fiche(s) citent ce playbook mais sans "
                "parametres : ils viennent du client (domaine, certificat), "
                "rien a inventer ici")
        else:
            resultat["cadre"] = ("AUCUNE fiche ne cite ce playbook : trou de "
                                 "couverture a combler, pas un defaut du "
                                 "playbook")
        return resultat

    # Parmi les fiches liees, la premiere dont l'objet existe sur cette
    # image ; sinon le banc mesurerait un fichier absent.
    choix = [(f, c) for f, c in liees
             if _objets_presents(executeur, c.parametres)]
    if not choix:
        absents = ", ".join(sorted({str(v) for _, c in liees
                                    for v in c.parametres.values()
                                    if isinstance(v, str)
                                    and v.startswith("/")}))[:120]
        resultat["cadre"] = f"objet de test absent de l'image : {absents}"
        return resultat
    fiche, controle = choix[0]
    parametres = dict(controle.parametres)
    ctx = depuis_declaration(systeme)

    # Meme regle qu'au banc des fiches : ce qu'un conteneur ne reproduit
    # pas (noyau, systemd) ne se juge pas ici. /proc/sys est en lecture
    # seule dans un conteneur : un playbook sysctl y « echoue » sans etre
    # faux. Constate au premier passage reel (20/09/2026).
    raison_vm = None if vraie_machine else en_vm(fiche)
    if raison_vm:
        resultat["vm"] = f"{raison_vm} (fiche liee {fiche.id})"
        return resultat

    # Copie des scripts scelles + bibliotheque commune. L'arborescence du
    # depot est REPRODUITE telle quelle (playbooks/<famille>/<nom>/) : les
    # scripts font « source $(dirname $0)/../../_commun/mael.sh », donc un
    # dossier a plat ne trouve rien (premier passage reel, 20/09/2026).
    chemin = pb.obtenir(pid).dossier.relative_to(pb.RACINE).as_posix()
    executeur.copier(pb.COMMUN, "/mael/_commun/mael.sh")
    executeur.copier(pb.obtenir(pid).dossier, f"/mael/{chemin}")

    avant = _snapshot(executeur)

    def lancer(nom_etape, simulation=False):
        args = pb.arguments(pid, nom_etape, parametres, simulation=simulation)
        cmd = ["bash", f"/mael/{chemin}/{nom_etape}.sh", *args]
        r = executeur.executer(cmd, racine=True)
        etape(nom_etape + (" --simulation" if simulation else ""), r.code,
              r.stderr.strip()[:120])
        return r

    # 1) detecter (constate, ne modifie rien)
    lancer("detecter")
    if _snapshot(executeur) != avant:
        resultat["ecarts"].append("detecter a modifie l'etat")

    # 2) simulation : aucun fichier ne doit changer
    r = lancer("appliquer", simulation=True)
    if _snapshot(executeur) != avant:
        resultat["ecarts"].append("appliquer --simulation a modifie l'etat")
    # Code 5 = REFUS documente (« le prealable n'est pas la ») : le playbook
    # a bien fait son travail en s'abstenant, il n'y a rien a prouver de
    # plus ici. Exemple : montage-option sur un conteneur, ou /boot n'est
    # pas une partition declaree dans /etc/fstab.
    if r.code == 5:
        resultat["cadre"] = ("le playbook a refuse d'agir (prealable absent "
                             f"de cette machine) : {resultat['etapes'][-1]['note']}")
        return resultat

    # 3) application reelle
    if r.code == 0:
        r = lancer("appliquer")
        sortie_erreur = (r.stderr or "") + (r.stdout or "")
        for marque, raison in HORS_CADRE:
            if r.code != 0 and marque in sortie_erreur:
                resultat["cadre"] = raison
                lancer("revenir")          # on laisse la machine propre
                return resultat

    # 4) verification
    if r.code == 0:
        r = lancer("verifier")
        if r.code != 0:
            raison = _systemd_refuse(executeur, parametres)
            if raison:
                resultat["cadre"] = raison
                lancer("revenir")          # on laisse la machine propre
                return resultat
            resultat["ecarts"].append("verifier != 0 apres application")

    # 5) re-mesure par la fiche liee (le code juge, conforme attendu)
    # Meme regle qu'au banc des fiches (Yelen Tech, 20/09/2026) : la variante de
    # commande du systeme (commande_pour) et le marqueur IMPOSSIBLE quand la
    # commande n'a pas pu s'executer -- une sortie vide n'est pas un ecart.
    sorties = {}
    for i, obs in enumerate(fiche.observer):
        cmd = commande_pour(obs, ctx)
        if classer(cmd).niveau is NIVEAU.LECTURE:
            r_obs = executeur.executer(["bash", "-c", cmd], racine=True)
            sorties[i] = ecarts.sortie_a_juger(r_obs.code, r_obs.stdout)
    verdicts = {v.controle: v for v in ecarts.evaluer_fiche(fiche, sorties)}
    v = verdicts.get(controle.controle)
    if v is None:
        resultat["ecarts"].append("re-mesure impossible (controle sans "
                                  "verdict)")
    else:
        etape("re-mesure", 0 if v.statut.value == "conforme" else 1,
              v.statut.value)
        # Un INDETERMINE n'accuse personne : la machine n'a pas de quoi
        # repondre (aucun fichier au motif, pas de montage separe...). La
        # chaine n'est pas prouvee ici, elle n'est pas fausse pour autant
        # -- meme regle que partout ailleurs dans MAEL.
        if v.statut.value == "indetermine":
            resultat["cadre"] = ("re-mesure sans objet sur cette machine : "
                                 f"{v.constate}")
            lancer("revenir")
            return resultat
        if v.statut.value != "conforme":
            resultat["ecarts"].append(f"re-mesure : {v.statut.value} "
                                      f"({v.constate})")

    # 6) retour arriere, puis etat d'origine retrouve a l'identique
    r = lancer("revenir")
    if r.code != 0:
        resultat["ecarts"].append(f"revenir a echoue (code {r.code})")
    if _snapshot(executeur) != avant:
        resultat["ecarts"].append("etat d'origine non restaure apres revenir")

    resultat["ok"] = not resultat["ecarts"]
    return resultat


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="banc.playbooks")
    ap.add_argument("--image", choices=sorted(IMAGES),
                    help="image Docker du banc (conteneur jetable)")
    ap.add_argument("--vm", metavar="DISTRIBUTION",
                    help="juger sur une VRAIE machine WSL (ex. --vm Ubuntu) "
                         "au lieu d'un conteneur : noyau et systemd reels, "
                         "donc les 5 playbooks mis de cote deviennent "
                         "jugeables. Implique --vraie-machine, et MODIFIE "
                         "reellement la distribution (le banc annule et "
                         "verifie que l'etat d'origine est retrouve).")
    ap.add_argument("--playbook")
    ap.add_argument("--rapport", type=Path)
    ap.add_argument("--vraie-machine", action="store_true",
                    help="le banc tourne sur une VM : juger aussi les "
                         "playbooks du noyau et de systemd")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    if not args.image and not args.vm:
        ap.error("choisir --image (conteneur) ou --vm (vraie machine WSL)")
    if args.image and args.vm:
        ap.error("--image et --vm s'excluent : un seul systeme de test")

    pids = [args.playbook] if args.playbook else sorted(pb.tous())
    resultats = []
    if args.vm:
        # Vraie machine : un seul systeme, pas de conteneur jetable entre
        # deux playbooks. C'est le prix a payer pour avoir un noyau.
        executeur = ExecuteurWSL(args.vm)
        systeme = executeur.systeme()
        print(f"banc sur machine reelle : {args.vm} ({systeme}) — les "
              f"playbooks MODIFIENT cette distribution, le retour arriere "
              f"est verifie a chaque fois")
        print()
        for pid in pids:
            resultats.append(aller_retour(executeur, pid, systeme,
                                          vraie_machine=True))
    else:
        image, systeme = IMAGES[args.image]
        for pid in pids:
            with ExecuteurDocker(image) as executeur:   # conteneur neuf
                resultats.append(aller_retour(executeur, pid, systeme,
                                              vraie_machine=args.vraie_machine))

    en_attente_vm = [r for r in resultats if r["vm"]]
    hors_cadre = [r for r in resultats if r["cadre"] and not r["vm"]]
    juges = [r for r in resultats if not r["vm"] and not r["cadre"]]
    rapport = {"systeme": systeme,
               "date": datetime.now(timezone.utc).isoformat(),
               "playbooks": resultats,
               "juges": len(juges),
               "reussis": sum(1 for r in juges if r["ok"]),
               "a_tester_en_vm": len(en_attente_vm),
               "hors_cadre": len(hors_cadre)}
    sortie = args.rapport or (Path("banc/rapports")
                              / f"playbooks-{args.image or ('vm-' + args.vm)}.json")
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps(rapport, ensure_ascii=False, indent=1) + "\n",
                      encoding="utf-8")

    for r in resultats:
        if r["vm"]:
            print(f"VM    {r['playbook']} — {r['vm']}")
            continue
        if r["cadre"]:
            print(f"CADRE {r['playbook']} — {r['cadre']}")
            continue
        print(f"{'OK   ' if r['ok'] else 'ECART'} {r['playbook']}")
        for e in r["ecarts"]:
            print(f"      {e}")
    print(f"{rapport['reussis']}/{rapport['juges']} playbooks reussis "
          f"({rapport['a_tester_en_vm']} a tester en VM, "
          f"{rapport['hors_cadre']} hors cadre du banc) — rapport : {sortie}")
    return 0 if rapport["reussis"] == rapport["juges"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
