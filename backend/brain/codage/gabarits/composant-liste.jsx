// React echappe tout texte place entre accolades : pas de XSS ici.
export function ListeProduits({ produits }) {
  if (produits.length === 0) return <p>Aucun produit pour le moment.</p>;
  return (
    <ul>
      {produits.map((p) => (
        <li key={p.id}>
          <img src={p.image} alt={p.nom} width="120" height="120" />
          <strong>{p.nom}</strong> — {p.prix} FCFA
        </li>
      ))}
    </ul>
  );
}
