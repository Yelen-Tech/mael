"""Juges PHP et Java : couche 2 (regles nommees) + syntaxe si l'outil est la.

Ce que ces juges SONT : des regles OWASP/CWE lues sur le texte, ligne par
ligne, apres effacement des commentaires et du contenu des chaines quand la
regle n'en a pas besoin, PLUS un suivi de contamination source -> puits
(contamination_php_java.py), lu instruction par instruction. Ce qu'ils NE
SONT PAS : une lecture de l'arbre complet du code. limites() le dit.

Syntaxe : `php -l` et `javac` sont utilises s'ils sont installes. Sinon, un
controle d'equilibre (accolades, parentheses, crochets, chaines fermees)
attrape au moins le fichier tronque — la faute la plus courante d'un petit
modele qui manque de place.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from .emplacements import trouver
from .juges import GRAVITE, Defaut


def _externe(nom: str) -> str | None:
    """php / javac : cherches aussi hors du PATH (emplacements.py). Les
    tests (MAEL_SANS_OUTILS) jugent NOS juges, sans outil de la machine."""
    if os.environ.get("MAEL_SANS_OUTILS"):
        return None
    return trouver(nom)

B, C = GRAVITE.BLOQUANT, GRAVITE.CONSEIL
# Fichiers ou le suivi de contamination a echoue : dit dans le bilan, jamais
# « propre » en silence (les regles par motifs restent appliquees).
echecs_contamination: list[str] = []


def _contamination(analyser, nom: str, texte: str) -> list[Defaut]:
    try:
        return analyser(nom, texte)
    except Exception as exc:   # un moteur casse ne doit pas taire les autres
        echecs_contamination.append(f"{nom} ({type(exc).__name__})")
        return []


def _ligne(texte: str, pos: int) -> int:
    return texte.count("\n", 0, pos) + 1


def _effacer(texte: str, diese: bool) -> tuple[str, list[str]]:
    """Remplace commentaires et contenus de chaines par des espaces (lignes
    conservees). Rend aussi les erreurs d'equilibre trouvees en route."""
    sortie, i, n = [], 0, len(texte)
    pile: list[tuple[str, int]] = []
    erreurs: list[str] = []
    paires = {")": "(", "]": "[", "}": "{"}

    def blanc(s: str) -> str:
        return re.sub(r"[^\n]", " ", s)

    while i < n:
        c = texte[i]
        if texte.startswith("//", i) or (diese and c == "#"
                                          and not texte.startswith("#[", i)):
            fin = texte.find("\n", i)
            fin = n if fin < 0 else fin
            sortie.append(blanc(texte[i:fin])); i = fin; continue
        if texte.startswith("/*", i):
            fin = texte.find("*/", i + 2)
            if fin < 0:
                erreurs.append(f"{_ligne(texte, i)}:commentaire /* jamais ferme")
                sortie.append(blanc(texte[i:])); break
            sortie.append(blanc(texte[i:fin + 2])); i = fin + 2; continue
        if c in "\"'":
            j = i + 1
            while j < n and texte[j] != c:
                if texte[j] == "\\":
                    j += 1
                elif texte[j] == "\n" and c == "'" and not diese:
                    break           # Java : un caractere ne passe pas la ligne
                j += 1
            if j >= n:
                erreurs.append(f"{_ligne(texte, i)}:chaine jamais fermee")
                sortie.append(blanc(texte[i:])); break
            sortie.append(c + blanc(texte[i + 1:j]) + c); i = j + 1; continue
        if c in "([{":
            pile.append((c, i))
        elif c in ")]}":
            if not pile or pile[-1][0] != paires[c]:
                erreurs.append(f"{_ligne(texte, i)}:{c} sans ouvrant")
            else:
                pile.pop()
        sortie.append(c); i += 1
    for c, pos in pile:
        erreurs.append(f"{_ligne(texte, pos)}:{c} jamais ferme")
    return "".join(sortie), erreurs


