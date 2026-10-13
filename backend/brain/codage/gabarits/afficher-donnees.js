// Afficher des donnees (API, saisie, URL) SANS innerHTML : aucune faille XSS.
function afficherProduits(liste, produits) {
  liste.replaceChildren();
  for (const p of produits) {
    const li = document.createElement("li");
    const nom = document.createElement("strong");
    nom.textContent = p.nom;
    const prix = document.createElement("span");
    prix.textContent = ` — ${p.prix} FCFA`;
    li.append(nom, prix);
    liste.append(li);
  }
}
