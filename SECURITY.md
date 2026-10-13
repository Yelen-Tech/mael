# Politique de sécurité

MAEL est un outil de sécurité : une faille dans MAEL est prise au sérieux.

## Signaler une faille

**Ne publiez pas la faille dans une issue publique.** Utilisez le
signalement privé de GitHub :

1. onglet **Security** du dépôt ;
2. **Report a vulnerability** ;
3. décrivez la faille, la version de MAEL, et comment la reproduire.

Seuls les mainteneurs voient votre signalement. Nous accusons réception,
corrigeons, puis publions un avis de sécurité en vous citant si vous le
souhaitez.

## Ce qui nous intéresse en priorité

- une commande classée **lecture** par le garde-fou alors qu'elle
  **modifie** le système (ou l'inverse pour une commande interdite) ;
- un **playbook** qui peut s'appliquer sans simulation, sans confirmation,
  ou dont le sceau peut être contourné ;
- une écriture de MAEL **hors de l'espace de travail** (`..`, chemins
  absolus, `.git`, `.env`) ;
- un correctif de l'agent sur dépôt qui **introduit** un défaut de sécurité
  sans être refusé ;
- une donnée de l'utilisateur qui **quitte la machine** (MAEL ne doit parler
  qu'à l'Ollama local).

## Versions prises en charge

Seule la dernière version publiée reçoit les correctifs de sécurité.
