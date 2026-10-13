<?php
// Identifiants lus dans l'environnement, erreurs levees en exceptions.
$pdo = new PDO(getenv('DB_DSN'), getenv('DB_USER'), getenv('DB_PASS'), [
    PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
    PDO::ATTR_EMULATE_PREPARES => false,
]);

function trouverProduit(PDO $pdo, int $id): ?array
{
    $req = $pdo->prepare('SELECT nom, prix FROM produits WHERE id = :id');
    $req->execute(['id' => $id]);
    return $req->fetch(PDO::FETCH_ASSOC) ?: null;
}
