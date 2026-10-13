"""Les ORM de Java, C#, Go et PHP (point 5, 13/10/2026) : un projet JUSTE
ne donne aucun defaut, chaque faute posee est trouvee, et un modele qu'on ne
voit pas en entier ne donne jamais de « champ inconnu »."""
import pytest

from brain.codage import juges_orm, juges_sql
from brain.codage.juges_orm_langages import pluriel, serpent


def _juger(tmp_path, fichiers: dict[str, str]):
    for nom, texte in fichiers.items():
        p = tmp_path / nom
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texte, encoding="utf-8")
    return juges_sql.juger(tmp_path, list(fichiers))


def _regles(d):
    return sorted(x.regle for x in d)


SCHEMA = """
CREATE TABLE clients (id INTEGER PRIMARY KEY, nom TEXT NOT NULL,
                      ville TEXT, created_at TEXT);
CREATE TABLE commandes (id INTEGER PRIMARY KEY,
                        client_id INTEGER REFERENCES clients(id),
                        montant INTEGER NOT NULL);
"""


@pytest.mark.parametrize("nom,attendu", [
    ("UserID", "user_id"), ("HTTPServer", "http_server"),
    ("CreatedAt", "created_at"), ("Client", "client"), ("ID", "id")])
def test_serpent(nom, attendu):
    assert serpent(nom) == attendu


@pytest.mark.parametrize("mot,attendu", [
    ("client", "clients"), ("category", "categories"), ("box", "boxes"),
    ("day", "days"), ("commande", "commandes")])
def test_pluriel(mot, attendu):
    assert pluriel(mot) == attendu


# ------------------------------------------------------------------ Java
JAVA_CLIENT = """package app.model;

import jakarta.persistence.*;
import java.util.List;

@Entity
@Table(name = "clients")
public class Client {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, length = 120)
    private String nom;

    private String ville;

    @OneToMany(mappedBy = "client")
    private List<Commande> commandes;

    @Transient
    private String libelle;

    private static final long serialVersionUID = 1L;

    public String getNom() { return nom; }
    public void setNom(String nom) { this.nom = nom; }
}
"""
JAVA_COMMANDE = """package app.model;

import jakarta.persistence.*;

@Entity
@Table(name = "commandes")
public class Commande {
    @Id @GeneratedValue
    private Long id;

    @ManyToOne
    @JoinColumn(name = "client_id")
    private Client client;

    private Integer montant;
}
"""
JAVA_DEPOT = """package app.repo;

import app.model.Client;
import org.springframework.data.jpa.repository.*;
import java.util.List;

public interface ClientRepository extends JpaRepository<Client, Long> {
    List<Client> findByVilleAndNomContainingIgnoreCase(String v, String n);
    List<Client> findByNomOrderByVilleDesc(String n);
    long countByVilleIsNull();
    List<Client> findByCommandesMontantGreaterThan(Integer m);
    %s
}
"""


def _java(depot_en_plus=""):
    return {"db/schema.sql": SCHEMA,
            "src/main/java/app/model/Client.java": JAVA_CLIENT,
            "src/main/java/app/model/Commande.java": JAVA_COMMANDE,
            "src/main/java/app/repo/ClientRepository.java":
                JAVA_DEPOT % depot_en_plus}


def test_jpa_juste(tmp_path):
    assert _juger(tmp_path, _java()) == []


def test_jpa_requete_derivee_fautive(tmp_path):
    d = _juger(tmp_path, _java("List<Client> findByVileAndNom(String v, "
                               "String n);"))
    assert _regles(d) == ["orm-champ-inconnu"]
    assert "« vile »" in d[0].message


def test_jpa_query_ecrite_non_jugee(tmp_path):
    d = _juger(tmp_path, _java('@Query("select c from Client c")\n'
                               "    List<Client> findByTruc();"))
    assert d == []


