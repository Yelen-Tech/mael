"""La carte du projet : la memoire du chantier, a la place de l'historique.

Un petit modele a une memoire de travail courte (4 096 jetons pour
phi4-mini sur 8 Go). Lui renvoyer toute la conversation a chaque tour la
remplit (sixieme essai reel : 3 186 jetons au 3e tour) et le ralentit. On
lui donne a la place une CARTE : pour chaque fichier, ce qu'un autre
fichier a besoin d'en savoir pour s'y raccorder — les id, les classes, les
liens, les champs de formulaire, les fonctions, les routes, les couleurs.

C'est ce qui l'empeche de « perdre le fil » : il sait que #contact existe
et ne vise pas form#contact ; il reprend les couleurs deja choisies.

Regles : lecture seule, deterministe, sous un budget en caracteres ; les
listes longues sont coupees et le disent (« +12 »).
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from .juges import fichiers_du_projet

BUDGET = 1_400          # ~350 jetons pour tout le projet
PAR_LISTE = 10          # elements montres par liste avant « +N »


def _liste(nom: str, elements) -> str:
    vus = list(dict.fromkeys(e for e in elements if e))
    if not vus:
        return ""
    reste = len(vus) - PAR_LISTE
    return (f"{nom}: " + ", ".join(vus[:PAR_LISTE])
            + (f" (+{reste})" if reste > 0 else ""))


class _Html(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.classes, self.liens, self.res = [], [], [], []
        self.formulaires: list[str] = []
        self.titre, self._dans_titre = "", False
        self._form: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if a.get("id"):
            self.ids.append("#" + a["id"])
        self.classes += ["." + c for c in a.get("class", "").split()]
        if tag == "a" and a.get("href"):
            self.liens.append(a["href"])
        if tag in {"link", "script", "img"} and (a.get("href") or a.get("src")):
            self.res.append(a.get("href") or a.get("src"))
        if tag == "title":
            self._dans_titre = True
        if tag == "form":
            self._form = [f"{a.get('method', 'get')} {a.get('action', '')}"]
        if tag in {"input", "textarea", "select"} and self._form is not None:
            self._form.append(a.get("name") or a.get("id") or tag)

    def handle_endtag(self, tag):
        if tag == "title":
            self._dans_titre = False
        if tag == "form" and self._form is not None:
            tete, *champs = self._form
            self.formulaires.append(f"{tete.strip()} [{', '.join(champs)}]")
            self._form = None

    def handle_data(self, data):
        if self._dans_titre:
            self.titre += data.strip()


def _html(texte: str) -> list[str]:
    p = _Html()
    try:
        p.feed(texte)
        p.close()
    except Exception:
        return ["(illisible)"]
    return [x for x in (
        f"titre: {p.titre}" if p.titre else "",
        _liste("id", p.ids), _liste("classes", p.classes),
        _liste("liens", p.liens), _liste("charge", p.res),
        _liste("formulaires", p.formulaires)) if x]


def _css(texte: str) -> list[str]:
    sans = re.sub(r"/\*.*?\*/", "", texte, flags=re.S)
    selecteurs = [s.strip() for bloc in re.findall(r"([^{}]+)\{", sans)
                  for s in bloc.split(",") if s.strip()
                  and not s.strip().startswith("@")]
    couleurs = re.findall(r"#[0-9a-fA-F]{3,8}\b", sans)
    return [x for x in (_liste("selecteurs", selecteurs),
                        _liste("couleurs", [c.lower() for c in couleurs]))
            if x]


def _js(texte: str) -> list[str]:
    fonctions = re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)", texte)
    fonctions += re.findall(
        r"\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(", texte)
    vises = re.findall(r"""(?:getElementById|querySelector(?:All)?)\s*\(\s*"""
                       r"""['"]([^'"]+)['"]""", texte)
    exports = re.findall(r"\bexport\s+(?:default\s+)?(?:function|const|class)"
                         r"\s+([A-Za-z_$][\w$]*)", texte)
    return [x for x in (_liste("fonctions", fonctions),
                        _liste("vise", vises), _liste("exporte", exports))
            if x]


def _py(texte: str) -> list[str]:
    routes = re.findall(r"""@\w+\.(?:route|get|post|put|delete|patch)\s*\(\s*"""
                        r"""['"]([^'"]+)['"]""", texte)
    fonctions = re.findall(r"^\s*(?:async\s+)?def\s+(\w+)", texte, re.M)
    classes = re.findall(r"^class\s+(\w+)", texte, re.M)
    return [x for x in (_liste("routes", routes),
                        _liste("fonctions", fonctions),
                        _liste("classes", classes)) if x]


_LECTEURS = {".html": _html, ".htm": _html, ".css": _css, ".js": _js,
             ".mjs": _js, ".jsx": _js, ".py": _py}


def carte(racine: Path, budget: int = BUDGET, sauf: str | None = None
          ) -> str:
    """La carte du projet en texte, sous le budget. Vide s'il n'y a rien.

    `sauf` : le fichier qu'on est en train d'ecrire ou de refaire. Son
    ancienne version n'est pas resumee : la montrer, c'est inviter le modele
    a la recopier (reprise du quatrieme essai)."""
    racine = Path(racine)
    morceaux, total = [], 0
    for p in fichiers_du_projet(racine):
        rel = p.relative_to(racine).as_posix()
        if rel == sauf:
            morceaux.append(f"- {rel} (a ecrire : ancienne version non "
                            "montree)")
            continue
        lecteur = _LECTEURS.get(p.suffix.lower())
        try:
            texte = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        details = lecteur(texte) if lecteur else []
        bloc = f"- {rel} ({texte.count(chr(10)) + 1} lignes)" + "".join(
            f"\n    {d}" for d in details)
        if total + len(bloc) > budget:
            morceaux.append(f"- {rel} (carte coupee : budget atteint)")
            continue
        total += len(bloc)
        morceaux.append(bloc)
    return "\n".join(morceaux)
