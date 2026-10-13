"""Execution des fiches sur un systeme de test (point 4, partie C).

Pour chaque fiche applicable au systeme (filtrage de brain.contexte, rien de
reecrit) : chaque commande `observer` est executee en root dans le
conteneur, puis jugee par brain.bibliotheque.ecarts (le code juge, ici comme
au terminal).

    python -m banc.fiches --image ubuntu2204 [--theme X] [--rapport out.json]

Limites du conteneur (documentees dans les consignes) : systemd et le noyau
(sysctl, modules, /proc/cmdline, /boot/config) ne sont pas ceux d'une vraie
machine. Les fiches de ces themes sont marquees « a tester en VM », pas
jugees fausses.

Deux choses differentes, jamais melangees dans le rapport (Claude,
20/09/2026, apres le banc reel des trois images) :
  - DEFAUT DE FICHE : la fiche est fausse (commande non LECTURE, erreur de
    syntaxe du shell). Le banc rend un code de sortie non nul.
  - COMMANDE IMPOSSIBLE : binaire absent (127) ou delai depasse (124). La
    machine ne peut pas repondre ; le verdict est « indetermine » et rien
    n'est invente. Ce n'est PAS un defaut : sur Debian 12 les fiches ufw et
    iptables tombent la (l'image n'installe que nftables), et la regle
    elle-meme est conditionnelle.
Rien n'est corrige ici : les defauts sont signales, jamais reecrits.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from brain import bibliotheque as bib
from brain.bibliotheque import ecarts
from brain.contexte import applicable, commande_pour, depuis_declaration
from brain.garde import NIVEAU, classer

from .executeurs import Executeur, ExecuteurDocker

# nom d'image du banc -> (image Docker locale, declaration de systeme)
IMAGES = {
    "ubuntu2204": ("mael-banc-ubuntu2204", "ubuntu:22.04"),
    "ubuntu2404": ("mael-banc-ubuntu2404", "ubuntu:24.04"),
    "debian12": ("mael-banc-debian12", "debian:12"),
}

# Ce qu'un conteneur ne peut pas prouver (consignes, limite connue) :
# le noyau (sysctl, modules, /proc/cmdline, /boot/config) et systemd.
THEMES_VM = {"parametres-noyau", "parametres-reseau", "modules-noyau",
             "compilation-noyau", "demarrage"}
LECTEURS_VM = {"systemctl"}       # systemd n'est pas PID 1 en conteneur


# Commandes qui lisent ce qu'un conteneur ne reproduit pas (banc reel du
# 19/09/2026, Claude) : /proc/cmdline de l'HOTE, systemd absent, montages
# Docker (/etc/resolv.conf, /etc/hostname) vus comme des partitions.
MARQUES_VM = ("/proc/cmdline", "systemctl", "mount |")
# Fiches manuelles a parametre (domaine, certificat a fournir) : rien a
# executer tel quel.
PARAMETRES = ("DOMAINE", "CERTIFICAT")

# Une commande qui balaye tout le disque n'a rien a voir avec la lecture
# d'un fichier : sur une machine lente, « find / -xdev ... » depassait le
# delai commun de 120 s et le rapport le lisait comme un defaut de fiche
# (banc reel Ubuntu 24.04, 19/09/2026). Delai propre a ces commandes.
BALAYAGES = ("find /", "find -H /", "find -L /")
DELAI_BALAYAGE = 900          # 15 min


def delai_pour(commande: str) -> int | None:
    """Delai accorde a cette commande, None = delai commun du banc."""
    return DELAI_BALAYAGE if any(b in commande for b in BALAYAGES) else None


def en_vm(fiche) -> str | None:
    """Raison pour laquelle la fiche releve d'une VM, sinon None."""
    theme = (fiche.taxonomie or {}).get("theme")
    if theme in THEMES_VM:
        return f"theme « {theme} » : noyau d'un conteneur ≠ vraie machine"
    for obs in fiche.observer:
        for m in MARQUES_VM:
            if m in obs.commande:
                return f"commande « {m} » : conteneur ≠ vraie machine"
    lecteurs = {s.get("lecteur") for c in fiche.controles
                for s in (c.evaluation or [])}
    if lecteurs & LECTEURS_VM:
        return "lecteur systemctl : systemd absent d'un conteneur"
    return None


