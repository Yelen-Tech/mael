"""VERIFIER les lecons de MAEL : relancer les missions ou la faiblesse a ete
vue, AVEC les leviers proposes, et comparer avant / apres.

    mael code --verifier-lecons --dossier <racine des missions>

Troisieme etape de la boucle d'auto-correction (se relire -> appliquer ->
verifier). Rien n'est ecrase : les missions sont refaites dans
<racine>/verification-N/ ; les missions d'origine restent la reference.

Pour chaque lecon « proposee » dont le levier est programme
(leviers.APPLIQUES) :
  - avant / apres : combien de fois sa faiblesse est vue par les juges dans
    ses missions, et leurs defauts bloquants ;
  - servi : combien de fois le levier a reellement joue (un levier qui n'a
    jamais servi ne prouve rien : « non eprouvee ») ;
  - verdict : VALIDEE (la faiblesse recule et rien n'empire), REJETEE (la
    faiblesse ne recule pas), INCERTAINE (elle recule, mais les bloquants
    montent) ; lecons.yaml est mis a jour, VERIFICATION.md l'explique.

Limite dite dans le rapport : UNE relance par mission ; un petit modele
varie d'un essai a l'autre, et les leviers d'une meme mission jouent
ensemble. Une lecon validee peut etre revue a la verification suivante.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from . import angles_morts
from . import leviers as cat
from .lecons import LECONS, SeRelire
from .missions import ETAT_MISSIONS, Missions

RAPPORT_VERIF = "VERIFICATION.md"
FAIT = ".verifiee"           # marque d'une verification terminee


@dataclass
class Verdict:
    levier: str
    famille: str
    missions: list[str]
    avant: int
    apres: int
    servi: int
    bloquants_avant: int
    bloquants_apres: int

    @property
    def verdict(self) -> str:
        if self.servi == 0:
            return "non eprouvee"
        if self.apres < self.avant:
            return ("validee" if self.bloquants_apres <= self.bloquants_avant
                    else "incertaine")
        return "rejetee"


def _lire(chemin: Path) -> dict:
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _vues(racine: Path) -> dict[tuple[str, str], int]:
    """(famille, mission) -> nombre de fois vue par les juges ; les angles
    morts (pages jamais ouvertes...) comptent aussi."""
    compte: dict[tuple[str, str], int] = {}
    for f in SeRelire(None, racine).relever():
        for c in f.constats:
            compte[(f.cle, c.mission)] = compte.get((f.cle, c.mission), 0) + 1
    compte.update(angles_morts.vues(racine, list(_lire(racine /
                                                       ETAT_MISSIONS))))
    return compte


class Verification:
    def __init__(self, backend, racine: Path, *, savoir=None,
                 annoncer: Callable[[str], None] | None = None):
        self.backend = backend
        self.racine = Path(racine)
        self.savoir = savoir
        self.annoncer = annoncer or (lambda _m: None)

    def _lecons(self) -> list[dict]:
        try:
            d = yaml.safe_load((self.racine / LECONS).read_text(
                encoding="utf-8")) or {}
        except OSError:
            return []
        return d.get("lecons", [])

    def a_verifier(self) -> list[dict]:
        return [l for l in self._lecons() if l.get("etat") == "proposee"
                and l.get("levier") in cat.APPLIQUES]

    def _dossier(self) -> Path:
        """La verification en cours (reprise), sinon une nouvelle."""
        n = 1
        while (self.racine / f"verification-{n}").exists():
            if not (self.racine / f"verification-{n}" / FAIT).exists():
                return self.racine / f"verification-{n}"
            n += 1
        return self.racine / f"verification-{n}"

    def lancer(self) -> list[Verdict]:
        lecons = self.a_verifier()
        if not lecons:
            self.annoncer("aucune lecon proposee a verifier")
            return []
        etat = _lire(self.racine / ETAT_MISSIONS)
        ids = sorted({m for l in lecons for m in l.get("missions", [])
                      if m in etat})
        dossier = self._dossier()
        dossier.mkdir(parents=True, exist_ok=True)
        actifs = {l["levier"] for l in lecons} | cat.retenus(
            self.racine / LECONS, {"validee"})
        self.annoncer(f"verification dans {dossier.name} : "
                      f"{len(ids)} mission(s) relancee(s) ({', '.join(ids)})"
                      f", lecons appliquees : {', '.join(sorted(actifs))}")
        (dossier / "missions.yaml").write_text(yaml.safe_dump(
            {"missions": [{k: etat[i].get(k, "") for k in
                           ("id", "titre", "demande", "attendu")}
                          for i in ids]}, allow_unicode=True,
            sort_keys=False), encoding="utf-8")
        Missions(self.backend, dossier, dossier / "missions.yaml",
                 savoir=self.savoir, annoncer=self.annoncer,
                 leviers=actifs).lancer()
        verdicts = self.comparer(lecons, dossier)
        self.conclure(verdicts, dossier, actifs)
        (dossier / FAIT).write_text(time.strftime("%Y-%m-%d %H:%M"),
                                    encoding="utf-8")
        return verdicts

    def comparer(self, lecons: list[dict], dossier: Path) -> list[Verdict]:
        avant, apres = _vues(self.racine), _vues(dossier)
        e_avant = _lire(self.racine / ETAT_MISSIONS)
        e_apres = _lire(dossier / ETAT_MISSIONS)
        out = []
        for l in lecons:
            ms = [m for m in l.get("missions", []) if m in e_apres]
            fam = l["famille"]
            out.append(Verdict(
                levier=l["levier"], famille=fam, missions=ms,
                avant=sum(avant.get((fam, m), 0) for m in ms),
                apres=sum(apres.get((fam, m), 0) for m in ms),
                servi=sum(e_apres[m].get("leviers", {}).get(l["levier"], 0)
                          for m in ms),
                bloquants_avant=sum(e_avant.get(m, {}).get("bloquants", 0)
                                    for m in ms),
                bloquants_apres=sum(e_apres[m].get("bloquants", 0)
                                    for m in ms)))
        return out

    def conclure(self, verdicts: list[Verdict], dossier: Path,
                 actifs: set[str]):
        chemin = self.racine / LECONS
        d = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
        par = {v.levier: v for v in verdicts}
        for l in d.get("lecons", []):
            v = par.get(l.get("levier"))
            if v is None or l.get("etat") != "proposee":
                continue
            if v.verdict in {"validee", "rejetee"}:
                l["etat"] = v.verdict
            l["verification"] = {
                "dossier": dossier.name, "date": time.strftime("%Y-%m-%d"),
                "verdict": v.verdict, "vue_avant": v.avant,
                "vue_apres": v.apres, "servi": v.servi,
                "bloquants_avant": v.bloquants_avant,
                "bloquants_apres": v.bloquants_apres}
        texte = chemin.read_text(encoding="utf-8")
        entete = "".join(x + "\n" for x in texte.splitlines()
                         if x.startswith("#"))
        chemin.write_text(entete + yaml.safe_dump(
            d, allow_unicode=True, sort_keys=False, width=88),
            encoding="utf-8")
        rapport = self.rapport(verdicts, dossier, actifs)
        (self.racine / RAPPORT_VERIF).write_text(rapport, encoding="utf-8")
        (dossier / RAPPORT_VERIF).write_text(rapport, encoding="utf-8")

    def rapport(self, verdicts: list[Verdict], dossier: Path,
                actifs: set[str]) -> str:
        e_avant = _lire(self.racine / ETAT_MISSIONS)
        e_apres = _lire(dossier / ETAT_MISSIONS)
        l = ["# Verification de mes lecons", "",
             f"- {time.strftime('%Y-%m-%d %H:%M')} — missions refaites dans "
             f"`{dossier.name}/`, avec les lecons : "
             + ", ".join(f"`{a}`" for a in sorted(actifs)), "",
             "## Lecon par lecon", "",
             "| lecon (levier) | faiblesse | vue avant -> apres | a servi | "
             "bloquants avant -> apres | verdict |",
             "|---|---|---|---|---|---|"]
        for v in verdicts:
            l.append(f"| `{v.levier}` | {v.famille} | {v.avant} -> {v.apres} "
                     f"| {v.servi} fois | {v.bloquants_avant} -> "
                     f"{v.bloquants_apres} | **{v.verdict.upper()}** |")
        l += ["", "## Mission par mission", "",
              "| mission | verdict avant | verdict apres | bloquants avant "
              "-> apres | duree avant -> apres |", "|---|---|---|---|---|"]
        for mid, m in e_apres.items():
            a = e_avant.get(mid, {})
            l.append(f"| {mid} | {a.get('verdict', '—')} | {m.get('verdict')}"
                     f" | {a.get('bloquants', 0)} -> {m.get('bloquants', 0)} "
                     f"| {a.get('secondes', 0) / 60:.0f} -> "
                     f"{m.get('secondes', 0) / 60:.0f} min |")
        l += ["", "## Ce que cette verification ne prouve pas", "",
              "- une seule relance par mission : un petit modele varie d'un "
              "essai a l'autre ; une lecon validee sera revue aux "
              "verifications suivantes ;",
              "- les lecons d'une meme mission jouent ensemble : le progres "
              "d'une mission ne s'attribue pas a une seule lecon ;",
              "- une lecon « non eprouvee » n'a jamais eu a servir (par "
              "exemple : aucune ecriture coupee cette fois) : elle reste "
              "proposee."]
        return "\n".join(l) + "\n"
