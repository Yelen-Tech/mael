"""Couche 4 pour PHP et Java : suivi de contamination (source -> puits).

php et javac sont souvent absents de la machine, et embarquer un analyseur
complet de chaque langage serait lourd. On lit donc le code INSTRUCTION PAR
INSTRUCTION (decoupe sur ; { } hors chaines et hors parentheses), ce qui
suffit au chemin que suivent presque toutes les failles reelles :

    $id = $_GET['id'];                       <- source (ligne retenue)
    $sql = "SELECT * FROM t WHERE id = $id"; <- propagation
    $pdo->query($sql);                       <- puits : defaut, « entree
                                                ligne 1 -> ici »

Regles du moteur :
  - une variable est contaminee par une SOURCE (entree de l'utilisateur) ou
    par une variable contaminee ; une reaffectation propre la nettoie ;
  - les ASSAINISSEURS effacent ce qu'ils entourent avant la lecture : les
    generaux (intval, (int), Integer.parseInt...) pour tous les puits, les
    specialises (htmlspecialchars pour l'affichage, escapeshellarg pour une
    commande, basename pour un chemin) pour leur famille seulement ;
  - une variable passee par une LISTE BLANCHE (in_array, switch/match,
    preg_match ancre, .matches(), .contains()) est tenue pour validee ;
  - seul l'argument dangereux du puits est juge (le 2e de mysqli_query, le
    1er de ->query, l'URL de curl_setopt) ;
  - chaque fonction repart de zero ; ses parametres annotes (@RequestParam,
    @PathVariable, @RequestBody...) sont des sources ;
  - meme origine, meme famille : un seul defaut (pas d'avalanche).

Ce que ce moteur NE fait PAS : suivre une donnee a travers un appel de
fonction, un champ d'objet ou une autre classe. limites() le dit.
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

from .juges import GRAVITE, Defaut

B = GRAVITE.BLOQUANT


# ------------------------------------------------------------ familles
@dataclass(frozen=True)
class Famille:
    regle: str
    message: str
    norme: str


SQL = Famille("injection-sql", "donnee de l'utilisateur collee dans une "
              "requete SQL : requete preparee + valeurs liees",
              "OWASP A03 — injection SQL (CWE-89)")
CMD = Famille("injection-commande", "donnee de l'utilisateur dans une "
              "commande systeme", "OWASP A03 — injection de commande (CWE-78)")
CODE = Famille("injection-code", "donnee de l'utilisateur executee comme du "
               "code", "OWASP A03 — injection de code (CWE-95)")
INCL = Famille("inclusion-fichier", "fichier inclus choisi par "
               "l'utilisateur : liste blanche", "OWASP A03 — CWE-98")
CHEMIN = Famille("traversee-chemin", "chemin de fichier fourni par "
                 "l'utilisateur (../ sort du dossier)", "OWASP A01 — CWE-22")
XSS = Famille("xss-serveur", "donnee de l'utilisateur ecrite dans la page "
              "sans echappement", "OWASP A03 — XSS (CWE-79)")
REDIR = Famille("redirection-ouverte", "redirection vers une adresse "
                "fournie par l'utilisateur", "OWASP A01 — CWE-601")
SSRF = Famille("ssrf", "le serveur appelle une adresse fournie par "
               "l'utilisateur", "OWASP A10 — SSRF (CWE-918)")
DESER = Famille("deserialisation", "donnee de l'utilisateur deserialisee : "
                "JSON a la place", "OWASP A08 — CWE-502")

TOUS = None          # selecteur d'arguments : tous
DERNIER = -1


@dataclass(frozen=True)
class Puits:
    motif: re.Pattern
    famille: Famille
    argument: int | None = 0     # index de l'argument dangereux, None = tous
    exige: re.Pattern | None = None   # condition sur le texte BRUT de l'appel
    cible: int | None = None     # argument a lire pour `exige`


@dataclass(frozen=True)
class Langage:
    nom: str
    sources: re.Pattern            # lue sur le texte brut (chaines intactes)
    variable: re.Pattern           # groupe 1 = nom de la variable
    generaux: tuple[str, ...]      # assainisseurs pour tous les puits
    specialises: dict              # Famille -> assainisseurs
    puits: tuple[Puits, ...]
    entete: re.Pattern             # debut de fonction (remise a zero)
    affectation: re.Pattern        # groupes : variable, operateur, valeur
    boucles: tuple[re.Pattern, ...]  # groupes : collection, variables...
    validation: tuple[re.Pattern, ...]  # groupe 1 = variable validee
    mots_cles: frozenset = frozenset()


# ------------------------------------------------------------------ PHP
def _p(motif: str, drapeaux=re.I) -> re.Pattern:
    return re.compile(motif, drapeaux)


_PAS_METHODE = r"(?<![\w$>:\\])"   # exec( mais pas ->exec( ni $exec(

PHP = Langage(
    nom="PHP",
    sources=_p(
        r"\$_(?:GET|POST|REQUEST|COOKIE|FILES)\b"
        r"|\$_SERVER\s*\[\s*['\"](?:HTTP_\w+|QUERY_STRING|REQUEST_URI|"
        r"PHP_SELF|PATH_INFO|CONTENT_TYPE)['\"]\s*\]"
        r"|file_get_contents\s*\(\s*['\"]php://input"
        r"|\bgetallheaders\s*\(|\bfilter_input(?:_array)?\s*\("
        r"|\$request\s*->\s*(?:input|query|get|post|all|cookie|header|file|"
        r"route|json|string|integer)\s*\("
        r"|\brequest\s*\(\s*['\"]|\bRequest::(?:input|query|get|all)\s*\("),
    variable=re.compile(r"\$(?!this\b)([A-Za-z_]\w*)"),
    generaux=("intval", "floatval", "boolval", "count", "strlen", "mb_strlen",
              "is_numeric", "ctype_digit", "ctype_alnum", "md5", "sha1",
              "hash", "crc32", "password_hash", "password_verify", "isset",
              "empty", "in_array", "array_key_exists", "uniqid", "abs",
              "round", "max", "min"),
    specialises={
        XSS: ("htmlspecialchars", "htmlentities", "e", "urlencode",
              "rawurlencode", "esc_html", "esc_attr", "esc_url"),
        CMD: ("escapeshellarg",),
        CHEMIN: ("basename",),
        SQL: ("mysqli_real_escape_string", "->real_escape_string",
              "pg_escape_string", "pg_escape_literal", "->quote"),
        REDIR: (),
    },
    puits=(
        Puits(_p(r"\bmysqli_(?:query|multi_query|real_query)\s*\("), SQL, 1),
        Puits(_p(r"\bmysql_query\s*\("), SQL, 0),
        Puits(_p(r"\bpg_query\s*\("), SQL, DERNIER),
        Puits(_p(r"->\s*(?:query|exec|prepare|multi_query|real_query)\s*\("),
              SQL, 0),
        Puits(_p(r"\bDB::(?:select|statement|unprepared|raw|insert|update|"
                 r"delete)\s*\("), SQL, 0),
        Puits(_p(r"->\s*(?:whereRaw|selectRaw|orderByRaw|havingRaw|"
                 r"groupByRaw)\s*\("), SQL, 0),
        Puits(_p(_PAS_METHODE + r"(?:system|exec|shell_exec|passthru|popen|"
                 r"proc_open|pcntl_exec)\s*\("), CMD, 0),
        Puits(_p(_PAS_METHODE + r"(?:eval|assert|create_function|"
                 r"call_user_func|call_user_func_array)\s*\("), CODE, 0),
        Puits(_p(_PAS_METHODE + r"(?:file_get_contents|fopen|readfile|file|"
                 r"unlink|file_put_contents|opendir|scandir|rmdir|copy|"
                 r"rename|fpassthru|parse_ini_file|highlight_file|"
                 r"show_source)\s*\("), CHEMIN, 0),
        Puits(_p(r"\bmove_uploaded_file\s*\("), CHEMIN, 1),
        Puits(_p(_PAS_METHODE + r"(?:printf|vprintf|die|exit)\s*\("), XSS,
              TOUS),
        Puits(_p(r"\bheader\s*\("), REDIR, 0, _p(r"location\s*:"), 0),
        Puits(_p(r"\bcurl_init\s*\("), SSRF, 0),
        Puits(_p(r"\bcurl_setopt\s*\("), SSRF, 2, _p(r"CURLOPT_URL"), 1),
        Puits(_p(r"\b(?:fsockopen|get_headers)\s*\("), SSRF, 0),
        Puits(_p(r"\bunserialize\s*\("), DESER, 0),
    ),
    entete=_p(r"(?:^|\s)function\s+&?\s*([A-Za-z_]\w*)\s*\("),
    affectation=re.compile(
        r"\s*\$([A-Za-z_]\w*)(?:\s*\[[^\]]*\])*\s*(\.=|\+=|\?\?=|=)(?![=>])"
        r"\s*(.*)\Z", re.S),
    boucles=(re.compile(
        r"\s*foreach\s*\((.*)\bas\s+(?:&?\s*\$(\w+)\s*=>\s*)?&?\s*\$(\w+)"
        r"\s*\)\s*\Z", re.S | re.I),),
    validation=(
        _p(r"\bin_array\s*\(\s*\$(\w+)"),
        _p(r"\barray_key_exists\s*\(\s*\$(\w+)"),
        _p(r"\bisset\s*\(\s*\$\w+\s*\[\s*\$(\w+)\s*\]"),
        _p(r"\bpreg_match\s*\(\s*(['\"])[^'\"]*\^[^'\"]*\$[^'\"]*\1\s*,"
           r"\s*\$(\w+)"),
        _p(r"\b(?:switch|match)\s*\(\s*\$(\w+)\s*\)"),
    ),
)


# ------------------------------------------------------------------ Java
_ANNOTATIONS_SOURCES = (r"@(?:RequestParam|PathVariable|RequestBody|"
                        r"RequestHeader|CookieValue|ModelAttribute|"
                        r"MatrixVariable|RequestPart|QueryParam|PathParam|"
                        r"FormParam|HeaderParam|CookieParam)\b")

JAVA = Langage(
    nom="Java",
    sources=re.compile(
        r"\.\s*(?:getParameter|getParameterValues|getParameterMap|getHeader|"
        r"getHeaders|getQueryString|getCookies|getInputStream|getReader|"
        r"getPathInfo|getRequestURI|getRequestURL|getPart|getParts)\s*\("),
    variable=re.compile(r"(?<![\w.@])([A-Za-z_]\w*)\b(?!\s*\()"),
    generaux=("Integer.parseInt", "Integer.valueOf", "Long.parseLong",
              "Long.valueOf", "Double.parseDouble", "Double.valueOf",
              "Float.parseFloat", "Short.parseShort", "Boolean.parseBoolean",
              "UUID.fromString", ".length", ".size", ".isEmpty", ".equals",
              ".equalsIgnoreCase", ".hashCode", ".contains"),
    specialises={
        XSS: ("HtmlUtils.htmlEscape", "StringEscapeUtils.escapeHtml4",
              "Encode.forHtml", "Encode.forHtmlContent",
              "Encode.forHtmlAttribute", ".encodeForHTML",
              ".encodeForHTMLAttribute", "URLEncoder.encode"),
        CHEMIN: ("FilenameUtils.getName", ".getFileName"),
        SQL: (), CMD: (), REDIR: (),
    },
    puits=(
        Puits(re.compile(r"\.\s*(?:executeQuery|executeUpdate|"
                         r"executeLargeUpdate|execute|addBatch|"
                         r"prepareStatement|prepareCall|createQuery|"
                         r"createNativeQuery|createSQLQuery)\s*\("), SQL, 0),
        Puits(re.compile(r"\b(?:jdbcTemplate|jdbc|template|"
                         r"namedParameterJdbcTemplate)\s*\.\s*(?:query\w*|"
                         r"update|batchUpdate)\s*\("), SQL, 0),
        Puits(re.compile(r"\.\s*exec\s*\("), CMD, TOUS),
        Puits(re.compile(r"\bnew\s+ProcessBuilder\s*\("), CMD, TOUS),
        Puits(re.compile(r"\.\s*command\s*\("), CMD, TOUS),
        Puits(re.compile(r"\.\s*(?:eval|parseExpression)\s*\("), CODE, 0),
        Puits(re.compile(r"\bClass\s*\.\s*forName\s*\("), CODE, 0),
        Puits(re.compile(r"\bnew\s+(?:File|FileInputStream|FileOutputStream|"
                         r"FileReader|FileWriter|RandomAccessFile|"
                         r"PrintWriter)\s*\("), CHEMIN, TOUS),
        Puits(re.compile(r"\b(?:Paths\s*\.\s*get|Path\s*\.\s*of)\s*\("),
              CHEMIN, TOUS),
        Puits(re.compile(r"\bFiles\s*\.\s*(?:readAllBytes|readString|"
                         r"readAllLines|newInputStream|newBufferedReader|"
                         r"newOutputStream|delete|deleteIfExists|write|"
                         r"writeString|copy|move|lines)\s*\("), CHEMIN, 0),
        Puits(re.compile(r"(?:getWriter\s*\(\s*\)|(?<!System\.)\bout|\bwriter|\bpw)\s*\.\s*"
                         r"(?:print|println|write|printf|append|format)"
                         r"\s*\("), XSS, TOUS),
        Puits(re.compile(r"\.\s*sendRedirect\s*\("), REDIR, 0),
        Puits(re.compile(r"\bnew\s+RedirectView\s*\("), REDIR, 0),
        Puits(re.compile(r"\bnew\s+URL\s*\("), SSRF, 0),
        Puits(re.compile(r"\bURI\s*\.\s*create\s*\("), SSRF, 0),
        Puits(re.compile(r"\.\s*(?:getForObject|getForEntity|postForObject|"
                         r"postForEntity|exchange)\s*\("), SSRF, 0),
        Puits(re.compile(r"\bnew\s+(?:ObjectInputStream|XMLDecoder)\s*\("),
              DESER, TOUS),
    ),
    entete=re.compile(r"(?<![\w.])([A-Za-z_]\w*)\s*\("),
    affectation=re.compile(
        r"\s*(?:final\s+)?(?:[\w.]+(?:\s*<[^;=()]*>)?(?:\s*\[\s*\])*\s+)?"
        r"([A-Za-z_]\w*)(?:\s*\[[^\]]*\])*\s*(\+=|=)(?!=)\s*(.*)\Z", re.S),
    boucles=(re.compile(
        r"\s*for\s*\(\s*(?:final\s+)?[\w.<>\[\],?\s]+?\s+(\w+)\s*:\s*(.*)\)"
        r"\s*\Z", re.S),),
    validation=(
        re.compile(r"(?<![\w.])(\w+)\s*\.\s*matches\s*\("),
        re.compile(r"\.\s*(?:contains|containsKey)\s*\(\s*(\w+)\s*\)"),
        re.compile(r"\.\s*matcher\s*\(\s*(\w+)\s*\)"),
        re.compile(r"\bswitch\s*\(\s*(\w+)\s*\)"),
    ),
    mots_cles=frozenset({
        "new", "return", "null", "true", "false", "this", "super", "if",
        "else", "for", "while", "int", "long", "double", "float", "boolean",
        "char", "byte", "short", "String", "var", "final", "throw",
        "instanceof", "class", "void", "static", "public", "private",
        "protected", "try", "catch", "case", "default", "break", "continue",
    }),
)
_JAVA_NON_ENTETES = {"if", "for", "while", "switch", "catch", "synchronized",
                     "return", "new", "else", "try", "do", "throw"}


# ----------------------------------------------------- preparation
def _blanc(s: str) -> str:
    return re.sub(r"[^\n]", " ", s)


def _preparer_php(texte: str) -> tuple[str, list[tuple[int, int]]]:
    """Le HTML autour du PHP devient des espaces ; `<?=` et `?>` deviennent
    des fins d'instruction. Rend aussi les zones `<?= ... ?>` (affichage).
    La longueur du texte est conservee : les positions restent justes."""
    sortie, i, echos = [], 0, []
    for m in re.finditer(r"<\?(php\b|=)(.*?)(\?>|\Z)", texte, re.S):
        sortie.append(_blanc(texte[i:m.start()]))
        ouvrant = texte[m.start():m.start(2)]
        if m.group(1) == "=":
            sortie.append(";" + " " * (len(ouvrant) - 1))
            echos.append((m.start(2), m.end(2)))
        else:
            sortie.append(_blanc(ouvrant))
        sortie.append(m.group(2))
        sortie.append(";" + " " * (len(m.group(3)) - 1) if m.group(3) else "")
        i = m.end()
    sortie.append(_blanc(texte[i:]))
    return "".join(sortie), echos


def _sans_commentaires(texte: str, diese: bool) -> str:
    sortie, i, n = [], 0, len(texte)
    while i < n:
        c = texte[i]
        if c in "\"'`":
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
            sortie.append(_blanc(texte[i:fin])); i = fin; continue
        sortie.append(c); i += 1
    return "".join(sortie)[:n]


def _blanchir_chaines(brut: str, garder_doubles: bool) -> str:
    """Contenu des chaines -> espaces (guillemets gardes). En PHP, les
    chaines doubles sont GARDEES : "$id" y est une vraie variable."""
    sortie, i, n = [], 0, len(brut)
    while i < n:
        c = brut[i]
        if c in "\"'`":
            j = i + 1
            while j < n and brut[j] != c:
                j += 2 if brut[j] == "\\" else 1
            contenu = brut[i + 1:j]
            garder = (c == '"' and garder_doubles) or c == "`"
            sortie.append(c + (contenu if garder else _blanc(contenu))
                          + (brut[j] if j < n else ""))
            i = j + 1
            continue
        sortie.append(c); i += 1
    return "".join(sortie)[:n]


def _instructions(code: str):
    """(debut, fin, separateur) de chaque instruction : decoupe sur ; { }
    hors chaines et hors parentheses/crochets."""
    debut, i, n, prof = 0, 0, len(code), 0
    while i < n:
        c = code[i]
        if c in "\"'`":
            j = i + 1
            while j < n and code[j] != c:
                j += 2 if code[j] == "\\" else 1
            i = j + 1
            continue
        if c in "([":
            prof += 1
        elif c in ")]":
            prof = max(0, prof - 1)
        elif c in ";{}" and prof == 0:
            yield debut, i, c
            debut = i + 1
        i += 1
    if debut < n:
        yield debut, n, ""


def _arguments(code: str, ouvrante: int) -> list[tuple[int, int]]:
    """Positions (debut, fin) de chaque argument d'un appel dont la
    parenthese ouvrante est a `ouvrante`."""
    args, prof, debut, i, n = [], 0, ouvrante + 1, ouvrante, len(code)
    while i < n:
        c = code[i]
        if c in "\"'`":
            j = i + 1
            while j < n and code[j] != c:
                j += 2 if code[j] == "\\" else 1
            i = j + 1
            continue
        if c in "([{":
            prof += 1
        elif c in ")]}":
            prof -= 1
            if prof == 0:
                if code[debut:i].strip():
                    args.append((debut, i))
                return args
        elif c == "," and prof == 1:
            args.append((debut, i))
            debut = i + 1
        i += 1
    if code[debut:].strip():
        args.append((debut, n))
    return args


def _fin_appel(code: str, ouvrante: int) -> int:
    """Position juste apres la parenthese qui ferme `ouvrante` — y compris
    pour un appel vide, f() (sans argument, il n'y a pas de fin d'argument
    a lire : c'etait le defaut du premier passage des tests)."""
    prof, i, n = 0, ouvrante, len(code)
    while i < n:
        c = code[i]
        if c in "\"'`":
            j = i + 1
            while j < n and code[j] != c:
                j += 2 if code[j] == "\\" else 1
            i = j + 1
            continue
        if c in "([{":
            prof += 1
        elif c in ")]}":
            prof -= 1
            if prof == 0:
                return i + 1
        i += 1
    return n


# ------------------------------------------------------- l'analyse
class _Analyse:
    def __init__(self, lg: Langage, nom: str, brut: str, code: str,
                 echos: list[tuple[int, int]]):
        self.lg, self.nom, self.brut, self.code = lg, nom, brut, code
        self.echos = echos
        self.debuts_lignes = [0] + [m.end() for m in
                                    re.finditer(r"\n", brut)]
        self.defauts: list[Defaut] = []
        self._zero()
        noms = [(f, n) for f, ns in lg.specialises.items() for n in ns]
        self.assainisseurs = {
            None: self._motif(lg.generaux),
            **{f: self._motif(lg.generaux + lg.specialises.get(f, ()))
               for f in {f for f, _ in noms} | set(lg.specialises)},
        }

    def _zero(self):
        self.contamine: dict[str, int] = {}
        # Familles pour lesquelles une variable contaminee a ete NETTOYEE :
        # $f = basename($_GET['f']) reste dangereuse pour du SQL, mais plus
        # pour un chemin.
        self.nettoye: dict[str, frozenset] = {}
        self.valide: set[str] = set()
        self.dits: set[tuple[str, int]] = set()

    def _motif(self, noms) -> re.Pattern:
        morceaux = []
        for n in noms:
            if n.startswith("->"):          # methode PHP : $pdo->quote(
                morceaux.append(r"->\s*" + re.escape(n[2:]) + r"\s*\(")
            elif n.startswith("."):
                morceaux.append(r"\.\s*" + re.escape(n[1:]) + r"\s*\(")
            else:
                parties = [re.escape(p) for p in n.split(".")]
                morceaux.append(r"(?<![\w$>.])" + r"\s*\.\s*".join(parties)
                                + r"\s*\(")
        if self.lg is PHP:
            morceaux.append(r"\(\s*(?:int|integer|float|double|bool|boolean)"
                            r"\s*\)\s*")   # transtypage : (int) $x
        return re.compile("|".join(morceaux), re.I if self.lg is PHP else 0)

    def ligne(self, pos: int) -> int:
        return bisect.bisect_right(self.debuts_lignes, pos)

    # ---- lecture d'une expression
    def _masquer(self, debut: int, fin: int, famille) -> tuple[str, str]:
        """(code, brut) de l'expression, ce qu'entourent les assainisseurs
        efface. Un transtypage efface le terme qui le suit."""
        code = list(self.code[debut:fin])
        brut = list(self.brut[debut:fin])
        texte = self.code[debut:fin]
        for m in self.assainisseurs.get(famille,
                                        self.assainisseurs[None]).finditer(
                                            texte):
            if m.group(0).rstrip().endswith("("):
                ouvrante = m.end() - 1
                fin_rel = _fin_appel(texte, ouvrante)
            else:   # (int) $x[...] ou (int) appel(...)
                t = re.match(r"\$?\w+(?:\s*\[[^\]]*\])*", texte[m.end():])
                fin_rel = m.end() + (t.end() if t else 0)
                if fin_rel < len(texte) and texte[fin_rel] == "(":
                    fin_rel = _fin_appel(texte, fin_rel)
            for k in range(m.start(), min(fin_rel, len(texte))):
                if code[k] != "\n":
                    code[k] = brut[k] = " "
        return "".join(code), "".join(brut)

    def origine(self, debut: int, fin: int, famille=None) -> int | None:
        code, brut = self._masquer(debut, fin, famille)
        lignes = []
        for m in self.lg.sources.finditer(brut):
            # Une source ecrite DANS une chaine ('$_GET', "x.getParameter(")
            # n'est que du texte : dans `code`, son premier caractere est
            # efface.
            if code[m.start()] == brut[m.start()]:
                lignes.append(self.ligne(debut + m.start()))
        for m in self.lg.variable.finditer(code):
            v = m.group(1)
            if v in self.contamine and v not in self.valide \
                    and v not in self.lg.mots_cles \
                    and famille not in self.nettoye.get(v, ()):
                lignes.append(self.contamine[v])
        return min(lignes) if lignes else None

    def _familles_nettoyees(self, debut: int, fin: int) -> frozenset:
        return frozenset(f for f, noms in self.lg.specialises.items()
                         if noms and self.origine(debut, fin, f) is None)

    # ---- une instruction
    def instruction(self, debut: int, fin: int, sep: str):
        texte = self.code[debut:fin]
        if not texte.strip():
            return
        if sep == "{" and self._entete(debut, fin):
            return
        for v in self._valides(texte):
            self.valide.add(v)
        self._puits(debut, fin)
        self._propager(debut, fin, texte)

    def _entete(self, debut: int, fin: int) -> bool:
        """Debut d'une fonction : on repart de zero, parametres annotes
        contamines. Rend True si c'etait un entete."""
        texte = self.code[debut:fin]
        if self.lg is PHP:
            m = self.lg.entete.search(texte)
            if not m:
                return False
            self._zero()
            return True
        # Java : nom(params) [throws ...] juste avant {. On part de la fin :
        # un @RequestParam(...) dans les parametres n'est pas le nom.
        for m in reversed(list(self.lg.entete.finditer(texte))):
            if m.start() > 0 and texte[m.start() - 1] == "@":
                continue
            if m.group(1) in _JAVA_NON_ENTETES:
                return False
            ouvrante = m.end() - 1
            fin_params = _fin_appel(texte, ouvrante)
            if not re.fullmatch(r"\s*(?:throws\s+[\w.,\s]+)?\s*",
                                texte[fin_params:]):
                continue
            avant = texte[:m.start()].split()
            if not avant or avant[-1] in {"new", "return", "->"} \
                    or avant[-1].endswith(("=", "(", ",")):
                return False         # appel ou creation, pas une declaration
            self._zero()
            for a, b in _arguments(texte, ouvrante):
                if re.search(_ANNOTATIONS_SOURCES,
                             self.brut[debut + a:debut + b]):
                    nom = re.findall(r"([A-Za-z_]\w*)\s*$", texte[a:b])
                    if nom:
                        self.contamine[nom[0]] = self.ligne(debut + a)
            return True
        return False

    def _valides(self, texte: str) -> list[str]:
        vus = []
        for motif in self.lg.validation:
            for m in motif.finditer(texte):
                vus.append(m.groups()[-1])
        return vus

    def _signaler(self, pos: int, famille: Famille, origine: int):
        cle = (famille.regle, origine)
        if cle in self.dits:
            return
        self.dits.add(cle)
        # Une instruction commence souvent par le retour a la ligne qui la
        # precede : la ligne du defaut est celle du premier vrai caractere.
        while pos < len(self.code) - 1 and self.code[pos].isspace():
            pos += 1
        self.defauts.append(Defaut(
            self.nom, self.ligne(pos), famille.regle, B,
            f"{famille.message} (entree ligne {origine} -> ici)",
            famille.norme))

    def _puits(self, debut: int, fin: int):
        texte = self.code[debut:fin]
        # PHP : echo / print / <?= ... ?>
        if self.lg is PHP:
            dans_echo = any(a <= debut + len(texte) - len(texte.lstrip()) < b
                            or a <= debut < b for a, b in self.echos)
            m = re.match(r"\s*(?:echo|print)\b", texte, re.I)
            if m or dans_echo:
                o = self.origine(debut + (m.end() if m else 0), fin, XSS)
                if o:
                    self._signaler(debut + (m.start() if m else 0), XSS, o)
            m = re.match(r"\s*(?:include|require)(?:_once)?\b", texte, re.I)
            if m:
                o = self.origine(debut + m.end(), fin, INCL)
                if o:
                    self._signaler(debut + m.start(), INCL, o)
            for m in re.finditer(r"`[^`]*`", texte):
                o = self.origine(debut + m.start(), debut + m.end(), CMD)
                if o:
                    self._signaler(debut + m.start(), CMD, o)
        else:
            # Java : return "redirect:" + x  /  return "<p>" + x
            m = re.match(r"\s*return\b", texte)
            if m:
                brut = self.brut[debut:fin]
                if re.search(r'"redirect:', brut):
                    o = self.origine(debut + m.end(), fin, REDIR)
                    if o:
                        self._signaler(debut + m.start(), REDIR, o)
                elif re.search(r'"[^"]*<[a-zA-Z/][^"]*"', brut):
                    o = self.origine(debut + m.end(), fin, XSS)
                    if o:
                        self._signaler(debut + m.start(), XSS, o)
        for p in self.lg.puits:
            for m in p.motif.finditer(texte):
                ouvrante = m.end() - 1
                args = _arguments(texte, ouvrante)
                if not args:
                    continue
                if p.exige is not None:
                    a = args[p.cible] if p.cible is not None and \
                        p.cible < len(args) else (ouvrante, len(texte))
                    if not p.exige.search(self.brut[debut + a[0]:
                                                    debut + a[1]]):
                        continue
                if p.argument is TOUS:
                    choisis = args
                elif p.argument == DERNIER:
                    choisis = args[-1:]
                elif p.argument < len(args):
                    choisis = [args[p.argument]]
                else:
                    choisis = []
                for a, b in choisis:
                    o = self.origine(debut + a, debut + b, p.famille)
                    if o:
                        self._signaler(debut + m.start(), p.famille, o)
                        break

    def _propager(self, debut: int, fin: int, texte: str):
        for motif in self.lg.boucles:
            m = motif.match(texte)
            if m:
                if self.lg is PHP:
                    o = self.origine(debut + m.start(1), debut + m.end(1))
                    for g in (2, 3):
                        if m.group(g) and o:
                            self.contamine[m.group(g)] = o
                            self.nettoye.pop(m.group(g), None)
                else:
                    o = self.origine(debut + m.start(2), debut + m.end(2))
                    if o:
                        self.contamine[m.group(1)] = o
                        self.nettoye.pop(m.group(1), None)
                return
        # Java : sb.append(x) contamine sb
        if self.lg is JAVA:
            m = re.match(r"\s*([A-Za-z_]\w*)\s*\.\s*(?:append|add|put|"
                         r"addAll|putAll|insert)\s*\(", texte)
            if m:
                o = self.origine(debut + m.end() - 1, fin)
                if o:
                    self.contamine.setdefault(m.group(1), o)
        m = self.lg.affectation.match(texte)
        if not m:
            return
        variable, operateur = m.group(1), m.group(2)
        if variable in self.lg.mots_cles:
            return
        o = self.origine(debut + m.start(3), fin)
        if o:
            nettoye = self._familles_nettoyees(debut + m.start(3), fin)
            if operateur != "=" and variable in self.contamine:
                nettoye &= self.nettoye.get(variable, frozenset())
                o = min(o, self.contamine[variable])
            self.contamine[variable] = o
            self.nettoye[variable] = nettoye
            self.valide.discard(variable)
        elif operateur == "=":
            self.contamine.pop(variable, None)   # reaffectee proprement
            self.nettoye.pop(variable, None)

    def lancer(self) -> list[Defaut]:
        for debut, fin, sep in _instructions(self.code):
            self.instruction(debut, fin, sep)
        return self.defauts


# ------------------------------------------------------------- entrees
def analyser_php(nom: str, texte: str) -> list[Defaut]:
    prepare, echos = _preparer_php(texte)
    brut = _sans_commentaires(prepare, diese=True)
    code = _blanchir_chaines(brut, garder_doubles=True)
    return _Analyse(PHP, nom, brut, code, echos).lancer()


def analyser_java(nom: str, texte: str) -> list[Defaut]:
    brut = _sans_commentaires(texte, diese=False)
    code = _blanchir_chaines(brut, garder_doubles=False)
    return _Analyse(JAVA, nom, brut, code, []).lancer()
