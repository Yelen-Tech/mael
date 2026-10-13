// Couches 3 et 4 pour JavaScript : l'arbre du code (acorn) et la contamination.
//
// Lance par analyse_js.py :  node analyse_js.cjs < source.js  -> JSON sur stdout
//   [{"ligne": 12, "regle": "xss-dom", "gravite": "bloquant",
//     "message": "...", "norme": "..."}, ...]
//
// Meme doctrine que analyse_py.py :
//   - l'arbre, pas des motifs : un commentaire ou une chaine ne declenche rien ;
//   - source -> puits, a travers les variables, fonction par fonction ;
//   - le doute profite au code : ce qu'on ne sait pas lire n'est pas contamine.
// Navigateur (DOM) ET serveur (Node/Express) : les deux vivent en .js.
"use strict";

const path = require("path");
const ACORN = path.join(__dirname, "vendor", "acorn", "acorn.js");
const acorn = require(ACORN);
// acorn-jsx cherche « acorn » par son nom : on le renvoie vers la copie
// embarquee, jamais vers un acorn installe ailleurs (version inconnue).
const Module = require("module");
const resoudreModule = Module._resolveFilename;
Module._resolveFilename = function (demande, ...reste) {
  if (demande === "acorn") return ACORN;
  return resoudreModule.call(this, demande, ...reste);
};
const ParseurJSX = acorn.Parser.extend(
  require(path.join(__dirname, "vendor", "acorn-jsx", "index.js"))());
const JSX = process.argv.includes("--jsx");

const B = "bloquant", C = "conseil";
const defauts = [];
function ajouter(noeud, regle, gravite, message, norme) {
  defauts.push({ ligne: noeud.loc ? noeud.loc.start.line : 1, regle, gravite,
                 message, norme });
}

// ------------------------------------------------------------ catalogue
// Sources navigateur : tout ce que l'URL, la page ou un autre site controlent.
const SOURCES_CHEMIN = new Set([
  "location.hash", "location.search", "location.href", "location.pathname",
  "window.location.hash", "window.location.search", "window.location.href",
  "document.location.hash", "document.location.search", "document.location.href",
  "document.URL", "document.documentURI", "document.referrer",
  "document.cookie", "window.name", "process.argv",
]);
// Sources serveur (Express, Koa, Fastify, http) : req.query, req.body...
const ATTRS_REQUETE = new Set(["query", "body", "params", "cookies",
                               "headers", "url", "originalUrl", "path"]);
const NOMS_REQUETE = new Set(["req", "request", "ctx.request", "ctx"]);

// Ce qui rend une valeur sure (ou de type sur).
const ASSAINISSEURS = new Set([
  "encodeURIComponent", "encodeURI", "parseInt", "parseFloat", "Number",
  "Boolean", "Math.floor", "Math.round", "DOMPurify.sanitize",
  "sanitize", "escapeHtml", "escape", "he.encode", "validator.escape",
  "path.basename", "CSS.escape",
]);

const P = {
  xss:   ["xss-dom", "donnee de l'utilisateur inseree comme HTML",
          "OWASP A03 — XSS DOM (CWE-79)"],
  code:  ["injection-code", "donnee de l'utilisateur executee comme du code",
          "OWASP A03 — CWE-95"],
  redir: ["redirection-ouverte", "l'utilisateur choisit l'adresse de "
          + "destination (javascript: compris)", "CWE-601 / CWE-79"],
  sql:   ["injection-sql", "donnee de l'utilisateur dans une requete SQL",
          "OWASP A03 — injection SQL (CWE-89)"],
  shell: ["injection-commande", "donnee de l'utilisateur dans une commande "
          + "systeme", "OWASP A03 — CWE-78"],
  chemin:["traversee-chemin", "donnee de l'utilisateur dans un chemin de "
          + "fichier", "OWASP A01 — CWE-22"],
  ssrf:  ["ssrf", "l'utilisateur choisit l'adresse que le serveur appelle",
          "OWASP A10 — SSRF (CWE-918)"],
  xssS:  ["xss-serveur", "donnee de l'utilisateur renvoyee en HTML",
          "OWASP A03 — XSS (CWE-79)"],
};

