"""Les juges des AUTRES langages de base : Prisma, CQL (Cassandra), Cypher
(Neo4j) — 09/10/2026.

Ils etaient ranges et installes par la logistique, mais pas juges. Regles
de lecture, sans modele, chacune avec sa source :

  prisma-sans-id        un model Prisma sans @id ni @@id (Prisma le refuse)
  prisma-relation       un champ vise un model qui n'existe pas
  prisma-datasource     schema.prisma sans bloc datasource (rien a migrer)
  cql-sans-cle          CREATE TABLE Cassandra sans PRIMARY KEY (refuse)
  cql-allow-filtering   ALLOW FILTERING : parcourt tout le cluster (lent)
  cypher-injection      requete Cypher construite avec une donnee collee
                        (+, ${}, f-string) au lieu de parametres $nom
  cypher-sans-etiquette MATCH (n) sans etiquette : parcourt tout le graphe
"""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from .juges import GRAVITE, Defaut

B = GRAVITE.BLOQUANT
C = GRAVITE.CONSEIL
_TYPES_PRISMA = {"String", "Int", "BigInt", "Float", "Decimal", "Boolean",
                 "DateTime", "Json", "Bytes", "Unsupported"}


def _ligne(t: str, i: int) -> int:
    return t.count("\n", 0, i) + 1


def juger_prisma(nom: str, texte: str) -> list[Defaut]:
    from .juges_orm import _accolade
    d = []
    blocs = list(re.finditer(r"(?m)^(model|enum|type)\s+(\w+)\s*\{", texte))
    connus = {m.group(2) for m in blocs}
    if not re.search(r"(?m)^datasource\s+\w+\s*\{", texte):
        d.append(Defaut(nom, 1, "prisma-datasource", C,
                        "aucun bloc datasource : Prisma ne sait pas a quelle "
                        "base se connecter (provider + url = "
                        "env(\"DATABASE_URL\"))", "Prisma — schema"))
    for m in blocs:
        if m.group(1) != "model":
            continue
        corps = texte[m.end():_accolade(texte, m.end() - 1)]
        if "@id" not in corps and "@@id" not in corps:
            d.append(Defaut(nom, _ligne(texte, m.start()), "prisma-sans-id",
                            B, f"model {m.group(2)} sans @id ni @@id : Prisma "
                            "refuse un model sans identifiant",
                            "Prisma — schema (models)"))
        for l in re.finditer(r"(?m)^\s*(\w+)\s+([A-Z]\w*)(\[\])?\??", corps):
            genre = l.group(2)
            if genre not in _TYPES_PRISMA and genre not in connus:
                d.append(Defaut(nom, _ligne(texte, m.end() + l.start()),
                                "prisma-relation", B,
                                f"le champ {l.group(1)} vise « {genre} », qui "
                                "n'est ni un type Prisma ni un model du "
                                "schema", "Prisma — relations"))
    return d


def juger_cql(nom: str, texte: str) -> list[Defaut]:
    d = []
    for m in re.finditer(r"(?is)CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                         r"([\w.]+)\s*\((.*?)\)\s*(?:WITH|;|$)", texte):
        if "PRIMARY KEY" not in m.group(2).upper():
            d.append(Defaut(nom, _ligne(texte, m.start()), "cql-sans-cle", B,
                            f"table Cassandra {m.group(1)} sans PRIMARY KEY : "
                            "Cassandra la refuse (la cle de partition choisit "
                            "le noeud)", "Apache Cassandra — CQL"))
    for m in re.finditer(r"(?i)ALLOW\s+FILTERING", texte):
        d.append(Defaut(nom, _ligne(texte, m.start()), "cql-allow-filtering",
                        C, "ALLOW FILTERING parcourt tout le cluster : "
                        "prevoir une table par requete (cle de partition)",
                        "Apache Cassandra — modelisation"))
    return d


_RUN = re.compile(r"""\.(?:run|execute_query|executeQuery|writeTransaction|"""
                  r"""readTransaction)\(\s*(f?)(['"`])((?:(?!\2).)*?)\2"""
                  r"""(\s*\+)?""", re.S)


def juger_cypher(nom: str, texte: str) -> list[Defaut]:
    d = []
    for m in _RUN.finditer(texte):
        requete = m.group(3)
        if not re.search(r"\b(MATCH|CREATE|MERGE|RETURN)\b", requete):
            continue
        colle = (m.group(1) == "f" and "{" in requete) or "${" in requete \
            or m.group(4)
        if colle:
            d.append(Defaut(nom, _ligne(texte, m.start()), "cypher-injection",
                            B, "requete Cypher construite avec une donnee "
                            "collee : parametres $nom, passes a part "
                            "(session.run(q, nom=v))",
                            "Neo4j — parametres ; OWASP injection"))
        if re.search(r"\bMATCH\s*\(\s*\w*\s*\)", requete):
            d.append(Defaut(nom, _ligne(texte, m.start()),
                            "cypher-sans-etiquette", C,
                            "MATCH sans etiquette : parcourt tout le graphe "
                            "(MATCH (c:Client) ...)", "Neo4j — performance"))
    return d


def juger(racine: Path, vus: list[str]) -> list[Defaut]:
    d = []
    for f in vus:
        ext = Path(f).suffix.lower()
        try:
            texte = (Path(racine) / f).read_text(encoding="utf-8",
                                                 errors="replace")
        except OSError:
            continue
        if ext == ".prisma":
            d += juger_prisma(f, texte)
        elif ext == ".cql":
            d += juger_cql(f, texte)
        elif ext in {".py", ".js", ".mjs", ".ts", ".java", ".go", ".cs"}:
            if re.search(r"neo4j", texte, re.I):
                d += juger_cypher(f, texte)
            if re.search(r"cassandra|gocql", texte, re.I):
                for m in re.finditer(r"""(['"])(\s*(?:SELECT|CREATE\s+TABLE)"""
                                     r"""(?:(?!\1).)*)\1""", texte, re.S | re.I):
                    for x in juger_cql(f, m.group(2)):
                        d.append(replace(x, ligne=_ligne(texte, m.start())))
    return d
