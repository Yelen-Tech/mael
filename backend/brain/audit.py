"""`mael audit <dossier>` : l'audit de securite d'un DEPOT, en une commande
(13/10/2026).

Trois regards, un seul rapport :
  1. SECRETS oublies           gitleaks (conteneur, valeurs MASQUEES)
  2. DEPENDANCES et CONFIG     Trivy « fs » (CVE des dependances declarees,
                               erreurs de Dockerfile/Kubernetes/Terraform)
  3. CODE                      les juges de MAEL, regles de securite
                               seulement (injections, XSS, secret en dur,
                               hachage faible, CSRF, CORS, Bandit...)

Regle de MAEL : un regard qui n'a PAS pu se faire (Docker absent, base
Trivy non preparee) est ECRIT dans le rapport comme « non verifie » — il
ne devient jamais « rien trouve ». Le code de sortie le dit aussi (2), pour
l'integration continue :
  0  rien d'eleve ni de critique
  1  au moins un constat eleve ou critique (ou bloquant cote code)
  2  audit incomplet (un regard n'a pas tourne)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ORDRE = ["critique", "elevee", "moyenne", "faible", "info"]

# Regles des juges de code qui relevent de la SECURITE (le reste — qualite,
# accessibilite, coherence — n'a pas sa place dans un audit de securite).
REGLES_SECURITE = {
    "injection-sql", "injection-commande", "injection-code", "xss-serveur",
    "nosql-injection", "nosql-where", "secret-en-dur", "hash-faible",
    "csrf-desactive", "cors-ouvert", "redirection-ouverte", "debug-actif",
    "py-dangereux", "sql-execution"}


@dataclass
class Constat:
    regard: str                 # secrets | dependances | code
    gravite: str                # critique .. info
    titre: str
    fichier: str = ""
    ligne: int | None = None
    detail: str = ""


@dataclass
class Rapport:
    dossier: Path
    constats: list[Constat] = field(default_factory=list)
    non_verifie: dict[str, str] = field(default_factory=dict)   # regard -> pourquoi
    lus: list[str] = field(default_factory=list)
    duree_s: float = 0.0

    def compte(self, gravite: str) -> int:
        return sum(1 for c in self.constats if c.gravite == gravite)

    @property
    def code_sortie(self) -> int:
        if self.compte("critique") or self.compte("elevee"):
            return 1
        return 2 if self.non_verifie else 0


def _gravite_code(d) -> str:
    """Un defaut BLOQUANT des juges vaut « elevee » ; un conseil, « faible »."""
    return "elevee" if d.gravite.value == "bloquant" else "faible"


def est_securite(d) -> bool:
    return (d.regle in REGLES_SECURITE or d.regle.startswith("bandit")
            or d.regle.startswith("ruff:S") or "bandit" in d.sources)


def regard_code(dossier: Path) -> list[Constat]:
    from brain.codage import juges
    defauts, _ = juges.juger_projet(dossier, outils_externes=True,
                                    executer=False)
    return [Constat("code", _gravite_code(d), d.message.split(" [")[0][:200],
                    d.fichier, d.ligne, f"{d.regle} — {d.norme}")
            for d in defauts if est_securite(d)]


def regard_outil(nom: str, regard: str, dossier: Path, rapport: Rapport
                 ) -> list[Constat]:
    from brain.tools import registre
    from brain.tools.base import OutilEchoue, OutilRefuse
    try:
        obs = registre[nom].executer(organisation=None,
                                     cible=str(dossier.resolve()))
    except (OutilEchoue, OutilRefuse) as e:
        rapport.non_verifie[regard] = str(e)[:300]
        return []
    out = []
    for c in obs.constats:
        d = c.get("details") or {}
        if c.get("code") == "depot.lu":
            rapport.lus = d.get("fichiers") or []
            continue
        correction = (f"corrige en {d['corrigee_en']}" if d.get("corrigee_en")
                      else d.get("correction") or "")
        if regard == "secrets" and not correction:
            correction = ("revoquer ce secret, puis le lire depuis "
                          "l'environnement ; il reste dans l'historique git")
        out.append(Constat(regard, c.get("gravite", "info"),
                           c.get("resume", ""), str(d.get("fichier") or ""),
                           d.get("ligne"), correction))
    return out


def auditer(dossier: Path, regards: tuple[str, ...] = ("secrets",
            "dependances", "code"), docker_ok=None) -> Rapport:
    import time
    debut = time.monotonic()
    dossier = Path(dossier)
    r = Rapport(dossier)
    if docker_ok is None:
        docker_ok = docker_disponible
    conteneurs = [g for g in ("secrets", "dependances") if g in regards]
    pourquoi = docker_ok() if conteneurs else ""
    for g in conteneurs:
        if pourquoi:
            r.non_verifie[g] = pourquoi
        else:
            r.constats += regard_outil(
                {"secrets": "secrets_exposes",
                 "dependances": "failles_depot"}[g], g, dossier, r)
    if "code" in regards:
        try:
            r.constats += regard_code(dossier)
        except Exception as e:                       # noqa: BLE001
            r.non_verifie["code"] = f"{type(e).__name__} : {e}"[:300]
    r.constats.sort(key=lambda c: (ORDRE.index(c.gravite)
                                   if c.gravite in ORDRE else 9,
                                   c.regard, c.fichier, c.ligne or 0))
    r.duree_s = round(time.monotonic() - debut, 1)
    return r


def docker_disponible() -> str:
    """'' si Docker repond ; sinon la phrase a dire. `docker version` (0,7 s)
    et non `docker info` (65 s sur le portable, 09/10)."""
    import subprocess
    try:
        p = subprocess.run(["docker", "version", "--format",
                            "{{.Server.Version}}"], capture_output=True,
                           text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "Docker absent : installer Docker, puis relancer"
    if p.returncode != 0:
        return "Docker ne repond pas : demarrer Docker Desktop, puis relancer"
    return ""


NOMS = {"secrets": "Secrets oublies (gitleaks)",
        "dependances": "Dependances et configuration (Trivy)",
        "code": "Code (juges de MAEL, regles de securite)"}


def en_markdown(r: Rapport) -> str:
    l = [f"# Audit de securite — {r.dossier.name}", "",
         f"Date : {datetime.now():%d/%m/%Y %H:%M} · duree {r.duree_s} s · "
         f"MAEL", ""]
    synthese = ", ".join(f"{r.compte(g)} {g}" for g in ORDRE if r.compte(g))
    l += ["## Synthese", "", f"- Constats : {synthese or 'aucun'}"]
    if r.non_verifie:
        l.append("- **AUDIT INCOMPLET** — non verifie : "
                 + ", ".join(NOMS[g] for g in r.non_verifie))
    l.append("")
    for g in ("secrets", "dependances", "code"):
        l += [f"## {NOMS[g]}", ""]
        if g in r.non_verifie:
            l += [f"**Non verifie** : {r.non_verifie[g]}", "",
                  "Ce n'est PAS « rien trouve ».", ""]
            continue
        cs = [c for c in r.constats if c.regard == g]
        if g == "dependances" and r.lus:
            l += [f"Fichiers lus : {', '.join(r.lus[:15])}", ""]
        elif g == "dependances":
            l += ["Aucun fichier de dependances ni de configuration reconnu.",
                  ""]
        if not cs:
            l += ["Rien trouve.", ""]
            continue
        l += ["| Gravite | Ou | Constat | Correction ou regle |", "|---|---|---|---|"]
        for c in cs:
            ou = f"{c.fichier}:{c.ligne}" if c.ligne else c.fichier or "-"
            l.append(f"| {c.gravite} | `{ou}` | {_cellule(c.titre)} | "
                     f"{_cellule(c.detail)} |")
        l.append("")
    l += ["---", "Les valeurs des secrets ne sont jamais recopiees (gitleaks "
          "--redact). Base de failles : hors ligne, preparee par "
          "`python -m brain.tools --preparer`."]
    return "\n".join(l) + "\n"


def _cellule(t: str) -> str:
    return (t or "").replace("|", "\\|").replace("\n", " ")[:220]


def resume_humain(r: Rapport, chemin: Path, n: int = 8) -> str:
    """Ce que le terminal affiche apres /audit."""
    l = ["", "  Audit : " + (", ".join(f"{r.compte(g)} {g}" for g in ORDRE
                                      if r.compte(g)) or "aucun constat")]
    for g, pourquoi in r.non_verifie.items():
        l.append(f"  NON VERIFIE — {NOMS[g]} : {pourquoi}")
    for c in r.constats[:n]:
        ou = f"{c.fichier}:{c.ligne}" if c.ligne else c.fichier or "-"
        l.append(f"  [{c.gravite}] {ou} — {c.titre[:90]}")
    if len(r.constats) > n:
        l.append(f"  ... et {len(r.constats) - n} de plus")
    l.append(f"  Rapport complet : {chemin}")
    return "\n".join(l)


def question(r: Rapport, n: int = 12) -> str:
    """La demande faite au modele : expliquer et prioriser CES constats,
    mesures par le code — jamais en ajouter. '' s'il n'y a rien a dire."""
    if not r.constats and not r.non_verifie:
        return ""
    l = ["[audit du depot — resultats MESURES par le code (gitleaks, Trivy, "
         "juges de MAEL). N'ajoute aucun constat absent de cette liste.]"]
    for c in r.constats[:n]:
        ou = f"{c.fichier}:{c.ligne}" if c.ligne else c.fichier or "-"
        l.append(f"- [{c.gravite}] {ou} : {c.titre[:120]}"
                 + (f" ({c.detail[:80]})" if c.detail else ""))
    if len(r.constats) > n:
        l.append(f"- ... {len(r.constats) - n} constats de plus, moins graves")
    for g, pourquoi in r.non_verifie.items():
        l.append(f"- NON VERIFIE : {NOMS[g]} ({pourquoi})")
    l.append("Explique en francais les 3 priorites, dans l'ordre, et pour "
             "chacune la premiere action concrete. Si une partie n'a pas ete "
             "verifiee, dis-le.")
    return "\n".join(l)