def _equilibre(nom: str, erreurs: list[str], langage: str) -> list[Defaut]:
    d = []
    for e in erreurs[:3]:
        ligne, _, quoi = e.partition(":")
        d.append(Defaut(nom, int(ligne), "syntaxe-equilibre", B,
                        f"structure cassee : {quoi} (fichier tronque ?)",
                        langage))
    return d


def _outil(nom: str, texte: str, commande: list[str], suffixe: str,
           motif_ligne: str, regle: str, langage: str) -> list[Defaut] | None:
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / suffixe
        f.write_text(texte, encoding="utf-8")
        try:
            r = subprocess.run([*commande, str(f)], capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=60, cwd=tmp)
        except (OSError, subprocess.TimeoutExpired):
            return None
    if r.returncode == 0:
        return []
    sortie = (r.stdout or "") + (r.stderr or "")
    m = re.search(motif_ligne, sortie)
    message = next((l.strip() for l in sortie.splitlines() if l.strip()),
                   "erreur de syntaxe")
    return [Defaut(nom, int(m.group(1)) if m else 1, regle, B,
                   message[:200], langage)]


def _regles(nom: str, texte: str, regles) -> list[Defaut]:
    d = []
    for motif, regle, gravite, message, norme in regles:
        for m in motif.finditer(texte):
            d.append(Defaut(nom, _ligne(texte, m.start()), regle, gravite,
                            message, norme))
    return d


# ------------------------------------------------------------------- PHP
_SUPER = r"\$_(?:GET|POST|REQUEST|COOKIE|SERVER|FILES)\b"
_SQL_MOT = r"(?:SELECT|INSERT|UPDATE|DELETE)\b"
_REGLES_PHP = [
    # requete SQL ou une variable est collee (interpolation ou concatenation)
    (re.compile(rf"""(?is)(?:mysqli_query|mysql_query|pg_query|->query|->exec|->prepare)\s*\((?:[^;]*?,)?\s*["'][^"';]*{_SQL_MOT}[^"';]*(?:\$\w|["']\s*\.)"""),
     "injection-sql", B, "requete SQL construite avec des variables : "
     "requete preparee + execute([...])", "OWASP A03 — injection SQL (CWE-89)"),
    (re.compile(rf"(?is)\b(?:echo|print)\b[^;]*{_SUPER}"),
     "xss-serveur", B, "entree de l'utilisateur affichee sans "
     "htmlspecialchars()", "OWASP A03 — XSS (CWE-79)"),
    (re.compile(r"(?i)\b(?:system|exec|shell_exec|passthru|popen|proc_open)\s*\([^;]*\$"),
     "injection-commande", B, "commande systeme avec une variable "
     "(escapeshellarg, ou mieux : pas de shell)", "OWASP A03 — CWE-78"),
    (re.compile(r"`[^`]*\$[^`]*`"), "injection-commande", B,
     "accent grave = commande shell avec une variable", "OWASP A03 — CWE-78"),
    (re.compile(r"(?i)\b(?:include|require)(?:_once)?\s*\(?\s*[^;'\"]*\$"),
     "inclusion-fichier", B, "include/require d'un chemin variable",
     "OWASP A03 — CWE-98"),
    (re.compile(r"(?i)\beval\s*\("), "injection-code", B,
     "eval() execute du texte comme du code", "OWASP A03 / CWE-95"),
    (re.compile(rf"(?i)\bunserialize\s*\([^;]*{_SUPER}"), "deserialisation",
     B, "unserialize() sur une entree : json_decode()", "OWASP A08 — CWE-502"),
    (re.compile(rf"(?i)\bextract\s*\(\s*{_SUPER}"), "py-dangereux", B,
     "extract($_...) ecrase n'importe quelle variable", "CWE-621"),
    (re.compile(rf"""(?i)header\s*\(\s*["']Location:[^;]*{_SUPER}"""),
     "redirection-ouverte", B, "redirection vers une adresse fournie par "
     "l'utilisateur", "CWE-601"),
    (re.compile(rf"(?i)\b(?:file_get_contents|fopen|readfile|file|unlink)\s*\([^;]*{_SUPER}"),
     "traversee-chemin", B, "chemin de fichier fourni par l'utilisateur "
     "(basename + dossier fixe)", "OWASP A01 — CWE-22"),
    (re.compile(r"(?i)\b(?:md5|sha1)\s*\(\s*\$\w*(?:pass|mdp|pwd)"),
     "hash-faible", B, "md5/sha1 pour un mot de passe : password_hash()",
     "OWASP A02 — CWE-916"),
    (re.compile(r"(?i)ini_set\s*\(\s*['\"]display_errors['\"]\s*,\s*['\"]?(?:1|on|true)"),
     "debug-actif", C, "display_errors active : erreurs visibles du public",
     "OWASP A05"),
    (re.compile(r"(?i)\$\w*(?:token|jeton|secret|mdp|password|otp)\w*\s*=\s*[^;]*\b(?:rand|mt_rand|uniqid|lcg_value)\s*\("),
     "hasard-faible", B, "rand/mt_rand/uniqid ne sont pas faits pour un "
     "secret : random_bytes() / random_int()", "OWASP A02 — CWE-338"),
]


