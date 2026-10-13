"""Le mode MISSIONS : MAEL execute une liste de missions et documente son
travail lui-meme.

Cap du responsable (08/10/2026) : au lieu de construire chaque piece
d'avance, on DELEGUE a MAEL une liste de missions de plus en plus grandes,
qu'il execute en local, sans surveillance ; il cree ses dossiers et ses
fichiers, et ecrit son journal. On cerne ainsi ses aptitudes reelles, et on
l'ameliore pas a pas, la ou il echoue vraiment.

    mael code --missions missions.yaml --dossier <racine>

  - chaque mission a SON dossier (<racine>/<id>/) : le chantier y travaille,
    et l'espace interdit d'ecrire ailleurs ;
  - chaque mission ecrit son JOURNAL.md (ce qu'il a compris et suppose, son
    plan, chaque tache, ses reparations, retouches et coupures, le verdict,
    ce qu'il n'a pas pu verifier) ;
  - <racine>/RAPPORT.md : le tableau de bord de toutes les missions, refait
    apres CHAQUE mission (on suit l'avancement pendant la nuit) ;
  - reprise : une mission faite n'est pas refaite ; une mission
    interrompue reprend son chantier ou il en etait ;
  - une mission qui plante n'arrete pas les suivantes : son journal le dit.

Le journal est ecrit par MAEL a partir de ce qu'il a REELLEMENT fait (le
bilan du chantier), pas raconte par le modele : il ne peut pas mentir sur
ses propres resultats.
"""
from __future__ import annotations

import json
import re
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from ..backends.sante import MoteurEnPanne
from .atelier import Bilan
from .chantier import ETAT, Chantier
from .espace import Espace
from .juges import GRAVITE
from .leviers import retenus

ETAT_MISSIONS = "missions-etat.json"
PANNES_MAX = 3            # pannes du moteur de suite avant l'arret de la serie
JOURNAL = "JOURNAL.md"
RAPPORT = "RAPPORT.md"


@dataclass
class Mission:
    id: str
    titre: str
    demande: str
    attendu: str = ""               # ce que le responsable veut observer
    etat: str = "a faire"           # a faire | en cours | faite | echec
    verdict: str = ""
    secondes: float = 0.0
    appels: int = 0
    taches: int = 0
    premier_coup: int = 0           # taches validees des le 1er appel
    bloquants: int = 0
    coupures: int = 0
    retouches: int = 0
    reparations: int = 0
    suppositions: int = 0
    leviers: dict = field(default_factory=dict)   # lecon -> fois appliquee
    reserves: list = field(default_factory=list)  # ce qui n'a pas tourne
    jugement: float = 0.0                         # s passees a juger
    specialistes: dict = field(default_factory=dict)
    debut: str = ""
    fin: str = ""


def lire_missions(fichier: Path) -> list[Mission]:
    donnees = yaml.safe_load(Path(fichier).read_text(encoding="utf-8")) or {}
    missions = []
    for m in donnees.get("missions", []):
        missions.append(Mission(id=str(m["id"]), titre=m.get("titre", ""),
                                demande=m["demande"].strip(),
                                attendu=m.get("attendu", "").strip()))
    return missions


# ------------------------------------------------------------ le journal
def mesurer(m: Mission, bilan: Bilan, taches) -> None:
    """Les chiffres de la mission, tires de ce qui s'est vraiment passe."""
    m.appels = len(bilan.tours) + 1 + bilan.appels_conseil  # plan, conseil
    m.taches = len(taches)
    m.premier_coup = sum(1 for t in taches
                         if t.etat == "fait" and t.tours == 1)
    m.bloquants = len(bilan.bloquants)
    m.retouches = sum(1 for t in bilan.tours
                      if t.mode.startswith("retouche"))
    m.reparations = sum(len(t.reparations) for t in bilan.tours)
    m.coupures = sum(1 for t in bilan.tours for r in t.refus
                     if "generation coupee" in r or "hors de la tache" in r)
    m.suppositions = len(bilan.suppositions)
    m.leviers = dict(bilan.leviers)
    m.jugement = bilan.jugement
    m.specialistes = dict(bilan.specialistes)
    m.verdict = ("CONFORME" if bilan.conforme else
                 "NON CONFORME" if bilan.fichiers else "RIEN PRODUIT")
    # Ce qui n'a JAMAIS tourne : un « conforme » sur du code lu mais non
    # execute n'est pas la meme chose (mission 08 du 08/10/2026).
    m.reserves = [x for x in bilan.limites if _RESERVE.search(x)]


_RESERVE = re.compile(r"LU mais non execute|tests NON executes|pages NON "
                      r"ouvertes|page\(s\) non ouverte\(s\)|navigateur non "
                      r"lance|EN PANNE")


def verdict_dit(m: "Mission") -> str:
    if m.verdict == "CONFORME" and m.reserves:
        return "CONFORME (sous reserve)"
    return m.verdict


