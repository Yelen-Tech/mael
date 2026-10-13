"""Couches 3 et 4 pour Python : lire l'ARBRE du code, et suivre la contamination.

Couche 3 — l'arbre au lieu des motifs. Une expression reguliere voit
`eval(` dans un commentaire et crie ; elle ne voit pas
`from os import system as s; s(cmd)` ni `getattr(os, "system")(cmd)`.
L'arbre (module `ast`, bibliotheque standard) sait ce qui est un appel, ce
qui est une chaine, et a quel module un nom renvoie.

Couche 4 — source -> puits. Une donnee qui vient de l'utilisateur
(request.args, input(), sys.argv, parametre d'une route web) et qui atteint
un puits (SQL, shell, fichier, eval, gabarit HTML, requete sortante,
redirection) sans passer par un assainisseur, c'est une faille — meme a
travers des variables intermediaires. Le defaut cite les DEUX lignes : d'ou
vient la donnee, ou elle tombe.

Approximation assumee (doc 15, la loi) : l'analyse est faite fonction par
fonction, dans l'ordre des instructions, sans suivre les appels entre
fonctions. Elle rate des chemins longs ; elle ne doit pas inventer de faux
chemins. Le doute profite au code : une valeur qu'on ne sait pas lire n'est
pas declaree contaminee.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from .juges import GRAVITE, Defaut

# ------------------------------------------------------------- catalogue
# Sources : attributs de requete des frameworks courants (Flask, Django,
# FastAPI/Starlette, aiohttp) et entrees du programme.
_ATTRS_REQUETE = {"args", "form", "values", "json", "cookies", "headers",
                  "GET", "POST", "data", "query_params", "path_params",
                  "files", "body", "query", "match_info", "get_json",
                  "get_data"}
_NOMS_REQUETE = {"request", "req", "self.request"}
_APPELS_SOURCES = {"input", "sys.stdin.read", "sys.stdin.readline"}
# Decorateurs qui font d'une fonction un point d'entree web : ses
# parametres viennent de l'URL ou du corps de la requete.
_DECORATEURS_ROUTE = {"route", "get", "post", "put", "patch", "delete",
                      "api_view", "websocket"}

# Assainisseurs : ce qui en sort n'est plus dangereux pour le puits vise.
# Simplification volontaire : un assainisseur vaut pour tous les puits
# (int() rend une valeur sure partout ; html.escape ne protege pas un
# shell, mais on prefere rater ce cas que crier sur du code juste).
_ASSAINISSEURS = {"int", "float", "bool", "len", "abs", "round",
                  "shlex.quote", "html.escape", "markupsafe.escape",
                  "escape", "bleach.clean", "secure_filename",
                  "werkzeug.utils.secure_filename", "uuid.UUID",
                  "ipaddress.ip_address", "urllib.parse.quote",
                  "quote", "re.escape", "os.path.basename"}

# Appels qui recopient leurs arguments dans leur resultat.
_PROPAGATEURS = {"str", "repr", "bytes", "os.path.join", "posixpath.join",
                 "os.path.normpath", "os.path.abspath", "urllib.parse.unquote",
                 "unquote", "base64.b64decode", "json.loads", "dict", "list",
                 "tuple", "sorted", "reversed"}


@dataclass(frozen=True)
class Puits:
    regle: str
    message: str
    norme: str


_SQL = Puits("injection-sql",
             "donnee de l'utilisateur dans une requete SQL",
             "OWASP A03 — injection SQL (CWE-89)")
_SHELL = Puits("injection-commande",
               "donnee de l'utilisateur dans une commande systeme",
               "OWASP A03 — injection de commande (CWE-78)")
_CODE = Puits("injection-code", "donnee de l'utilisateur executee comme du "
              "code", "OWASP A03 — CWE-95")
_CHEMIN = Puits("traversee-chemin", "donnee de l'utilisateur dans un chemin "
                "de fichier (../../etc/passwd)", "OWASP A01 — CWE-22")
_XSS = Puits("xss-serveur", "donnee de l'utilisateur rendue en HTML sans "
             "echappement", "OWASP A03 — XSS (CWE-79)")
_SSRF = Puits("ssrf", "l'utilisateur choisit l'adresse que le serveur "
              "appelle", "OWASP A10 — SSRF (CWE-918)")
_REDIR = Puits("redirection-ouverte", "l'utilisateur choisit la page de "
               "redirection", "CWE-601")
_DESER = Puits("deserialisation", "donnee de l'utilisateur deserialisee",
               "OWASP A08 — CWE-502")

# Nom canonique de l'appel -> puits. « *.execute » : n'importe quel objet.
_PUITS = {
    "*.execute": _SQL, "*.executemany": _SQL, "*.executescript": _SQL,
    "*.raw": _SQL, "*.extra": _SQL, "sqlalchemy.text": _SQL, "text": _SQL,
    "os.system": _SHELL, "os.popen": _SHELL, "subprocess.run": _SHELL,
    "subprocess.call": _SHELL, "subprocess.check_call": _SHELL,
    "subprocess.check_output": _SHELL, "subprocess.Popen": _SHELL,
    "subprocess.getoutput": _SHELL, "subprocess.getstatusoutput": _SHELL,
    "eval": _CODE, "exec": _CODE, "compile": _CODE,
    "open": _CHEMIN, "send_file": _CHEMIN, "flask.send_file": _CHEMIN,
    "os.remove": _CHEMIN, "os.unlink": _CHEMIN, "shutil.rmtree": _CHEMIN,
    "pathlib.Path": _CHEMIN, "Path": _CHEMIN, "FileResponse": _CHEMIN,
    "render_template_string": _XSS, "flask.render_template_string": _XSS,
    "Markup": _XSS, "markupsafe.Markup": _XSS, "mark_safe": _XSS,
    "django.utils.safestring.mark_safe": _XSS,
    "RawSQL": _SQL, "django.db.models.expressions.RawSQL": _SQL,
    "django.db.models.RawSQL": _SQL,
    "HttpResponse": _XSS, "HTMLResponse": _XSS,
    "requests.get": _SSRF, "requests.post": _SSRF, "requests.request": _SSRF,
    "httpx.get": _SSRF, "httpx.post": _SSRF, "urllib.request.urlopen": _SSRF,
    "urlopen": _SSRF,
    "redirect": _REDIR, "flask.redirect": _REDIR,
    "HttpResponseRedirect": _REDIR, "RedirectResponse": _REDIR,
    "pickle.loads": _DESER, "pickle.load": _DESER, "marshal.loads": _DESER,
    "yaml.unsafe_load": _DESER,
}
# Seul l'argument DANGEREUX compte : la requete SQL, la commande, le chemin,
# l'adresse, le gabarit. Les autres sont la bonne pratique elle-meme : les
# valeurs SQL passees en parametres, les variables d'un gabarit (echappees
# automatiquement), les params= d'une requete HTTP. C'est le premier
# argument positionnel, ou l'un de ces mots-cles s'il est nomme.
_MOTS_CLES_DANGEREUX = {"sql", "statement", "query", "args", "cmd",
                        "command", "file", "path", "filename", "url",
                        "location", "source", "source_string", "data",
                        "content", "to", "redirect_to"}


def _argument_dangereux(n: ast.Call) -> list[ast.AST]:
    if n.args:
        return [n.args[0]]
    return [k.value for k in n.keywords if k.arg in _MOTS_CLES_DANGEREUX]


# --------------------------------------------------------------- noms
class _Noms:
    """Resout un nom local vers son module : `from os import system as s`
    -> s = os.system ; `import subprocess as sp` -> sp = subprocess."""

    def __init__(self, arbre: ast.AST):
        self.alias: dict[str, str] = {}
        for n in ast.walk(arbre):
            if isinstance(n, ast.Import):
                for a in n.names:
                    self.alias[a.asname or a.name.split(".")[0]] = (
                        a.name if a.asname else a.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom) and n.module:
                for a in n.names:
                    self.alias[a.asname or a.name] = f"{n.module}.{a.name}"

    def nom(self, noeud: ast.AST) -> str | None:
        if isinstance(noeud, ast.Name):
            return self.alias.get(noeud.id, noeud.id)
        if isinstance(noeud, ast.Attribute):
            base = self.nom(noeud.value)
            return f"{base}.{noeud.attr}" if base else f"*.{noeud.attr}"
        # getattr(os, "system") : l'attribut deguise est un attribut.
        if (isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)
                and noeud.func.id == "getattr" and len(noeud.args) >= 2
                and isinstance(noeud.args[1], ast.Constant)
                and isinstance(noeud.args[1].value, str)):
            base = self.nom(noeud.args[0])
            return f"{base}.{noeud.args[1].value}" if base else None
        return None


def _puits_de(nom: str | None) -> Puits | None:
    if not nom:
        return None
    if nom in _PUITS:
        return _PUITS[nom]
    queue = "*." + nom.rsplit(".", 1)[-1]
    return _PUITS.get(queue) if queue in ("*.execute", "*.executemany",
                                          "*.executescript", "*.raw",
                                          "*.extra") else None


def _constante(n: ast.AST) -> bool:
    return isinstance(n, ast.Constant)


def _kw(appel: ast.Call, nom: str) -> ast.AST | None:
    return next((k.value for k in appel.keywords if k.arg == nom), None)


def _vrai(n: ast.AST | None) -> bool:
    return isinstance(n, ast.Constant) and n.value is True


def _chaine_construite(n: ast.AST) -> bool:
    """f-string avec valeurs, « ... » % x, « ... » + x, « ... ».format(x)."""
    if isinstance(n, ast.JoinedStr):
        return any(isinstance(v, ast.FormattedValue) for v in n.values)
    if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Mod, ast.Add)):
        # Une chaine litterale d'un cote, une valeur de l'autre. « base +
        # filtre » (deux variables) ne suffit pas : le doute profite au code.
        cotes = (n.left, n.right)
        texte = any(isinstance(c, (ast.JoinedStr,)) or (
            isinstance(c, ast.Constant) and isinstance(c.value, str))
            or _chaine_construite(c) for c in cotes)
        return texte and not all(_constante(c) for c in cotes)
    if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "format"):
        return True
    return False


# ------------------------------------------------------------- analyse
class _Analyse(ast.NodeVisitor):
    def __init__(self, fichier: str, noms: _Noms):
        self.f = fichier
        self.noms = noms
        self.defauts: list[Defaut] = []
        # nom de variable -> ligne ou la contamination est entree
        self.contamines: dict[str, int] = {}
        # variable -> ligne ou une requete SQL a ete construite avec des valeurs
        self.sql_construit: dict[str, int] = {}

    def ajouter(self, n, regle, gravite, message, norme):
        self.defauts.append(Defaut(self.f, getattr(n, "lineno", 1), regle,
                                   gravite, message, norme))

    # ------------------------------------------------ contamination
    def source(self, n: ast.AST) -> int | None:
        """Ligne d'origine si l'expression porte une donnee utilisateur."""
        if isinstance(n, ast.Name):
            return self.contamines.get(n.id)
        if isinstance(n, ast.Attribute):
            nom = self.noms.nom(n) or ""
            base = nom.rsplit(".", 1)[0] if "." in nom else ""
            if (n.attr in _ATTRS_REQUETE and base.split(".")[-1] in
                    {x.split(".")[-1] for x in _NOMS_REQUETE}):
                return n.lineno
            if nom == "sys.argv":
                return n.lineno
            return self.source(n.value)
        if isinstance(n, ast.Call):
            nom = self.noms.nom(n.func)
            if nom in _ASSAINISSEURS:
                return None
            if nom in _APPELS_SOURCES:
                return n.lineno
            # request.args.get("x"), x.strip(), x.lower()... : la donnee
            # reste celle de l'utilisateur.
            if isinstance(n.func, ast.Attribute):
                origine = self.source(n.func.value)
                if origine:
                    return origine
            # Ce qui recopie ses arguments garde leur contamination :
            # str(x), "-".join(xs), os.path.join(base, x), "{}".format(x).
            court = (nom or "").rsplit(".", 1)[-1]
            if nom in _PROPAGATEURS or court in {"join", "format"}:
                for a in [*n.args, *(k.value for k in n.keywords)]:
                    o = self.source(a)
                    if o:
                        return o
            return None
        if isinstance(n, ast.Subscript):
            return self.source(n.value)
        if isinstance(n, ast.JoinedStr):
            for v in n.values:
                if isinstance(v, ast.FormattedValue):
                    o = self.source(v.value)
                    if o:
                        return o
            return None
        if isinstance(n, ast.BinOp):
            return self.source(n.left) or self.source(n.right)
        if isinstance(n, (ast.List, ast.Tuple, ast.Set)):
            for e in n.elts:
                o = self.source(e)
                if o:
                    return o
        if isinstance(n, ast.IfExp):
            return self.source(n.body) or self.source(n.orelse)
        return None

    # ------------------------------------------------ portees
    def _fonction(self, n):
        sauve = dict(self.contamines), dict(self.sql_construit)
        decorateurs = {(self.noms.nom(d.func if isinstance(d, ast.Call)
                                      else d) or "").rsplit(".", 1)[-1]
                       for d in n.decorator_list}
        route_avant = getattr(self, "dans_route", False)
        self.dans_route = bool(decorateurs & _DECORATEURS_ROUTE)
        if self.dans_route:
            for a in n.args.args + n.args.kwonlyargs:
                if a.arg not in {"self", "request", "req", "db", "session"}:
                    self.contamines[a.arg] = n.lineno
        self.generic_visit(n)
        self.contamines, self.sql_construit = sauve
        self.dans_route = route_avant

    def visit_Return(self, n: ast.Return):
        """Une ROUTE qui renvoie du HTML construit avec une donnee de
        l'utilisateur (f-string, +, format) : XSS. Lot neuf de la chaine du
        08/10/2026 : « return f'<h1>Bonjour {nom}</h1>' » n'etait pas vu."""
        self.generic_visit(n)
        v = n.value
        if not getattr(self, "dans_route", False) or v is None:
            return
        litteraux = [x.value for x in ast.walk(v)
                     if isinstance(x, ast.Constant) and isinstance(x.value,
                                                                   str)]
        if any(re.search(r"<\s*[a-zA-Z]", t) for t in litteraux) and \
                self.source(v):
            self.ajouter(n, _XSS.regle, GRAVITE.BLOQUANT,
                         f"{_XSS.message} : HTML construit avec une donnee de "
                         "la requete (utiliser un gabarit, ou "
                         "markupsafe.escape)", _XSS.norme)

    visit_FunctionDef = _fonction
    visit_AsyncFunctionDef = _fonction

    def visit_Assign(self, n: ast.Assign):
        self.generic_visit(n)
        origine = self.source(n.value)
        construit = _chaine_construite(n.value)
        for cible in n.targets:
            for nom in _noms_cibles(cible):
                if origine:
                    self.contamines[nom] = origine
                else:
                    self.contamines.pop(nom, None)   # reassignee proprement
                if construit:
                    self.sql_construit[nom] = n.lineno
                else:
                    self.sql_construit.pop(nom, None)

    def visit_AnnAssign(self, n: ast.AnnAssign):
        if n.value is not None:
            self.visit_Assign(ast.Assign(targets=[n.target], value=n.value,
                                         lineno=n.lineno))
        else:
            self.generic_visit(n)

    def visit_AugAssign(self, n: ast.AugAssign):
        self.generic_visit(n)
        origine = self.source(n.value)
        for nom in _noms_cibles(n.target):
            if origine:
                self.contamines[nom] = origine
            if _constante(n.value) is False:
                self.sql_construit[nom] = n.lineno

    def visit_For(self, n: ast.For):
        origine = self.source(n.iter)
        if origine:
            for nom in _noms_cibles(n.target):
                self.contamines[nom] = origine
        self.generic_visit(n)

    # ------------------------------------------------ handlers d'erreur
    def visit_ExceptHandler(self, n: ast.ExceptHandler):
        if n.type is None:
            self.ajouter(n, "erreur-avalee", GRAVITE.CONSEIL,
                         "except: nu (attrape meme Ctrl+C)", "PEP 8")
        elif (len(n.body) == 1 and isinstance(n.body[0], ast.Pass)):
            self.ajouter(n, "erreur-avalee", GRAVITE.CONSEIL,
                         "erreur attrapee puis ignoree (pass) : une panne "
                         "devient invisible", "CWE-390")
        self.generic_visit(n)

    # ------------------------------------------------ appels
    def visit_Call(self, n: ast.Call):
        self.generic_visit(n)
        nom = self.noms.nom(n.func) or ""
        court = nom.rsplit(".", 1)[-1]

        # --- puits + contamination (couche 4)
        puits = _puits_de(nom)
        if puits is not None:
            for a in _argument_dangereux(n):
                origine = self.source(a)
                if origine:
                    self.ajouter(n, puits.regle, GRAVITE.BLOQUANT,
                                 f"{puits.message} (entree ligne {origine} "
                                 f"-> ici)", puits.norme)
                    break
            else:
                self._regles_sans_contamination(n, nom, court, puits)
        else:
            self._regles_sans_contamination(n, nom, court, None)

    def _regles_sans_contamination(self, n, nom, court, puits):
        # SQL construit a la main, meme sans source connue : la forme est
        # fautive en soi (on ne sait jamais d'ou viendra la valeur demain).
        if puits is _SQL and n.args:
            req = n.args[0]
            ligne = (self.sql_construit.get(req.id)
                     if isinstance(req, ast.Name) else None)
            if _chaine_construite(req) or ligne:
                self.ajouter(n, "injection-sql", GRAVITE.BLOQUANT,
                             "requete SQL construite avec des valeurs"
                             + (f" (montee ligne {ligne})" if ligne else "")
                             + " : passer les valeurs en parametres (?, %s)",
                             "OWASP A03 — injection SQL (CWE-89)")
            return
        if nom in {"eval", "exec"}:
            litteral = n.args and _constante(n.args[0])
            self.ajouter(n, "py-dangereux",
                         GRAVITE.CONSEIL if litteral else GRAVITE.BLOQUANT,
                         f"{nom}() execute du texte comme du code",
                         "OWASP A03 / CWE-95")
            return
        if nom.startswith("subprocess.") and _vrai(_kw(n, "shell")):
            litteral = n.args and _constante(n.args[0])
            self.ajouter(n, "py-dangereux",
                         GRAVITE.CONSEIL if litteral else GRAVITE.BLOQUANT,
                         "subprocess avec shell=True : passer une liste "
                         "d'arguments", "OWASP A03 / CWE-78")
            return
        if nom in {"os.system", "os.popen"}:
            litteral = n.args and _constante(n.args[0])
            self.ajouter(n, "py-dangereux",
                         GRAVITE.CONSEIL if litteral else GRAVITE.BLOQUANT,
                         f"{nom}() passe par le shell", "OWASP A03 / CWE-78")
            return
        if nom in {"pickle.load", "pickle.loads", "marshal.loads",
                   "marshal.load", "shelve.open", "yaml.unsafe_load"}:
            self.ajouter(n, "py-dangereux", GRAVITE.BLOQUANT,
                         f"{nom} : charger des donnees non sures execute du "
                         "code", "OWASP A08 / CWE-502")
            return
        if nom == "yaml.load":
            loader = _kw(n, "Loader") or (n.args[1] if len(n.args) > 1
                                          else None)
            nom_loader = (self.noms.nom(loader) or "") if loader else ""
            if not nom_loader.endswith(("SafeLoader", "CSafeLoader",
                                        "BaseLoader")):
                self.ajouter(n, "py-dangereux", GRAVITE.BLOQUANT,
                             "yaml.load sans SafeLoader (utiliser "
                             "yaml.safe_load)", "OWASP A08 / CWE-502")
            return
        verify = _kw(n, "verify")
        if isinstance(verify, ast.Constant) and verify.value is False:
            self.ajouter(n, "py-dangereux", GRAVITE.BLOQUANT,
                         "verification TLS desactivee (verify=False)",
                         "OWASP A02 / CWE-295")
            return
        if court == "run" and _vrai(_kw(n, "debug")):
            # « debug-actif » : la regle des fiches et des remedes, pour que
            # le conseil retrouve son savoir (etait rangee en py-dangereux).
            self.ajouter(n, "debug-actif", GRAVITE.BLOQUANT,
                         "serveur lance en mode debug (console de debogage "
                         "ouverte a distance)", "OWASP A05")
            return
        if nom in {"hashlib.md5", "hashlib.sha1"}:
            usage = _kw(n, "usedforsecurity")
            if not (isinstance(usage, ast.Constant) and usage.value is False):
                self.ajouter(n, "hash-faible", GRAVITE.CONSEIL,
                             f"{nom} : trop faible pour un mot de passe ou "
                             "une signature", "OWASP A02 / CWE-328")
            return
        if nom == "tempfile.mktemp":
            self.ajouter(n, "py-dangereux", GRAVITE.BLOQUANT,
                         "tempfile.mktemp : course entre le nom et la "
                         "creation (utiliser mkstemp / NamedTemporaryFile)",
                         "CWE-377")
            return


