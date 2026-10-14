"""La COUVERTURE de l'exemple d'un ticket : les fonctions du depot qu'il
traverse VRAIMENT — Phase 1 du plan agentique (15/10/2026).

Un ticket « mauvais resultat » (sympy-12236 : apart() se trompe, aucune
erreur) n'a pas de trace a suivre ; mais l'exemple du ticket, execute,
passe forcement par le code fautif. On l'execute sous sys.settrace : les
imports d'abord, SANS trace (importer sympy execute des milliers de
fonctions qui n'ont rien a voir), puis le reste, trace. Le script produit
tourne dans l'environnement du depot (Python 3.8 a 3.12) : rien de plus
recent que 3.6 dans le prelude.
"""
from __future__ import annotations

import ast
import json
from collections import Counter

MARQUE = "=====MAEL-COUVERTURE====="

_PRELUDE = '''import sys as _mael_sys, os as _mael_os, json as _mael_json
import atexit as _mael_atexit
_mael_r = _mael_os.path.abspath(_mael_os.getcwd()) + _mael_os.sep
_mael_v = {}
_mael_i = 0
_mael_abs = {}
def _mael_t(frame, event, arg):
    c = frame.f_code
    f = c.co_filename
    if f not in _mael_abs:
        # Python < 3.9 : un module importe depuis le dossier courant a un
        # chemin RELATIF (sympy-11400 sur 3.8 : 0 fichier traverse)
        _mael_abs[f] = "" if f.startswith("<") else _mael_os.path.abspath(f)
    f = _mael_abs[f]
    if f.startswith(_mael_r):
        k = (f[len(_mael_r):].replace(_mael_os.sep, "/"), c.co_name,
             c.co_firstlineno, _mael_i)
        _mael_v[k] = _mael_v.get(k, 0) + 1
    return None
def _mael_fin():
    _mael_sys.settrace(None)
    _mael_sys.stderr.write(chr(10) + "MARQUE" + _mael_json.dumps(
        [[a, b, c, i, n] for (a, b, c, i), n in _mael_v.items()]) + chr(10))
_mael_atexit.register(_mael_fin)
'''.replace("MARQUE", MARQUE)


def script(code: str) -> str:
    """Le script a executer : prelude, imports de l'exemple (non traces),
    puis le reste sous trace. Code illisible : tel quel, trace entier."""
    try:
        arbre = ast.parse(code)
    except SyntaxError:
        return _PRELUDE + "_mael_sys.settrace(_mael_t)\n" + code
    lignes = code.splitlines()
    imports, reste = [], []
    for n in arbre.body:
        bloc = "\n".join(lignes[n.lineno - 1:n.end_lineno])
        (imports if isinstance(n, (ast.Import, ast.ImportFrom))
         else reste).append(bloc)
    # chaque instruction porte son numero : la DERNIERE montre souvent le
    # bug, les precedentes preparent (ou montrent le cas qui marche)
    return (_PRELUDE + "\n".join(imports) + "\n_mael_sys.settrace(_mael_t)\n"
            + "".join(f"_mael_i = {k}\n{b}\n"
                      for k, b in enumerate(reste, 1)))


def lire(sortie: str) -> dict[str, Counter]:
    """{fichier: Counter((fonction, ligne, instruction) -> appels)}."""
    i = sortie.rfind(MARQUE)
    if i < 0:
        return {}
    try:
        brut = json.loads(sortie[i + len(MARQUE):].splitlines()[0])
    except (ValueError, IndexError):
        return {}
    out: dict[str, Counter] = {}
    for f, nom, ligne, i, n in brut:
        out.setdefault(f, Counter())[(nom, ligne, i)] += n
    return out