def journal(m: Mission, bilan: Bilan | None, taches, erreur: str = "") -> str:
    l = [f"# Mission {m.id} — {m.titre}", "",
         f"- **Demande** : {m.demande}",
         f"- **Ce que le responsable veut observer** : {m.attendu or '—'}",
         f"- **Debut** : {m.debut} — **fin** : {m.fin} — **duree** : "
         f"{m.secondes / 60:.1f} min",
         f"- **Verdict** : {verdict_dit(m) or 'ECHEC'}"]
    l += [f"  - reserve : {r}" for r in m.reserves] + [""]
    if erreur:
        l += ["## La mission a plante", "", "```", erreur.strip()[-3000:],
              "```", ""]
    if bilan is None:
        return "\n".join(l)
    # La raison de l'arret : sans elle, « RIEN PRODUIT » et « rien de
    # bloquant » se contredisaient (missions 07 et 10 du 08/10/2026).
    l.insert(-1, f"- **Arret** : {bilan.arret or '—'}")
    l += ["## Ce que j'ai compris et suppose", ""]
    l += [f"- {s}" for s in bilan.suppositions] or ["- rien de suppose"]
    if bilan.leviers:
        l += ["", "## Les lecons que j'ai appliquees", ""]
        l += [f"- `{k}` : {n} fois" + ("" if n else " (n'a pas eu a servir)")
              for k, n in bilan.leviers.items()]
    if bilan.etapes:
        l += ["", "## Les etapes (grand projet, decoupe par l'architecte)", ""]
        l += [f"- {e}" for e in bilan.etapes]
    l += ["", "## Mon plan", ""]
    l += [f"- {p}" for p in bilan.plan] or ["- (aucun plan)"]
    l += ["", "## Deroule (chaque appel au modele)", "",
          "| tour | tache | mode | duree | bloquants | notes |",
          "|---|---|---|---|---|---|"]
    for t in bilan.tours:
        notes = "; ".join(t.reparations + t.refus)[:300].replace("|", "/")
        l.append(f"| {t.numero} | {t.tache} | {t.mode or '—'} | "
                 f"{t.secondes:.0f} s | {t.bloquants} | {notes or '—'} |")
    l += ["", "## Ce qui reste a corriger", ""]
    restes = [d for d in bilan.defauts if d.gravite is GRAVITE.BLOQUANT]
    l += [f"- `{d.fichier}:{d.ligne}` {d.message} ({d.norme})"
          for d in restes] or ["- rien de bloquant"]
    if bilan.memoire or bilan.resolus:
        # La memoire de travail : rien n'est laisse sans sa raison.
        l += ["", "## Ma memoire de travail (pourquoi chaque probleme reste)",
              "", f"- {bilan.resolus} probleme(s) vu(s) puis resolu(s) en "
              "route"]
        l += [f"- {x}" for x in bilan.memoire]
    if bilan.conseil:
        # Le verdict du conseil des professeurs sur ce qui reste (sans
        # modele) : solutions, impertinences dejouees, reserves.
        l += ["", "## Ce que conclut le conseil des professeurs", "",
              "```", bilan.conseil, "```"]
    if bilan.logistique:
        l += ["", "## La logistique (rangement standard, fichiers ecrits "
              "par MAEL)", ""]
        l += [f"- {g.removeprefix('logistique : ')}" for g in bilan.logistique]
    if bilan.provisoires:
        l += ["", "## Images provisoires (a remplacer par les vraies)", ""]
        l += [f"- {p}" for p in bilan.provisoires]
    l += ["", "## Ce que je n'ai PAS pu verifier", ""]
    l += [f"- {x}" for x in bilan.limites] or ["- rien"]
    l += ["", "## Mes chiffres", "",
          f"- {m.appels} appel(s) au modele, {m.taches} tache(s), "
          f"{m.premier_coup} validee(s) du premier coup",
          f"- {m.reparations} reparation(s) faites sans le modele, "
          f"{m.retouches} retouche(s), {m.coupures} generation(s) coupee(s) "
          "ou fichier(s) hors tache", f"- {m.suppositions} supposition(s)",
          f"- {m.jugement / 60:.1f} min passees a juger"
          + (" ; specialistes : " + ", ".join(
              f"{k} {n} fois" for k, n in m.specialistes.items())
             if m.specialistes else "")]
    return "\n".join(l) + "\n"


