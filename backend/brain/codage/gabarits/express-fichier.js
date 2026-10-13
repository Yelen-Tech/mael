const path = require("path");
const DOSSIER = path.join(__dirname, "documents");

app.get("/documents/:nom", (req, res, next) => {
  const nom = path.basename(req.params.nom); // retire tout ../
  res.sendFile(nom, { root: DOSSIER, dotfiles: "deny" }, (err) => {
    if (err) next(err);
  });
});
