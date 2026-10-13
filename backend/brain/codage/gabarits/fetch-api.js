async function chargerProduits() {
  const etat = document.getElementById("etat");
  const liste = document.getElementById("produits");
  if (!etat || !liste) return; // page sans liste de produits : rien a faire
  try {
    const reponse = await fetch("/api/produits", { headers: { Accept: "application/json" } });
    if (!reponse.ok) throw new Error(`HTTP ${reponse.status}`);
    afficherProduits(liste, await reponse.json());
    etat.textContent = "";
  } catch (erreur) {
    etat.textContent = "Impossible de charger les produits. Réessayez plus tard.";
    console.error(erreur);
  }
}
document.addEventListener("DOMContentLoaded", chargerProduits);
