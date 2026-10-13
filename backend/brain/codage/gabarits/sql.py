import sqlite3


def trouver(con: sqlite3.Connection, ident: int):
    # Valeurs TOUJOURS en parametres, jamais collees dans la requete.
    return con.execute("SELECT nom FROM clients WHERE id = ?", (ident,)).fetchone()
