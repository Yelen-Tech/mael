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


def lignes_touchees(patch: str) -> dict[str, set[int]]:
    """Les lignes PRECISES de l'ancien fichier que le correctif officiel
    retire (-) ou devant lesquelles il insere (+), sans le contexte du
    diff : ce que le modele doit VOIR pour pouvoir corriger."""
    out: dict[str, set[int]] = defaultdict(set)
    courant, n, precedente = None, 0, ""
    for l in patch.splitlines():
        if l.startswith("--- a/"):
            courant = l[6:].strip()
        elif l.startswith("+++") or courant is None:
            continue
        elif l.startswith("@@"):
            n = int(re.match(r"@@ -(\d+)", l).group(1))
        elif l.startswith("-"):
            out[courant].add(n)
            n += 1
        elif l.startswith("+") and not precedente.startswith(("-", "+")):
            out[courant].add(n)         # insertion pure : devant la ligne n
        elif l.startswith(" "):
            n += 1
        precedente = l
    return dict(out)


# Ce que le modele voit a l'examen Kaggle : Qwen3-Coder-30B-A3B, 32 768
# jetons (le banc mesure avec le MEME budget d'extraits que le correcteur)
ENVERGURE_EXAMEN = ("Qwen3-Coder-30B-A3B", 30.5, 32_768)


def montrees(racine: Path, lieux, idx, patch: str, cible: str) -> dict:
    """Les lignes a corriger sont-elles dans les extraits montres au
    modele ? Mesure du rejeu du 15/10 : 2 tickets sur 5 seulement — la
    localisation est le frein, pas l'application des correctifs."""
    from . import correctif
    from .envergure import Envergure
    env = Envergure(*ENVERGURE_EXAMEN)
    extraits = correctif.choisir_extraits(
        racine, lieux, correctif.budget_correction(env), idx)
    touchees = lignes_touchees(patch).get(cible, set())
    vues = {n for n in touchees if any(
        e.fichier == cible and e.debut <= n <= e.fin for e in extraits)}
    return {"lignes": len(touchees), "vues": len(vues),
            "montre": bool(touchees) and vues == touchees,
            "fichiers_montres": len({e.fichier for e in extraits})}


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


def executer_exemple(instance: dict, depot_dir: Path, idx,
                     cache: Path) -> tuple[str, dict, list[str]]:
    """(trace, couverture, notes) de l'exemple du ticket, execute une fois
    puis relu du cache."""
    from collections import Counter

    from .agent_depot import AgentDepot, Bilan
    fichier = cache / f"{instance['id']}.json"
    if fichier.exists():
        d = json.loads(fichier.read_text(encoding="utf-8"))
        cv = {f: Counter({tuple(k): n for k, n in appels})
              for f, appels in d["couverture"].items()}
        return d["trace"], cv, d["notes"]
    a, b = AgentDepot(None, depot_dir), Bilan()
    try:
        trace = a._executer_exemples(instance["ticket"], idx, b)
    except Exception as e:                              # noqa: BLE001
        trace, b.notes = "", [f"panne : {type(e).__name__} {e}"[:200]]
    cache.mkdir(parents=True, exist_ok=True)
    fichier.write_text(json.dumps({
        "trace": trace, "notes": b.notes,
        "couverture": {f: [[list(k), n] for k, n in c.items()]
                       for f, c in a.couverture.items()}}),
        encoding="utf-8")
    return trace, a.couverture, b.notes


