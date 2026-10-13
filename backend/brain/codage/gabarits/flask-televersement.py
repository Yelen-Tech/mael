from pathlib import Path

from flask import Flask, abort, request
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 Mo maximum
DOSSIER = Path("televersements").resolve()
PERMIS = {".png", ".jpg", ".jpeg", ".pdf"}


@app.post("/envoyer")
def envoyer():
    fichier = request.files.get("fichier")
    if fichier is None or not fichier.filename:
        abort(400)
    nom = secure_filename(fichier.filename)  # retire ../ et caracteres speciaux
    if Path(nom).suffix.lower() not in PERMIS:
        abort(415)
    fichier.save(DOSSIER / nom)
    return {"enregistre": nom}, 201