def executer_fiche(executeur: Executeur, fiche, ctx) -> dict:
    """Execute les observations d'une fiche, rend fiche + verdicts + defauts.

    Chaque commande passe d'abord par le garde-fou : ce qui n'est pas
    LECTURE n'est jamais execute (ceinture et bretelles)."""
    sorties, defauts, impossibles = {}, [], []
    for i, obs in enumerate(fiche.observer):
        cmd = commande_pour(obs, ctx)
        if any(p in cmd for p in PARAMETRES):
            continue                  # commande a parametre : non executable
        v = classer(cmd)
        if v.niveau is not NIVEAU.LECTURE:
            defauts.append(f"commande non LECTURE ({v.motif}) : {cmd[:80]}")
            continue
        r = executeur.executer(["bash", "-c", cmd], racine=True,
                               delai=delai_pour(cmd))
        erreur = (r.stderr or "").lower()
        if r.code == 127:
            impossibles.append(f"binaire absent (127) : {cmd[:80]}")
        elif r.code == 124:
            impossibles.append(f"delai depasse : {cmd[:80]}")
        # Code 2 seul ne prouve rien : grep le rend quand un fichier lu
        # n'existe pas (cas normal). Seule une erreur de syntaxe du shell
        # est un defaut de fiche. (Claude, 19/09/2026)
        elif "syntax error" in erreur or "unexpected eof" in erreur:
            defauts.append(f"erreur de syntaxe : {cmd[:80]} ({erreur[:80]})")
        # Commande impossible (126/127/124) : indetermine, jamais « vide ».
        sorties[i] = ecarts.sortie_a_juger(r.code, r.stdout)
    verdicts = ecarts.evaluer_fiche(fiche, sorties)
    return {
        "fiche": fiche.id,
        "verdicts": [{"controle": v.controle, "statut": v.statut.value,
                      "constate": v.constate, "motif": v.motif}
                     for v in verdicts],
        "defauts": defauts,
        "impossibles": impossibles,
    }


def executer_fiches(executeur: Executeur, systeme: str,
                    theme: str | None = None) -> dict:
    """Banc complet des fiches applicables au systeme declare."""
    ctx = depuis_declaration(systeme)
    resultats, ecartees_vm, hors_champ = [], [], 0
    for fiche in bib.toutes():
        if fiche.etat == "obsolete":
            continue
        if theme and (fiche.taxonomie or {}).get("theme") != theme:
            continue
        ok, raison = applicable(fiche, ctx)
        if not ok:
            hors_champ += 1
            continue
        vm = en_vm(fiche)
        if vm:
            ecartees_vm.append({"fiche": fiche.id, "raison": vm})
            continue
        resultats.append(executer_fiche(executeur, fiche, ctx))

    statuts = {}
    for r in resultats:
        for v in r["verdicts"]:
            statuts[v["statut"]] = statuts.get(v["statut"], 0) + 1
    defauts = [f'{r["fiche"]} : {d}' for r in resultats for d in r["defauts"]]
    impossibles = [f'{r["fiche"]} : {d}'
                   for r in resultats for d in r["impossibles"]]
    return {
        "systeme": systeme,
        "date": datetime.now(timezone.utc).isoformat(),
        "fiches_testees": len(resultats),
        "fiches_hors_champ": hors_champ,
        "fiches_a_tester_en_vm": ecartees_vm,
        "verdicts": statuts,
        "defauts_de_fiche": defauts,
        "commandes_impossibles": impossibles,
        "detail": resultats,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="banc.fiches")
    ap.add_argument("--image", required=True, choices=sorted(IMAGES))
    ap.add_argument("--theme")
    ap.add_argument("--rapport", type=Path)
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    image, systeme = IMAGES[args.image]
    with ExecuteurDocker(image) as executeur:
        rapport = executer_fiches(executeur, systeme, theme=args.theme)

    sortie = args.rapport or Path("banc/rapports") / f"fiches-{args.image}.json"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps(rapport, ensure_ascii=False, indent=1) + "\n",
                      encoding="utf-8")

    print(f"{rapport['fiches_testees']} fiches testees sur {systeme} "
          f"({rapport['fiches_hors_champ']} hors champ, "
          f"{len(rapport['fiches_a_tester_en_vm'])} a tester en VM)")
    print(f"verdicts : {rapport['verdicts']}")
    print(f"defauts de fiche : {len(rapport['defauts_de_fiche'])}")
    for d in rapport["defauts_de_fiche"][:20]:
        print(f"  {d}")
    impossibles = rapport["commandes_impossibles"]
    print(f"commandes impossibles (verdict indetermine) : {len(impossibles)}")
    for d in impossibles[:20]:
        print(f"  {d}")
    print(f"rapport : {sortie}")
    return 1 if rapport["defauts_de_fiche"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
