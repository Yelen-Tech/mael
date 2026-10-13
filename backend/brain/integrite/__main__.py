"""CLI du noyau d'integrite : python -m brain.integrite [options]."""
from __future__ import annotations

import sys

from . import (
    binaires,
    coherence,
    derive_etat,
    entropie,
    infiltration,
    invariants,
    isolation,
    merkle,
)


def _etat_merkle() -> list[str]:
    if not merkle.SCEAU.exists():
        return ["bibliotheque NON scellee (--sceller apres relecture)"]
    ecarts = merkle.controler()
    if ecarts:
        return ecarts
    import json
    sceau = json.loads(merkle.SCEAU.read_text(encoding="utf-8"))
    return [f"intacte — racine {sceau['racine'][:16]}…, "
            f"{len(sceau['feuilles'])} fiches, scellee le {sceau['cree_le']}"]


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    if "--sceller" in argv:
        s = merkle.sceller()
        print(f"Bibliotheque scellee : {len(s['feuilles'])} fiches, "
              f"racine {s['racine']}")
        return 0

    # Module 4 : il faut une MACHINE a mesurer, pas la bibliotheque. Sur un
    # poste Windows, c'est un conteneur jetable du banc ; sur une machine
    # Linux, ce sera l'executeur local (a venir avec le paquet « sur site »).
    if "--isolation" in argv:
        # 1) ce que MAEL lance : le contrat d'enfermement de chaque outil
        print("== Isolation (module 7) ==")
        print("  -- conteneurs lances par MAEL --")
        import os as _os
        _os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
        import django as _django
        _django.setup()
        from brain.tools import registre as _registre
        defaillants = 0
        for nom, outil in sorted(_registre._outils.items()):
            if not outil.image:
                print(f"  {nom:24s} : sans conteneur (mode local)")
                continue
            manques = isolation.exigences_conteneur(
                outil.arguments_docker("image@sha256:x", ["--aide"]))
            if manques:
                defaillants += 1
                print(f"  {nom:24s} : MANQUE " + " ; ".join(manques))
            else:
                print(f"  {nom:24s} : enferme")
        # 2) la machine auditee : filtres d'appels systeme en place ?
        if "--image" in argv:
            image = argv[argv.index("--image") + 1]
            from banc.executeurs import ExecuteurDocker
            print(f"  -- machine mesuree : {image} --")
            with ExecuteurDocker(image) as machine:
                mesure = isolation.mesurer(machine)
            for mode, nombre in mesure["repartition"].items():
                print(f"  {mode:16s} : {nombre} processus")
            if mesure["sans_filtre"]:
                print("  sans filtre      : "
                      + ", ".join(mesure["sans_filtre"]))
            for ligne in mesure["espaces_de_noms_pid1"][:8]:
                print(f"  espace de noms   : {ligne}")
        return 1 if defaillants else 0

    if "--etat" in argv:
        # Photographie de l'etat d'une machine (module 8). Sans --comparer,
        # on enregistre ; avec, on dit ce qui a bouge depuis.
        import json as _json
        from pathlib import Path as _Path
        image = "mael-banc-ubuntu2204"
        if "--image" in argv:
            image = argv[argv.index("--image") + 1]
        from banc.executeurs import ExecuteurDocker
        print(f"== Derive d'etat (module 8) — {image} ==")
        with ExecuteurDocker(image) as machine:
            etat = derive_etat.photographier(machine, image)
        for nom, lignes in etat["rubriques"].items():
            print(f"  {nom:10s} : {len(lignes)} ligne(s)")
        if "--comparer" in argv:
            avant = _json.loads(_Path(argv[argv.index("--comparer") + 1])
                                .read_text(encoding="utf-8"))
            comparaison = derive_etat.comparer(avant, etat)
            print("  -- derive depuis le releve du "
                  f"{comparaison['avant']} --")
            for ligne in derive_etat.resumer(comparaison):
                print(f"  {ligne}")
            return 1 if comparaison["graves"] else 0
        if "--enregistrer" in argv:
            chemin = _Path(argv[argv.index("--enregistrer") + 1])
            chemin.write_text(_json.dumps(etat, ensure_ascii=False, indent=1),
                              encoding="utf-8")
            print(f"  etat enregistre : {chemin}")
        return 0

    if "--infiltration" in argv:
        image = "mael-banc-ubuntu2204"
        if "--image" in argv:
            image = argv[argv.index("--image") + 1]
        from banc.executeurs import ExecuteurDocker
        print(f"== Infiltration LD_PRELOAD et hooks (module 6) — {image} ==")
        with ExecuteurDocker(image) as machine:
            rapport = infiltration.controler(machine)
        for ligne in rapport["constats"]:
            print(f"  {ligne}")
        print(f"  graves : {len(rapport['graves'])}, "
              f"a verifier : {len(rapport['a_verifier'])}")
        return 1 if rapport["graves"] else 0

    if "--binaires" in argv:
        image = "mael-banc-ubuntu2204"
        if "--image" in argv:
            image = argv[argv.index("--image") + 1]
        from banc.executeurs import ExecuteurDocker  # import tardif : le
        # noyau d'integrite ne depend pas du banc, c'est la CLI qui les relie
        print(f"== Integrite des binaires (module 4) — {image} ==")
        with ExecuteurDocker(image) as machine:
            rapport = binaires.controler(machine)
        for titre, cle in (("modifications signalees", "modifications"),
                           ("GRAVES", "graves"),
                           ("fichiers sans paquet", "sans_paquet"),
                           ("detournements declares (dpkg-divert)",
                            "detournements")):
            lignes = rapport[cle]
            print(f"  {titre} : {len(lignes)}")
            for l in lignes[:15]:
                print(f"      {l}")
        print(f"  empreintes relevees : {len(rapport['empreintes'])} binaires "
              "sensibles")
        return 1 if rapport["graves"] or rapport["sans_paquet"] else 0

    tout = not any(a in argv for a in
                   ("--merkle", "--coherence", "--invariants", "--entropie"))
    code = 0

    if tout or "--merkle" in argv:
        print("== Sceau de la bibliotheque (modules 1+5) ==")
        for l in _etat_merkle():
            print(f"  {l}")
    if tout or "--coherence" in argv:
        print("== Coherence fiches <-> playbooks (module 9) ==")
        vs = coherence.resoudre()
        for v in vs:
            print(f"  {v}")
        print(f"  {len(vs)} violation(s)")
        code = code or bool(vs)
    if tout or "--invariants" in argv:
        print("== Invariants (module 3) ==")
        for nom, violations in invariants.verifier().items():
            etat = "tenu" if not violations else f"ROMPU ({len(violations)})"
            print(f"  {nom} : {etat}")
            for v in violations[:5]:
                print(f"      {v}")
            code = code or bool(violations)
    if tout or "--entropie" in argv:
        print("== Entropie de Shannon (module 2) ==")
        from pathlib import Path
        anomalies = {}
        for racine, motif in ((merkle.FICHES, "*.yaml"),
                              (Path("playbooks"), "*.sh"),
                              (Path("playbooks"), "*.yaml")):
            anomalies.update(entropie.analyser_arborescence(racine, motif))
        for chemin, liste in sorted(anomalies.items()):
            for a in liste:
                print(f"  {chemin} : {a.ou} — {a.valeur} bits/o ({a.extrait})")
        print(f"  {len(anomalies)} fichier(s) a signaler")
        code = code or bool(anomalies)
    return int(code)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
