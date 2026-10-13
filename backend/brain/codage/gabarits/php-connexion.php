<?php
session_start();
$courriel = $_POST['courriel'] ?? '';
$mdp = $_POST['mdp'] ?? '';
$req = $pdo->prepare('SELECT id, hash FROM comptes WHERE courriel = ?');
$req->execute([$courriel]);
$compte = $req->fetch();
if (!$compte || !password_verify($mdp, $compte['hash'])) {
    http_response_code(401);
    exit('Identifiants incorrects'); // meme message dans les deux cas
}
session_regenerate_id(true); // pas de fixation de session
$_SESSION['compte'] = $compte['id'];
header('Location: /tableau-de-bord');
