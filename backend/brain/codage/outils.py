"""Couche 5 : des outils libres reconnus, comme juges supplementaires.

Regles de cette couche (doc 15) :
  - on n'utilise QUE ce qui est installe : aucun telechargement, aucun
    reseau. Absent = dit dans le bilan, jamais « rien a signaler » ;
  - licences compatibles avec un produit vendu : ruff (MIT), bandit
    (Apache 2.0), eslint (MIT), gitleaks (MIT), html-validate (MIT),
    stylelint (MIT), Trivy (Apache 2.0). Semgrep est ecarte tant que la
    licence de ses regles officielles n'est pas tranchee ;
  - chaque outil lit en JSON (jamais du texte a deviner) ; une sortie
    illisible = outil « en panne », pas « propre » ;
  - VOTE CROISE : un defaut vu par MAEL ET par un outil, au meme endroit et
    de la meme famille, devient « certain ». Vu par un seul : « probable ».

Chaque adaptateur a deux moitiés : `commande(...)` (ce qu'on lance) et
`lire(...)` (ce qu'on comprend de la sortie). `lire` est une fonction pure :
elle se teste sans l'outil, sur une sortie enregistree.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from .emplacements import trouver
from .juges import GRAVITE, Defaut

B, C = GRAVITE.BLOQUANT, GRAVITE.CONSEIL
DELAI = 120   # secondes par outil : une machine sans GPU est lente
CONFIGS = Path(__file__).parent / "configs"


# ----------------------------------------------------------- familles
# Code d'un outil -> famille MAEL. Sert au vote croise : deux temoins ne
# comptent que s'ils parlent de la MEME chose.
FAMILLES = {
    # ruff (regles S = celles de bandit) et bandit
    "S102": "py-dangereux", "B102": "py-dangereux",            # exec
    "S307": "py-dangereux", "B307": "py-dangereux",            # eval
    "S301": "py-dangereux", "B301": "py-dangereux",            # pickle
    "S506": "py-dangereux", "B506": "py-dangereux",            # yaml.load
    "S501": "py-dangereux", "B501": "py-dangereux",            # verify=False
    "S602": "py-dangereux", "B602": "py-dangereux",            # shell=True
    "S605": "py-dangereux", "B605": "py-dangereux",            # os.system
    "S201": "py-dangereux", "B201": "py-dangereux",            # debug=True
    "S306": "py-dangereux", "B306": "py-dangereux",            # mktemp
    "S324": "hash-faible", "B324": "hash-faible",
    "S311": "hasard-faible", "B311": "hasard-faible",
    "S608": "injection-sql", "B608": "injection-sql",
    "S105": "secret-en-dur", "S106": "secret-en-dur", "S107": "secret-en-dur",
    "B105": "secret-en-dur", "B106": "secret-en-dur", "B107": "secret-en-dur",
    "S704": "xss-serveur", "B703": "xss-serveur", "B308": "xss-serveur",
    "E999": "py-syntaxe",
    # eslint (regles de base, configuration embarquee)
    "no-eval": "js-dangereux", "no-implied-eval": "js-dangereux",
    "no-new-func": "js-dangereux", "no-script-url": "href-javascript",
    "eslint-syntaxe": "js-syntaxe",
    # html-validate
    "wcag/h37": "img-alt", "input-missing-label": "champ-sans-label",
    "missing-doctype": "doctype", "element-required-attributes": "lang",
    "no-dup-id": "id-duplique", "close-order": "balise-non-fermee",
    "text-content": "nom-accessible", "no-inline-style": "",
    "require-sri": "sri", "prefer-button": "button-type",
    # stylelint
    "CssSyntaxError": "css-accolade",
}
# Codes qui bloquent (les autres sont des conseils). On reste prudent : un
# outil externe qui bloque a tort ferait tourner l'atelier pour rien.
BLOQUANTS = {
    "S102", "S307", "S301", "S506", "S501", "S602", "S605", "S201", "S306",
    "S608", "S105", "S106", "S107", "S704", "E999", "F821", "F811", "F823",
    "B102", "B307", "B301", "B506", "B501", "B602", "B605", "B201", "B306",
    "B608", "B105", "B106", "B107", "B703",
    "no-eval", "no-implied-eval", "no-new-func", "no-script-url",
    "eslint-syntaxe", "wcag/h37", "input-missing-label", "missing-doctype",
    "no-dup-id", "close-order", "CssSyntaxError", "gitleaks",
}
NORMES = {
    "ruff": "ruff", "bandit": "bandit (OWASP)", "eslint": "eslint",
    "gitleaks": "gitleaks — OWASP A07 / CWE-798",
    "html-validate": "html-validate (W3C / WCAG)", "stylelint": "stylelint",
    "trivy": "Trivy — dependance vulnerable (OWASP A06)",
}


@dataclass
class Outil:
    nom: str
    licence: str
    extensions: set[str]
    executable: Callable[[], list[str] | None]
    commande: Callable[[list[str], Path, list[str]], list[str]]
    lire: Callable[[str, Path], list[Defaut]]
    codes_sortie_ok: set[int] = field(default_factory=lambda: {0, 1})
    entree: Callable[[Path, list[str]], str | None] | None = None


def _dans_le_path(nom: str) -> Callable[[], list[str] | None]:
    """Le PATH, puis le dossier d'outils de MAEL (emplacements.py)."""
    def chercher():
        chemin = trouver(nom)
        return [chemin] if chemin else None
    return chercher


