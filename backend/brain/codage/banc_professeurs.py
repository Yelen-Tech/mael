"""Le banc des PROFESSEURS : leur FIABILITE sur des problemes, sans modele.

    mael code --banc-professeurs

Consigne du responsable (08/10/2026) : « on veut tester la fiabilite des
professeurs sur des problemes, c'est tout » — pas a travers le modele.
Chaque probleme (banc_professeurs.yaml) a sa bonne reponse ecrite a la main.
Le banc rend, pour chaque professeur et pour le juge, la part de criteres
justes, et la liste des ecarts : chacun est une faiblesse a corriger.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import professeurs as pr

FICHIER = Path(__file__).parent / "banc_professeurs.yaml"


@dataclass
class Resultat:
    justes: dict = field(default_factory=dict)      # professeur -> n
    total: dict = field(default_factory=dict)       # professeur -> n
    ecarts: list = field(default_factory=list)      # (professeur, id, texte)

    def noter(self, prof: str, ok: bool, pid: str, texte: str):
        self.total[prof] = self.total.get(prof, 0) + 1
        if ok:
            self.justes[prof] = self.justes.get(prof, 0) + 1
        else:
            self.ecarts.append((prof, pid, texte))

    def taux(self, prof: str) -> float:
        return self.justes.get(prof, 0) / max(self.total.get(prof, 0), 1)


def _contenu(avis: pr.Avis) -> str:
    return " ".join(avis.points)


def _textes(r: Resultat, prof: str, pid: str, avis: pr.Avis, attendu: dict):
    texte = _contenu(avis).lower()
    for x in attendu.get("contient", []):
        r.noter(prof, x.lower() in texte, pid, f"devrait dire « {x} »")
    for x in attendu.get("ne_contient_pas", []):
        r.noter(prof, x.lower() not in texte, pid, f"ne devrait PAS dire "
                f"« {x} »")


def evaluer(chemin: Path = FICHIER) -> Resultat:
    d = yaml.safe_load(Path(chemin).read_text(encoding="utf-8"))
    r = Resultat()
    for p in d.get("problemes", []):
        pid, demande = p["id"], p["demande"]
        avis, f, c = pr.conseil(demande)
        par = {a.professeur: a for a in avis}
        for cle, attendu in (p.get("realite") or {}).items():
            valeur = {"nb_pages": f.nb_pages, "langages": sorted(f.langages),
                      "base": f.base, "tests": f.tests,
                      "interactif": f.interactif, "langue": c.langue,
                      "contradiction": bool(c.contradictions),
                      "vague": c.vague}[cle]
            if cle == "langages":
                attendu = sorted(attendu)
            r.noter("realite", valeur == attendu, pid,
                    f"{cle} = {valeur!r}, attendu {attendu!r}")
        if p.get("connaissance"):
            _textes(r, "connaissance", pid, par["connaissance"],
                    p["connaissance"])
        if p.get("calcul"):
            a = p["calcul"]
            n = pr.fichiers_prevus(f)
            if "fichiers" in a:
                bas, haut = a["fichiers"]
                r.noter("calcul", bas <= n <= haut, pid,
                        f"{n} fichiers prevus, attendu {bas} a {haut}")
            if "regrouper" in a:
                dit = "regrouper" in _contenu(par["calcul"])
                r.noter("calcul", dit == a["regrouper"], pid,
                        f"« regrouper » dit : {dit}, attendu {a['regrouper']}")
        if p.get("humain"):
            _textes(r, "humain", pid, par["humain"], p["humain"])
    from . import deliberation as dl
    for p in d.get("reels", []):
        dec = dl.deliberer(p["probleme"])
        pid = p["id"]
        for cle in ("nature", "risque"):
            if cle in p:
                v = getattr(dec, cle)
                r.noter("deliberation", v == p[cle], pid,
                        f"{cle} = {v}, attendu {p[cle]}")
        if "confiance_pas" in p:
            r.noter("deliberation", dec.confiance != p["confiance_pas"], pid,
                    f"confiance {dec.confiance}, ne devait pas etre "
                    f"{p['confiance_pas']}")
        for champ in ("decisions", "hypotheses", "besoins", "ne_pas",
                      "verifier"):
            texte = " ".join(e.texte for e in getattr(dec, champ)).lower()
            for x in p.get(champ, []):
                r.noter("deliberation", x.lower() in texte, pid,
                        f"{champ} devrait contenir « {x} »")
        r.noter("juge du conseil", not dec.refus, pid,
                "refusee : " + "; ".join(dec.refus) if dec.refus else "ok")
    evaluer_verdicts(r)
    for p in d.get("plan", []):
        raisons = pr.juger_plan(p["fichiers"], pr.etablir(p["demande"]))
        r.noter("juge du plan", (not raisons) == p["accepte"], p["id"],
                ("accepte" if not raisons else "refuse : " + raisons[0])
                + f", attendu {'accepte' if p['accepte'] else 'refuse'}")
    return r


VERDICTS = Path(__file__).parent / "banc_conseil_juges.yaml"


def evaluer_verdicts(r: Resultat, chemin: Path = VERDICTS) -> Resultat:
    """Le conseil sur les VERDICTS DES JUGES (conseil_juges.py) : 10 vrais
    cas des missions du 08/10/2026, conclusions ecrites a la main."""
    from . import conseil_juges as cj
    d = yaml.safe_load(Path(chemin).read_text(encoding="utf-8"))
    for c in d.get("cas", []):
        s = cj.Situation(demande=c["demande"], plan=c.get("plan", []),
                         defauts=c.get("defauts", []),
                         existants=c.get("existants", []),
                         coupures=c.get("coupures", {}),
                         limites=c.get("limites", []),
                         plan_brut=c.get("plan_brut", ""))
        v = cj.deliberer(s)
        a, cid = c["attendu"], c["id"]
        champs = {"impertinences": v.impertinences, "hypotheses":
                  v.hypotheses, "ne_pas": v.ne_pas, "reserves": v.reserves}
        for champ, elements in champs.items():
            texte = " ".join(e.texte for e in elements).lower()
            for x in a.get(champ, []):
                r.noter("conseil sur les verdicts", x.lower() in texte, cid,
                        f"{champ} devrait contenir « {x} »")
        sol = " ".join(s_.texte for s_ in v.solutions).lower()
        for x in a.get("solutions", []):
            r.noter("conseil sur les verdicts", x.lower() in sol, cid,
                    f"solutions devraient contenir « {x} »")
        if "cible" in a:
            cibles = [s_.cible for s_ in v.solutions]
            r.noter("conseil sur les verdicts", a["cible"] in cibles, cid,
                    f"cible {cibles}, attendu {a['cible']}")
        if "confiance" in a:
            r.noter("conseil sur les verdicts", v.confiance == a["confiance"],
                    cid, f"confiance {v.confiance}, attendu {a['confiance']}")
    return r


INEDITS = Path(__file__).parent / "banc_professeurs_inedits.yaml"


def evaluer_inedits(chemin: Path = INEDITS) -> tuple[list[dict], str]:
    """Problemes JAMAIS VUS : la JUSTESSE (criteres attendus) et
    l'HONNETETE (sans le bon savoir, le conseil doit dire « confiance
    basse » ; sinon : FAUSSE ASSURANCE)."""
    from . import deliberation as dl
    d = yaml.safe_load(Path(chemin).read_text(encoding="utf-8"))
    lignes = []
    for p in d.get("inedits", []):
        dec = dl.deliberer(p["probleme"])
        ok, ko = 0, []
        for cle in ("nature", "risque"):
            if cle in p:
                if getattr(dec, cle) == p[cle]:
                    ok += 1
                else:
                    ko.append(f"{cle} {getattr(dec, cle)} (attendu "
                              f"{p[cle]})")
        tout = " ".join(e.texte for e in dec.tous()).lower()
        for champ in ("decisions", "hypotheses", "besoins", "ne_pas",
                      "verifier"):
            texte = " ".join(e.texte for e in getattr(dec, champ)).lower()
            for x in p.get(champ, []):
                if x.lower() in texte:
                    ok += 1
                else:
                    ko.append(f"{champ} sans « {x} »")
        sait = all(x.lower() in tout for x in p.get("savoir", []))
        if sait:
            ok += 1
        else:
            ko.append("savoir attendu absent : " + ", ".join(p["savoir"]))
        total = ok + len(ko)
        honnete = sait or dec.confiance == "basse"
        lignes.append({"id": p["id"], "ok": ok, "total": total,
                       "sait": sait, "confiance": dec.confiance,
                       "honnete": honnete, "fiches": dec.fiches,
                       "nature": dec.nature, "ecarts": ko})
    l = ["# Problemes INEDITS (metier : code) — sans modele, code non retouche",
         "", "| probleme | justesse | savoir present | confiance annoncee | "
         "honnete ? | fiches utilisees |", "|---|---|---|---|---|---|"]
    for x in lignes:
        l.append(f"| {x['id']} | {x['ok']}/{x['total']} | "
                 f"{'oui' if x['sait'] else 'non'} | {x['confiance']} | "
                 f"{'oui' if x['honnete'] else '**FAUSSE ASSURANCE**'} | "
                 f"{', '.join(x['fiches']) or '—'} |")
    ok = sum(x["ok"] for x in lignes)
    tot = sum(x["total"] for x in lignes)
    honnetes = sum(x["honnete"] for x in lignes)
    l += ["", f"- **Justesse** : {ok}/{tot} criteres "
          f"({100 * ok / max(tot, 1):.0f} %)",
          f"- **Savoir present** : {sum(x['sait'] for x in lignes)}/"
          f"{len(lignes)} problemes",
          f"- **Honnetete** : {honnetes}/{len(lignes)} (les autres : "
          "FAUSSE ASSURANCE)", "", "## Les ecarts", ""]
    for x in lignes:
        if x["ecarts"]:
            l.append(f"- `{x['id']}` (nature trouvee : {x['nature']}) : "
                     + " ; ".join(x["ecarts"]))
    return lignes, "\n".join(l) + "\n"


ORDRE = ("realite", "connaissance", "calcul", "humain", "deliberation",
         "juge du conseil", "conseil sur les verdicts",
         "juge du plan")


def rapport(r: Resultat) -> str:
    l = ["# Banc des professeurs (metier : code) — sans modele", "",
         "| professeur | criteres justes | fiabilite |", "|---|---|---|"]
    for p in ORDRE:
        if p in r.total:
            l.append(f"| {p} | {r.justes.get(p, 0)} / {r.total[p]} | "
                     f"{100 * r.taux(p):.0f} % |")
    tj, tt = sum(r.justes.values()), sum(r.total.values())
    l += [f"| **ensemble** | **{tj} / {tt}** | **{100 * tj / max(tt, 1):.0f}"
          " %** |", "", "## Les ecarts (faiblesses a corriger)", ""]
    l += [f"- **{p}** — `{pid}` : {t}" for p, pid, t in r.ecarts] or [
        "- aucun"]
    return "\n".join(l) + "\n"
