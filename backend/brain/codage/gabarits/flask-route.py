import sqlite3

from flask import Flask, abort, jsonify

app = Flask(__name__)


@app.get("/produits/<int:ident>")
def produit(ident: int):
    # <int:...> : Flask refuse d'avance tout ce qui n'est pas un entier
    with sqlite3.connect("boutique.db") as con:
        ligne = con.execute("SELECT nom, prix FROM produits WHERE id = ?",
                            (ident,)).fetchone()
    if ligne is None:
        abort(404)
    return jsonify(nom=ligne[0], prix=ligne[1])