def _module_python(module: str, fallback: str) -> Callable[[], list[str] | None]:
    """ruff/bandit installes comme commande OU comme module du venv."""
    def trouver():
        chemin = shutil.which(fallback)
        if chemin:
            return [chemin]
        try:
            import importlib.util
            if importlib.util.find_spec(module):
                return [sys.executable, "-m", module]
        except (ImportError, ValueError):
            pass
        return None
    return trouver


def _rel(racine: Path, chemin: str) -> str:
    p = Path(chemin)
    try:
        return (p if p.is_absolute() else (racine / p)).resolve() \
            .relative_to(racine.resolve()).as_posix()
    except ValueError:
        return Path(chemin).as_posix()


def _defaut(outil: str, fichier: str, ligne, code: str, message: str
            ) -> Defaut:
    famille = FAMILLES.get(code, "") or f"{outil}:{code}"
    return Defaut(fichier, int(ligne or 1), famille,
                  B if code in BLOQUANTS else C,
                  f"{message} [{outil} {code}]", NORMES.get(outil, outil),
                  sources=(outil,))


# ---------------------------------------------------------- adaptateurs
def lire_ruff(sortie: str, racine: Path) -> list[Defaut]:
    d = []
    for x in json.loads(sortie or "[]"):
        code = x.get("code") or "E999"      # null = erreur de syntaxe
        d.append(_defaut("ruff", _rel(racine, x["filename"]),
                         (x.get("location") or {}).get("row", 1), code,
                         x.get("message", "")))
    return d


def lire_bandit(sortie: str, racine: Path) -> list[Defaut]:
    d = []
    for x in json.loads(sortie or "{}").get("results", []):
        code = x.get("test_id", "B000")
        defaut = _defaut("bandit", _rel(racine, x["filename"]),
                         x.get("line_number", 1), code,
                         x.get("issue_text", ""))
        # bandit dit lui-meme sa confiance : faible = conseil, toujours.
        if x.get("issue_confidence") == "LOW":
            defaut = replace(defaut, gravite=C)
        d.append(defaut)
    return d


def lire_eslint(sortie: str, racine: Path) -> list[Defaut]:
    d = []
    for f in json.loads(sortie or "[]"):
        for m in f.get("messages", []):
            code = m.get("ruleId") or "eslint-syntaxe"   # null = syntaxe
            d.append(_defaut("eslint", _rel(racine, f["filePath"]),
                             m.get("line", 1), code, m.get("message", "")))
    return d


