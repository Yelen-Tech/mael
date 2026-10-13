const bcrypt = require("bcrypt");

// Session (express-session) : cookie { httpOnly: true, secure: true, sameSite: "lax" }
app.post("/connexion", async (req, res) => {
  const { courriel, mdp } = req.body ?? {};
  const compte = await trouverCompte(String(courriel ?? "")); // requete parametree
  const valide = compte && (await bcrypt.compare(String(mdp ?? ""), compte.hash));
  if (!valide) return res.status(401).json({ erreur: "Identifiants incorrects" });
  req.session.regenerate(() => { // nouvel identifiant : pas de fixation
    req.session.compte = compte.id;
    res.json({ ok: true });
  });
});