// --------------------------------------------------------------- noms
// Nom pointe d'une expression : a.b.c, ou null si elle n'en a pas.
function nom(n) {
  if (!n) return null;
  if (n.type === "Identifier") return n.name;
  if (n.type === "ThisExpression") return "this";
  if (n.type === "MemberExpression") {
    const base = nom(n.object);
    let prop = null;
    if (!n.computed && n.property.type === "Identifier") prop = n.property.name;
    else if (n.property.type === "Literal" && typeof n.property.value === "string")
      prop = n.property.value;            // window["eval"] = window.eval
    if (prop === null) return null;
    return base ? base + "." + prop : "*." + prop;
  }
  return null;
}
const court = (s) => (s || "").split(".").pop();
const litteral = (n) => n && (n.type === "Literal" ||
  (n.type === "TemplateLiteral" && n.expressions.length === 0));

// Alias de require/import : const { exec } = require("child_process")
const alias = new Map();
function noterAlias(id, module, membre) {
  alias.set(id, membre ? module + "." + membre : module);
}
function resoudre(s) {
  if (!s) return s;
  const [tete, ...reste] = s.split(".");
  const a = alias.get(tete);
  return a ? [a, ...reste].join(".") : s;
}

// ------------------------------------------------------- contamination
let portee = [new Map()];               // pile de { variable -> ligne }
const lire = (v) => { for (let i = portee.length - 1; i >= 0; i--)
  if (portee[i].has(v)) return portee[i].get(v); return null; };
const ecrire = (v, l) => { portee[portee.length - 1].set(v, l); };
const effacer = (v) => { for (const p of portee) p.delete(v); };
const elements = new Set();             // variables qui tiennent un element DOM

function estRequete(n) {
  const s = nom(n);
  return s && (NOMS_REQUETE.has(s) || NOMS_REQUETE.has(court(s)));
}

// Ligne d'origine si l'expression porte une donnee utilisateur, sinon null.
function source(n) {
  if (!n) return null;
  switch (n.type) {
    case "Identifier": return lire(n.name);
    case "MemberExpression": {
      const s = resoudre(nom(n));
      if (s && SOURCES_CHEMIN.has(s)) return n.loc.start.line;
      if (!n.computed && n.property.name && ATTRS_REQUETE.has(n.property.name)
          && estRequete(n.object)) return n.loc.start.line;
      // champ.value d'un element de formulaire, e.target.value, e.data
      // (message d'une autre fenetre)
      const p = n.computed ? null : n.property.name;
      if (p === "value" && (elementDOM(n.object) ||
          court(nom(n.object)) === "target")) return n.loc.start.line;
      return source(n.object);
    }
    case "CallExpression": {
      const s = resoudre(nom(n.callee));
      if (s && (ASSAINISSEURS.has(s) || ASSAINISSEURS.has(court(s))))
        return null;
      if (s === "localStorage.getItem" || s === "sessionStorage.getItem" ||
          s === "prompt" || s === "window.prompt") return n.loc.start.line;
      // x.trim(), params.get("q"), JSON.parse(x), String(x), a.concat(b)
      if (n.callee.type === "MemberExpression") {
        const o = source(n.callee.object);
        if (o) return o;
      }
      if (["String", "JSON.parse", "decodeURIComponent", "decodeURI", "atob",
           "path.join", "path.resolve", "Array.from"].includes(s)
          || ["concat", "join", "replace", "format"].includes(court(s))) {
        for (const a of n.arguments) { const o = source(a); if (o) return o; }
      }
      return null;
    }
    case "NewExpression": {
      // new URLSearchParams(location.search), new URL(req.query.u)
      for (const a of n.arguments) { const o = source(a); if (o) return o; }
      return null;
    }
    case "TemplateLiteral":
      for (const e of n.expressions) { const o = source(e); if (o) return o; }
      return null;
    case "BinaryExpression":
      return n.operator === "+" ? (source(n.left) || source(n.right)) : null;
    case "LogicalExpression": return source(n.left) || source(n.right);
    case "ConditionalExpression": return source(n.consequent) || source(n.alternate);
    case "AwaitExpression": return source(n.argument);
    case "ArrayExpression":
      for (const e of n.elements) { const o = source(e); if (o) return o; }
      return null;
    case "SpreadElement": return source(n.argument);
    case "ChainExpression": return source(n.expression);
  }
  return null;
}

