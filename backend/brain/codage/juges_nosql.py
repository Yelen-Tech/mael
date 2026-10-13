"""Les juges du NoSQL : MongoDB et Redis (09/10/2026).

Pas de schema a rejouer, mais des failles PROPRES, connues et documentees
(OWASP — Testing for NoSQL Injection, WSTG-INPV-05.6) :

  nosql-injection   la requete recoit l'objet de l'utilisateur TEL QUEL
                    (find(req.body), find_one(request.json)) : il peut
                    envoyer {"motdepasse": {"$ne": null}} et entrer sans mot
                    de passe — injection d'OPERATEUR ;
  nosql-where       $where execute du JavaScript dans la base ; avec une
                    donnee de l'utilisateur dedans, c'est une injection de
                    code ;
  redis-keys        KEYS * parcourt TOUTES les cles et bloque le serveur
                    (documentation Redis : « never use KEYS in production »).
Juge par lecture, sans deviner : seulement l'objet de requete entier venu de
l'utilisateur, pas un champ choisi (find({nom: req.body.nom}) est juste
s'il est verifie en chaine — c'est le juge de contamination qui le suit).
"""
from __future__ import annotations

import re
from pathlib import Path

from .juges import GRAVITE, Defaut

B = GRAVITE.BLOQUANT
C = GRAVITE.CONSEIL
NORME = "OWASP WSTG-INPV-05.6 (NoSQL injection)"

_OPS = (r"find|findOne|find_one|findOneAndUpdate|find_one_and_update|"
        r"updateOne|update_one|updateMany|update_many|deleteOne|delete_one|"
        r"deleteMany|delete_many|countDocuments|count_documents|aggregate|"
        r"findById|exists")
_ENTREE = (r"req\.(?:body|query|params)|request\.(?:json|args|form|"
           r"get_json\(\)|args\.to_dict\(\))|ctx\.request\.body|"
           r"\$_(?:GET|POST|REQUEST)")
_INJECTION = re.compile(rf"\.(?:{_OPS})\s*\(\s*(?:{_ENTREE})\s*[,)]")
_WHERE = re.compile(r"""['"]?\$where['"]?\s*:""")
_KEYS = re.compile(r"""\.keys\(\s*['"]\*['"]\s*\)|\bKEYS\s+\*""")


def _ligne(texte: str, i: int) -> int:
    return texte.count("\n", 0, i) + 1


def juger_texte(nom: str, texte: str) -> list[Defaut]:
    d = []
    for m in _INJECTION.finditer(texte):
        d.append(Defaut(nom, _ligne(texte, m.start()), "nosql-injection", B,
                        "la requete recoit l'objet de l'utilisateur tel quel "
                        f"({m.group(0).strip()[:50]}) : il peut y glisser "
                        "un operateur ($ne, $gt) et contourner le filtre",
                        NORME))
    for m in _WHERE.finditer(texte):
        bloc = texte[m.end():m.end() + 160]
        if re.search(rf"{_ENTREE}|\$\{{|\+\s*\w|f['\"]", bloc):
            d.append(Defaut(nom, _ligne(texte, m.start()), "nosql-where", B,
                            "$where avec une donnee de l'utilisateur : "
                            "du JavaScript execute dans la base", NORME))
        else:
            d.append(Defaut(nom, _ligne(texte, m.start()), "nosql-where", C,
                            "$where execute du JavaScript dans la base (lent,"
                            " risque) : preferer un filtre ($eq, $gt...)",
                            NORME))
    for m in _KEYS.finditer(texte):
        d.append(Defaut(nom, _ligne(texte, m.start()), "redis-keys", B,
                        "KEYS * parcourt toutes les cles et bloque Redis : "
                        "SCAN par petits lots", "documentation Redis — KEYS"))
    return d


def juger(racine: Path, vus: list[str]) -> list[Defaut]:
    d = []
    for f in vus:
        if Path(f).suffix.lower() not in {".py", ".js", ".mjs", ".ts", ".php"}:
            continue
        try:
            texte = (Path(racine) / f).read_text(encoding="utf-8",
                                                 errors="replace")
        except OSError:
            continue
        if re.search(r"mongo|redis|\$where", texte, re.I):
            d += juger_texte(f, texte)
    return d