def _code_php(texte: str) -> str:
    """Seul ce qui est entre <?php (ou <?=) et ?> est du PHP : le HTML
    autour est remplace par des espaces (lignes conservees). Sinon
    l'apostrophe de « l'utilisateur » dans le HTML ouvrirait une chaine."""
    sortie, i = [], 0
    for m in re.finditer(r"<\?(?:php\b|=)(.*?)(?:\?>|\Z)", texte, re.S):
        sortie.append(re.sub(r"[^\n]", " ", texte[i:m.start(1)]))
        sortie.append(m.group(1))
        i = m.end(1)
    sortie.append(re.sub(r"[^\n]", " ", texte[i:]))
    return "".join(sortie)


def juger_php(nom: str, texte: str) -> list[Defaut]:
    code = _code_php(texte)
    _, erreurs = _effacer(code, diese=True)
    php = _externe("php")
    if php:
        syntaxe = _outil(nom, texte, [php, "-l"], "verif.php",
                         r"on line (\d+)", "php-syntaxe", "PHP")
        d = syntaxe if syntaxe is not None else _equilibre(nom, erreurs, "PHP")
    else:
        d = _equilibre(nom, erreurs, "PHP")
    # Les regles lisent le texte SANS commentaires, mais AVEC les chaines :
    # une requete SQL se reconnait a son contenu.
    # Contamination d'abord : a meme ligne et meme regle, son message
    # (« entree ligne N -> ici ») est celui que garde juger_fichier.
    from .contamination_php_java import analyser_php
    d += _contamination(analyser_php, nom, texte)
    sans_commentaires = _sans_commentaires(code, diese=True)
    d += [x for x in _regles(nom, sans_commentaires, _REGLES_PHP)
          if not _protege_php(texte, x)]
    return d


def _protege_php(texte: str, x: Defaut) -> bool:
    """Le contre-juge : sur la ligne, la valeur est deja neutralisee."""
    ligne = texte.splitlines()[x.ligne - 1] if x.ligne <= len(
        texte.splitlines()) else ""
    if x.regle == "xss-serveur":
        return bool(re.search(r"htmlspecialchars|htmlentities|intval|\(int\)",
                              ligne))
    if x.regle == "injection-commande":
        return "escapeshellarg" in ligne
    if x.regle == "traversee-chemin":
        return "basename(" in ligne
    return False