function elementDOM(n) {
  if (!n) return false;
  if (n.type === "Identifier") return elements.has(n.name);
  if (n.type === "CallExpression") {
    const c = court(nom(n.callee));
    return ["querySelector", "getElementById", "getElementsByName",
            "closest"].includes(c);
  }
  if (n.type === "MemberExpression" && n.computed) return elementDOM(n.object);
  return false;
}

// Chaine montee a la main : `...${x}`, "..." + x
function construite(n) {
  if (!n) return false;
  if (n.type === "TemplateLiteral") return n.expressions.length > 0;
  if (n.type === "BinaryExpression" && n.operator === "+")
    return !(litteral(n.left) && litteral(n.right)) &&
      (litteral(n.left) || litteral(n.right) || construite(n.left)
       || construite(n.right));
  return false;
}

// ------------------------------------------------------------- puits
function puits(n, cle, argument) {
  const o = source(argument);
  if (o) {
    const [regle, message, norme] = P[cle];
    ajouter(n, regle, B, `${message} (entree ligne ${o} -> ici)`, norme);
    return true;
  }
  return false;
}

const MOTS_SECRETS = ["token", "jeton", "password", "passwd", "secret",
                      "otp", "nonce", "salt", "apikey", "api_key", "cle"];
function nomSecret(v) {
  const l = v.toLowerCase();
  // resetToken -> reset_token -> [reset, token] : decouper AVANT de baisser
  const mots = v.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase()
    .split(/[_\-]/);
  return MOTS_SECRETS.some((m) => l === m || mots.includes(m) ||
    (m.length > 3 && l.endsWith(m)));
}

