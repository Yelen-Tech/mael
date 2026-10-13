"""Banc de la LOCALISATION sur de vrais tickets (SWE-bench Lite) — 12/10/2026.

SWE-bench Lite (Princeton, licence MIT) : 300 tickets GitHub reels de 12
depots Python, chacun corrige dans UN fichier. Pour chaque ticket, le depot
est remis dans l'etat d'AVANT le correctif (base_commit), MAEL l'indexe et
localise — sans modele — et l'on regarde :
  - le RANG du fichier reellement corrige (top 1 / 3 / 5 / 10) ;
  - si une des 3 premieres fonctions designees dans ce fichier recouvre les
    lignes changees par le correctif officiel.
Ce que le banc ne fait pas : il ne lit pas le correctif pour localiser (il
ne sert qu'a noter), et il ne lit jamais les « hints » des mainteneurs.

    python -m brain.codage.banc_depot <lite.json> <dossier>
           [--depot django/django] [--max 20] [--sortie resultats.json]
Chaque depot est telecharge en archive au bon commit (dossier/archives/,
garde pour la fois suivante) puis extrait dans dossier/travail/.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tarfile
import time
from collections import defaultdict
from pathlib import Path

from . import depot, localisation


def moitie(instance_id: str) -> str:
    """« reglage » ou « controle », fixe pour toujours d'apres l'identifiant.
    On ajuste MAEL en regardant les ratés de la moitie « reglage » ; on le
    NOTE sur la moitie « controle », jamais regardee en detail — sinon on
    regle MAEL sur les reponses (12/10/2026)."""
    import hashlib
    h = hashlib.sha256(instance_id.encode()).digest()[0]
    return "reglage" if h % 2 == 0 else "controle"


def lignes_changees(patch: str) -> dict[str, list[tuple[int, int]]]:
    """Les plages de lignes (dans l'ANCIEN fichier) touchees par un diff."""
    out: dict[str, list[tuple[int, int]]] = defaultdict(list)
    courant = None
    for l in patch.splitlines():
        m = re.match(r"^--- a/(\S+)", l)
        if m:
            courant = m.group(1)
            continue
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? ", l)
        if m and courant:
            debut, n = int(m.group(1)), int(m.group(2) or 1)
            out[courant].append((debut, debut + max(n, 1) - 1))
    return dict(out)


def telecharger(repo: str, commit: str, archives: Path) -> Path | None:
    """L'archive du depot a ce commit (codeload.github.com). Le clonage git
    restait bloque sur la connexion du responsable (12/10/2026) ; une archive
    se telecharge en quelques secondes, et l'on reessaie sur coupure."""
    cible = archives / repo.replace("/", "__") / f"{commit}.tar.gz"
    if cible.exists() and cible.stat().st_size > 0:
        return cible
    cible.parent.mkdir(parents=True, exist_ok=True)
    tmp = cible.with_suffix(".part")
    url = f"https://codeload.github.com/{repo}/tar.gz/{commit}"
    for essai in range(5):
        r = subprocess.run(["curl", "-sfL", "--max-time", "900", "-o",
                            str(tmp), url], capture_output=True)
        if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            tmp.replace(cible)
            return cible
        time.sleep(20 * (essai + 1))
    return None


def extraire(archive: Path, dossier: Path) -> None:
    """Extrait l'archive (DONNEES non sures : filtre « data » de tarfile —
    ni lien hors du dossier, ni chemin absolu) en retirant le dossier de
    tete « nom-commit/ »."""
    import shutil
    import tarfile
    if dossier.exists():
        shutil.rmtree(dossier)
    dossier.mkdir(parents=True)
    with tarfile.open(archive) as t:
        membres = []
        for m in t.getmembers():
            parties = m.name.split("/", 1)
            if len(parties) < 2 or not parties[1]:
                continue
            m.name = parties[1]
            membres.append(m)
        t.extractall(dossier, members=membres, filter="data")


def _backend():
    """Le moteur de MAEL, pour --choix (le banc tourne hors de manage.py)."""
    import os

    import django
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
    from brain.backends.base import obtenir_backend
    return obtenir_backend()


def evaluer(instance: dict, archives: Path, travail: Path,
            backend=None) -> dict:
    archive = telecharger(instance["repo"], instance["commit"], archives)
    if archive is None:
        return {"id": instance["id"], "erreur": "telechargement impossible"}
    # UN dossier par ticket, extrait UNE fois et garde (avec le cache d'index
    # de MAEL) : re-extraire a chaque passage coutait 15 a 40 s par ticket
    # (l'antivirus inspecte chaque fichier ecrit) pour 0,5 s de localisation
    # (12/10/2026). La marque « .mael-extrait » dit que l'extraction est
    # complete.
    depot_dir = travail / instance["id"]
    marque = depot_dir / ".mael-extrait"
    try:
        if not marque.exists():
            extraire(archive, depot_dir)
            marque.write_text(instance["commit"], encoding="utf-8")
    except (OSError, tarfile.TarError) as e:
        # ex. chemin > 260 caracteres sous Windows (depot pytest, 12/10) :
        # le ticket n'est pas evalue, le banc continue
        return {"id": instance["id"], "erreur": f"extraction : {e}"[:300]}
    d = time.monotonic()
    idx = depot.indexer(depot_dir)
    t_index = time.monotonic() - d
    d = time.monotonic()
    lieux = localisation.localiser(idx, instance["ticket"], n=10)
    t_loc = time.monotonic() - d
    cible = instance["fichiers"][0]
    rang_calcule = next((k + 1 for k, l in enumerate(lieux)
                         if l.fichier == cible), None)
    choix_info = {}
    if backend is not None:                 # levier 3 : le modele departage
        from . import choix
        textes = {}
        for l in lieux[:choix.CANDIDATS]:
            try:
                textes[l.fichier] = (depot_dir / l.fichier).read_text(
                    encoding="utf-8", errors="replace")
            except OSError:
                pass
        d = time.monotonic()
        lieux, c = choix.choisir(backend, instance["ticket"], lieux, textes)
        choix_info = {"rang_calcule": rang_calcule, "choisis": c.fichiers,
                      "t_choix": round(time.monotonic() - d, 1)}
    rang = next((k + 1 for k, l in enumerate(lieux) if l.fichier == cible),
                None)
    fonction = False
    if rang:
        plages = lignes_changees(instance["patch"]).get(cible, [])
        for s in lieux[rang - 1].symboles[:3]:
            if any(s.debut <= fin and debut <= s.fin for debut, fin in plages):
                fonction = True
    return {"id": instance["id"], "moitie": moitie(instance["id"]),
            "rang": rang, "fonction": fonction,
            "fichiers": len(idx.fichiers), "t_index": round(t_index, 1),
            "t_loc": round(t_loc, 1),
            "premier": lieux[0].fichier if lieux else None,
            "raisons": lieux[rang - 1].raisons[:4] if rang else [],
            **choix_info}


def appliquer_patch(racine: Path, patch: str) -> tuple[bool, str]:
    """git apply (fonctionne hors d'un depot git). Le diff est ecrit en \\n :
    sous Windows, ecrit en mode texte, il passait en \\r\\n et git le
    refusait (essai du 12/10)."""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False,
                                     encoding="utf-8", newline="\n") as f:
        f.write(patch)
        chemin = f.name
    try:
        r = subprocess.run(["git", "apply", "--whitespace=nowarn", chemin],
                           cwd=racine, capture_output=True, text=True)
        return r.returncode == 0, r.stderr[:300]
    finally:
        Path(chemin).unlink(missing_ok=True)