def _sans_commentaires(texte: str, diese: bool) -> str:
    sortie, i, n = [], 0, len(texte)
    while i < n:
        c = texte[i]
        if c in "\"'":
            j = i + 1
            while j < n and texte[j] != c:
                j += 2 if texte[j] == "\\" else 1
            sortie.append(texte[i:j + 1]); i = j + 1; continue
        if texte.startswith("//", i) or (diese and c == "#"
                                          and not texte.startswith("#[", i)):
            fin = texte.find("\n", i)
            fin = n if fin < 0 else fin
            sortie.append(" " * (fin - i)); i = fin; continue
        if texte.startswith("/*", i):
            fin = texte.find("*/", i + 2)
            fin = n if fin < 0 else fin + 2
            sortie.append(re.sub(r"[^\n]", " ", texte[i:fin])); i = fin
            continue
        sortie.append(c); i += 1
    return "".join(sortie)


# ------------------------------------------------------------------ Java
_REGLES_JAVA = [
    (re.compile(rf"""(?is)\.(?:executeQuery|executeUpdate|execute|prepareStatement|addBatch|createQuery|createNativeQuery)\s*\(\s*"[^"]*{_SQL_MOT}[^"]*"\s*\+"""),
     "injection-sql", B, "requete SQL construite par concatenation : "
     "PreparedStatement + setXxx()", "OWASP A03 — injection SQL (CWE-89)"),
    (re.compile(rf"""(?is)String\.format\s*\(\s*"[^"]*{_SQL_MOT}"""),
     "injection-sql", B, "requete SQL montee avec String.format",
     "OWASP A03 — injection SQL (CWE-89)"),
    (re.compile(r"(?s)Runtime\.getRuntime\(\)\s*\.exec\s*\((?!\s*new\s+String\[\])(?!\s*\"[^\"]*\"\s*\))"),
     "injection-commande", B, "Runtime.exec avec une chaine construite : "
     "ProcessBuilder avec une liste d'arguments", "OWASP A03 — CWE-78"),
    (re.compile(r"""new\s+ProcessBuilder\s*\(\s*"(?:sh|bash|cmd|cmd\.exe|/bin/sh)"\s*,\s*"(?:-c|/c)\""""),
     "injection-commande", B, "ProcessBuilder qui passe par un shell",
     "OWASP A03 — CWE-78"),
    (re.compile(r"new\s+ObjectInputStream\s*\("), "deserialisation", B,
     "ObjectInputStream : deserialiser des donnees non sures execute du "
     "code (JSON a la place)", "OWASP A08 — CWE-502"),
    (re.compile(r"""MessageDigest\.getInstance\s*\(\s*"(?:MD5|SHA-?1)"\s*\)"""),
     "hash-faible", C, "MD5/SHA-1 : trop faible pour un mot de passe ou "
     "une signature", "OWASP A02 — CWE-328"),
    (re.compile(r"""Cipher\.getInstance\s*\(\s*"(?:DES|RC4|[^"]*/ECB/)"""),
     "chiffrement-faible", B, "chiffrement faible (DES, RC4 ou mode ECB) : "
     "AES/GCM/NoPadding", "OWASP A02 — CWE-327"),
    (re.compile(r"(?i)csrf\s*\(\s*\)\s*\.\s*disable\s*\(|csrf\s*\(\s*\w+\s*->\s*\w+\s*\.\s*disable\s*\(|AbstractHttpConfigurer::disable"),
     "csrf-desactive", B, "protection CSRF desactivee",
     "OWASP A01 — CSRF (CWE-352)"),
    (re.compile(r"""@CrossOrigin\s*\(\s*(?:origins\s*=\s*)?"\*\""""),
     "cors-ouvert", C, "CORS ouvert a tous les sites", "OWASP A05"),
    (re.compile(r"NoopHostnameVerifier|ALLOW_ALL_HOSTNAME_VERIFIER|"
                r"setHostnameVerifier\s*\(\s*\([^)]*\)\s*->\s*true"),
     "py-dangereux", B, "verification du nom d'hote TLS desactivee",
     "OWASP A02 — CWE-295"),
    (re.compile(r"""(?i)(?:getWriter\(\)|out)\s*\.\s*(?:print|println|write)\s*\([^;]*getParameter\s*\("""),
     "xss-serveur", B, "parametre de la requete ecrit tel quel dans la "
     "reponse", "OWASP A03 — XSS (CWE-79)"),
    (re.compile(r"""new\s+File(?:InputStream|Reader)?\s*\([^;]*getParameter\s*\("""),
     "traversee-chemin", B, "chemin de fichier fourni par l'utilisateur",
     "OWASP A01 — CWE-22"),
    (re.compile(r"(?i)\b\w*(?:token|password|secret|jeton|otp)\w*\s*=\s*[^;]*new\s+Random\s*\("),
     "hasard-faible", B, "java.util.Random pour un secret : SecureRandom",
     "OWASP A02 — CWE-338"),
    (re.compile(r"\.printStackTrace\s*\(\s*\)"), "erreur-avalee", C,
     "printStackTrace : journaliser (logger) au lieu d'ecrire la pile",
     "OWASP A09"),
]