def evaluer(instance: dict, archives: Path, travail: Path,
            backend=None, executer: bool = False) -> dict:
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
    ticket, cv, execution = instance["ticket"], None, []
    if executer:
        # phase 1 : l'exemple du ticket EXECUTE (trace + couverture), comme
        # l'agent le fait a l'examen (environnement du mode hote). Le
        # resultat est GARDE (execution/<id>.json) : regler les poids de la
        # localisation ne demande pas de tout reexecuter
        trace, cv, execution = executer_exemple(instance, depot_dir, idx,
                                                travail.parent / "execution")
        if trace:
            ticket += ("\n\nTRACE OBTENUE PAR MAEL EN EXECUTANT L'EXEMPLE "
                       "DU TICKET (code actuel) :\n```\n" + trace + "\n```")
    lieux = localisation.localiser(idx, ticket, n=10, couverture=cv)
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
    m = montrees(depot_dir, lieux, idx, instance["patch"], cible)
    return {"id": instance["id"], "moitie": moitie(instance["id"]),
            "rang": rang, "fonction": fonction,
            "montre": m["montre"], "vues": f"{m['vues']}/{m['lignes']}",
            "fichiers_montres": m["fichiers_montres"],
            **({"execution": execution[-1][:160] if execution else "aucun "
                "exemple"} if executer else {}),
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


_TEST_DJANGO = re.compile(r"^(\w+) \(([\w.]+)\)")


def identifiant(test: str) -> str:
    """Un test officiel de SWE-bench -> l'identifiant que MAEL lit. Les
    tickets Django nomment « test_x (forms_tests.tests.Classe) » (parfois
    suivi de la docstring) : -> « tests/forms_tests/tests.py::Classe::
    test_x ». Verifie en vrai le 15/10 sur django-15202 : FAIL_TO_PASS en
    echec avant le correctif officiel, reussis apres, PASS_TO_PASS 6/6."""
    m = _TEST_DJANGO.match(test.split("\n", 1)[0])
    if not m or "::" in test:
        return test
    p = m.group(2).split(".")
    if p[-1] == m.group(1):
        p = p[:-1]
    return f"tests/{'/'.join(p[:-1])}.py::{p[-1]}::{m.group(1)}"


def tests_officiels(instance: dict, cle: str) -> list[str]:
    return [identifiant(t) for t in json.loads(instance[cle])]


def fichiers_de_tests(instance: dict) -> list[str]:
    """Les fichiers de test a lancer : ceux que touche le patch de tests
    officiel (comme SWE-bench), plus ceux que nomment les tests. sympy ne
    donne que des noms nus (« test_ccode_Relational ») : sans cela, toute
    la suite tournait."""
    touches = re.findall(r"^\+\+\+ b/(\S+\.py)$", instance["test_patch"],
                         re.M)
    nommes = [t.split("::")[0] for t in tests_officiels(instance, "f2p")
              + tests_officiels(instance, "p2p") if "::" in t]
    return sorted(set(touches) | {f for f in nommes if f.endswith(".py")})


def reussi(ex, test: str) -> bool:
    """Un test officiel a-t-il reussi ? Un nom nu (sympy) vaut pour le
    test de ce nom dans les fichiers lances."""
    if test in ex.statuts or "::" in test or " " in test:
        return ex.reussi(test)
    trouves = [t for t in ex.statuts if t.endswith("::" + test)]
    return bool(trouves) and all(ex.reussi(t) for t in trouves)


def etalonner(instance: dict, racine: Path, env) -> set[str]:
    """Les tests que NOTRE environnement ne peut pas faire reussir, meme avec
    le correctif officiel (requests-3362 : 2 tests sur 75 veulent internet,
    le conteneur n'en a pas). Ils sont ecartes de la note — et LISTES dans le
    rapport, jamais caches. `racine` : une copie neuve du depot."""
    from . import essais_depot as ed
    tests = tests_officiels(instance, "f2p") + tests_officiels(instance, "p2p")
    for patch in (instance["patch"], instance["test_patch"]):
        ok, _ = appliquer_patch(racine, patch)
        if not ok:
            return set()
    ex = ed.executer_tests(env, racine, fichiers_de_tests(instance))
    return {t for t in tests if not reussi(ex, t)} if ex.lance else set()


def controler(instance: dict, archives: Path, travail: Path) -> dict:
    """Le CONTROLE de la chaine de test de MAEL sur un ticket, comme les
    auteurs de SWE-bench valident leurs environnements : les tests
    officiels doivent ECHOUER sur le code d'origine et REUSSIR avec le
    correctif officiel. Si non, MAEL ne sait pas tester ce depot (ou cette
    version) : on le sait AVANT l'examen. Les tests qui echouent meme avec
    le correctif sont listes (environnement), jamais caches."""
    import shutil

    from . import essais_depot as ed
    archive = telecharger(instance["repo"], instance["commit"], archives)
    if archive is None:
        return {"id": instance["id"], "verdict": "TELECHARGEMENT IMPOSSIBLE"}
    copie = travail / f"controle-{instance['id']}"
    extraire(archive, copie)
    try:
        f2p = tests_officiels(instance, "f2p")
        p2p = tests_officiels(instance, "p2p")
        ok, err = appliquer_patch(copie, instance["test_patch"])
        if not ok:
            return {"id": instance["id"],
                    "verdict": f"TESTS OFFICIELS NON APPLIQUES {err[:150]}"}
        idx = depot.indexer(copie, cache=False)
        suites = [s for s in idx.suites if ed.sorte(s) == "python"]
        if not suites:
            return {"id": instance["id"], "verdict": "AUCUNE SUITE PYTHON"}
        env = ed.preparer(copie, min(suites, key=lambda s: len(s.dossier)))
        if not env.pret:
            return {"id": instance["id"], "verdict": "ENVIRONNEMENT IMPOSSIBLE",
                    "raison": env.raison, "journal": env.journal[-600:]}
        cibles = fichiers_de_tests(instance)
        r = {"id": instance["id"], "version": instance.get("version", "")}
        for etape in ("avant", "apres"):
            if etape == "apres":
                ok, err = appliquer_patch(copie, instance["patch"])
                if not ok:
                    r["verdict"] = f"CORRECTIF OFFICIEL NON APPLIQUE {err[:150]}"
                    return r
            ex = ed.executer_tests(env, copie, cibles)
            r[etape] = {"f2p": sum(reussi(ex, t) for t in f2p),
                        "p2p": sum(reussi(ex, t) for t in p2p),
                        "lance": ex.lance, "raison": ex.raison}
            if etape == "apres":
                r["p2p_casses"] = [t for t in p2p if not reussi(ex, t)][:10]
        r["f2p_total"], r["p2p_total"] = len(f2p), len(p2p)
        av, ap = r["avant"], r["apres"]
        if ap["f2p"] == len(f2p) and av["f2p"] < len(f2p):
            r["verdict"] = ("VALIDE" if ap["p2p"] == len(p2p)
                            else "VALIDE, tests d'environnement ecartes")
        else:
            r["verdict"] = "A VOIR"
        return r
    finally:
        shutil.rmtree(copie, ignore_errors=True)


def noter(instance: dict, racine: Path, env,
          exclus: set[str] = frozenset()) -> dict:
    """La note SWE-bench, APRES le passage de MAEL : on applique les tests
    caches (test_patch) sur le depot tel que MAEL l'a laisse, et l'on
    execute FAIL_TO_PASS et PASS_TO_PASS. Resolu = tous reussissent (la
    regle officielle). MAEL n'a jamais vu ces tests."""
    from . import essais_depot as ed
    f2p = [t for t in tests_officiels(instance, "f2p") if t not in exclus]
    p2p = [t for t in tests_officiels(instance, "p2p") if t not in exclus]
    if not f2p:
        return {"resolu": False, "note": "aucun test FAIL_TO_PASS mesurable "
                                         "dans cet environnement"}
    ok, erreur = appliquer_patch(racine, instance["test_patch"])
    if not ok:
        return {"resolu": False, "note": f"tests caches non appliques : "
                                         f"{erreur}"}
    ex = ed.executer_tests(env, racine, fichiers_de_tests(instance))
    if not ex.lance:
        return {"resolu": False, "note": f"tests non lances : {ex.raison}"}
    f2p_ok = sum(1 for t in f2p if reussi(ex, t))
    p2p_ok = sum(1 for t in p2p if reussi(ex, t))
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
         f"  LIGNES A CORRIGER MONTREES AU MODELE : "
         f"{sum(r.get('montre', False) for r in ok)} "
         f"({100 * sum(r.get('montre', False) for r in ok) / n:.0f} %)",
         f"  temps moyen : index {sum(r['t_index'] for r in ok) / n:.1f} s, "
         f"localisation {sum(r['t_loc'] for r in ok) / n:.1f} s"]
    for m in ("reglage", "controle"):
        rs = [r for r in ok if moitie(r["id"]) == m]
        if rs:
            t1 = sum(1 for r in rs if r["rang"] == 1)
            t5 = sum(1 for r in rs if r["rang"] and r["rang"] <= 5)
            mo = sum(r.get("montre", False) for r in rs)
            l.append(f"  moitie {m:9}: top 1 {t1}/{len(rs)}, "
                     f"top 5 {t5}/{len(rs)}, montrees {mo}/{len(rs)}")
    par = defaultdict(list)
    for r in ok:
        par[r["id"].rsplit("-", 1)[0]].append(r)
    for d, rs in sorted(par.items()):
        t5 = sum(1 for r in rs if r["rang"] and r["rang"] <= 5)
        mo = sum(r.get("montre", False) for r in rs)
        l.append(f"    {d:28} {t5}/{len(rs)} dans le top 5, "
                 f"{mo}/{len(rs)} montrees")
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
    a.add_argument("--executer", action="store_true",
                   help="phase 1 : execute l'exemple du ticket (mode hote, "
                        "uv) — trace et couverture")
    a.add_argument("--controle", action="store_true",
                   help="tests officiels : en echec avant le correctif "
                        "officiel, reussis apres (MAEL sait-il tester ?)")
    a.add_argument("--id", action="append", help="ces tickets seulement")
    o = a.parse_args(argv)
    if o.executer or o.controle:
        import os
        os.environ["MAEL_ESSAIS"] = "hote"
        os.environ.setdefault("MAEL_ENVS", str(Path(o.dossier) / "envs"))
    instances = json.loads(Path(o.donnees).read_text(encoding="utf-8"))
    if o.id:
        instances = [i for i in instances if i["id"] in o.id]
    if o.controle:
        base = Path(o.dossier)
        res = []
        for inst in instances:
            r = controler(inst, base / "archives", base / "travail")
            res.append(r)
            print(json.dumps(r, ensure_ascii=False), flush=True)
        for r in res:
            print(f"  {r['id']:38} {r.get('version', ''):5} {r['verdict']}")
        if o.sortie:
            Path(o.sortie).write_text(json.dumps(res, ensure_ascii=False,
                                                 indent=1), encoding="utf-8")
        return
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
                        moteur, executer=o.executer)
            resultats.append(r)
            print(json.dumps(r, ensure_ascii=False), flush=True)
    print(bilan(resultats))
    if o.sortie:
        Path(o.sortie).write_text(json.dumps(resultats, ensure_ascii=False,
                                             indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
