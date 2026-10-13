"""Le CHANTIER PAR ETAPES : un grand projet se construit en lots ordonnes.

Feuille de route « agent autonome » (09/10/2026), point 3. Le chantier avait
UN plan de 8 fichiers au plus : une plateforme de cours (catalogue,
inscriptions, progression, espace formateur, API, base, tests) n'y tient
pas, et un petit modele qui ecrit 40 fichiers d'un coup se perd. Ici :

  1. l'ARCHITECTE (un appel, sortie contrainte par schema) decoupe la
     demande en ETAPES dans l'ordre de construction — les donnees, puis le
     serveur, puis les pages, puis les tests — chacune livrable SEULE ;
  2. chaque etape est planifiee par le chef de chantier (au plus
     envergure.taches_par_lot fichiers), puis ecrite, jugee, reparee ;
  3. entre deux etapes, MAEL RELEVE les contrats etablis (contrats.py) et
     les donne a la suivante ; les juges verifient qu'elle les tient ;
  4. l'etat de chaque etape est garde : un chantier interrompu reprend a
     l'etape ou il s'etait arrete.
Decider s'il faut des etapes ne demande pas le modele : c'est un calcul sur
la demande (nombre de besoins, nombre de couches), dit et explique.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

ETAPES_MAX = 12

SYSTEME_ARCHITECTE = """Tu es l'architecte de MAEL. Tu decoupes un GRAND projet
en ETAPES, dans l'ordre ou on les construit. Tu n'ecris AUCUN code.

Regles :
- d'abord les donnees (le schema de la base), puis le serveur (l'API et sa
  logique metier), puis les pages, puis les tests et la securite ;
- chaque etape LIVRE quelque chose qui marche seul avant la suivante ;
- chaque etape tient en {par_lot} fichiers au plus ;
- entre 2 et {max} etapes ; pas d'etape « finition » vague.

Reponds UNIQUEMENT par une liste, une ligne par etape :
- nom court de l'etape : ce qu'elle livre (une phrase)"""

SCHEMA_ETAPES = {
    "type": "object",
    "properties": {"etapes": {
        "type": "array", "minItems": 2, "maxItems": ETAPES_MAX,
        "items": {"type": "object",
                  "properties": {"nom": {"type": "string", "maxLength": 60},
                                 "livre": {"type": "string",
                                           "maxLength": 200}},
                  "required": ["nom", "livre"]}}},
    "required": ["etapes"],
}


@dataclass
class Etape:
    nom: str
    livre: str
    etat: str = "a faire"         # a faire | faite
    fichiers: list | None = None  # les fichiers que l'etape a ajoutes

    def vers_dict(self) -> dict:
        return asdict(self)


_COUCHES = {
    "base": r"\b(sqlite|postgres\w*|mysql|mariadb|mongo\w*|base de donn|bdd|"
            r"sql|redis|oracle|sql server)\b",
    "serveur": r"\b(api|flask|fastapi|django|express|node|php|backend|serveur|"
               r"spring|laravel)\b",
    "pages": r"\b(pages?|site|interface|tableau de bord|ecran|espace|react|"
             r"vue|formulaire)\b",
    "tests": r"\btests?\b",
    "droits": r"\b(connexion|inscription|roles?|droits|admin|authentif\w*|"
              r"compte)\b",
}
_GRAND = re.compile(r"\b(complet|complete|plateforme|application|systeme|"
                    r"portail|gestion|comme\s+[A-Z]\w+|marketplace|erp|crm)\b",
                    re.I)


def ampleur(demande: str) -> tuple[int, int, bool]:
    """(besoins nommes, couches techniques, mot de grand projet)."""
    d = demande.lower()
    corps = d.split(":", 1)[1] if ":" in d else d
    besoins = [x for x in re.split(r",|;|\bet\b|\+", corps) if len(
        x.strip()) > 2]
    couches = sum(bool(re.search(m, d)) for m in _COUCHES.values())
    return len(besoins), couches, bool(_GRAND.search(demande))


def faut_des_etapes(demande: str, par_lot: int, prevus: int = 0
                    ) -> tuple[bool, str]:
    """Faut-il un chantier par etapes ? (decision, raison dite)."""
    besoins, couches, grand = ampleur(demande)
    if prevus > par_lot:
        return True, (f"environ {prevus} fichiers pour {par_lot} par lot")
    if couches >= 4 or (couches >= 3 and besoins >= 4):
        return True, (f"{couches} couches (base, serveur, pages, tests, "
                      f"droits) et {besoins} besoin(s) nommes")
    if grand and besoins >= 4:
        return True, f"grand projet ({besoins} besoins nommes)"
    return False, (f"{besoins} besoin(s), {couches} couche(s) : un seul plan "
                   "suffit")


_LIGNE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*\**([^:*]{2,60}?)\**\s*[:—–-]\s*"
                    r"(.+?)\s*$")


def lire_etapes(texte: str = "", donnees: dict | None = None
                ) -> list[Etape]:
    """Les etapes de l'architecte : depuis la sortie contrainte (donnees),
    sinon depuis la liste ecrite."""
    brutes = []
    if donnees and isinstance(donnees.get("etapes"), list):
        brutes = [(e.get("nom", ""), e.get("livre", ""))
                  for e in donnees["etapes"] if isinstance(e, dict)]
    else:
        for ligne in (texte or "").splitlines():
            m = _LIGNE.match(ligne)
            if m:
                brutes.append((m.group(1), m.group(2)))
    etapes, vus = [], set()
    for nom, livre in brutes:
        nom, livre = nom.strip(" .`"), livre.strip(" .`")
        if not nom or not livre or nom.lower() in vus:
            continue
        if re.fullmatch(r"(?i)finition|divers|reste|autres?", nom):
            continue
        vus.add(nom.lower())
        etapes.append(Etape(nom, livre))
    return etapes[:ETAPES_MAX]


def consigne_etape(i: int, etapes: list[Etape], contrats: str,
                   deja: list[str]) -> str:
    """Ce que le chef de chantier recoit pour planifier l'etape i."""
    e = etapes[i]
    l = [f"[etape {i + 1}/{len(etapes)} : {e.nom}] {e.livre}",
         "Planifie UNIQUEMENT les fichiers de CETTE etape. Les etapes "
         "suivantes viendront ensuite : " + ("; ".join(
             f"{x.nom}" for x in etapes[i + 1:]) or "aucune") + "."]
    if deja:
        l.append("Fichiers DEJA faits (ne les replanifie pas, sers-t'en) : "
                 + ", ".join(deja))
    if contrats:
        l.append(contrats)
    return "\n".join(l)
