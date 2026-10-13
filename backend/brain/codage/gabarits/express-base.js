const express = require("express");
const helmet = require("helmet");

const app = express();
app.disable("x-powered-by");
app.use(helmet()); // en-tetes de securite (CSP, HSTS, nosniff...)
app.use(express.json({ limit: "100kb" })); // corps de requete borne
app.use(express.static("public", { dotfiles: "deny" }));

// Erreurs : jamais la pile d'appels envoyee au client.
app.use((err, req, res, next) => {
  console.error(err);
  res.status(500).json({ erreur: "Erreur interne" });
});

const port = Number(process.env.PORT) || 3000;
app.listen(port);