def test_jpa_requete_native_jugee(tmp_path):
    d = _juger(tmp_path, _java('@Query(value = "SELECT * FROM client", '
                               "nativeQuery = true)\n"
                               "    List<Client> tous();"))
    assert _regles(d) == ["sql-table-inconnue"]


def test_jpa_colonne_et_table_absentes(tmp_path):
    f = _java()
    f["src/main/java/app/model/Client.java"] = JAVA_CLIENT.replace(
        "private String ville;", '@Column(name = "telephone")\n'
                                 "    private String tel;")
    f["src/main/java/app/model/Commande.java"] = JAVA_COMMANDE.replace(
        'name = "commandes"', 'name = "ventes"')
    f["src/main/java/app/repo/ClientRepository.java"] = JAVA_DEPOT.replace(
        "findByVilleAndNom", "findByTelAndNom").replace(
        "OrderByVilleDesc", "OrderByTelDesc").replace(
        "countByVilleIsNull", "countByTelIsNull") % ""
    d = _juger(tmp_path, f)
    assert _regles(d) == ["orm-colonne-absente", "orm-table-absente"]
    assert any("« telephone »" in x.message for x in d)


def test_jpa_cle_etrangere_par_defaut(tmp_path):
    f = _java()
    f["src/main/java/app/model/Commande.java"] = JAVA_COMMANDE.replace(
        '@JoinColumn(name = "client_id")\n', "")
    assert _juger(tmp_path, f) == []        # client -> client_id


def test_jpa_parent_inconnu_jamais_de_champ_inconnu(tmp_path):
    f = _java("List<Client> findByCreeLe(String d);")
    f["src/main/java/app/model/Client.java"] = JAVA_CLIENT.replace(
        "public class Client {", "public class Client extends Auditable {")
    assert _juger(tmp_path, f) == []


def test_jpa_parent_mapped_superclass_lu(tmp_path):
    f = _java("List<Client> findByCreatedAtAfter(String d);")
    f["src/main/java/app/model/Client.java"] = JAVA_CLIENT.replace(
        "public class Client {", "public class Client extends Base {")
    f["src/main/java/app/model/Base.java"] = (
        "package app.model;\nimport jakarta.persistence.*;\n"
        "@MappedSuperclass\npublic abstract class Base {\n"
        "    private String createdAt;\n}\n")
    assert _juger(tmp_path, f) == []
    f["src/main/java/app/repo/ClientRepository.java"] = JAVA_DEPOT % \
        "List<Client> findByUpdatedAtAfter(String d);"
    assert _regles(_juger(tmp_path, f)) == ["orm-champ-inconnu"]


def test_jpa_commentaire_et_chaine_de_parents(tmp_path):
    """« a base class for objects » dans un commentaire n'est pas une
    classe ; Client -> Nomme -> Base, deux @MappedSuperclass (PetClinic)."""
    f = _java("List<Client> findByLibelleCourtAndCreatedAt(String l, "
              "String d);")
    f["src/main/java/app/model/Client.java"] = JAVA_CLIENT.replace(
        "public class Client {", "public class Client extends Nomme {")
    f["src/main/java/app/model/Nomme.java"] = (
        "package app.model;\nimport jakarta.persistence.*;\n"
        "/**\n * Adds a name. Used as a base class for objects needing it.\n"
        " */\n@MappedSuperclass\npublic class Nomme extends Base {\n"
        "    private String libelleCourt; // { pas un bloc ;\n}\n")
    f["src/main/java/app/model/Base.java"] = (
        "package app.model;\nimport jakarta.persistence.*;\n"
        "@MappedSuperclass\npublic abstract class Base {\n"
        "    private String createdAt;\n}\n")
    schema = SCHEMA.replace("ville TEXT,", "ville TEXT, libelle_court TEXT,")
    f["db/schema.sql"] = schema
    assert _juger(tmp_path, f) == []
    f["src/main/java/app/repo/ClientRepository.java"] = JAVA_DEPOT % \
        "List<Client> findByLibelleLong(String l);"
    assert _regles(_juger(tmp_path, f)) == ["orm-champ-inconnu"]