def lire_gitleaks(sortie: str, racine: Path) -> list[Defaut]:
    d = []
    for x in json.loads(sortie or "[]") or []:
        d.append(Defaut(_rel(racine, x.get("File", "")),
                        int(x.get("StartLine", 1)), "secret-en-dur", B,
                        f"secret detecte ({x.get('Description') or x.get('RuleID')}) "
                        "[gitleaks]", NORMES["gitleaks"],
                        sources=("gitleaks",)))
    return d


def lire_html_validate(sortie: str, racine: Path) -> list[Defaut]:
    d = []
    for f in json.loads(sortie or "[]"):
        for m in f.get("messages", []):
            code = m.get("ruleId", "html")
            defaut = _defaut("html-validate", _rel(racine, f["filePath"]),
                             m.get("line", 1), code, m.get("message", ""))
            if m.get("severity", 2) < 2:
                defaut = replace(defaut, gravite=C)
            d.append(defaut)
    return d


def lire_stylelint(sortie: str, racine: Path) -> list[Defaut]:
    d = []
    for f in json.loads(sortie or "[]"):
        for m in f.get("warnings", []):
            code = m.get("rule", "stylelint")
            texte = (m.get("text") or "").rsplit(" (", 1)[0]
            defaut = _defaut("stylelint", _rel(racine, f["source"]),
                             m.get("line", 1), code, texte)
            if m.get("severity") == "warning" and code not in BLOQUANTS:
                defaut = replace(defaut, gravite=C)
            d.append(defaut)
    return d


def lire_trivy(sortie: str, racine: Path) -> list[Defaut]:
    d = []
    for r in json.loads(sortie or "{}").get("Results", []) or []:
        for v in r.get("Vulnerabilities", []) or []:
            grave = v.get("Severity") in {"CRITICAL", "HIGH"}
            correctif = v.get("FixedVersion")
            d.append(Defaut(
                _rel(racine, r.get("Target", "")), 1, "dependance-vulnerable",
                B if grave else C,
                f"{v.get('PkgName')} {v.get('InstalledVersion')} : "
                f"{v.get('VulnerabilityID')} ({v.get('Severity')})"
                + (f", corrige en {correctif}" if correctif else
                   ", pas encore de correctif") + " [trivy]",
                NORMES["trivy"], sources=("trivy",)))
    return d


def _fichiers(racine: Path, vus: list[str], exts: set[str]) -> list[str]:
    return [str(racine / f) for f in vus if Path(f).suffix.lower() in exts]


OUTILS = [
    Outil("ruff", "MIT", {".py"}, _module_python("ruff", "ruff"),
          lambda exe, r, f: [*exe, "check", "--output-format", "json",
                             "--no-cache", "--isolated",
                             "--select", "E9,F,B,S", "--exit-zero", *f],
          lire_ruff, {0}),
    Outil("bandit", "Apache-2.0", {".py"}, _module_python("bandit", "bandit"),
          lambda exe, r, f: [*exe, "-f", "json", "-q", *f], lire_bandit),
    Outil("eslint", "MIT", {".js", ".mjs"}, _dans_le_path("eslint"),
          lambda exe, r, f: [*exe, "--format", "json", "--no-config-lookup",
                             "--config", str(CONFIGS / "eslint.config.mjs"),
                             *f],
          lire_eslint),
    Outil("html-validate", "MIT", {".html", ".htm"},
          _dans_le_path("html-validate"),
          lambda exe, r, f: [*exe, "--formatter", "json", "--config",
                             str(CONFIGS / "html-validate.json"), *f],
          lire_html_validate),
    Outil("stylelint", "MIT", {".css"}, _dans_le_path("stylelint"),
          lambda exe, r, f: [*exe, "--formatter", "json", "--config",
                             str(CONFIGS / "stylelint.json"), *f],
          lire_stylelint, {0, 2}),
    Outil("gitleaks", "MIT", {"*"}, _dans_le_path("gitleaks"),
          lambda exe, r, f: [*exe, "dir", str(r), "--no-banner",
                             "--report-format", "json", "--report-path", "-",
                             "--exit-code", "0"],
          lire_gitleaks, {0}),
    Outil("trivy", "Apache-2.0", {"*"}, _dans_le_path("trivy"),
          lambda exe, r, f: [*exe, "fs", "--offline-scan", "--skip-db-update",
                             "--scanners", "vuln", "--format", "json",
                             "--quiet", str(r)],
          lire_trivy, {0}),
]


