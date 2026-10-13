<?php
function e(string $texte): string
{
    return htmlspecialchars($texte, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}
$nom = $_GET['nom'] ?? '';
?>
<p>Bonjour <?= e($nom) ?> !</p>