def etalonner(instance: dict, racine: Path, env) -> set[str]:
    """Les tests que NOTRE environnement ne peut pas faire reussir, meme avec
    le correctif officiel (requests-3362 : 2 tests sur 75 veulent internet,
    le conteneur n'en a pas). Ils sont ecartes de la note — et LISTES dans le
    rapport, jamais caches. `racine` : une copie neuve du depot."""
    from . import essais_depot as ed
    tests = json.loads(instance["f2p"]) + json.loads(instance["p2p"])
    for patch in (instance["patch"], instance["test_patch"]):
        ok, _ = appliquer_patch(racine, patch)
        if not ok:
            return set()
    ex = ed.executer_tests(env, racine,
                           sorted({t.split("::")[0] for t in tests}))
    return {t for t in tests if not ex.reussi(t)} if ex.lance else set()


def noter(instance: dict, racine: Path, env,
          exclus: set[str] = frozenset()) -> dict:
    """La note SWE-bench, APRES le passage de MAEL : on applique les tests
    caches (test_patch) sur le depot tel que MAEL l'a laisse, et l'on
    execute FAIL_TO_PASS et PASS_TO_PASS. Resolu = tous reussissent (la
    regle officielle). MAEL n'a jamais vu ces tests."""
    from . import essais_depot as ed
    f2p = [t for t in json.loads(instance["f2p"]) if t not in exclus]
    p2p = [t for t in json.loads(instance["p2p"]) if t not in exclus]
    if not f2p:
        return {"resolu": False, "note": "aucun test FAIL_TO_PASS mesurable "
                                         "dans cet environnement"}
    ok, erreur = appliquer_patch(racine, instance["test_patch"])
    if not ok:
        return {"resolu": False, "note": f"tests caches non appliques : "
                                         f"{erreur}"}
    cibles = sorted({t.split("::")[0] for t in f2p + p2p})
    ex = ed.executer_tests(env, racine, cibles)
    if not ex.lance:
        return {"resolu": False, "note": f"tests non lances : {ex.raison}"}
    f2p_ok = sum(1 for t in f2p if ex.reussi(t))
    p2p_ok = sum(1 for t in p2p if ex.reussi(t))
    return {"resolu": f2p_ok == len(f2p) and p2p_ok == len(p2p),
            "f2p": f"{f2p_ok}/{len(f2p)}", "p2p": f"{p2p_ok}/{len(p2p)}",
            "non_mesurables": sorted(exclus)}