def _noms_cibles(cible: ast.AST) -> list[str]:
    if isinstance(cible, ast.Name):
        return [cible.id]
    if isinstance(cible, (ast.Tuple, ast.List)):
        return [x for e in cible.elts for x in _noms_cibles(e)]
    # app.secret_key = "..." et app.config["SECRET_KEY"] = "..." : la facon
    # courante de regler Flask (banc de la chaine du 08/10/2026 : non vu).
    if isinstance(cible, ast.Attribute):
        return [cible.attr]
    if (isinstance(cible, ast.Subscript) and isinstance(cible.slice,
                                                         ast.Constant)
            and isinstance(cible.slice.value, str)):
        return [cible.slice.value]
    return []


_MOTS_SECRETS = ("token", "jeton", "password", "passwd", "mot_de_passe",
                 "mdp", "secret", "cle", "key", "otp", "code_verif", "sel",
                 "salt", "nonce")


_FACTICES = ("example", "exemple", "changeme", "xxxx", "votre", "your",
             "dummy", "test", "django-insecure")


# Pour un secret ecrit en dur, on est plus strict que pour le hasard : une
# valeur en dur dans CACHE_KEY ou SORT_KEY est normale. Seuls ces mots, ou
# « key » precede d'un qualificatif de secret, designent un secret.
_SECRETS_SEULS = {"secret", "password", "passwd", "pwd", "mdp", "token",
                  "jeton", "apikey", "credentials"}