@dataclass
class Rapport:
    """Ce que la couche 5 a fait, pour le bilan : rien n'est cache."""
    lances: list[str] = field(default_factory=list)
    absents: list[str] = field(default_factory=list)
    en_panne: list[str] = field(default_factory=list)


dernier_rapport = Rapport()


def juger(racine: Path, vus: list[str],
          seulement: set[str] | frozenset[str] | None = None
          ) -> list[Defaut]:
    """Lance chaque outil installe concerne par les fichiers du projet.
    `seulement` : les outils d'un specialiste (specialistes.py) ; les autres
    ne sont ni lances ni comptes absents."""
    global dernier_rapport
    rapport = Rapport()
    racine = Path(racine)
    defauts: list[Defaut] = []
    if os.environ.get("MAEL_SANS_OUTILS") == "1":   # banc de mesure, tests
        dernier_rapport = rapport
        return []
    for o in OUTILS:
        if seulement is not None and o.nom not in seulement:
            continue
        fichiers = (_fichiers(racine, vus, o.extensions)
                    if "*" not in o.extensions else [str(racine)])
        if not fichiers:
            continue
        exe = o.executable()
        if not exe:
            rapport.absents.append(o.nom)
            continue
        try:
            r = subprocess.run(o.commande(exe, racine, fichiers),
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=DELAI, cwd=racine)
            if r.returncode not in o.codes_sortie_ok:
                raise RuntimeError(f"code de sortie {r.returncode}")
            defauts += o.lire(r.stdout, racine)
            rapport.lances.append(o.nom)
        except (OSError, subprocess.TimeoutExpired, RuntimeError,
                json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            rapport.en_panne.append(f"{o.nom} ({type(exc).__name__})")
    dernier_rapport = rapport
    # gitleaks et trivy parcourent tout le dossier : les sauvegardes de MAEL
    # (.mael/), node_modules ou venv ne sont pas le code de l'utilisateur.
    from .juges import DOSSIERS_IGNORES
    return [d for d in defauts
            if not set(Path(d.fichier).parts) & DOSSIERS_IGNORES]


def fusionner(mael: list[Defaut], externes: list[Defaut],
              tolerance: int = 1) -> list[Defaut]:
    """Vote croise. Un defaut externe de la MEME famille, dans le meme
    fichier, a +/- `tolerance` ligne d'un defaut MAEL, n'est pas ajoute :
    il devient un second temoin du defaut MAEL, qui passe « certain ».
    Les autres defauts externes sont ajoutes tels quels (« probables »)."""
    resultat = list(mael)
    for x in externes:
        for i, m in enumerate(resultat):
            if (m.fichier == x.fichier and m.regle == x.regle
                    and abs(m.ligne - x.ligne) <= tolerance):
                if x.sources[0] not in m.sources:
                    resultat[i] = replace(m, sources=(*m.sources, *x.sources),
                                          gravite=(B if B in (m.gravite,
                                                              x.gravite)
                                                   else C))
                break
        else:
            resultat.append(x)
    return resultat


def limites() -> list[str]:
    l = []
    r = dernier_rapport
    if r.lances:
        l.append("outils externes lances : " + ", ".join(r.lances))
    if r.absents:
        l.append("outils externes absents (non lances) : "
                 + ", ".join(r.absents))
    if r.en_panne:
        l.append("outils externes EN PANNE (leurs verdicts manquent) : "
                 + ", ".join(r.en_panne))
    return l
