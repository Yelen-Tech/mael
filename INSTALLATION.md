# Installer MAEL

MAEL est un outil d'audit et de cybersécurité qui tourne **sur votre
machine**, avec **votre** modèle local. Pas de compte, pas de clé, pas
d'envoi de vos données : il n'ouvre aucun port et ne contacte rien d'autre
que l'Ollama qui tourne chez vous.

## Ce qu'il vous faut

1. **Python 3.12 ou plus récent** — `python --version` pour vérifier.
2. **[Ollama](https://ollama.com/download)** installé et lancé (`ollama serve`).
3. **Un modèle**, celui que vous avez déjà. Si vous n'en avez aucun :
   `ollama pull qwen2.5:3b` (1,8 Go, tourne sans carte graphique).

MAEL prend le meilleur modèle installé **qui tient dans la mémoire de votre
machine**. Il ne télécharge jamais rien tout seul.

## Installer

Le paquet Python est dans le dossier `backend/` du dépôt.

**Linux / macOS :**

```bash
git clone https://github.com/Yelen-Tech/mael.git
python3 -m venv ~/mael
~/mael/bin/pip install ./mael/backend
~/mael/bin/mael
```

**Windows (PowerShell) :**

```powershell
git clone https://github.com/Yelen-Tech/mael.git
python -m venv $HOME\mael
$HOME\mael\Scripts\pip install .\mael\backend
$HOME\mael\Scripts\mael
```

Sans cloner : `pip install "mael @ git+https://github.com/Yelen-Tech/mael.git#subdirectory=backend"`.

C'est tout. Aucune base de données, aucune migration, aucun serveur.

### « mael : commande introuvable » ?

C'est normal, et ce n'est pas une panne : la commande vit **dans
l'environnement que vous venez de créer**, pas dans votre PATH. Deux
façons de faire, au choix :

- **donner le chemin**, comme ci-dessus (`~/mael/bin/mael`, ou sous Windows
  `$HOME\mael\Scripts\mael`) ;
- **activer l'environnement une fois**, puis taper `mael` tout court :

```bash
source ~/mael/bin/activate      # Linux / macOS
```
```powershell
$HOME\mael\Scripts\Activate.ps1   # Windows
```

L'activation ne vaut que pour la fenêtre ouverte : à la suivante, il faut la
refaire (ou garder le chemin complet).

### Sans Internet

Depuis une machine connectée, préparez le jeu de paquets une fois :

```bash
pip download -d roues -r backend/requirements-local.txt
pip wheel --no-deps -w roues backend/
```

Copiez le dossier `roues/` sur la machine hors ligne, puis :

```bash
python -m venv monenv
monenv/bin/pip install --no-index --find-links roues mael
monenv/bin/mael
```

Le jeu de roues est propre à un système et à une version de Python :
préparez-le depuis une machine du même type que la machine visée.

## Premières commandes

```bash
mael                      # le terminal : posez vos questions en français
mael modeles              # ce qui est installé chez vous, et lequel sert
mael modeles --utiliser <nom>   # en changer
```

Dans le terminal : `/aide` liste les commandes, `/parametres` les réglages,
`/q` pour quitter.

## Où MAEL écrit

Tout reste chez vous, dans `~/.mael/` :

| Fichier | Contenu |
|---|---|
| `reglages.json` | vos préférences (thème, modèle, largeur…) |
| `audits/` | vos audits, un fichier par audit |
| `historique` | les lignes que vous avez tapées |
| `cle` | la clé de signature tirée au premier lancement |

Pour déplacer le tout : `MAEL_DOSSIER=/un/autre/chemin`.

## Ce que MAEL ne fait pas

- il **n'exécute rien** sans votre accord : par défaut il est en simulation,
  il montre la commande et son classement ; `mael --executer` autorise les
  **lectures** ;
- il **n'applique jamais** une modification sans que vous la validiez ;
- il **n'envoie rien** : aucune télémétrie, aucun compte, aucun rapport qui
  part tout seul ;
- il n'audite pas une machine distante sans que vous ayez défini un
  périmètre (`--perimetre`).

## Si quelque chose ne va pas

| Message | Ce qu'il faut faire |
|---|---|
| « Ollama ne répond pas… » | lancer `ollama serve`, ou donner l'adresse : `BRAIN_BASE_URL=http://…` |
| « aucun modèle n'est installé » | `ollama pull qwen2.5:3b` |
| « le modèle demandé n'est pas installé » | `mael modeles` pour voir ce que vous avez |
| « ce modèle dépasse ce que cette machine peut porter » | en prendre un plus petit : `mael modeles` les liste avec leur taille |

Une question, une gêne, un verdict qui vous paraît faux : dites-le nous —
c'est ce qui fait progresser l'outil.
