# MAEL

**Audit de sécurité et atelier de code, sur votre machine.** Pas de compte,
pas de clé, pas d'envoi de vos données : MAEL utilise le modèle installé chez
vous ([Ollama](https://ollama.com), ou son propre moteur posé par
`mael installer`).

Un projet de **Yelen Tech**, sous licence [Apache 2.0](LICENSE).

---

> **Avertissement.** MAEL audite des machines, et ses playbooks peuvent
> **modifier** un système (avec simulation et confirmation obligatoires).
> N'auditez et ne corrigez que des machines **dont vous avez la
> responsabilité ou l'autorisation écrite**. Le logiciel est fourni sans
> garantie (licence Apache 2.0, sections 7 et 8). Une faille dans MAEL se
> signale en privé : voir [SECURITY.md](SECURITY.md).

## Le principe : le code décide, le modèle propose

Un modèle de langage écrit des choses qui *ont l'air* justes. MAEL ne le croit
pas sur parole :

- ce qui peut être **mesuré** l'est par du code déterministe (juges, tests
  exécutés, comparaisons) ;
- le modèle **explique et propose** ; il ne décide jamais seul ;
- tout ce qui n'a pas pu être vérifié est **dit** dans le bilan — jamais de
  « c'est corrigé » sans preuve.

## Ce que fait MAEL

### 1. Audit de sécurité (`mael`)

Un terminal d'audit Linux qui observe avant de conclure :

- **733 fiches de contrôle** relues, tirées de ComplianceAsCode, avec leurs
  références **CIS** et **ANSSI** ; c'est le code qui juge la conformité, le
  modèle n'explique que les écarts ;
- un **garde-fou** classe chaque commande proposée (lecture / modification /
  interdite) ; rien ne s'exécute sans ce classement ;
- des **playbooks de correction scellés** (empreinte SHA-256) : simulation
  obligatoire, confirmation, re-mesure, retour arrière automatique ;
- un **noyau d'intégrité** : bibliothèque scellée par arbre de Merkle,
  vérifications d'invariants et d'entropie.

### 2. Atelier de code (`mael code "..."`)

Le modèle écrit, **des juges contrôlent** contre des normes nommées
(HTML/W3C, accessibilité WCAG 2.2, sécurité OWASP, injections SQL, suivi de
contamination), le modèle corrige ; on s'arrête quand les juges se taisent,
ou on dit ce qui reste.

- grands projets **découpés en étapes**, avec reprise après coupure ;
- **bases de données** : 12 bases connues (SQLite, PostgreSQL, MySQL, MariaDB,
  SQL Server, Oracle, DuckDB, MongoDB, Redis, Cassandra, Neo4j,
  Elasticsearch), schémas jugés, et **rejoués dans la vraie base** (Docker,
  sans réseau) ;
- fichiers de construction (pom.xml, go.mod, .csproj) aux versions exactes.

### 3. Travailler sur un dépôt existant (`mael code --ticket`)

```bash
mael code --ticket ticket.md --dossier mon-depot
```

