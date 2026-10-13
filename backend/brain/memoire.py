"""Memoire d'audit : ou l'IA retient ce qu'elle fait et ou elle en est.

Un audit = un fichier JSON dans `reports/audits/<id>.json`. On peut fermer la
session et la rouvrir : l'IA reprend a la meme etape, avec les memes constats.

L'ETAPE n'est jamais decidee par le modele. Elle avance par des regles, au fil
des evenements observes (une lecture executee, un constat formule...). Un petit
modele se trompe sur "ou j'en suis" ; le code, non.

Le coeur est pur (aucun Django) pour rester testable ; seul le chemin par defaut
est resolu via Django quand on ne le fournit pas.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Les cinq etapes de la methode d'audit, dans l'ordre. L'index = l'avancement.
ETAPES = ["perimetre", "observer", "verifier", "expliquer", "proposer"]

GRAVITES = {"critique", "elevee", "élevée", "moyenne", "faible"}


@dataclass
class Constat:
    resume: str
    risque: str = ""
    gravite: str = ""
    action: str = ""
    quand: float = field(default_factory=time.time)
    # Renseigne quand un constat est requalifie (ex. critique -> faible apres
    # explication de l'humain). Garde la trace, on ne perd pas l'historique.
    gravite_precedente: str = ""
    # Fonde sur une observation (brain.fondement) ? Sinon c'est une HYPOTHESE.
    # Vrai par defaut pour relire les audits anterieurs.
    fonde: bool = True
    fondement: str = ""
    # Etape 5 : ecart MESURE par le code (brain.bibliotheque.ecarts), et non
    # formule par le modele. `cle` = fiche#controle ; `corrige` = une mesure
    # ulterieure l'a trouve conforme (trace gardee).
    origine: str = ""
    cle: str = ""
    corrige: bool = False


@dataclass
class Commande:
    commande: str
    niveau: str          # lecture | modification | interdit
    but: str = ""
    executee: bool = False
    quand: float = field(default_factory=time.time)
    # Controle contre les fiches (etape 2.3) : conforme | usuel | hors_fiche |
    # non_verifie. Vide pour les audits anterieurs.
    verification: str = ""


class MemoireAudit:
    """Etat persistant d'un audit. Sauvegarde a chaque changement."""

    def __init__(self, identifiant: str, dossier: Path,
                 perimetre: str | None = None, hote: str | None = None):
        self.id = identifiant
        self.dossier = Path(dossier)
        self.perimetre = perimetre
        self.hote = hote
        self.debut = time.time()
        self.etape = "perimetre" if not perimetre else "observer"
        self.constats: list[Constat] = []
        self.commandes: list[Commande] = []
        # Observations deposees par l'humain (/preuve) : sortie collee, etc.
        self.preuves: list[str] = []
        # Contexte de la machine auditee (brain.contexte.Contexte en dict).
        self.contexte: dict | None = None
        # Constats du dernier enregistrement juges non fondes (pour le terminal).
        self.derniers_non_fondes: list[Constat] = []
        # Verdicts du code par controle (fiche#controle -> dernier verdict).
        self.evaluations: dict[str, dict] = {}
        # Corrections par playbook (etape 2.6) : trace complete de chaque
        # tentative (simulation, confirmation, resultat, re-mesure, retour).
        self.corrections: list[dict] = []

    # --------------------------------------------------------- persistance
    @property
    def fichier(self) -> Path:
        return self.dossier / f"{self.id}.json"

    def sauver(self) -> None:
        self.dossier.mkdir(parents=True, exist_ok=True)
        donnees = {
            "id": self.id,
            "perimetre": self.perimetre,
            "hote": self.hote,
            "debut": self.debut,
            "etape": self.etape,
            "constats": [asdict(c) for c in self.constats],
            "commandes": [asdict(c) for c in self.commandes],
            "preuves": self.preuves,
            "contexte": self.contexte,
            "evaluations": self.evaluations,
            "corrections": self.corrections,
        }
        self.fichier.write_text(
            json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def charger(cls, identifiant: str, dossier: Path) -> "MemoireAudit":
        m = cls(identifiant, dossier)
        d = json.loads(m.fichier.read_text(encoding="utf-8"))
        m.perimetre = d.get("perimetre")
        m.hote = d.get("hote")
        m.debut = d.get("debut", m.debut)
        m.etape = d.get("etape", m.etape)
        m.constats = [Constat(**c) for c in d.get("constats", [])]
        m.commandes = [Commande(**c) for c in d.get("commandes", [])]
        m.preuves = list(d.get("preuves", []))
        m.contexte = d.get("contexte")
        m.evaluations = dict(d.get("evaluations") or {})
        m.corrections = list(d.get("corrections") or [])
        return m

    @classmethod
    def ouvrir(cls, identifiant: str, dossier: Path, *,
               perimetre: str | None = None, hote: str | None = None
               ) -> "MemoireAudit":
        """Reprend l'audit s'il existe, sinon en cree un neuf."""
        m = cls(identifiant, dossier, perimetre=perimetre, hote=hote)
        if m.fichier.exists():
            return cls.charger(identifiant, dossier)
        m.sauver()
        return m

    # ---------------------------------------------------- avancement d'etape
    def _monter_jusqu_a(self, etape: str) -> None:
        """L'etape ne recule jamais : on garde le point le plus avance atteint."""
        if ETAPES.index(etape) > ETAPES.index(self.etape):
            self.etape = etape

    def enregistrer_commande(self, commande: str, niveau: str, *,
                             but: str = "", executee: bool = False,
                             verification: str = "") -> None:
        self.commandes.append(
            Commande(commande=commande, niveau=niveau, but=but,
                     executee=executee, verification=verification)
        )
        # Regles d'avancement (le code decide, pas le modele) :
        if niveau == "lecture" and executee:
            nb_lectures = sum(
                1 for c in self.commandes if c.niveau == "lecture" and c.executee
            )
            # 1re lecture -> on observe ; a partir de la 2e -> on recoupe.
            self._monter_jusqu_a("verifier" if nb_lectures >= 2 else "observer")
        if niveau == "modification":
            # Proposer une correction = on est a l'etape "proposer".
            self._monter_jusqu_a("proposer")
        self.sauver()

    def enregistrer_constats(self, texte: str, juge=None) -> int:
        """Detecte les constats au format impose dans le texte du modele et les
        memorise. Retourne le nombre de constats ajoutes ou requalifies.

        `juge(texte) -> (fonde, motif)` (cf. brain.fondement.juge_pour) decide
        si chaque constat repose sur une observation. Un constat non fonde est
        garde comme hypothese : il ne fait pas avancer l'etape, et il est
        liste dans `derniers_non_fondes`. Sans juge : tout est fonde
        (compatibilite)."""
        extraits = _extraire_constats(texte)
        ajoutes = requalifies = 0
        fondes_ajoutes = 0
        self.derniers_non_fondes = []
        for c in extraits:
            if juge is not None:
                c.fonde, c.fondement = juge(f"{c.resume} {c.risque}")
            if not c.fonde:
                self.derniers_non_fondes.append(c)
            existant = self._constat_du_meme_sujet(c)
            if existant is None:
                self.constats.append(c)
                ajoutes += 1
                fondes_ajoutes += c.fonde
                continue
            if c.fonde and not existant.fonde:
                existant.fonde, existant.fondement = True, c.fondement
                fondes_ajoutes += 1
            elif existant.fonde and not c.fonde:
                # Sujet deja etabli sur preuve : une reformulation ne le
                # ramene pas au rang d'hypothese.
                self.derniers_non_fondes.remove(c)
            # Meme sujet : on met a jour au lieu de dupliquer. Si la gravite
            # change, on la requalifie et on garde l'ancienne en trace.
            if c.gravite and c.gravite != existant.gravite:
                existant.gravite_precedente = existant.gravite
                existant.gravite = c.gravite
                requalifies += 1
            if c.risque:
                existant.risque = c.risque
            if c.action:
                existant.action = c.action
            if len(c.resume) > len(existant.resume):
                existant.resume = c.resume
        if ajoutes or requalifies or fondes_ajoutes:
            if fondes_ajoutes:
                # Seul un constat FONDE fait passer a l'etape « expliquer ».
                self._monter_jusqu_a("expliquer")
            self.sauver()
        return ajoutes + requalifies

    def enregistrer_verdicts(self, verdicts) -> dict[str, list[Constat]]:
        """Memorise les verdicts du code (etape 5). Un ECART devient un
        constat fonde (origine « code ») ; un controle en ecart puis mesure
        conforme est marque corrige. Rend {"ecarts": nouveaux, "corriges":
        ...}."""
        nouveaux, corriges = [], []
        for v in verdicts:
            statut = getattr(v.statut, "value", v.statut)
            self.evaluations[v.cle] = {
                "fiche": v.fiche, "titre": v.titre, "controle": v.controle,
                "statut": statut, "constate": v.constate,
                "attendu": v.attendu, "gravite": v.gravite,
                "commande": v.commande, "motif": v.motif,
                "playbook": getattr(v, "playbook", None),
                "parametres": getattr(v, "parametres", {}) or {},
                "quand": time.time()}
            existant = next((c for c in self.constats if c.cle == v.cle), None)
            if statut == "ecart":
                resume = (f"{v.titre} : constate « {v.constate} » (attendu : "
                          f"{v.attendu})")
                if existant is None:
                    c = Constat(resume=resume, risque=v.risque,
                                gravite=v.gravite, action=v.action,
                                fonde=True, origine="code", cle=v.cle,
                                fondement=f"mesure par le code sur "
                                          f"« {v.commande} »")
                    self.constats.append(c)
                    nouveaux.append(c)
                else:
                    existant.resume, existant.corrige = resume, False
            elif (statut == "conforme" and existant is not None
                  and not existant.corrige):
                existant.corrige = True
                corriges.append(existant)
        if nouveaux:
            self._monter_jusqu_a("expliquer")
        if verdicts:
            self.sauver()
        return {"ecarts": nouveaux, "corriges": corriges}

    def enregistrer_correction(self, trace: dict) -> None:
        """Trace d'une correction (jamais effacee, meme revenue)."""
        self.corrections.append(dict(trace, quand=time.time()))
        if trace.get("applique"):
            self._monter_jusqu_a("proposer")
        self.sauver()

    def fixer_contexte(self, contexte) -> None:
        """Memorise le contexte (objet Contexte) pour les reprises d'audit."""
        self.contexte = contexte.en_dict() if contexte.connu else None
        self.sauver()

    def ajouter_preuve(self, texte: str) -> None:
        """Observation apportee par l'humain (sortie de commande collee...)."""
        texte = (texte or "").strip()
        if texte:
            self.preuves.append(texte)
            self.sauver()

    def reevaluer(self, juge) -> list["Constat"]:
        """Rejuge les hypotheses apres une nouvelle observation. Rend celles
        qui deviennent fondees."""
        devenus = []
        for c in self.constats:
            if not c.fonde:
                fonde, motif = juge(f"{c.resume} {c.risque}")
                if fonde:
                    c.fonde, c.fondement = True, motif
                    devenus.append(c)
        if devenus:
            self._monter_jusqu_a("expliquer")
            self.sauver()
        return devenus

    def _constat_du_meme_sujet(self, c: "Constat") -> "Constat | None":
        """Retrouve un constat deja etabli qui porte sur le meme sujet, pour le
        mettre a jour plutot que d'en creer un doublon. Conservateur : on ne
        fusionne que sur un signal fort (meme port/numero, ou fort recouvrement
        de mots), jamais deux constats vaguement proches."""
        cible = _signature(c.resume)
        for existant in self.constats:
            sig = _signature(existant.resume)
            # Signal fort 1 : un meme numero distinctif (port, version...).
            if cible["nombres"] & sig["nombres"]:
                return existant
            # Signal fort 2 : fort recouvrement de mots significatifs.
            mots = cible["mots"] & sig["mots"]
            union = cible["mots"] | sig["mots"]
            if union and len(mots) / len(union) >= 0.5:
                return existant
        return None

    # ------------------------------------------------------------- rendu
    def resume_pour_prompt(self) -> str:
        """Injecte dans le systeme a chaque tour : l'IA sait ou elle en est."""
        lignes = [f"Etape courante : {self.etape} "
                  f"(progression {ETAPES.index(self.etape) + 1}/5)."]
        if self.contexte:
            from brain.contexte import Contexte
            lignes.append("Systeme audite : "
                          + Contexte.depuis_dict(self.contexte).libelle()
                          + ". Utilise les commandes de ce systeme.")
        if self.commandes:
            faites = [c for c in self.commandes if c.executee]
            if faites:
                lignes.append("Deja observe (commandes executees) :")
                for c in faites[-6:]:
                    lignes.append(f"  - {c.commande}")
        etablis = [c for c in self.constats if c.fonde]
        hypotheses = [c for c in self.constats if not c.fonde]
        if etablis:
            lignes.append("Constats deja etablis :")
            for c in etablis:
                g = f" [{c.gravite}]" if c.gravite else ""
                r = (f" (requalifie depuis {c.gravite_precedente})"
                     if c.gravite_precedente else "")
                o = (" (CORRIGE : mesure conforme depuis)" if c.corrige else
                     " (ecart mesure par le code)" if c.origine == "code"
                     else "")
                lignes.append(f"  - {c.resume}{g}{r}{o}")
        if hypotheses:
            lignes.append("HYPOTHESES NON VERIFIEES (aucune observation ; "
                          "a confirmer par une commande de lecture avant de "
                          "les presenter comme des constats) :")
            for c in hypotheses:
                lignes.append(f"  - {c.resume}")
        lignes.append("Reprends a partir de la, sans refaire ce qui est fait.")
        return "\n".join(lignes)

    def resume_humain(self) -> str:
        """Affichage /etat pour l'operateur."""
        h = [f"Audit {self.id} — etape : {self.etape} "
             f"({ETAPES.index(self.etape) + 1}/5)",
             f"perimetre : {self.perimetre or 'non defini'}",
             "systeme   : " + (self._libelle_contexte()),
             f"commandes : {len(self.commandes)} "
             f"({sum(c.executee for c in self.commandes)} executees)",
             f"constats  : {sum(c.fonde for c in self.constats)} fonde(s), "
             f"{sum(not c.fonde for c in self.constats)} hypothese(s)"]
        non_verifiees = sum(c.verification == "non_verifie"
                            for c in self.commandes)
        if non_verifiees:
            h.insert(3, f"non verifiees (fiches) : {non_verifiees}")
        for c in self.constats:
            g = f" [{c.gravite}]" if c.gravite else ""
            f = ("  (CORRIGE)" if c.corrige else
                 "" if c.fonde else "  (HYPOTHESE non fondee)")
            h.append(f"  • {c.resume}{g}{f}")
        if self.evaluations:
            statuts = [e["statut"] for e in self.evaluations.values()]
            h.append(f"mesures du code : {statuts.count('conforme')} "
                     f"conforme(s), {statuts.count('ecart')} ecart(s), "
                     f"{statuts.count('indetermine')} indetermine(s) — /ecarts")
        if self.preuves:
            h.append(f"preuves deposees : {len(self.preuves)}")
        h.append(f"fichier   : {self.fichier}")
        return "\n".join(h)

    def _libelle_contexte(self) -> str:
        from brain.contexte import Contexte
        return Contexte.depuis_dict(self.contexte).libelle()


# --------------------------------------------------------------------------- #
# Extraction des constats depuis le texte du modele (format impose par le
# mode d'emploi : **Constat** — ... **Risque** — ... **Gravite** — ... **Action**)
# --------------------------------------------------------------------------- #
# Mots trop courants pour distinguer un sujet d'audit d'un autre.
_VIDES = {
    "sur", "pour", "avec", "dans", "les", "des", "une", "est", "sont", "par",
    "que", "qui", "pas", "plus", "acces", "service", "serveur", "systeme",
    "configuration", "connexion", "expose", "exposee", "ouvert", "ouverte",
}


def _signature(resume: str) -> dict:
    """Signature d'un constat pour reconnaitre 'le meme sujet' :
    - nombres distinctifs (ports, versions) : 5432, 22, 443...
    - mots significatifs (>= 4 lettres, hors mots vides) : postgresql, ssh...
    """
    bas = resume.lower()
    nombres = set(re.findall(r"\d{2,5}", bas))
    mots = {
        m for m in re.findall(r"[a-zA-Zàâéèêëîïôûùç]{4,}", bas)
        if m not in _VIDES
    }
    return {"nombres": nombres, "mots": mots}


def _champ(texte: str, libelle: str) -> str:
    m = re.search(
        rf"\*\*{libelle}\*\*\s*[—:-]\s*(.+?)(?=\n\s*\*\*|\Z)",
        texte, re.IGNORECASE | re.DOTALL,
    )
    return " ".join(m.group(1).split()) if m else ""


def _extraire_constats(texte: str) -> list[Constat]:
    constats: list[Constat] = []
    # Un bloc commence a chaque **Constat**. On decoupe la-dessus.
    morceaux = re.split(r"(?=\*\*Constat\*\*)", texte or "",
                        flags=re.IGNORECASE)
    for bloc in morceaux:
        resume = _champ(bloc, "Constat")
        if not resume:
            continue
        gravite = (_champ(bloc, "Gravite") or _champ(bloc, "Gravité"))
        gravite = gravite.strip(" .").lower()
        # On ne garde que le mot de gravite s'il est reconnu (le modele ajoute
        # parfois une phrase apres). Sinon on garde tel quel.
        for g in ("critique", "elevee", "élevée", "moyenne", "faible"):
            if g in gravite:
                gravite = g
                break
        constats.append(Constat(
            resume=resume,
            risque=_champ(bloc, "Risque"),
            gravite=gravite,
            action=_champ(bloc, "Action"),
        ))
    return constats


def dossier_par_defaut() -> Path:
    """Ou vont les audits.

    Un outil installe n'ecrit pas chez lui : les audits d'un utilisateur lui
    appartiennent, ils vont dans ~/.mael/audits (MAEL_DOSSIER pour deplacer).
    Le serveur, lui, garde reports/audits sous la racine du projet."""
    from django.conf import settings

    from . import reglages

    if getattr(settings, "LOCAL", False):
        return reglages.dossier() / "audits"
    return Path(settings.BASE_DIR) / "reports" / "audits"
