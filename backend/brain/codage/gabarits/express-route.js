const { Pool } = require("pg");
const pool = new Pool(); // connexion lue dans les variables PG* de l'environnement

app.get("/produits/:id", async (req, res, next) => {
  const id = Number.parseInt(req.params.id, 10);
  if (!Number.isInteger(id) || id <= 0) {
    return res.status(400).json({ erreur: "id invalide" });
  }
  try {
    const { rows } = await pool.query("SELECT nom, prix FROM produits WHERE id = $1", [id]);
    if (rows.length === 0) return res.status(404).json({ erreur: "introuvable" });
    res.json(rows[0]);
  } catch (err) {
    next(err);
  }
});
