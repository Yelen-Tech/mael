// La validation du navigateur aide l'utilisateur ; le SERVEUR revalide toujours.
const formulaire = document.querySelector("form");
if (formulaire && formulaire.elements.courriel) { // page sans formulaire : rien
  formulaire.addEventListener("submit", (e) => {
    const courriel = formulaire.elements.courriel;
    courriel.setCustomValidity("");
    if (!courriel.value.includes("@")) {
      courriel.setCustomValidity("Saisissez une adresse de courriel valide.");
    }
    if (!formulaire.reportValidity()) {
      e.preventDefault(); // message affiche ET lu par les lecteurs d'ecran
    }
  });
}