# -------------------------------------------------------------------- C#
CS_MODELES = """namespace App.Models;

public class Client
{
    public int Id { get; set; }
    public string Nom { get; set; } = "";
    public string? Ville { get; set; }
    public List<Commande> Commandes { get; set; } = new();
    [NotMapped]
    public string Libelle => Nom;
}

[Table("commandes")]
public class Commande
{
    public int Id { get; set; }
    [Column("client_id")]
    public int ClientId { get; set; }
    public Client Client { get; set; } = null!;
    public int Montant { get; set; }
}
"""
CS_CONTEXTE = """using Microsoft.EntityFrameworkCore;
namespace App.Data;

public class BoutiqueContext : DbContext
{
    public DbSet<Client> Clients { get; set; }
    public DbSet<Commande> Commandes { get; set; }
}
"""
CS_SERVICE = """namespace App.Services;

public class ClientService
{
    private readonly BoutiqueContext _db;
    public List<Client> ParVille(string v) =>
        _db.Clients.Where(c => c.Ville == v && c.Nom != "").ToList();
    public bool Gros() => _db.Commandes.Any(x => x.Montant > 5000);
    %s
}
"""


def _cs(en_plus=""):
    return {"db/schema.sql": SCHEMA, "Models/Modeles.cs": CS_MODELES,
            "Data/BoutiqueContext.cs": CS_CONTEXTE,
            "Services/ClientService.cs": CS_SERVICE % en_plus}


def test_efcore_juste(tmp_path):
    assert _juger(tmp_path, _cs()) == []


def test_efcore_linq_fautif(tmp_path):
    d = _juger(tmp_path, _cs("public int N(string v) => "
                             "_db.Clients.Count(c => c.Vile == v);"))
    assert _regles(d) == ["orm-champ-inconnu"]
    assert "« Vile »" in d[0].message


def test_efcore_colonne_absente(tmp_path):
    f = _cs()
    f["Models/Modeles.cs"] = CS_MODELES.replace(
        "public int Montant", "public string Statut { get; set; } = \"\";\n"
                              "    public int Montant")
    d = _juger(tmp_path, f)
    assert _regles(d) == ["orm-colonne-absente"]
    assert "« statut »" in d[0].message


def test_efcore_snake_case(tmp_path):
    f = _cs()
    f["Models/Modeles.cs"] = CS_MODELES.replace('[Column("client_id")]\n', "")
    assert _regles(_juger(tmp_path, f)) == ["orm-colonne-absente"]  # ClientId
    f["Data/BoutiqueContext.cs"] = CS_CONTEXTE.replace(
        "{\n    public DbSet", "{\n    protected override void OnConfiguring("
        "DbContextOptionsBuilder o) => o.UseSnakeCaseNamingConvention();\n"
        "    public DbSet", 1)
    assert _juger(tmp_path, f) == []


def test_efcore_configuration_to_table(tmp_path):
    f = _cs()
    f["Data/Config/ClientConfiguration.cs"] = (
        "public class ClientConfiguration : IEntityTypeConfiguration<Client>\n"
        "{\n    public void Configure(EntityTypeBuilder<Client> builder)\n"
        "    {\n        builder.ToTable(\"Clientele\");\n    }\n}\n")
    d = _juger(tmp_path, f)
    assert _regles(d) == ["orm-table-absente"]
    assert "« clientele »" in d[0].message


def test_efcore_parent_inconnu(tmp_path):
    f = _cs("public int N() => _db.Clients.Count(c => c.CreeLe != null);")
    f["Models/Modeles.cs"] = CS_MODELES.replace(
        "public class Client\n", "public class Client : EntiteAuditee\n")
    assert _juger(tmp_path, f) == []