function appel(n) {
  const brut = nom(n.callee);
  const s = resoudre(brut) || "";
  const c = court(s);
  const a0 = n.arguments[0];

  // --- execution de texte
  if (s === "eval" || s === "window.eval") {
    if (!puits(n, "code", a0))
      ajouter(n, "js-dangereux", litteral(a0) ? C : B,
              "eval() execute du texte comme du code", "OWASP A03 / CWE-95");
    return;
  }
  if ((s === "setTimeout" || s === "setInterval" || s === "window.setTimeout")
      && a0 && (a0.type === "Literal" || a0.type === "TemplateLiteral"
                || a0.type === "BinaryExpression")) {
    if (!puits(n, "code", a0))
      ajouter(n, "js-dangereux", B, `${c} avec une chaine = eval`,
              "OWASP A03 / CWE-95");
    return;
  }
  if (s === "document.write" || s === "document.writeln") {
    if (!puits(n, "xss", a0))
      ajouter(n, "js-dangereux", B, `${s}()`, "OWASP A03 — XSS");
    return;
  }
  if (c === "insertAdjacentHTML" || c === "createContextualFragment") {
    const arg = c === "insertAdjacentHTML" ? n.arguments[1] : a0;
    if (!puits(n, "xss", arg) && arg && !litteral(arg))
      ajouter(n, "innerhtml", B, `${c} recoit une valeur construite`,
              "OWASP A03 — XSS (CWE-79)");
    return;
  }
  // jQuery : $(x).html(y), $(y) ou y est du HTML de l'utilisateur
  if (c === "html" && n.callee.type === "MemberExpression" && a0
      && !litteral(a0)) {
    if (!puits(n, "xss", a0))
      ajouter(n, "innerhtml", C, ".html() recoit une valeur construite : "
              + ".text() si c'est du texte", "OWASP A03 — XSS (CWE-79)");
    return;
  }
  // --- navigation
  if (["location.assign", "location.replace", "window.location.assign",
       "window.location.replace", "window.open"].includes(s)) {
    puits(n, "redir", a0); return;
  }
  if (c === "setAttribute" && n.arguments[0] && n.arguments[0].type === "Literal"
      && ["href", "src", "action", "formaction"].includes(
        String(n.arguments[0].value).toLowerCase())) {
    puits(n, "redir", n.arguments[1]); return;
  }
  if (c === "setAttribute" && n.arguments[0] && n.arguments[0].type === "Literal"
      && /^on/i.test(String(n.arguments[0].value))) {
    if (!puits(n, "code", n.arguments[1]))
      ajouter(n, "evenement-en-ligne", C, "setAttribute(\"on...\") : "
              + "utiliser addEventListener", "OWASP — CSP");
    return;
  }
  // --- messages entre fenetres
  if (c === "postMessage" && n.arguments[1] && n.arguments[1].type === "Literal"
      && n.arguments[1].value === "*") {
    ajouter(n, "postmessage-etoile", C, "postMessage(..., \"*\") : n'importe "
            + "quel site peut lire le message", "CWE-345");
  }
  if (c === "addEventListener" && a0 && a0.type === "Literal"
      && a0.value === "message") {
    const f = n.arguments[1];
    const corps = f && f.body ? JSON.stringify(f.body, (k, v) =>
      k === "loc" ? undefined : v) : "";
    if (f && !/"origin"/.test(corps))
      ajouter(n, "message-sans-origine", B, "message recu d'une autre "
              + "fenetre sans verifier event.origin", "CWE-346");
  }

  // --- serveur (Node)
  if (["child_process.exec", "child_process.execSync"].includes(s)
      || (["exec", "execSync"].includes(c) && s.startsWith("child_process"))) {
    if (!puits(n, "shell", a0) && a0 && !litteral(a0))
      ajouter(n, "js-dangereux", B, `${c}() passe par le shell : `
              + "execFile(prog, [args])", "OWASP A03 / CWE-78");
    return;
  }
  if (["child_process.spawn", "child_process.execFile"].includes(s)) {
    const opts = n.arguments.find((a) => a.type === "ObjectExpression");
    const shell = opts && opts.properties.some((p) => p.key &&
      (p.key.name === "shell") && p.value.type === "Literal" && p.value.value);
    if (shell && !puits(n, "shell", a0))
      ajouter(n, "js-dangereux", B, `${c} avec shell: true`,
              "OWASP A03 / CWE-78");
    else if (!shell) puits(n, "shell", a0);
    return;
  }
  if (s.startsWith("fs.") || s.startsWith("fs/promises.")
      || ["sendFile", "download", "createReadStream", "readFile",
          "readFileSync", "unlink", "unlinkSync"].includes(c)) {
    if (["sendFile", "download"].includes(c) || s.startsWith("fs"))
      puits(n, "chemin", a0);
    return;
  }
  if (["query", "execute", "raw", "run", "all", "get", "prepare", "exec"]
      .includes(c) && n.callee.type === "MemberExpression" && a0
      && /\b(select|insert|update|delete)\b/i.test(texteDe(a0))) {
    if (!puits(n, "sql", a0) && construite(a0))
      ajouter(n, "injection-sql", B, "requete SQL construite avec des "
              + "valeurs : placeholders (?, $1) + tableau de valeurs",
              "OWASP A03 — injection SQL (CWE-89)");
    return;
  }
  if (c === "redirect" && n.callee.type === "MemberExpression") {
    puits(n, "redir", n.arguments[n.arguments.length - 1]); return;
  }
  if (c === "send" && n.callee.type === "MemberExpression" &&
      ["res", "response", "reply"].includes(court(nom(n.callee.object)))) {
    // res.send(objet) renvoie du JSON : pas de HTML, pas de XSS. Seul un
    // texte monte a la main (gabarit, concatenation) est du HTML.
    if (construite(a0)) puits(n, "xssS", a0);
    return;
  }
  if (["fetch", "axios", "axios.get", "axios.post", "http.get", "https.get",
       "got", "request"].includes(s)) {
    // SSRF n'a de sens que cote serveur : on ne le signale que si la
    // donnee vient d'une requete entrante (req.*), pas de la page.
    if (sourceServeur(a0)) puits(n, "ssrf", a0);
  }
}

function sourceServeur(n) {
  const t = JSON.stringify(n, (k, v) => (k === "loc" ? undefined : v));
  return /"name":"(req|request|ctx)"/.test(t) || serveurVu;
}
let serveurVu = false;

function texteDe(n) {
  if (!n) return "";
  if (n.type === "Literal") return String(n.value);
  if (n.type === "TemplateLiteral") return n.quasis.map((q) => q.value.raw).join(" ");
  if (n.type === "BinaryExpression") return texteDe(n.left) + " " + texteDe(n.right);
  if (n.type === "Identifier") return requetes.get(n.name) || "";
  return "";
}
const requetes = new Map();             // variable -> texte SQL montee

