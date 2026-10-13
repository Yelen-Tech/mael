const ORIGINE_PERMISE = "https://paiement.exemple.bf";
window.addEventListener("message", (e) => {
  if (e.origin !== ORIGINE_PERMISE) return; // tout autre site est ignore
  if (typeof e.data !== "object" || e.data === null) return;
  const statut = document.getElementById("statut");
  if (statut) statut.textContent = String(e.data.statut ?? "");
});
function envoyer(cadre, donnee) {
  cadre.contentWindow.postMessage(donnee, ORIGINE_PERMISE); // jamais "*"
}