_QUALIFIE_KEY = {"api", "secret", "private", "access", "signing", "auth",
                 "encryption", "master"}


def _nom_secret(nom: str) -> bool:
    parties = nom.lower().split("_")
    if set(parties) & _SECRETS_SEULS or "mot_de_passe" in nom.lower():
        return True
    return any(p == "key" and i > 0 and parties[i - 1] in _QUALIFIE_KEY
               for i, p in enumerate(parties))


def _configuration(arbre: ast.AST, noms: _Noms, fichier: str
                   ) -> list[Defaut]:
    """Reglages dangereux ecrits en dur (Django, Flask, tout script)."""
    d = []

    def ajouter(n, regle, gravite, message, norme):
        d.append(Defaut(fichier, n.lineno, regle, gravite, message, norme))

    for n in ast.walk(arbre):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in n.decorator_list:
                if (noms.nom(dec) or "").endswith("csrf_exempt"):
                    ajouter(n, "csrf-desactive", GRAVITE.BLOQUANT,
                            f"protection CSRF retiree sur {n.name}()",
                            "OWASP A01 — CSRF (CWE-352)")
        if not isinstance(n, ast.Assign):
            continue
        cibles = [x for c in n.targets for x in _noms_cibles(c)]
        v = n.value
        for nom in cibles:
            # SECRET_KEY = "..." : le motif texte ne voit pas « secret »
            # colle a « _KEY » ; l'arbre, lui, lit le nom de la variable.
            if (_nom_secret(nom) and isinstance(v, ast.Constant)
                    and isinstance(v.value, str) and len(v.value) >= 8
                    and not any(f in v.value.lower() for f in _FACTICES)):
                ajouter(n, "secret-en-dur", GRAVITE.BLOQUANT,
                        f"{nom} ecrit en dur : a lire depuis "
                        "l'environnement", "OWASP A07 / CWE-798")
            if nom == "DEBUG" and isinstance(v, ast.Constant) and v.value is True:
                ajouter(n, "debug-actif", GRAVITE.CONSEIL,
                        "DEBUG = True ecrit en dur : pages d'erreur "
                        "detaillees en production", "OWASP A05")
            if (nom == "ALLOWED_HOSTS" and isinstance(v, (ast.List, ast.Tuple))
                    and any(isinstance(e, ast.Constant) and e.value == "*"
                            for e in v.elts)):
                ajouter(n, "hotes-ouverts", GRAVITE.CONSEIL,
                        "ALLOWED_HOSTS = ['*'] : n'importe quel nom d'hote "
                        "est accepte", "OWASP A05")
            if (nom in {"SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE",
                        "SESSION_COOKIE_HTTPONLY"}
                    and isinstance(v, ast.Constant) and v.value is False):
                ajouter(n, "cookie-faible", GRAVITE.BLOQUANT,
                        f"{nom} = False", "OWASP A05 / CWE-614")
    return d