function affectation(cible, valeur, noeud) {
  // el.innerHTML = ..., el.outerHTML += ...
  if (cible.type === "MemberExpression") {
    const p = cible.computed ? null : cible.property.name;
    if (p === "innerHTML" || p === "outerHTML") {
      if (!puits(noeud, "xss", valeur) && valeur && !litteral(valeur))
        ajouter(noeud, "innerhtml", B, "innerHTML recoit une valeur "
                + "construite : textContent ou createElement",
                "OWASP A03 — XSS (CWE-79)");
      return;
    }
    const s = resoudre(nom(cible));
    if (["location", "location.href", "window.location",
         "window.location.href", "document.location"].includes(s)
        || ((p === "href" || p === "src" || p === "action")
            && !SOURCES_CHEMIN.has(s))) {
      puits(noeud, "redir", valeur);
      return;
    }
    if (p && /^on[a-z]+$/.test(p) && valeur && valeur.type === "Literal"
        && typeof valeur.value === "string") {
      ajouter(noeud, "js-dangereux", B, `${p} = "chaine" : du code dans une `
              + "chaine (eval deguise)", "OWASP A03 / CWE-95");
    }
    return;
  }
  if (cible.type === "Identifier") {
    const o = source(valeur);
    if (o) ecrire(cible.name, o); else effacer(cible.name);
    if (elementDOM(valeur)) elements.add(cible.name);
    if (valeur && /\b(select|insert|update|delete)\b/i.test(texteDe(valeur))
        && construite(valeur)) requetes.set(cible.name, texteDe(valeur));
    // Math.random pour un secret
    if (nomSecret(cible.name) && contient(valeur, (x) => x.type ===
        "CallExpression" && resoudre(nom(x.callee)) === "Math.random"))
      ajouter(noeud, "hasard-faible", B, "Math.random() pour un secret : "
              + "previsible (crypto.getRandomValues / crypto.randomUUID)",
              "OWASP A02 / CWE-338");
  }
}

function contient(n, test) {
  let trouve = false;
  (function voir(x) {
    if (trouve || !x || typeof x.type !== "string") return;
    if (test(x)) { trouve = true; return; }
    for (const k of Object.keys(x)) {
      if (k === "loc") continue;
      const v = x[k];
      if (Array.isArray(v)) v.forEach(voir);
      else if (v && typeof v.type === "string") voir(v);
    }
  })(n);
  return trouve;
}

// ------------------------------------------------------------ parcours
// Dans l'ordre du texte : une variable n'est contaminee qu'APRES la ligne
// qui la contamine.
// ------------------------------------------------------------- JSX
const etiquettesJSX = new Set();        // valeurs de htmlFor du fichier
const champsJSX = [];                   // champs a verifier en fin de fichier
let dansLabel = 0;

function nomJSX(n) {
  if (!n) return "";
  if (n.type === "JSXIdentifier") return n.name;
  if (n.type === "JSXMemberExpression") return nomJSX(n.object) + "." + nomJSX(n.property);
  return "";
}
function attrs(ouvrant) {
  const m = new Map();
  for (const a of ouvrant.attributes)
    if (a.type === "JSXAttribute") m.set(nomJSX(a.name), a.value);
  return m;
}
const valeurAttr = (v) => !v ? true : v.type === "Literal" ? v.value
  : v.type === "JSXExpressionContainer" ? v.expression : null;
const aTexte = (el) => el.children.some((c) =>
  (c.type === "JSXText" && c.value.trim()) || c.type === "JSXExpressionContainer"
  && c.expression.type !== "JSXEmptyExpression" || (c.type === "JSXElement"
  && (nomJSX(c.openingElement.name) === "img"
      ? attrs(c.openingElement).get("alt") : aTexte(c))));