def rapport(missions: list[Mission]) -> str:
    faites = [m for m in missions if m.etat in {"faite", "echec"}]
    conformes = sum(m.verdict == "CONFORME" for m in faites)
    sous_reserve = sum(m.verdict == "CONFORME" and bool(m.reserves)
                       for m in faites)
    taches = sum(m.taches for m in faites)
    premier = sum(m.premier_coup for m in faites)
    l = ["# Rapport des missions de MAEL", "",
         f"- Missions terminees : {len(faites)} / {len(missions)} — "
         f"conformes : {conformes}"
         + (f" (dont {sous_reserve} sous reserve)" if sous_reserve else ""),
         f"- Taches validees du premier coup : {premier} / {taches}"
         + (f" ({100 * premier / taches:.0f} %)" if taches else ""),
         f"- Duree totale : {sum(m.secondes for m in faites) / 60:.0f} min "
         f"— appels au modele : {sum(m.appels for m in faites)}", "",
         "| mission | etat | verdict | duree | appels | 1er coup | "
         "bloquants | coupures | suppositions |",
         "|---|---|---|---|---|---|---|---|---|"]
    for m in missions:
        l.append(f"| [{m.id}]({m.id}/{JOURNAL}) {m.titre} | {m.etat} | "
                 f"{verdict_dit(m) or '—'} | {m.secondes / 60:.1f} min | "
                 f"{m.appels} | {m.premier_coup}/{m.taches} | {m.bloquants} "
                 f"| {m.coupures} | {m.suppositions} |")
    return "\n".join(l) + "\n"


# ---------------------------------------------------------- l'execution
class Missions:
    def __init__(self, backend, racine: Path, fichier: Path, *,
                 savoir: Callable | None = None,
                 annoncer: Callable[[str], None] | None = None,
                 leviers: set[str] | None = None):
        self.backend = backend
        self.racine = Path(racine)
        self.fichier = Path(fichier)
        self.savoir = savoir
        self.annoncer = annoncer or (lambda _m: None)
        self.racine.mkdir(parents=True, exist_ok=True)
        # Sans liste imposee (la verification en impose une), MAEL applique
        # les lecons VALIDEES de ce dossier : ce qu'il a appris et prouve.
        self.leviers = (set(leviers) if leviers is not None else
                        retenus(self.racine / "lecons.yaml", {"validee"}))

    def _etat(self) -> dict:
        try:
            return json.loads((self.racine / ETAT_MISSIONS).read_text(
                encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _sauver(self, missions: list[Mission]):
        (self.racine / ETAT_MISSIONS).write_text(json.dumps(
            {m.id: asdict(m) for m in missions}, ensure_ascii=False,
            indent=1), encoding="utf-8")
        (self.racine / RAPPORT).write_text(rapport(missions),
                                           encoding="utf-8")

    def lancer(self) -> list[Mission]:
        missions = lire_missions(self.fichier)
        deja = self._etat()
        for m in missions:                 # reprendre l'etat enregistre
            if m.id in deja:
                for cle, valeur in deja[m.id].items():
                    if cle not in {"id", "titre", "demande", "attendu"}:
                        setattr(m, cle, valeur)
        pannes_de_suite = 0
        for i, m in enumerate(missions, 1):
            if m.etat in {"faite", "echec"}:
                continue
            self.annoncer(f"=== mission {i}/{len(missions)} : {m.id} — "
                          f"{m.titre} ===")
            self._une(m, missions)
            # Le moteur en panne n'est pas MAEL en echec : la mission sera
            # refaite a la relance. Trois de suite : on s'arrete au lieu de
            # brûler toute la serie (examen du 09/10 : 75 missions perdues).
            pannes_de_suite = pannes_de_suite + 1 if m.etat == "panne" else 0
            if pannes_de_suite >= PANNES_MAX:
                self.annoncer(f"ARRET : {PANNES_MAX} pannes du moteur de "
                              "suite. Relancez le moteur (ou la machine), puis "
                              "relancez : les missions en panne seront "
                              "refaites.")
                break
        return missions

    def _une(self, m: Mission, missions: list[Mission]):
        dossier = self.racine / m.id
        espace = Espace(dossier)
        chantier = Chantier(self.backend, espace, savoir=self.savoir,
                            annoncer=lambda x: self.annoncer(f"[{m.id}] {x}"),
                            leviers=self.leviers)
        m.etat = "en cours"
        m.debut = m.debut or time.strftime("%Y-%m-%d %H:%M")
        self._sauver(missions)
        debut = time.monotonic()
        bilan, erreur = None, ""
        try:
            sante = getattr(self.backend, "verifier_sante", None)
            if sante and sante(chantier.role) == "relance":
                self.annoncer(f"[{m.id}] sonde ratee : modele relance avant "
                              "la mission")
            if (dossier / ETAT).exists():
                bilan = chantier.reprendre()
            else:
                bilan = chantier.lancer(m.demande)
            mesurer(m, bilan, chantier.taches)
            m.etat = "faite"
        except MoteurEnPanne as exc:
            erreur = f"MoteurEnPanne : {exc}"
            m.etat, m.verdict = "panne", "PANNE DU MOTEUR (a refaire)"
        except Exception:                       # noqa: BLE001
            erreur = traceback.format_exc()
            m.etat, m.verdict = "echec", "ECHEC (plantage)"
        m.secondes += time.monotonic() - debut
        m.fin = time.strftime("%Y-%m-%d %H:%M")
        (dossier / JOURNAL).write_text(
            journal(m, bilan, chantier.taches, erreur), encoding="utf-8")
        self._sauver(missions)
        self.annoncer(f"[{m.id}] {m.verdict} en {m.secondes / 60:.1f} min "
                      f"— journal : {dossier / JOURNAL}")