def _xxe(nom: str, texte: str) -> list[Defaut]:
    """Un analyseur XML sans protection lit les fichiers du serveur (XXE)."""
    m = re.search(r"(?:DocumentBuilderFactory|SAXParserFactory|"
                  r"XMLInputFactory)\.newInstance\s*\(", texte)
    if m and not re.search(r"disallow-doctype-decl|"
                           r"FEATURE_SECURE_PROCESSING|SUPPORT_DTD|"
                           r"ACCESS_EXTERNAL_DTD", texte):
        return [Defaut(nom, _ligne(texte, m.start()), "xxe", B,
                       "analyseur XML sans protection contre les entites "
                       "externes", "OWASP A05 — XXE (CWE-611)")]
    return []


def juger_java(nom: str, texte: str) -> list[Defaut]:
    _, erreurs = _effacer(texte, diese=False)
    javac = _externe("javac")
    d = None
    if javac:
        # javac exige que le fichier porte le nom de sa classe publique.
        m = re.search(r"public\s+(?:final\s+|abstract\s+)*(?:class|interface|"
                      r"enum|record)\s+(\w+)", texte)
        nom_fichier = f"{m.group(1) if m else 'Verif'}.java"
        d = _outil(nom, texte, [javac, "-proc:none", "-d", "."],
                   nom_fichier, r"\.java:(\d+):", "java-syntaxe", "Java")
        # Une erreur « symbole introuvable » vient des dependances absentes
        # (Spring, JDBC...), pas d'une faute : on ne garde que la syntaxe.
        if d and any(x in d[0].message.lower() for x in (
                "cannot find symbol", "does not exist",
                "symbole introuvable", "n'existe pas")):
            d = []
    if d is None:
        d = _equilibre(nom, erreurs, "Java")
    from .contamination_php_java import analyser_java
    d += _contamination(analyser_java, nom, texte)
    sans_commentaires = _sans_commentaires(texte, diese=False)
    d += _regles(nom, sans_commentaires, _REGLES_JAVA)
    d += _xxe(nom, sans_commentaires)
    return d


def limites() -> list[str]:
    l = []
    if not _externe("php"):
        l.append("PHP : syntaxe controlee par equilibre seulement (php "
                 "absent)")
    if not _externe("javac"):
        l.append("Java : syntaxe controlee par equilibre seulement (javac "
                 "absent)")
    l.append("PHP et Java : contamination suivie dans chaque fonction, "
             "pas a travers les appels, les champs ni les autres fichiers")
    if echecs_contamination:
        l.append("PHP/Java : suivi de contamination EN PANNE sur "
                 + ", ".join(dict.fromkeys(echecs_contamination)))
    return l