def _hasard_faible(arbre: ast.AST, noms: _Noms, fichier: str
                   ) -> list[Defaut]:
    """random.* pour fabriquer un jeton ou un mot de passe : previsible."""
    d = []
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Assign):
            continue
        # Mot ENTIER du nom (api_token, mot_de_passe) : « selection » ne
        # contient pas « sel », « cycle » ne contient pas « cle ».
        cibles = [x.lower() for c in n.targets for x in _noms_cibles(c)]
        if not any(c in _MOTS_SECRETS or set(c.split("_")) & set(_MOTS_SECRETS)
                   or any(c.endswith(m) and len(m) > 3 for m in _MOTS_SECRETS)
                   for c in cibles):
            continue
        for sous in ast.walk(n.value):
            if isinstance(sous, ast.Call):
                nom = noms.nom(sous.func) or ""
                if nom.startswith("random."):
                    d.append(Defaut(fichier, n.lineno, "hasard-faible",
                                    GRAVITE.BLOQUANT,
                                    f"{nom} pour un secret : previsible "
                                    "(utiliser le module secrets)",
                                    "OWASP A02 / CWE-338"))
                    break
    return d


def analyser(fichier: str, texte: str) -> list[Defaut] | None:
    """Rend les defauts, ou None si le texte n'est pas du Python lisible
    (la syntaxe est alors jugee ailleurs, et les motifs prennent le
    relais)."""
    try:
        arbre = ast.parse(texte, filename=fichier)
    except (SyntaxError, ValueError):
        return None
    noms = _Noms(arbre)
    a = _Analyse(fichier, noms)
    a.visit(arbre)
    return (a.defauts + _hasard_faible(arbre, noms, fichier)
            + _configuration(arbre, noms, fichier))
