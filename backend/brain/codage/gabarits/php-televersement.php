<?php
$permis = ['image/png' => 'png', 'image/jpeg' => 'jpg', 'application/pdf' => 'pdf'];
$f = $_FILES['fichier'] ?? null;
if (!$f || $f['error'] !== UPLOAD_ERR_OK || $f['size'] > 5 * 1024 * 1024) {
    http_response_code(400);
    exit('Fichier refuse');
}
$type = (new finfo(FILEINFO_MIME_TYPE))->file($f['tmp_name']); // type REEL
if (!isset($permis[$type])) {
    http_response_code(415);
    exit('Type non permis');
}
$nom = bin2hex(random_bytes(16)) . '.' . $permis[$type]; // nom choisi par le serveur
move_uploaded_file($f['tmp_name'], __DIR__ . '/../televersements/' . $nom);