# -------------------------------------------------------------------- Go
GO_MODELES = """package models

import "gorm.io/gorm"

type Client struct {
	gorm.Model
	Nom       string `gorm:"size:120;not null"`
	Ville     string
	Commandes []Commande
	Cache     string `gorm:"-"`
}

type Commande struct {
	ID       uint
	ClientID uint
	Client   Client
	Montant  int
}
"""
GO_SCHEMA = SCHEMA.replace("created_at TEXT", "created_at TEXT, "
                           "updated_at TEXT, deleted_at TEXT")


def test_gorm_juste(tmp_path):
    assert _juger(tmp_path, {"db/schema.sql": GO_SCHEMA,
                             "models/models.go": GO_MODELES}) == []


def test_gorm_fautif(tmp_path):
    code = GO_MODELES.replace("\tVille     string\n",
                              "\tVille     string\n"
                              "\tTel       string `gorm:\"column:telephone\"`\n")
    d = _juger(tmp_path, {"db/schema.sql": SCHEMA, "models/models.go": code})
    assert _regles(d) == ["orm-colonne-absente"] * 3
    assert {x.message.split("« ")[1].split(" »")[0] for x in d} == {
        "telephone", "updated_at", "deleted_at"}


def test_gorm_table_name(tmp_path):
    code = GO_MODELES + ('\nfunc (Commande) TableName() string '
                         '{ return "ventes" }\n')
    d = _juger(tmp_path, {"db/schema.sql": GO_SCHEMA,
                          "models/models.go": code})
    assert _regles(d) == ["orm-table-absente"]


# ------------------------------------------------------------------- PHP
PHP_CLIENT = """<?php
namespace App\\Models;

use Illuminate\\Database\\Eloquent\\Model;

class Client extends Model
{
    protected $fillable = ['nom', 'ville'];

    public function commandes()
    {
        return $this->hasMany(Commande::class);
    }
}
"""
PHP_CTRL = """<?php
namespace App\\Http\\Controllers;

use App\\Models\\Client;

class ClientController extends Controller
{
    public function store($r)
    {
        return Client::create(['nom' => $r->nom, 'ville' => $r->ville,
                               'meta' => ['a' => 1]]);
    }

    public function index()
    {
        return Client::where('ville', 'Bobo')->orderBy('nom')->get();
    }
}
"""


def test_eloquent_juste(tmp_path):
    ctrl = PHP_CTRL.replace(",\n                               'meta' => "
                            "['a' => 1]", "")
    assert _juger(tmp_path, {"db/schema.sql": SCHEMA,
                             "app/Models/Client.php": PHP_CLIENT,
                             "app/Http/Controllers/ClientController.php":
                                 ctrl}) == []


def test_eloquent_hors_fillable_et_colonne(tmp_path):
    ctrl = PHP_CTRL.replace("where('ville'", "where('vile'")
    d = _juger(tmp_path, {"db/schema.sql": SCHEMA,
                          "app/Models/Client.php": PHP_CLIENT,
                          "app/Http/Controllers/ClientController.php": ctrl})
    assert _regles(d) == ["orm-champ-inconnu", "orm-champ-inconnu"]
    assert any("« meta »" in x.message and "fillable" in x.message for x in d)
    assert any("« vile »" in x.message for x in d)
    assert not any("« a »" in x.message for x in d)    # cle imbriquee


def test_eloquent_guarded_vide_pas_de_defaut(tmp_path):
    modele = PHP_CLIENT.replace("$fillable = ['nom', 'ville'];",
                                "$guarded = [];")
    d = _juger(tmp_path, {"db/schema.sql": SCHEMA,
                          "app/Models/Client.php": modele,
                          "app/Http/Controllers/ClientController.php":
                              PHP_CTRL})
    assert d == []


