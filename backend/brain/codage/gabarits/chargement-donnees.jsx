import { useEffect, useState } from "react";

export function Produits() {
  const [etat, setEtat] = useState({ chargement: true, erreur: "", produits: [] });

  useEffect(() => {
    const controleur = new AbortController(); // annule si le composant disparait
    fetch("/api/produits", { signal: controleur.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((produits) => setEtat({ chargement: false, erreur: "", produits }))
      .catch((e) => {
        if (e.name !== "AbortError") {
          setEtat({ chargement: false, erreur: "Chargement impossible.", produits: [] });
        }
      });
    return () => controleur.abort();
  }, []);

  if (etat.chargement) return <p role="status">Chargement…</p>;
  if (etat.erreur) return <p role="alert">{etat.erreur}</p>;
  return <ListeProduits produits={etat.produits} />;
}
