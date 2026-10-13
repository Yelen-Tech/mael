import { useState } from "react";

export function FormulaireContact({ onEnvoyer }) {
  const [courriel, setCourriel] = useState("");
  const [erreur, setErreur] = useState("");

  function soumettre(e) {
    e.preventDefault();
    if (!courriel.includes("@")) return setErreur("Adresse de courriel invalide.");
    setErreur("");
    onEnvoyer({ courriel });
  }

  return (
    <form onSubmit={soumettre} noValidate>
      <label htmlFor="courriel">Courriel</label>
      <input id="courriel" type="email" value={courriel} required
             onChange={(e) => setCourriel(e.target.value)} aria-describedby="erreur" />
      <p id="erreur" role="alert">{erreur}</p>
      <button type="submit">Envoyer</button>
    </form>
  );
}
