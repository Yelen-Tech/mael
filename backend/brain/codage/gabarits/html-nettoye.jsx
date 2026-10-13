import DOMPurify from "dompurify";

// Seulement si du HTML est VRAIMENT voulu (texte d'un editeur) : nettoye d'abord.
export function Article({ html }) {
  return <article dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html) }} />;
}
