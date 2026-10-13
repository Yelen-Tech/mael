"""Les CONTRATS du projet : ce qui est deja etabli, releve par MAEL.

Chantier par etapes (09/10/2026, feuille de route « agent autonome ») : un
grand projet se construit en plusieurs etapes ; l'etape 4 (les pages) doit
appeler les routes que l'etape 2 (l'API) a vraiment ecrites, avec les
colonnes que l'etape 1 (la base) a vraiment creees. Un petit modele ne s'en
souvient pas — et ne relit pas 40 fichiers. MAEL, lui, RELEVE les faits
apres chaque etape, par lecture, et les donne a l'etape suivante :

  - les tables et leurs colonnes (schema SQL ou modeles d'ORM) ;
  - les routes du serveur (methode + chemin : Flask, FastAPI, Express) ;
  - les pages et leurs id (ce que les scripts peuvent viser) ;
  - les variables d'environnement lues ;
  - les modules du code et ce qu'ils definissent (classes, fonctions).
Les juges verifient ensuite que le nouveau code les respecte (contrat-api,
sql-table-inconnue, orm-champ-inconnu...). Rien n'est invente : un contrat
est ce qui est ECRIT dans le projet.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

_ROUTE_PY = re.compile(r"""@\w+\.(get|post|put|patch|delete|route|"""
                       r"""api_route)\(\s*['"](/[^'"]*)['"](.*)""")
_ROUTE_JS = re.compile(r"""\b(?:app|router|server)\.(get|post|put|patch|"""
                       r"""delete|all)\(\s*['"`](/[^'"`]*)['"`]""")
_METHODES = re.compile(r"""methods\s*=\s*\[([^\]]*)\]""")
_IDS = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""")


@dataclass
class Contrats:
    tables: dict[str, list[str]] = field(default_factory=dict)
    routes: list[str] = field(default_factory=list)          # "GET /api/x"
    pages: dict[str, list[str]] = field(default_factory=dict)  # page -> ids
    variables: list[str] = field(default_factory=list)
    modules: dict[str, list[str]] = field(default_factory=dict)

    def vide(self) -> bool:
        return not (self.tables or self.routes or self.pages
                    or self.variables or self.modules)

    def texte(self, budget: int = 1_500) -> str:
        """Le resume a donner au modele, dans un budget de caracteres (les
        plus importants d'abord : base, puis API, puis pages)."""
        if self.vide():
            return ""
        l = ["[contrats deja etablis dans le projet — a respecter tels "
             "quels, MAEL les verifie]"]
        if self.tables:
            l.append("- tables : " + " ; ".join(
                f"{t}({', '.join(c)})" for t, c in sorted(self.tables.items())))
        if self.routes:
            l.append("- routes du serveur : " + ", ".join(self.routes))
        if self.pages:
            l.append("- pages : " + " ; ".join(
                f"{p}" + (f" (id : {', '.join(i[:12])})" if i else "")
                for p, i in sorted(self.pages.items())))
        if self.variables:
            l.append("- variables d'environnement : "
                     + ", ".join(self.variables))
        if self.modules:
            l.append("- modules : " + " ; ".join(
                f"{m} ({', '.join(n[:10])})" if n else m
                for m, n in sorted(self.modules.items())))
        texte = "\n".join(l)
        return texte if len(texte) <= budget else texte[:budget - 3] + "..."


def _lire(racine: Path, f: str) -> str:
    try:
        return (Path(racine) / f).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _noms_python(texte: str) -> list[str]:
    try:
        arbre = ast.parse(texte)
    except SyntaxError:
        return []
    return [n.name for n in arbre.body
            if isinstance(n, (ast.ClassDef, ast.FunctionDef,
                              ast.AsyncFunctionDef))
            and not n.name.startswith("_")]


def _noms_js(texte: str) -> list[str]:
    noms = re.findall(r"\bexport\s+(?:default\s+)?(?:async\s+)?"
                      r"(?:function|class|const|let)\s+(\w+)", texte)
    m = re.search(r"module\.exports\s*=\s*\{([^}]*)\}", texte)
    if m:
        noms += re.findall(r"(\w+)\s*(?:[:,]|$)", m.group(1))
    return list(dict.fromkeys(noms))


def relever(racine: Path, fichiers: list[str]) -> Contrats:
    """Les contrats que les fichiers ECRITS etablissent."""
    from . import arborescence as arbo
    from . import juges_orm
    racine = Path(racine)
    c = Contrats()
    tables = arbo.tables_du_schema(racine)
    for t, cols in juges_orm.tables_orm(racine, fichiers).items():
        tables.setdefault(t, set()).update(cols)
    c.tables = {t: sorted(cols - {"*"}) for t, cols in tables.items()}
    for f in sorted(fichiers):
        ext = Path(f).suffix.lower()
        texte = _lire(racine, f)
        if not texte:
            continue
        if ext == ".py":
            for m in _ROUTE_PY.finditer(texte):
                methode = m.group(1).upper()
                if methode in {"ROUTE", "API_ROUTE"}:
                    meth = _METHODES.search(m.group(3) or "")
                    methode = ("/".join(x.strip(" '\"").upper()
                                        for x in meth.group(1).split(","))
                               if meth else "GET")
                c.routes.append(f"{methode} {m.group(2)}")
            if not _ROUTE_PY.search(texte) and not Path(f).name.startswith(
                    "test"):
                noms = _noms_python(texte)
                if noms:
                    c.modules[f] = noms
        elif ext in {".js", ".mjs", ".ts", ".jsx"}:
            routes = [f"{m.group(1).upper()} {m.group(2)}"
                      for m in _ROUTE_JS.finditer(texte)]
            c.routes += routes
            noms = _noms_js(texte)
            if noms:
                c.modules[f] = noms
        elif ext in {".html", ".htm", ".php"}:
            c.pages[f] = list(dict.fromkeys(_IDS.findall(texte)))
    c.routes = list(dict.fromkeys(c.routes))
    c.variables = arbo.variables_env(racine)
    return c
