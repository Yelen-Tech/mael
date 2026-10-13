"""L'execution REELLE des bases a serveur : la vraie base, dans Docker.

SQLite se rejoue en memoire (juges_sql.executer_sqlite). PostgreSQL, MySQL,
MariaDB, SQL Server, Oracle et Cassandra (ses .cql) ont un serveur : MAEL le demarre dans un
conteneur ISOLE (aucun reseau, memoire plafonnee, detruit a la fin), y
copie le schema, les migrations et les donnees, et les rejoue dans l'ordre
avec le CLIENT OFFICIEL de la base. Ce qu'elle refuse est un defaut
certain : c'est la base qui le dit, pas un motif.

Prudence de machine (8 Go) : le modele est decharge avant ; une image
absente n'est jamais telechargee en silence — le bilan dit la commande
« docker pull » a lancer. MongoDB, Redis, Neo4j, Elasticsearch n'ont pas de
fichier de schema a rejouer : non concernes ici.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import bases
from .juges import GRAVITE, Defaut
from .juges_sql import ordre_d_application

B = GRAVITE.BLOQUANT
# Secondes pour qu'une base soit prete, MESUREES sur le portable de 8 Go
# (09/10/2026) : MySQL 8.4 met plus de 2 minutes a s'initialiser.
DEMARRAGE = {"postgres": 180, "mysql": 600, "mariadb": 420,
             "sqlserver": 480, "oracle": 900, "cassandra": 600}
# Secondes par fichier applique : Oracle, sur 8 Go, a depasse 120 s pour un
# simple INSERT juste apres son demarrage (essai reel du 09/10).
APPLIQUER = {"oracle": 420, "sqlserver": 240, "cassandra": 240}
RESEAU_ISOLE = "mael-isole"   # docker network create --internal : aucune sortie
MEMOIRE = {"postgres": "512m", "mysql": "1g", "mariadb": "768m",
           "sqlserver": "2g", "oracle": "2g", "cassandra": "1536m"}
# Bases qui ne demarrent pas sans adresse IP (--network none refuse) : un
# reseau docker INTERNE, sans aucune sortie.
RESEAU_INTERNE = {"oracle", "cassandra"}
# Le schema de chaque base : .sql, sauf Cassandra (.cql).
EXTENSION = {"cassandra": ".cql"}
# Cassandra, sur 8 Go : le tas Java plafonne (sinon 1/4 de la machine).
ENV_EN_PLUS = {"cassandra": (("MAX_HEAP_SIZE", "512M"),
                             ("HEAP_NEWSIZE", "128M"))}
ESPACE_CQL = "app"     # keyspace cree par MAEL si le projet n'en cree aucun


@dataclass(frozen=True)
class Recette:
    pret: tuple[str, ...]                 # commande qui reussit quand la base est prete
    appliquer: str                        # {f} = fichier dans le conteneur
    # La marque d'ERREUR de la base, cherchee dans TOUTE la sortie : certains
    # clients (sqlplus) finissent sans code d'erreur meme quand la base
    # refuse (essai reel du 09/10 : une cle etrangere violee « acceptee »).
    erreur: str = r"(?m)^ERROR"
    entete: str = ""                      # pose en tete de chaque fichier
    # La marque de LENTEUR du client (delai d'attente depasse) : la base n'a
    # rien refuse — ce n'est pas un defaut du projet, la base est non
    # verifiee (essai reel Cassandra du 12/10 : CREATE TABLE « refuse » a
    # tort par le delai de 10 s de cqlsh).
    lenteur: str = ""


RECETTES = {
    "postgres": Recette(("pg_isready", "-U", "app", "-d", "app"),
                        "psql -v ON_ERROR_STOP=1 -q -U app -d app -f {f}",
                        r"\bERROR:"),
    # -h 127.0.0.1 : par TCP. Pendant l'initialisation, l'image demarre un
    # serveur TEMPORAIRE sans reseau (--skip-networking) : seul le vrai
    # serveur repond en TCP — on ne le confond plus avec le temporaire.
    "mysql": Recette(("sh", "-c", "mysql -h 127.0.0.1 -uroot "
                      "-p$MYSQL_ROOT_PASSWORD -e 'SELECT 1' app"),
                     "mysql -h 127.0.0.1 -uroot -p$MYSQL_ROOT_PASSWORD app "
                     "< {f}", r"\bERROR \d+"),
    "mariadb": Recette(("sh", "-c", "mariadb -h 127.0.0.1 -uroot "
                        "-p$MARIADB_ROOT_PASSWORD -e 'SELECT 1' app"),
                       "mariadb -h 127.0.0.1 -uroot "
                       "-p$MARIADB_ROOT_PASSWORD app < {f}", r"\bERROR \d+"),
    # 127.0.0.1 et non « localhost » : sans reseau (--network none), le nom
    # n'est pas resolu par le pilote ODBC (erreur 0x2AFA, 09/10/2026).
    "sqlserver": Recette(("sh", "-c", "/opt/mssql-tools18/bin/sqlcmd -C -S "
                          "127.0.0.1 -U sa -P \"$MSSQL_SA_PASSWORD\" -Q "
                          "'SELECT 1'"),
                         "/opt/mssql-tools18/bin/sqlcmd -C -b -S 127.0.0.1 "
                         "-U sa -P \"$MSSQL_SA_PASSWORD\" -i {f}",
                         r"\bMsg \d+, Level (1[1-9]|2\d)"),
    "oracle": Recette(("healthcheck.sh",),
                      "echo exit | sqlplus -S app/$APP_USER_PASSWORD"
                      "@//127.0.0.1/FREEPDB1 @{f}", r"\b(ORA|SP2)-\d+",
                      "WHENEVER SQLERROR EXIT SQL.SQLCODE\n"),
    # cqlsh -f continue apres une erreur : la marque est cherchee dans la
    # sortie (« /tmp/x.cql:3:InvalidRequest: Error from server ... »).
    # --request-timeout : 10 s par defaut, trop court pour un CREATE TABLE
    # sur une base fraiche de 8 Go (essai reel du 12/10).
    "cassandra": Recette(("cqlsh", "-e", "DESCRIBE KEYSPACES"),
                         "cqlsh --request-timeout=180 -f {f}",
                         r"(Error from server|SyntaxException|InvalidRequest"
                         r"|ConfigurationException|AlreadyExists"
                         r"|:\d+:\w*(Error|Exception))",
                         lenteur=r"OperationTimedOut|Client request timeout"),
}


def _espace_cql(textes: list[str]) -> tuple[str, str]:
    """(keyspace a choisir, ordre qui le cree) : celui que le projet cree,
    sinon « app », cree par MAEL — un .cql sans keyspace est refuse par
    Cassandra (« No keyspace has been specified »)."""
    for t in textes:
        m = re.search(r'(?i)CREATE\s+KEYSPACE\s+(?:IF\s+NOT\s+EXISTS\s+)?'
                      r'"?(\w+)', t)
        if m:
            return m.group(1), ""
    return ESPACE_CQL, (f"CREATE KEYSPACE IF NOT EXISTS {ESPACE_CQL} WITH "
                        "replication = {'class': 'SimpleStrategy', "
                        "'replication_factor': 1};\n")


@dataclass
class Rapport:
    base: str = ""
    lance: bool = False
    raison: str = ""
    secondes: float = 0.0
    fichiers: list[str] = field(default_factory=list)


dernier_rapport = Rapport()


def _docker(args, delai=60, entree=None):
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          timeout=delai, input=entree)


def base_a_executer(racine: Path, vus: list[str]):
    """La base relationnelle A SERVEUR du projet (pilote dans le code)."""
    code = {}
    for f in vus:
        if Path(f).suffix.lower() in {".py", ".js", ".mjs", ".ts", ".php",
                                      ".java", ".go", ".cs"}:
            try:
                code[f] = (Path(racine) / f).read_text(encoding="utf-8",
                                                       errors="replace")
            except OSError:
                pass
    return next((b for b in bases.detecter("", code)
                 if b.id in RECETTES), None)


def executer(racine: Path, vus: list[str], *, decharger=None
             ) -> list[Defaut]:
    global dernier_rapport
    r = Rapport()
    dernier_rapport = r
    racine = Path(racine)
    b = base_a_executer(racine, vus)
    ext = EXTENSION.get(b.id, ".sql") if b else ".sql"
    sqls = [f for f in vus if f.lower().endswith(ext)]
    if not sqls or b is None:
        r.raison = "aucune base a serveur a rejouer"
        return []
    r.base = b.nom
    if os.environ.get("MAEL_SANS_EXECUTION") == "1":
        r.raison = "desactive (MAEL_SANS_EXECUTION=1)"
        return []
    try:
        # « docker version » : 0,7 s ; « docker info » : 65 s (mesure 09/10).
        if _docker(["version", "--format", "{{.Server.Version}}"],
                   30).returncode:
            r.raison = "Docker ne repond pas (Docker Desktop arrete ?)"
            return []
        if _docker(["image", "inspect", b.image], 30).returncode:
            r.raison = (f"image {b.image} absente — la telecharger une fois : "
                        f"docker pull {b.image}")
            return []
    except (FileNotFoundError, subprocess.TimeoutExpired):
        r.raison = "Docker n'est pas installe ou ne repond pas"
        return []
    if decharger is not None:
        decharger()                     # 8 Go : le modele OU la base
    nom = f"mael-base-{b.id}-{uuid.uuid4().hex[:8]}"
    recette = RECETTES[b.id]
    debut = time.monotonic()
    env = [x for k, v in b.env_docker + ENV_EN_PLUS.get(b.id, ())
           for x in ("-e", f"{k}={v}")]
    d: list[Defaut] = []
    try:
        reseau = "none"
        if b.id in RESEAU_INTERNE:
            # Oracle exige une adresse IP privee (ORA-00600 « ksipc: no
            # private ips avail », 09/10/2026) ; Cassandra se lie a l'adresse
            # du conteneur : un reseau docker INTERNE, sans aucune sortie
            # (ni internet, ni la machine).
            reseau = RESEAU_ISOLE
            if _docker(["network", "inspect", reseau], 30).returncode:
                _docker(["network", "create", "--internal", reseau], 60)
        if _docker(["run", "-d", "--name", nom, "--network", reseau,
                    "--memory", MEMOIRE[b.id], *env, b.image], 120).returncode:
            r.raison = f"le conteneur {b.image} n'a pas demarre"
            return []
        pret = False
        delai = DEMARRAGE[b.id]
        while time.monotonic() - debut < delai:
            try:
                if _docker(["exec", nom, *recette.pret], 60).returncode == 0:
                    pret = True
                    break
            except subprocess.TimeoutExpired:
                # Une sonde lente pendant le demarrage n'est pas un echec
                # (Oracle, 09/10 : sa sonde a pris plus de 30 s) : on
                # reessaie jusqu'au delai de la base.
                pass
            time.sleep(3)
        if not pret:
            r.raison = f"{b.nom} pas prete en {delai} s"
            return []
        espace, creation = "", ""
        if b.id == "cassandra":
            espace, creation = _espace_cql([
                (racine / f).read_text(encoding="utf-8", errors="replace")
                for f in sqls])
        for f in ordre_d_application(sqls):
            cible = f"/tmp/{Path(f).name}"
            source = racine / f
            entete = recette.entete
            if b.id == "cassandra":
                # chaque cqlsh est une session neuve : le keyspace est (cree
                # puis) choisi en tete de chaque fichier qui ne le fait pas.
                texte = source.read_text(encoding="utf-8", errors="replace")
                if not re.search(r"(?im)^\s*USE\s", texte) and \
                        not re.search(r"(?i)CREATE\s+KEYSPACE", texte):
                    entete = f"{creation}USE {espace};\n"
                    creation = ""
            if entete:
                # une copie avec l'en-tete (WHENEVER SQLERROR EXIT pour
                # Oracle, keyspace pour Cassandra) ; le fichier du projet
                # n'est jamais touche.
                import tempfile
                tmp = Path(tempfile.mkdtemp()) / Path(f).name
                tmp.write_text(entete + source.read_text(
                    encoding="utf-8", errors="replace"), encoding="utf-8")
                source = tmp
            _docker(["cp", str(source), f"{nom}:{cible}"], 60)
            res = _docker(["exec", nom, "sh", "-c",
                           recette.appliquer.format(f=cible)],
                          APPLIQUER.get(b.id, 120))
            r.fichiers.append(f)
            sortie = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
            if recette.lenteur and re.search(recette.lenteur, sortie):
                # la base n'a pas repondu a temps : rien n'est juge (les
                # fichiers suivants dependent de celui-ci)
                r.raison = (f"{b.nom} trop lente sur {f} (delai du client "
                            "depasse) : non verifiee")
                return d
            if res.returncode != 0 or re.search(recette.erreur, sortie):
                d.append(Defaut(f, 1, "sql-execution" if ext == ".sql"
                                else "cql-execution", B,
                                f"{b.nom} refuse ce fichier (rejoue apres les "
                                f"precedents) : {sortie[-300:]}",
                                f"execution reelle ({b.nom}, conteneur)",
                                sources=("mael", b.id)))
        r.lance = True
    except subprocess.TimeoutExpired:
        r.raison = f"{b.nom} : delai depasse"
    finally:
        try:
            _docker(["rm", "-f", nom], 60)
        except Exception:                               # noqa: BLE001
            pass
        r.secondes = time.monotonic() - debut
    return d


def limites() -> list[str]:
    r = dernier_rapport
    if r.base and not r.lance and r.raison:
        return [f"base {r.base} non rejouee en vrai : {r.raison}"]
    return []