1. **index** du dépôt et **localisation** : du ticket aux fichiers et
   fonctions à lire (traces d'erreur, imports, messages, noms) ;
2. un **test qui reproduit** le ticket, écrit d'abord — il doit échouer ;
3. une **correction ciblée** : le modèle ne voit que les extraits utiles et
   ne peut modifier que ce qu'on lui a montré ;
4. les **tests du dépôt avant / après**, dans un conteneur sans réseau :
   aucune régression tolérée ;
5. aucun correctif ne peut **introduire un défaut de sécurité** (eval,
   `shell=True`, SQL construit à la main...) : il est refusé ;
6. un bilan : `.mael/BILAN-TICKET.md`, le correctif `.mael/correctif.diff`,
   et le journal complet des échanges avec le modèle.

### 4. Audit de sécurité d'un dépôt (`mael audit`)

```bash
mael audit mon-depot
```

Trois regards, un seul rapport (`.mael/AUDIT-SECURITE.md`) :

- **secrets oubliés** — [gitleaks](https://github.com/gitleaks/gitleaks) ; les
  valeurs ne sont jamais recopiées dans le rapport ;
- **dépendances et configuration** — [Trivy](https://github.com/aquasecurity/trivy) :
  failles connues (CVE) des dépendances déclarées, avec la version qui
  corrige, et erreurs de Dockerfile, Kubernetes, Terraform ;
- **code** — les juges de MAEL : injections SQL/commande/NoSQL, XSS, secrets en
  dur, hachage faible, CSRF, CORS, désérialisation, Bandit.

Les outils tournent dans des conteneurs **sans réseau, en lecture seule**,
images figées par empreinte ; la base de failles est téléchargée une fois et
sert hors ligne. Un regard qui n'a pas pu tourner (Docker absent) est écrit
**« non vérifié »** — jamais « rien trouvé ». Code de sortie pour
l'intégration continue : `0` propre, `1` faille élevée ou critique, `2` audit
incomplet.

## Installer

Voir **[INSTALLATION.md](INSTALLATION.md)**. En bref : Python 3.12+, puis

```bash
git clone https://github.com/Yelen-Tech/mael.git
python -m venv ~/mael && ~/mael/bin/pip install ./mael/backend
~/mael/bin/mael
```

**Le modèle.** MAEL fonctionne avec le modèle de votre choix (Ollama). Pour
une machine plus puissante, `mael installer` pose en une commande le moteur
[llama.cpp](https://github.com/ggml-org/llama.cpp) et **MAEL-Coder** —
c'est-à-dire [Qwen3-Coder-30B-A3B-Instruct](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct)
(Alibaba Qwen, Apache 2.0), utilisé **tel quel** en version compressée
Q4_K_M (18,6 Go ; 22 Go de mémoire conseillés). Ce n'est pas un modèle
entraîné par Yelen Tech : ce que MAEL ajoute est **autour** du modèle (juges,
vérification, réparation, outils). La commande annonce tout cela avant de
télécharger, vérifie l'empreinte SHA-256 et reprend après une coupure. Sur
une machine à cartes graphiques, MAEL parle aussi à un modèle servi par
[vLLM](https://github.com/vllm-project/vllm) sur la même machine
(`BRAIN_BACKEND=vllm`).

Docker est **facultatif** : il sert à exécuter les tests et à rejouer les
bases de données ; sans lui, MAEL le dit et juge sans exécuter.

## Deux modes

| | **Mode local** (par défaut) | **Mode serveur** (facultatif) |
|---|---|---|
| Pour qui | une personne, sur sa machine | une équipe, sur un serveur qu'elle maîtrise |
| Lancement | `mael` dans le terminal | application web Django |
| Base de données | aucune | PostgreSQL |
| Cache, file d'attente | aucun | Redis |
| Réseau | rien n'écoute sur le réseau | services joignables depuis la machine seulement (`127.0.0.1`), façade web derrière un proxy TLS |
| Fichier concerné | — | `docker-compose.yml` (développement) |

Le **mode local** est celui de l'outil décrit plus haut : il n'a besoin ni de
PostgreSQL, ni de Redis, ni de `docker-compose.yml`. Le **mode serveur** ne
fournit **aucun mot de passe par défaut** : `docker-compose.yml` refuse de
démarrer tant que `POSTGRES_PASSWORD` n'est pas défini dans `.env` (voir
`.env.example`), et les images des outils y sont figées par empreinte
`@sha256`, comme MAEL l'exige à l'exécution.

## Mesures (octobre 2026)

MAEL est mesuré, et les chiffres sont publiés tels quels :

| Mesure | Résultat |
|---|---|
| Tests automatiques du projet (Windows) | 1 467 + 133 (Django), tous verts ; ruff propre |
| Couverture du cœur (`backend/brain`) par ces tests | 87 % des instructions (mesure du 16/10, avant l'ajout des tests des moteurs et du bac à sable) |
| Projets de SWE-bench Lite dont MAEL installe et lance les tests (tests officiels en échec avant le correctif officiel, réussis après) | 10 sur 12, soit 271 tickets sur 300 (matplotlib validé sous Linux le 16/10) ; scikit-learn (« à voir ») et astropy (code de 2017, construction à confirmer) restent |
| Bases de données rejouées en vrai (clé étrangère fautive refusée) | PostgreSQL, MySQL, MariaDB, SQL Server, Oracle, Cassandra |
| pom.xml / go.mod / .csproj produits, résolus par les outils officiels | 36 / 36 |
| Localisation sur 63 tickets réels de SWE-bench Lite (sans modèle, mesure du 12/10) | bon fichier 1er : 29 (46 %) ; dans les 5 premiers : 51 (81 %) ; dans les 10 premiers : 55 (87 %) |
| Choix du fichier par un petit modèle (phi4-mini) parmi ces candidats | aucun gain mesuré (2 tickets gagnés, 2 perdus) : désactivé par défaut |
| Juges ORM (JPA, EF Core, GORM, Eloquent, Doctrine) sur Spring PetClinic, eShopOnWeb, playground GORM | 0 faux défaut |
| Tests d'un dépôt exécutés et lus test par test (Python, Go, Maven, .NET, Node) | 5 langages éprouvés en conteneur |
| `mael audit` sur Vulnerable-Flask-App (application volontairement vulnérable) | 7 critiques, 43 élevées, 23 moyennes ; gitleaks : 3 clés piégées sur 3 |
| Tickets SWE-bench Lite résolus de bout en bout (répétitions des 15-16/10 sur 20 tickets, détail dans [docs/examen-swebench-2026-10.md](docs/examen-swebench-2026-10.md)) | **1 sur 20 (v8, v9) puis 0 sur 20 (v10) en auto-notation stricte** — la v10 teste enfin tout pour de vrai, et les correctifs du modèle échouent majoritairement ; la chaîne, elle, est prouvée (12 reproductions validées, record) ; note officielle sb-cli pas encore calculée |

## Limites connues

- Sur une machine **sans carte graphique**, un petit modèle (3 à 4 milliards
  de paramètres) répond en plusieurs minutes et ne résout pas seul des
  tickets difficiles : MAEL le détecte et le dit. Un modèle plus grand
  change beaucoup les résultats.
- L'agent sur dépôt exécute les tests **Python, Go, Java (Maven), .NET et
  Node** et lit leur résultat **test par test** (éprouvé en conteneur le
  13/10 : un test qui passe, un qui échoue, par langage ; pour Node : jest et
  `node --test` — vitest et mocha ne sont vérifiés que par des tests
  unitaires). Gradle, Cargo et PHPUnit ne sont pas encore pris en charge.
  Sans Docker, seuls les dépôts **Python** sont testés (environnement isolé
  par dépôt, dépendances installées à la date de son code).
- L'audit couvre **Ubuntu 22.04 / 24.04 et Debian 12** (versions de
  ComplianceAsCode intégrées).

## Licence

Apache 2.0 — voir [LICENSE](LICENSE). Les éléments de tiers
(ComplianceAsCode, acorn, axe-core) gardent leurs licences : voir
[NOTICE](NOTICE).
