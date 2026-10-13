from django.db import connection

from .models import Produit


def moins_chers_que(prix_max: int):
    # %s est rempli par le pilote de la base, jamais par Python.
    with connection.cursor() as cur:
        cur.execute("SELECT id, nom FROM boutique_produit WHERE prix < %s",
                    [prix_max])
        return cur.fetchall()


def par_categorie(categorie: str):
    return Produit.objects.raw(
        "SELECT * FROM boutique_produit WHERE categorie = %s", [categorie])
