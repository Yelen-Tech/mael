const bouton = document.getElementById("bouton-menu");
const menu = document.getElementById("menu");
// Le script est charge sur TOUTES les pages : sans menu, il ne fait rien.
if (bouton && menu) {
  bouton.addEventListener("click", () => {
    const ouvert = bouton.getAttribute("aria-expanded") === "true";
    bouton.setAttribute("aria-expanded", String(!ouvert));
    menu.hidden = ouvert;
  });
  // Echap ferme le menu et rend le focus au bouton (navigation au clavier)
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !menu.hidden) {
      menu.hidden = true;
      bouton.setAttribute("aria-expanded", "false");
      bouton.focus();
    }
  });
}