def bilan(resultats: list[dict]) -> str:
    ok = [r for r in resultats if "erreur" not in r]
    if not ok:
        return "aucun resultat"
    n = len(ok)

    def part(k):
        return sum(1 for r in ok if r["rang"] and r["rang"] <= k)
    l = [f"{n} tickets ({len(resultats) - n} non evalues)",
         *(f"  fichier corrige dans le top {k:2} : {part(k):3} "
           f"({100 * part(k) / n:.0f} %)" for k in (1, 3, 5, 10)),
         f"  bonne fonction (top 3, si fichier trouve) : "
         f"{sum(r['fonction'] for r in ok)} "
         f"({100 * sum(r['fonction'] for r in ok) / n:.0f} %)",
         f"  temps moyen : index {sum(r['t_index'] for r in ok) / n:.1f} s, "
         f"localisation {sum(r['t_loc'] for r in ok) / n:.1f} s"]
    for m in ("reglage", "controle"):
        rs = [r for r in ok if moitie(r["id"]) == m]
        if rs:
            t1 = sum(1 for r in rs if r["rang"] == 1)
            t5 = sum(1 for r in rs if r["rang"] and r["rang"] <= 5)
            l.append(f"  moitie {m:9}: top 1 {t1}/{len(rs)}, "
                     f"top 5 {t5}/{len(rs)}")
    par = defaultdict(list)
    for r in ok:
        par[r["id"].rsplit("-", 1)[0]].append(r)
    for d, rs in sorted(par.items()):
        t5 = sum(1 for r in rs if r["rang"] and r["rang"] <= 5)
        l.append(f"    {d:28} {t5}/{len(rs)} dans le top 5")
    return "\n".join(l)


def main(argv=None):
    a = argparse.ArgumentParser()
    a.add_argument("donnees")
    a.add_argument("dossier", help="archives/ et travail/ y sont crees")
    a.add_argument("--depot", action="append")
    a.add_argument("--max", type=int, default=0)
    a.add_argument("--sortie", default="")
    a.add_argument("--moitie", choices=("reglage", "controle"))
    a.add_argument("--choix", action="store_true",
                   help="levier 3 : le modele departage les candidats")
    o = a.parse_args(argv)
    instances = json.loads(Path(o.donnees).read_text(encoding="utf-8"))
    if o.moitie:
        instances = [i for i in instances if moitie(i["id"]) == o.moitie]
    if o.depot:
        instances = [i for i in instances if i["repo"] in o.depot]
    par_depot = defaultdict(list)
    for i in instances:
        par_depot[i["repo"]].append(i)
    resultats = []
    moteur = _backend() if o.choix else None
    base = Path(o.dossier)
    for repo, liste in par_depot.items():
        for inst in liste[:o.max or None]:
            r = evaluer(inst, base / "archives", base / "travail",
                        moteur)
            resultats.append(r)
            print(json.dumps(r, ensure_ascii=False), flush=True)
    print(bilan(resultats))
    if o.sortie:
        Path(o.sortie).write_text(json.dumps(resultats, ensure_ascii=False,
                                             indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
