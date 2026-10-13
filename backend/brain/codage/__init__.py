"""L'atelier de code de MAEL : ecrire du code, ou aider a l'ecrire, DANS LA NORME.

Pourquoi un atelier et pas « le modele ecrit du code » : un modele, meme
grand, rend du code qui a l'air juste. Il oublie le `alt` d'une image, le
`label` d'un champ, le `rel="noopener"` d'un lien, il met `shell=True` ou
une requete SQL montee a la main. Personne ne le lui dit, donc il ne
corrige pas.

Ici, la regle de tout MAEL s'applique au code : LE CODE DECIDE.
    1. le modele propose des fichiers (blocs ```langage fichier=chemin) ;
    2. ils sont ecrits dans un ESPACE borne (rien ne sort du dossier) ;
    3. des JUGES deterministes les controlent contre des normes nommees
       (HTML/W3C, accessibilite WCAG 2.2, securite OWASP, syntaxe) ;
    4. chaque defaut bloquant est renvoye au modele, qui corrige ;
    5. on s'arrete quand les juges se taisent — ou on DIT ce qui reste.

Deux usages :
    - ecrire  : « fais-moi un site » -> fichiers + bilan des juges ;
    - assister: relire un projet existant -> defauts dates et localises,
                corrections proposees (jamais appliquees sans accord).

Les juges tournent SANS modele : la relecture d'un projet marche meme sans
Ollama, et elle ne ment jamais sur ce qu'elle a verifie.
"""
from .juges import GRAVITE, Defaut, juger_fichier, juger_projet  # noqa: F401
