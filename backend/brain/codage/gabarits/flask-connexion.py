import os

from flask import Flask, redirect, request, session, url_for
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]
app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_SAMESITE="Lax")


@app.post("/connexion")
def connexion():
    compte = trouver_compte(request.form.get("courriel", ""))
    mdp = request.form.get("mdp", "")
    if compte is None or not check_password_hash(compte.hash, mdp):
        return "Identifiants incorrects", 401  # meme message
    session.clear()  # pas de fixation de session
    session["compte"] = compte.id
    return redirect(url_for("accueil"))