function elementJSX(el) {
  const o = el.openingElement;
  const balise = nomJSX(o.name);
  const a = attrs(o);
  const etiquette = a.has("aria-label") || a.has("aria-labelledby")
                    || a.has("title");
  if (balise === "label" && a.has("htmlFor")) {
    const v = valeurAttr(a.get("htmlFor"));
    if (typeof v === "string") etiquettesJSX.add(v);
  }
  if (balise === "img" && !a.has("alt"))
    ajouter(o, "img-alt", B, "<img> sans alt (alt=\"\" si decorative)",
            "WCAG 2.2 — 1.1.1");
  if (["input", "select", "textarea"].includes(balise)) {
    const type = valeurAttr(a.get("type"));
    if (!["hidden", "submit", "button", "reset", "image"].includes(type)) {
      const id = valeurAttr(a.get("id"));
      champsJSX.push({ noeud: o, balise, id: typeof id === "string" ? id : null,
                       etiquete: etiquette || dansLabel > 0 });
    }
  }
  if ((balise === "a" || balise === "button") && !etiquette && !aTexte(el))
    ajouter(o, "nom-accessible", B, `<${balise}> sans texte ni aria-label`,
            "WCAG 2.2 — 2.4.4 / 4.1.2");
  if (balise === "button" && !a.has("type"))
    ajouter(o, "button-type", C, "<button> sans type : il soumet le "
            + "formulaire par defaut", "HTML §4.10.6");
  if (balise === "a" && valeurAttr(a.get("target")) === "_blank") {
    const rel = String(valeurAttr(a.get("rel")) || "");
    if (!/noopener|noreferrer/.test(rel))
      ajouter(o, "blank-noopener", C, "target=\"_blank\" sans rel=\"noopener\"",
              "OWASP — reverse tabnabbing");
  }
  // Un div cliquable n'existe pas pour le clavier ni le lecteur d'ecran.
  if (/^[a-z]/.test(balise) && !["button", "a", "input", "select", "textarea",
       "summary", "label", "option"].includes(balise) && a.has("onClick")
      && !(a.has("role") && (a.has("onKeyDown") || a.has("onKeyUp"))))
    ajouter(o, "clic-sans-clavier", B, `<${balise} onClick> : utiliser un `
            + "<button type=\"button\">", "WCAG 2.2 — 2.1.1 / 4.1.2");
  // href={...} venant de l'utilisateur : javascript:alert(1) passe.
  for (const attr of ["href", "src", "action", "formAction"]) {
    const v = valeurAttr(a.get(attr));
    if (v && typeof v === "object") puits(o, "redir", v);
  }
  // dangerouslySetInnerHTML={{ __html: x }}
  const d = valeurAttr(a.get("dangerouslySetInnerHTML"));
  if (d && d.type === "ObjectExpression") {
    const prop = d.properties.find((p) => p.key && (p.key.name === "__html"
                                                    || p.key.value === "__html"));
    const x = prop && prop.value;
    const nettoye = x && x.type === "CallExpression" && ASSAINISSEURS.has(
      court(resoudre(nom(x.callee))));
    if (x && !nettoye && !puits(o, "xss", x) && !litteral(x))
      ajouter(o, "innerhtml", B, "dangerouslySetInnerHTML avec une valeur "
              + "non nettoyee : DOMPurify.sanitize(html), ou du texte",
              "OWASP A03 — XSS (CWE-79)");
  }
  // Les expressions des attributs et des enfants sont analysees comme du JS.
  for (const at of o.attributes) parcourir(at.type === "JSXSpreadAttribute"
                                            ? at.argument : at.value);
  if (balise === "label") dansLabel++;
  for (const c of el.children) parcourir(c);
  if (balise === "label") dansLabel--;
}

