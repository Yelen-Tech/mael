import os


def lire(nom: str) -> str:
    valeur = os.environ.get(nom)
    if not valeur:
        raise RuntimeError(f"Variable d'environnement {nom} manquante")
    return valeur


# Les secrets viennent de l'environnement (ou d'un fichier .env ignore par
# git), jamais du code.
DATABASE_URL = lire("DATABASE_URL")
SECRET_KEY = lire("SECRET_KEY")
DEBUG = os.environ.get("DEBUG") == "1"  # faux par defaut
