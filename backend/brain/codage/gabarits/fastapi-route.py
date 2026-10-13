from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()


class Commande(BaseModel):
    # La validation est faite AVANT d'entrer dans la fonction.
    produit_id: int = Field(gt=0)
    quantite: int = Field(gt=0, le=100)


@app.post("/commandes", status_code=201)
async def creer(commande: Commande):
    if not produit_existe(commande.produit_id):
        raise HTTPException(status_code=404, detail="Produit inconnu")
    return {"ok": True, "quantite": commande.quantite}