function parcourir(n) {
  if (!n || typeof n.type !== "string") return;
  if (n.type === "JSXElement") { elementJSX(n); return; }
  switch (n.type) {
    case "FunctionDeclaration": case "FunctionExpression":
    case "ArrowFunctionExpression": {
      portee.push(new Map());
      // (req, res) => ... : les parametres d'un gestionnaire de route
      // ne sont pas des donnees ; req.query, lui, en est une (voir source).
      for (const p of n.params) {
        if (p.type === "Identifier" && NOMS_REQUETE.has(p.name)) serveurVu = true;
      }
      parcourir(n.body);
      portee.pop();
      return;
    }
    case "ImportDeclaration":
      for (const sp of n.specifiers) {
        const module = String(n.source.value).replace(/^node:/, "");
        if (sp.type === "ImportSpecifier") noterAlias(sp.local.name, module,
                                                      sp.imported.name);
        else noterAlias(sp.local.name, module, null);
      }
      return;
    case "VariableDeclarator": {
      parcourir(n.init);
      // const x = require("child_process") / const { exec } = require(...)
      if (n.init && n.init.type === "CallExpression"
          && nom(n.init.callee) === "require" && n.init.arguments[0]
          && n.init.arguments[0].type === "Literal") {
        const module = String(n.init.arguments[0].value).replace(/^node:/, "");
        if (n.id.type === "Identifier") noterAlias(n.id.name, module, null);
        if (n.id.type === "ObjectPattern")
          for (const p of n.id.properties)
            if (p.key && p.value && p.value.type === "Identifier")
              noterAlias(p.value.name, module, p.key.name || p.key.value);
        return;
      }
      if (n.id.type === "Identifier") affectation(n.id, n.init, n);
      else if (n.id.type === "ObjectPattern" || n.id.type === "ArrayPattern") {
        // const { q } = req.query : chaque morceau herite de la source
        const o = source(n.init);
        for (const id of identifiants(n.id)) if (o) ecrire(id, o);
      }
      return;
    }
    case "AssignmentExpression":
      parcourir(n.right);
      if (n.operator === "+=" && n.left.type === "Identifier") {
        const o = source(n.right);
        if (o) ecrire(n.left.name, o);
        return;
      }
      affectation(n.left, n.right, n);
      return;
    case "CallExpression":
      for (const a of n.arguments) parcourir(a);
      parcourir(n.callee);
      appel(n);
      return;
    case "NewExpression": {
      for (const a of n.arguments) parcourir(a);
      const s = resoudre(nom(n.callee));
      if (s === "Function") {
        const dernier = n.arguments[n.arguments.length - 1];
        if (!puits(n, "code", dernier))
          ajouter(n, "js-dangereux", B, "new Function() = eval deguise",
                  "OWASP A03 / CWE-95");
      }
      return;
    }
  }
  for (const k of Object.keys(n)) {
    if (k === "loc" || k === "type") continue;
    const v = n[k];
    if (Array.isArray(v)) v.forEach(parcourir);
    else if (v && typeof v.type === "string") parcourir(v);
  }
}

function identifiants(motif) {
  if (!motif) return [];
  if (motif.type === "Identifier") return [motif.name];
  if (motif.type === "ObjectPattern")
    return motif.properties.flatMap((p) => identifiants(p.value || p.argument));
  if (motif.type === "ArrayPattern") return motif.elements.flatMap(identifiants);
  if (motif.type === "AssignmentPattern") return identifiants(motif.left);
  if (motif.type === "RestElement") return identifiants(motif.argument);
  return [];
}

// ------------------------------------------------------------- entree
let texte = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (d) => { texte += d; });
process.stdin.on("end", () => {
  let arbre = null;
  let erreur = null;
  // Module d'abord (import/export, await de haut niveau), script ensuite.
  // Un fichier .jsx est lu avec l'extension JSX (React).
  const parseur = JSX ? ParseurJSX : acorn.Parser;
  for (const sourceType of ["module", "script"]) {
    try {
      arbre = parseur.parse(texte, { ecmaVersion: "latest", sourceType,
                                     locations: true, allowHashBang: true,
                                     allowReturnOutsideFunction: sourceType
                                       === "script" });
      break;
    } catch (e) { erreur = erreur || e; }
  }
  if (!arbre) {
    const ligne = erreur && erreur.loc ? erreur.loc.line : 1;
    const message = String(erreur && erreur.message || "erreur de syntaxe")
      .replace(/\s*\(\d+:\d+\)$/, "");
    process.stdout.write(JSON.stringify([{ ligne, regle: "js-syntaxe",
      gravite: B, message: "erreur de syntaxe : " + message,
      norme: "ECMAScript" }]));
    return;
  }
  for (const n of arbre.body) parcourir(n);
  // Champs JSX sans etiquette : juges a la fin, quand tous les htmlFor du
  // fichier sont connus (le <label> peut venir apres le champ).
  for (const ch of champsJSX)
    if (!ch.etiquete && !(ch.id && etiquettesJSX.has(ch.id)))
      ajouter(ch.noeud, "champ-sans-label", B, `<${ch.balise}> sans `
              + "etiquette (<label htmlFor> ou aria-label)",
              "WCAG 2.2 — 1.3.1 / 4.1.2");
  // var : simple conseil, une seule fois
  const v = arbre.body.find((n) => n.type === "VariableDeclaration"
                                    && n.kind === "var");
  if (v) ajouter(v, "js-var", C, "var : preferer const / let",
                 "ECMAScript 2015+");
  process.stdout.write(JSON.stringify(defauts));
});