def test_eloquent_sans_schema_requete_sql_non_jugee(tmp_path):
    """Sans .sql, la table d'Eloquent est connue mais pas ses colonnes : le
    SQL ecrit a la main n'y est pas juge colonne par colonne."""
    ctrl = PHP_CTRL.replace(",\n                               'meta' => "
                            "['a' => 1]", "") + (
        '\n$n = DB::select("SELECT telephone FROM clients WHERE id = ?", '
        '[1]);\n')
    d = _juger(tmp_path, {"app/Models/Client.php": PHP_CLIENT,
                          "app/Http/Controllers/ClientController.php": ctrl})
    assert d == []


PHP_DOCTRINE = """<?php
namespace App\\Entity;

use Doctrine\\ORM\\Mapping as ORM;

#[ORM\\Entity(repositoryClass: ClientRepository::class)]
#[ORM\\Table(name: 'clients')]
class Client
{
    #[ORM\\Id]
    #[ORM\\GeneratedValue]
    #[ORM\\Column]
    private ?int $id = null;

    #[ORM\\Column(length: 120)]
    private ?string $nom = null;

    #[ORM\\Column(name: 'ville', nullable: true)]
    private ?string $commune = null;

    #[ORM\\OneToMany(mappedBy: 'client', targetEntity: Commande::class)]
    private Collection $commandes;

    public function getNom(): ?string
    {
        return $this->nom;
    }
}
"""


def test_doctrine(tmp_path):
    assert _juger(tmp_path, {"db/schema.sql": SCHEMA,
                             "src/Entity/Client.php": PHP_DOCTRINE}) == []
    faux = PHP_DOCTRINE.replace("name: 'ville'", "name: 'commune'")
    d = _juger(tmp_path, {"db/schema.sql": SCHEMA,
                          "src/Entity/Client.php": faux})
    assert _regles(d) == ["orm-colonne-absente"]
    assert "« commune »" in d[0].message


def test_modeles_lus_par_langage(tmp_path):
    fichiers = {**_java(), **_cs(), "models/models.go": GO_MODELES,
                "app/Models/Client.php": PHP_CLIENT}
    for nom, texte in fichiers.items():
        p = tmp_path / nom
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texte, encoding="utf-8")
    orms = sorted({m.orm for m in juges_orm.modeles_du_projet(
        tmp_path, list(fichiers))})
    assert orms == ["efcore", "eloquent", "gorm", "jpa"]


# ------------------------------ SQL : constats de l'essai sur PetClinic
def test_schema_par_base_lu_dans_son_dialecte(tmp_path):
    from brain.codage.juges_sql import dialecte_du_chemin
    assert dialecte_du_chemin("db/h2/schema.sql") == ""
    assert dialecte_du_chemin("db/postgres/schema.sql") == "postgres"
    assert dialecte_du_chemin("resources/schema-mysql.sql") == "mysql"
    assert dialecte_du_chemin("db/schema.sql") is None
    h2 = ("DROP TABLE clients IF EXISTS;\n"
          "CREATE TABLE clients (id INTEGER IDENTITY PRIMARY KEY, nom TEXT);\n")
    mysql = ("CREATE TABLE clients (id INT AUTO_INCREMENT PRIMARY KEY, "
             "nom TEXT) ENGINE=InnoDB;\n")
    d = _juger(tmp_path, {"db/h2/schema.sql": h2,
                          "db/mysql/schema.sql": mysql})
    assert [x for x in d if x.gravite.value == "bloquant"] == []


def test_table_de_liaison_sans_cle_conseil(tmp_path):
    schema = SCHEMA + """
CREATE TABLE client_tags (client_id INTEGER NOT NULL,
                          tag_id INTEGER NOT NULL,
                          FOREIGN KEY (client_id) REFERENCES clients(id),
                          FOREIGN KEY (tag_id) REFERENCES commandes(id));
CREATE TABLE journal (message TEXT, quand TEXT);
"""
    d = _juger(tmp_path, {"db/schema.sql": schema})
    par_table = {x.message.split("« ")[1].split(" »")[0]: x.gravite.value
                 for x in d if x.regle == "sql-sans-cle"}
    assert par_table == {"client_tags": "conseil", "journal": "bloquant"}
