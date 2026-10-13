"""Les ANGLES MORTS de MAEL : ce qu'il n'a PAS pu verifier, et ses BESOINS.

Retour du responsable (08/10/2026), apres les 10 missions : les journaux
disent aussi ce que MAEL n'a pas pu lancer (php, javac, eslint, trivy...,
6 pages sur 8 jamais ouvertes dans le navigateur, un formulaire PHP « lu
mais non execute » dans une mission notee CONFORME). MAEL doit en prendre
conscience lui-meme, et dire ce dont il a besoin.

Sans modele, a partir de la section « Ce que je n'ai PAS pu verifier » de
chaque JOURNAL.md :

  - chaque manque est rattache a sa mission, et juge PERTINENT ou non :
    « php absent » ne compte que si la mission a des fichiers .php ;
  - BESOINS-DE-MAEL.md : ce qui lui manque (quoi, pourquoi, ce que ca
    change, comment l'installer, licence, ou le mettre), par priorite ; ce
    qui est absent mais sans effet ; ce qu'il a trouve sur la machine ;
  - ce qu'il peut corriger LUI-MEME (leviers « programme » du navigateur)
    devient une lecon proposee, verifiee ensuite comme les autres.

MAEL n'installe rien : il demande. Le responsable decide.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import leviers
from .emplacements import dossier_outils, trouver

BESOINS = "BESOINS-DE-MAEL.md"
_IGNORES = {".mael", "JOURNAL.md"}

# Ce que chaque outil verifie, et pour quels fichiers il compte.
MANIFESTES = {"requirements.txt", "package.json", "package-lock.json",
              "composer.json", "composer.lock", "pyproject.toml", "pom.xml"}
OUTILS = {
    "php": ({".php"}, "la syntaxe PHP reelle (php -l), au lieu d'un simple "
            "controle d'equilibre",
            "PHP portable pour Windows (« VS17 x64 Non Thread Safe », zip) "
            "depuis https://windows.php.net/download/ , decompresse dans "
            "{dossier}/php/", "PHP License 3.01"),
    "javac": ({".java"}, "la compilation Java reelle (javac)",
              "un JDK (par exemple Microsoft OpenJDK 17) ; son dossier bin "
              "dans le PATH, ou dans {dossier}/bin/", "GPLv2 + Classpath"),
    "eslint": ({".js", ".mjs"}, "un second avis sur les scripts (eval, "
               "fonctions redefinies...) : le vote croise avec mes juges",
               "npm install --prefix {dossier} eslint", "MIT"),
    "html-validate": ({".html", ".htm"}, "un second avis sur les pages HTML "
                      "et leur accessibilite", "npm install --prefix "
                      "{dossier} html-validate", "MIT"),
    "stylelint": ({".css"}, "un second avis sur les feuilles de style",
                  "npm install --prefix {dossier} stylelint", "MIT"),
    "gitleaks": ({"*"}, "les secrets oublies dans le code (cles, mots de "
                 "passe)", "gitleaks_<version>_windows_x64.zip depuis "
                 "https://github.com/gitleaks/gitleaks/releases , "
                 "gitleaks.exe dans {dossier}/bin/", "MIT"),
    "trivy": (MANIFESTES, "les failles connues des dependances (CVE)",
              "trivy_<version>_windows-64bit.zip depuis "
              "https://github.com/aquasecurity/trivy/releases , trivy.exe "
              "dans {dossier}/bin/, puis une fois : trivy fs "
              "--download-db-only (base des failles)", "Apache-2.0"),
}


@dataclass
class AngleMort:
    mission: str
    genre: str          # outil-absent | page-expiree | pages-hors-budget |
    #                     code-non-execute | tests-non-executes | navigateur
    objet: str          # l'outil, la page, le fichier
    detail: str         # la ligne du journal
    pertinent: bool = True


@dataclass
class Besoin:
    outil: str
    missions: list[str] = field(default_factory=list)
    sans_effet: list[str] = field(default_factory=list)
    fichiers: int = 0


def _section(texte: str) -> list[str]:
    m = re.search(r"## Ce que je n'ai PAS pu verifier\n(.*?)(?:\n## |\Z)",
                  texte, re.S)
    return [l[2:].strip() for l in (m.group(1) if m else "").splitlines()
            if l.startswith("- ")]


def _fichiers(dossier: Path) -> list[str]:
    if not dossier.is_dir():
        return []
    return [p.relative_to(dossier).as_posix() for p in dossier.rglob("*")
            if p.is_file() and not set(p.relative_to(dossier).parts)
            & _IGNORES]


def pertinent(outil: str, fichiers: list[str]) -> int:
    """Combien de fichiers de la mission cet outil aurait verifies."""
    exts = OUTILS.get(outil, ({"*"},))[0]
    if "*" in exts:
        return len(fichiers)
    return sum(1 for f in fichiers
               if Path(f).suffix.lower() in exts or Path(f).name in exts)


def lire_journal(texte: str, mission: str, fichiers: list[str]
                 ) -> list[AngleMort]:
    out = []
    for l in _section(texte):
        m = re.match(r"outils externes absents \(non lances\) : (.+)$", l)
        if m:
            for o in (x.strip() for x in m.group(1).split(",")):
                out.append(AngleMort(mission, "outil-absent", o, l,
                                     pertinent(o, fichiers) > 0))
            continue
        m = re.match(r"(PHP|Java) : syntaxe .*\((php|javac) absent\)", l)
        if m:
            o = m.group(2)
            out.append(AngleMort(mission, "outil-absent", o, l,
                                 pertinent(o, fichiers) > 0))
            continue
        m = re.match(r"pages NON ouvertes .*: (.+)$", l)
        if m:
            for p in m.group(1).split(", "):
                out.append(AngleMort(mission, "page-expiree",
                                     p.split(" (")[0], l))
            continue
        m = re.match(r"(\d+) page\(s\) non ouverte\(s\) : budget", l)
        if m:
            out.append(AngleMort(mission, "pages-hors-budget",
                                 f"{m.group(1)} page(s)", l))
            continue
        m = re.match(r"code serveur LU mais non execute.*: (.+)$", l)
        if m:
            for f in m.group(1).split(", "):
                out.append(AngleMort(mission, "code-non-execute", f.strip(),
                                     l))
            continue
        m = re.match(r"dependance absente sur la machine : (?:extension "
                     r"PHP )?(\S+)", l)
        if m:
            out.append(AngleMort(mission, "dependance-absente", m.group(1),
                                 l))
            continue
        if l.startswith(("savoir-faire perime", "savoir-faire :")):
            out.append(AngleMort(mission, "savoir-perime", l.split(":")[1]
                                 .strip()[:60], l))
            continue
        if l.startswith("tests NON executes"):
            out.append(AngleMort(mission, "tests-non-executes", "pytest", l))
        elif l.startswith(("navigateur non lance", "couche 6 EN PANNE")):
            out.append(AngleMort(mission, "navigateur", "chromium", l))
    return out


def relever(racine: Path, missions: list[str]) -> list[AngleMort]:
    out = []
    for mid in missions:
        dossier = Path(racine) / mid
        try:
            texte = (dossier / "JOURNAL.md").read_text(encoding="utf-8")
        except OSError:
            continue
        out += lire_journal(texte, mid, _fichiers(dossier))
    return out


def besoins(angles: list[AngleMort], racine: Path) -> list[Besoin]:
    par: dict[str, Besoin] = {}
    for a in angles:
        if a.genre == "outil-absent":
            b = par.setdefault(a.objet, Besoin(a.objet))
            cible = b.missions if a.pertinent else b.sans_effet
            if a.mission not in cible:
                cible.append(a.mission)
                if a.pertinent:
                    b.fichiers += pertinent(a.objet, _fichiers(
                        Path(racine) / a.mission))
        elif (a.genre == "code-non-execute" and a.objet.endswith(".php")
              and (Path(racine) / a.mission / a.objet).is_file()):
            b = par.setdefault("php", Besoin("php"))
            if a.mission not in b.missions:
                b.missions.append(a.mission)
    for b in par.values():
        b.sans_effet = [m for m in b.sans_effet if m not in b.missions]
    return sorted(par.values(), key=lambda b: (-len(b.missions), b.outil))


# Ce que MAEL corrige lui-meme : genre d'angle mort -> levier « programme ».
CORRIGEABLES = {"page-expiree": "reessayer-page-expiree",
                "pages-hors-budget": "budget-selon-les-pages"}


def rediger(racine: Path, missions: list[str]) -> tuple[str, list[AngleMort]]:
    racine = Path(racine)
    angles = relever(racine, missions)
    bs = besoins(angles, racine)
    dossier = dossier_outils()
    l = ["# Mes besoins — ce que je n'ai PAS pu verifier", "",
         f"- Relu le {time.strftime('%Y-%m-%d %H:%M')} : {len(missions)} "
         f"mission(s), {len(angles)} angle(s) mort(s) dans mes journaux",
         f"- Mon dossier d'outils : `{dossier}` (je cherche aussi le PATH) ;"
         " je n'installe rien moi-meme : c'est au responsable de decider.",
         ""]
    trouves = [(b, trouver(b.outil)) for b in bs]
    manquent = [b for b, ch in trouves if not ch and b.missions]
    l += ["## Ce qui me manque (a installer), par priorite", ""]
    if not manquent:
        l += ["- rien : tout ce qui comptait est la", ""]
    for b in manquent:
        exts, sert, comment, licence = OUTILS.get(
            b.outil, (set(), "", "(a preciser)", "?"))
        l += [f"### {b.outil} — {len(b.missions)} mission(s) concernee(s)",
              "",
              f"- **Ce que je n'ai pas pu verifier** : {sert}, sur "
              f"{b.fichiers} fichier(s) ({', '.join(b.missions)})",
              f"- **Comment** : {comment.format(dossier=dossier)}",
              f"- **Licence** : {licence}", ""]
    trouve = [(b, ch) for b, ch in trouves if ch]
    if trouve:
        l += ["## Deja sur la machine (je le trouve desormais)", ""]
        l += [f"- `{b.outil}` : {ch}" for b, ch in trouve]
        l += [""]
    inutiles = [b for b, ch in trouves if not ch and not b.missions]
    if inutiles:
        l += ["## Absents, mais sans effet sur ces missions", ""]
        l += [f"- `{b.outil}` : aucun fichier concerne dans "
              f"{', '.join(b.sans_effet)}" for b in inutiles]
        l += [""]
    reserves = [a for a in angles
                if a.genre in {"code-non-execute", "tests-non-executes"}]
    if reserves:
        l += ["## Verdicts SOUS RESERVE (du code jamais execute)", ""]
        l += [f"- mission {a.mission} : {a.objet} — {a.detail}"
              for a in reserves]
        l += [""]
    deps = {}
    for a in angles:
        if a.genre == "dependance-absente":
            deps.setdefault(a.detail, []).append(a.mission)
    if deps:
        l += ["## Dependances absentes sur la machine (pour mes taches)", ""]
        l += [f"- {d} — missions : {', '.join(sorted(set(ms)))}"
              for d, ms in deps.items()]
        l += [""]
    l += _section_savoir()
    corr = [a for a in angles if a.genre in CORRIGEABLES]
    if corr:
        l += ["## Ce que je corrige moi-meme (lecons proposees, a verifier)",
              ""]
        for genre, levier in CORRIGEABLES.items():
            vus = [a for a in corr if a.genre == genre]
            if vus:
                l.append(f"- `{levier}` : "
                         + leviers.PAR_ID[levier].action + " — vu dans "
                         + ", ".join(f"{a.mission} ({a.objet})" for a in vus))
        l += [""]
    (racine / BESOINS).write_text("\n".join(l), encoding="utf-8")
    return "\n".join(l), angles


def _section_savoir() -> list[str]:
    """La fraicheur de mon savoir-faire : un savoir perime est un probleme
    (consigne du responsable), meme sans mission qui l'ait vu."""
    from . import fraicheur, savoir_faire
    releve = fraicheur.charger()
    problemes = fraicheur.problemes_hors_ligne(releve)
    problemes += [f"fiche {f.id} perimee : {r}" for f in savoir_faire.toutes()
                  if (r := savoir_faire.perimee(f, releve))]
    l = ["## Mon savoir-faire : est-il recent ?", ""]
    if releve.date:
        l.append(f"- derniere verification en ligne : {releve.date} "
                 f"({len(savoir_faire.toutes())} fiches)")
    if problemes:
        l += [f"- PROBLEME : {p}" for p in problemes]
    else:
        l.append("- a jour : aucune fiche perimee, aucune dependance en "
                 "retard")
    return l + [""]


def vues(racine: Path, missions: list[str]) -> dict[tuple[str, str], int]:
    """(genre, mission) -> nombre : pour verifier les leviers du navigateur
    comme les autres (avant / apres)."""
    compte: dict[tuple[str, str], int] = {}
    for a in relever(racine, missions):
        compte[(a.genre, a.mission)] = compte.get((a.genre, a.mission),
                                                  0) + 1
    return compte
