"""Le SAVOIR des bases de donnees : chaque base, ses pilotes, ses outils.

Demande du responsable (09/10/2026) : « a peu pres toutes les bases, meme si
c'est long, avec leurs dependances » — sans base de donnees, un developpeur
ne fait rien de serieux, et MAEL n'en connaissait aucune (un .sql etait meme
refuse par le lecteur du plan).

Pour chaque base : sa famille, son dialecte SQL (pour sqlglot), son port, son
image Docker (pour l'executer en vrai), l'adresse de connexion type, et, par
LANGAGE, le pilote a installer et l'outil de migration / ORM d'usage. Ce
savoir sert :
  - a la logistique (dependances, .env.example, docker-compose.yml) ;
  - aux juges (le dialecte qui lit le schema) ;
  - au plan (ce que le modele doit prevoir : schema, migrations, donnees).
Les 120 noms de paquets ont ete VERIFIES aupres de leur registre officiel
le 09/10/2026 (PyPI, npm, Packagist, Maven Central, proxy Go, NuGet) ; les
« ext-... » sont des extensions PHP, pas des paquets.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

LANGAGES = ("python", "node", "php", "java", "go", "csharp")


@dataclass(frozen=True)
class Base:
    id: str
    nom: str
    famille: str            # relationnelle | document | cle-valeur | colonnes | graphe | recherche
    dialecte: str = ""      # dialecte sqlglot ("" : pas du SQL)
    port: int = 0
    image: str = ""         # image Docker officielle (etiquette figee)
    url: str = ""           # DATABASE_URL type (sans vrai secret)
    env_docker: tuple[tuple[str, str], ...] = ()
    mots: tuple[str, ...] = ()
    pilotes: dict = field(default_factory=dict)      # langage -> [paquets]
    outils: dict = field(default_factory=dict)       # langage -> [ORM / migrations]

    @property
    def sql(self) -> bool:
        return bool(self.dialecte)

    def pilotes_pour(self, langage: str) -> list[str]:
        return list(self.pilotes.get(langage, []))


_MDP = "changer-moi"          # jamais un vrai secret dans un fichier d'exemple

CATALOGUE: tuple[Base, ...] = (
    Base("sqlite", "SQLite", "relationnelle", "sqlite",
         url="sqlite:///db/app.db",
         mots=("sqlite", "sqlite3", "fichier de base"),
         pilotes={"python": [], "node": ["better-sqlite3"],
                  "php": ["ext-pdo_sqlite"], "java": ["org.xerial:sqlite-jdbc"],
                  "go": ["modernc.org/sqlite"],
                  "csharp": ["Microsoft.Data.Sqlite"]},
         outils={"python": ["sqlalchemy", "alembic"],
                 "node": ["knex", "prisma"],
                 "php": ["doctrine/migrations"],
                 "java": ["org.flywaydb:flyway-core"],
                 "go": ["github.com/golang-migrate/migrate/v4"],
                 "csharp": ["Microsoft.EntityFrameworkCore.Sqlite"]}),
    Base("postgres", "PostgreSQL", "relationnelle", "postgres", 5432,
         "postgres:16-alpine",
         f"postgresql://app:{_MDP}@localhost:5432/app",
         (("POSTGRES_USER", "app"), ("POSTGRES_PASSWORD", _MDP),
          ("POSTGRES_DB", "app")),
         ("postgres", "postgresql", "psql", "supabase", "pgsql"),
         {"python": ["psycopg[binary]"], "node": ["pg"],
          "php": ["ext-pdo_pgsql"], "java": ["org.postgresql:postgresql"],
          "go": ["github.com/jackc/pgx/v5"], "csharp": ["Npgsql"]},
         {"python": ["sqlalchemy", "alembic"], "node": ["prisma", "knex"],
          "php": ["doctrine/migrations"],
          "java": ["org.flywaydb:flyway-database-postgresql"],
          "go": ["github.com/golang-migrate/migrate/v4"],
          "csharp": ["Npgsql.EntityFrameworkCore.PostgreSQL"]}),
    Base("mysql", "MySQL", "relationnelle", "mysql", 3306, "mysql:8.4",
         f"mysql://app:{_MDP}@localhost:3306/app",
         (("MYSQL_USER", "app"), ("MYSQL_PASSWORD", _MDP),
          ("MYSQL_ROOT_PASSWORD", _MDP), ("MYSQL_DATABASE", "app")),
         ("mysql",),
         {"python": ["pymysql"], "node": ["mysql2"], "php": ["ext-pdo_mysql"],
          "java": ["com.mysql:mysql-connector-j"],
          "go": ["github.com/go-sql-driver/mysql"],
          "csharp": ["MySqlConnector"]},
         {"python": ["sqlalchemy", "alembic"], "node": ["prisma", "knex"],
          "php": ["doctrine/migrations"],
          "java": ["org.flywaydb:flyway-mysql"],
          "go": ["github.com/golang-migrate/migrate/v4"],
          "csharp": ["Pomelo.EntityFrameworkCore.MySql"]}),
    Base("mariadb", "MariaDB", "relationnelle", "mysql", 3306, "mariadb:11.4",
         f"mysql://app:{_MDP}@localhost:3306/app",
         (("MARIADB_USER", "app"), ("MARIADB_PASSWORD", _MDP),
          ("MARIADB_ROOT_PASSWORD", _MDP), ("MARIADB_DATABASE", "app")),
         ("mariadb",),
         {"python": ["pymysql"], "node": ["mariadb"], "php": ["ext-pdo_mysql"],
          "java": ["org.mariadb.jdbc:mariadb-java-client"],
          "go": ["github.com/go-sql-driver/mysql"],
          "csharp": ["MySqlConnector"]},
         {"python": ["sqlalchemy", "alembic"], "node": ["knex"],
          "php": ["doctrine/migrations"],
          "java": ["org.flywaydb:flyway-mysql"],
          "go": ["github.com/golang-migrate/migrate/v4"],
          "csharp": ["Pomelo.EntityFrameworkCore.MySql"]}),
    Base("sqlserver", "SQL Server", "relationnelle", "tsql", 1433,
         "mcr.microsoft.com/mssql/server:2022-latest",
         f"mssql://sa:{_MDP}@localhost:1433/app",
         (("ACCEPT_EULA", "Y"), ("MSSQL_SA_PASSWORD", "Changer-moi-1")),
         ("sql server", "sqlserver", "mssql", "t-sql", "tsql", "azure sql"),
         {"python": ["pyodbc"], "node": ["mssql"], "php": ["ext-pdo_sqlsrv"],
          "java": ["com.microsoft.sqlserver:mssql-jdbc"],
          "go": ["github.com/microsoft/go-mssqldb"],
          "csharp": ["Microsoft.Data.SqlClient"]},
         {"python": ["sqlalchemy", "alembic"], "node": ["prisma", "knex"],
          "php": ["doctrine/migrations"],
          "java": ["org.flywaydb:flyway-sqlserver"],
          "go": ["github.com/golang-migrate/migrate/v4"],
          "csharp": ["Microsoft.EntityFrameworkCore.SqlServer"]}),
    Base("oracle", "Oracle", "relationnelle", "oracle", 1521,
         "gvenzl/oracle-free:23-slim",
         f"oracle://app:{_MDP}@localhost:1521/FREEPDB1",
         (("ORACLE_PASSWORD", _MDP), ("APP_USER", "app"),
          ("APP_USER_PASSWORD", _MDP)),
         ("oracle", "plsql", "pl/sql"),
         {"python": ["oracledb"], "node": ["oracledb"], "php": ["ext-oci8"],
          "java": ["com.oracle.database.jdbc:ojdbc11"],
          "go": ["github.com/sijms/go-ora/v2"],
          "csharp": ["Oracle.ManagedDataAccess.Core"]},
         {"python": ["sqlalchemy", "alembic"], "node": ["knex"],
          "php": ["doctrine/migrations"],
          "java": ["org.flywaydb:flyway-database-oracle"],
          "go": ["github.com/golang-migrate/migrate/v4"],
          "csharp": ["Oracle.EntityFrameworkCore"]}),
    Base("duckdb", "DuckDB", "relationnelle", "duckdb",
         url="duckdb:///db/analyse.duckdb", mots=("duckdb",),
         pilotes={"python": ["duckdb"], "node": ["@duckdb/node-api"],
                  "java": ["org.duckdb:duckdb_jdbc"],
                  "go": ["github.com/marcboeker/go-duckdb"],
                  "csharp": ["DuckDB.NET.Data.Full"]}),
    Base("mongodb", "MongoDB", "document", "", 27017, "mongo:7",
         "mongodb://localhost:27017/app", (),
         ("mongodb", "mongo", "mongoose", "nosql", "atlas"),
         {"python": ["pymongo"], "node": ["mongodb"],
          "php": ["mongodb/mongodb"], "java": ["org.mongodb:mongodb-driver-sync"],
          "go": ["go.mongodb.org/mongo-driver/v2"], "csharp": ["MongoDB.Driver"]},
         {"python": ["beanie"], "node": ["mongoose"],
          "php": ["doctrine/mongodb-odm"],
          "java": ["org.springframework.data:spring-data-mongodb"],
          "go": [], "csharp": ["MongoDB.EntityFrameworkCore"]}),
    Base("redis", "Redis", "cle-valeur", "", 6379, "redis:7-alpine",
         "redis://localhost:6379/0", (),
         ("redis", "cache", "file d'attente", "session"),
         {"python": ["redis"], "node": ["redis"], "php": ["predis/predis"],
          "java": ["redis.clients:jedis"], "go": ["github.com/redis/go-redis/v9"],
          "csharp": ["StackExchange.Redis"]}),
    Base("cassandra", "Cassandra", "colonnes", "", 9042, "cassandra:5",
         "cassandra://localhost:9042/app", (),
         ("cassandra", "scylla", "cql"),
         {"python": ["cassandra-driver"], "node": ["cassandra-driver"],
          "java": ["org.apache.cassandra:java-driver-core"],
          "go": ["github.com/gocql/gocql"],
          "csharp": ["CassandraCSharpDriver"]}),
    Base("neo4j", "Neo4j", "graphe", "", 7687, "neo4j:5",
         "neo4j://localhost:7687", (("NEO4J_AUTH", f"neo4j/{_MDP}"),),
         ("neo4j", "graphe", "cypher"),
         {"python": ["neo4j"], "node": ["neo4j-driver"],
          "php": ["laudis/neo4j-php-client"],
          "java": ["org.neo4j.driver:neo4j-java-driver"],
          "go": ["github.com/neo4j/neo4j-go-driver/v5"],
          "csharp": ["Neo4j.Driver"]}),
    Base("elasticsearch", "Elasticsearch", "recherche", "", 9200,
         "elasticsearch:9.5.5", "http://localhost:9200",
         (("discovery.type", "single-node"), ("xpack.security.enabled",
                                               "false")),
         ("elasticsearch", "elastic", "opensearch", "recherche plein texte"),
         {"python": ["elasticsearch"], "node": ["@elastic/elasticsearch"],
          "php": ["elasticsearch/elasticsearch"],
          "java": ["co.elastic.clients:elasticsearch-java"],
          "go": ["github.com/elastic/go-elasticsearch/v9"],
          "csharp": ["Elastic.Clients.Elasticsearch"]}),
)
PAR_ID = {b.id: b for b in CATALOGUE}


# Versions STABLES des paquets Java, Go et C# : pom.xml, go.mod et .csproj
# exigent un numero exact, et MAEL travaille hors ligne. Relevees le
# 09/10/2026 dans les registres officiels (Maven Central, proxy Go, NuGet) ;
# a relever de nouveau a chaque version de MAEL.
# La directive « go » du go.mod : au moins l'exigence la plus haute des
# modules ci-dessous, RELEVEE en vrai (essai du 10/10/2026, Go en
# GOTOOLCHAIN=local) : go-redis v9.23 exige 1.26.0, golang-migrate v4.20
# 1.25.11, mongo-driver v2.9 1.25.0, go-sql-driver/mysql et go-duckdb 1.24.
# « go 1.23 » (avant) : aucun de ces projets ne se construisait.
GO_VERSION = "1.26.0"

VERSIONS = {
    "CassandraCSharpDriver": "3.23.0",
    "DuckDB.NET.Data.Full": "1.5.6",
    "Elastic.Clients.Elasticsearch": "9.5.3",
    "Microsoft.Data.SqlClient": "7.1.1",
    "Microsoft.Data.Sqlite": "10.0.12",
    "Microsoft.EntityFrameworkCore.SqlServer": "10.0.12",
    "Microsoft.EntityFrameworkCore.Sqlite": "10.0.12",
    "MongoDB.Driver": "3.12.0",
    "MongoDB.EntityFrameworkCore": "10.0.4",
    "MySqlConnector": "2.6.2",
    "Neo4j.Driver": "6.3.0",
    "Npgsql": "10.0.3",
    "Npgsql.EntityFrameworkCore.PostgreSQL": "10.0.3",
    "Oracle.EntityFrameworkCore": "10.23.26301",
    "Oracle.ManagedDataAccess.Core": "23.26.301",
    "Pomelo.EntityFrameworkCore.MySql": "9.0.0",
    "StackExchange.Redis": "3.4.0",
    "co.elastic.clients:elasticsearch-java": "9.5.5",
    "com.microsoft.sqlserver:mssql-jdbc": "13.6.0.jre11",
    "com.mysql:mysql-connector-j": "26.7.0",
    "com.oracle.database.jdbc:ojdbc11": "23.26.3.0.0",
    "github.com/elastic/go-elasticsearch/v9": "v9.5.2",
    "github.com/go-sql-driver/mysql": "v1.10.1",
    "github.com/gocql/gocql": "v1.7.0",
    "github.com/golang-migrate/migrate/v4": "v4.20.1",
    "github.com/jackc/pgx/v5": "v5.11.0",
    "github.com/marcboeker/go-duckdb": "v1.8.5",
    "github.com/microsoft/go-mssqldb": "v1.11.2",
    "github.com/neo4j/neo4j-go-driver/v5": "v5.28.5",
    "github.com/redis/go-redis/v9": "v9.23.0",
    "github.com/sijms/go-ora/v2": "v2.9.0",
    "go.mongodb.org/mongo-driver/v2": "v2.9.2",
    "modernc.org/sqlite": "v1.60.1",
    "org.apache.cassandra:java-driver-core": "4.19.3",
    "org.duckdb:duckdb_jdbc": "1.5.6.0",
    "org.flywaydb:flyway-core": "13.10.0",
    "org.flywaydb:flyway-database-oracle": "13.10.0",
    "org.flywaydb:flyway-database-postgresql": "13.10.0",
    "org.flywaydb:flyway-mysql": "13.10.0",
    "org.flywaydb:flyway-sqlserver": "13.10.0",
    "org.mariadb.jdbc:mariadb-java-client": "3.5.10",
    "org.mongodb:mongodb-driver-sync": "5.13.0",
    "org.neo4j.driver:neo4j-java-driver": "6.3.0",
    "org.postgresql:postgresql": "42.7.14",
    "org.springframework.data:spring-data-mongodb": "5.1.1",
    "org.xerial:sqlite-jdbc": "3.53.4.0",
    "redis.clients:jedis": "8.0.2",
}

# Les mots qui disent « une base » sans dire laquelle.
_BASE_VAGUE = re.compile(r"\b(base de donn[ée]es|bdd|database|\bdb\b|"
                         r"enregistr|persist|stock(?:e|er|age)\b)", re.I)
# Les pilotes reconnus dans le CODE (import / require / use / using).
_PILOTE_CODE = {
    "sqlite": r"\bimport sqlite3\b|better-sqlite3|['\"]sqlite3['\"]|"
              r"sqlite:///|new PDO\(\s*['\"]sqlite:",
    "postgres": r"psycopg|asyncpg|require\(\s*['\"]pg['\"]|from ['\"]pg['\"]|"
                r"postgres(?:ql)?://|pgsql:|Npgsql|jackc/pgx",
    "mysql": r"pymysql|mysqlclient|mysql2|mysql://|mysql:host|"
             r"mysql-connector|go-sql-driver/mysql|MySqlConnector",
    "mariadb": r"['\"]mariadb['\"]|\bimport mariadb\b|mariadb-java-client|"
               r"mariadb://",
    "sqlserver": r"pyodbc|['\"]mssql['\"]|sqlsrv:|SqlClient|go-mssqldb",
    "oracle": r"oracledb|cx_Oracle|oci_connect|ojdbc|go-ora",
    "duckdb": r"\bduckdb\b",
    "mongodb": r"pymongo|motor\.|['\"]mongodb['\"]|mongoose|mongodb://|"
               r"MongoDB\.Driver",
    "redis": r"\bimport redis\b|['\"]redis['\"]|ioredis|redis://|predis|"
             r"StackExchange\.Redis|go-redis",
    "cassandra": r"cassandra(?:-driver|\.cluster)|gocql",
    "neo4j": r"\bneo4j\b",
    "elasticsearch": r"elasticsearch",
}


def detecter(demande: str = "", textes: dict[str, str] | None = None
             ) -> list[Base]:
    """Les bases du projet : nommees dans la demande, ou reconnues dans le
    code (pilotes importes). Ordre du catalogue, sans doublon."""
    d = (demande or "").lower()
    code = "\n".join((textes or {}).values())
    trouvees = []
    for b in CATALOGUE:
        nommee = any(re.search(rf"(?<![\w-]){re.escape(m)}(?![\w-])", d)
                     for m in b.mots if m not in {"cache", "session",
                                                  "graphe", "nosql"})
        if nommee or (code and re.search(_PILOTE_CODE[b.id], code)):
            trouvees.append(b)
    # MariaDB est aussi lu « mysql:// » : on ne garde pas les deux par erreur.
    if PAR_ID["mariadb"] in trouvees and PAR_ID["mysql"] in trouvees \
            and "mysql" not in d:
        trouvees.remove(PAR_ID["mysql"])
    return trouvees


def base_par_defaut(demande: str) -> Base | None:
    """« une API avec une base de donnees » sans dire laquelle : SQLite
    (aucun serveur a installer) — une SUPPOSITION, dite comme telle."""
    if detecter(demande):
        return None
    return PAR_ID["sqlite"] if _BASE_VAGUE.search(demande or "") else None


def langage_du_projet(sorte: str) -> str:
    """Le type d'arborescence -> la langue des pilotes."""
    return {"python": "python", "django": "python", "node": "node",
            "react": "node", "php": "php", "java": "java", "go": "go",
            "csharp": "csharp"}.get(sorte, "")
