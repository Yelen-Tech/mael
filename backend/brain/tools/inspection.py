"""Outils d'inspection : ils exigent tous une preuve de propriete.

Trois exemples complets, qui montrent les trois formes possibles :
  - ScanVuln   : conteneur + sortie JSON ligne par ligne
  - VerifTls   : conteneur + sortie JSON structuree
  - EntetesWeb : Python pur, aucun binaire externe
"""
from __future__ import annotations

import json
import re

import httpx
from django.conf import settings

from .base import Observation, Outil, OutilEchoue, registre

CIBLE_DOMAINE = {
    "type": "object",
    "properties": {
        "cible": {
            "type": "string",
            "description": "Domaine ou adresse IP declaree comme actif du client",
        }
    },
    "required": ["cible"],
    "additionalProperties": False,
}


@registre.inscrire
class ScanVuln(Outil):
    nom = "scan_vulnerabilites"
    description = (
        "Recherche des vulnerabilites web connues sur une cible declaree, "
        "via les modeles Nuclei. Lecture seule, non intrusif."
    )
    schema = {
        "type": "object",
        "properties": {
            "cible": {"type": "string", "description": "Domaine ou URL du client"},
            "gravite_minimale": {
                "type": "string",
                "enum": ["info", "low", "medium", "high", "critical"],
                "default": "medium",
            },
        },
        "required": ["cible"],
        "additionalProperties": False,
    }
    image = "projectdiscovery/nuclei"   # figee par images.lock (@sha256)
    # Conteneur --read-only : nuclei ecrit son dossier de travail dans /tmp
    # ET sa configuration dans /root/.config (nuclei, uncover) ; sans les
    # deux il refuse de demarrer (premiers lancements reels, 20/09/2026).
    # Tout est en memoire et disparait avec le conteneur.
    tmpfs = {"/tmp": "256m", "/root": "64m"}
    # Modeles nuclei : telecharges UNE fois dans un volume nomme par
    # « python -m brain.tools --preparer », comme la base de Trivy. Sans
    # cela nuclei les retelecharge a chaque scan (ou ne trouve rien du tout
    # quand le conteneur est en lecture seule) : constate au premier
    # lancement reel, 20/09/2026. Le scan tourne ensuite sans rien
    # telecharger -- indispensable pour l'offre sur site.
    volumes = {"mael-nuclei-modeles": "/modeles"}
    PREPARATION = ["-update-templates", "-update-template-dir", "/modeles"]
    # Preuve que les modeles sont bien dans le volume : les lister.
    VERIFICATION = ["-templates", "/modeles", "-tl",
                    "-disable-update-check", "-silent"]
    VERIFICATION_ATTENDU = ".yaml"        # au moins un modele liste
    delai = 900

    GRAVITES = {
        "critical": "critique",
        "high": "elevee",
        "medium": "moyenne",
        "low": "faible",
        "info": "info",
    }

    def commande(self, *, cible: str, gravite_minimale: str = "medium") -> list[str]:
        return [
            "-target", cible,
            "-templates", "/modeles",
            "-disable-update-check",
            "-severity", f"{gravite_minimale},high,critical",
            "-jsonl", "-silent",
            "-rate-limit", "50",      # on ne malmene pas l'infrastructure du client
            "-timeout", "10",
        ]

    def analyser(self, sortie: str, obs: Observation) -> None:
        for ligne in sortie.splitlines():
            ligne = ligne.strip()
            if not ligne.startswith("{"):
                continue
            try:
                r = json.loads(ligne)
            except json.JSONDecodeError:
                continue
            info = r.get("info", {})
            obs.ajouter(
                code=r.get("template-id", "inconnu"),
                gravite=self.GRAVITES.get(info.get("severity", "info"), "info"),
                resume=info.get("name", "Constat sans intitule"),
                url=r.get("matched-at", ""),
                cve=info.get("classification", {}).get("cve-id") or [],
                reference=info.get("reference") or [],
            )


@registre.inscrire
class VerifTls(Outil):
    nom = "verifier_tls"
    description = (
        "Analyse la configuration TLS d'un service : protocoles acceptes, "
        "suites de chiffrement, validite et chaine du certificat."
    )
    schema = {
        "type": "object",
        "properties": {
            "cible": {"type": "string"},
            "port": {"type": "integer", "default": 443, "minimum": 1, "maximum": 65535},
        },
        "required": ["cible"],
        "additionalProperties": False,
    }
    image = "drwetter/testssl.sh"       # figee par images.lock (@sha256)
    # Conteneur --read-only : testssl.sh ecrit des fichiers temporaires et,
    # sans TMPDIR, les cherche a la RACINE (« //testssl.XXXXXX ») -- le scan
    # s'interrompait en silence au milieu (premier lancement reel,
    # 20/09/2026). Un tmpfs en memoire, et on l'y envoie.
    tmpfs = {"/tmp": "256m"}
    env = {"TMPDIR": "/tmp"}
    delai = 600
    # testssl.sh rend un code non nul quand il trouve des problemes : ce
    # n'est pas un echec. Seul le JSON (lu par analyser) fait foi.
    codes_succes = frozenset(range(0, 246))

    # On ne remonte que ce qui est actionnable : chaque code correspond
    # a un playbook de la bibliotheque.
    INTERESSANTS = {
        "SSLv2": ("critique", "app.tls-durcissement"),
        "SSLv3": ("critique", "app.tls-durcissement"),
        "TLS1": ("elevee", "app.tls-durcissement"),
        "TLS1_1": ("elevee", "app.tls-durcissement"),
        "cert_expiration_status": ("critique", None),
        "cert_chain_of_trust": ("elevee", None),
        "heartbleed": ("critique", None),
        "ROBOT": ("elevee", None),
    }

    def commande(self, *, cible: str, port: int = 443) -> list[str]:
        # --color 0 : sans cela les codes de couleur du terminal se melent
        # au JSON (premier lancement reel, 20/09/2026).
        return ["--jsonfile", "/dev/stdout", "--quiet", "--color", "0",
                "--severity", "LOW", f"{cible}:{port}"]

    def analyser(self, sortie: str, obs: Observation) -> None:
        # testssl.sh ecrit son JSON sur la sortie standard EN MEME TEMPS que
        # son rapport lisible : le flux n'est donc pas un document JSON. Le
        # lire d'un bloc echouait en silence et rendait « aucun probleme »
        # sur un serveur au certificat auto-signe -- 26 resultats dont 2
        # critiques etaient jetes (premier lancement reel, 20/09/2026).
        # On releve donc chaque objet un par un.
        lignes = []
        for bloc in re.findall(r"\{[^{}]*\}", sortie):
            try:
                objet = json.loads(bloc)
            except json.JSONDecodeError:
                continue
            if isinstance(objet, dict) and "id" in objet:
                lignes.append(objet)
        if not lignes:
            raise OutilEchoue(
                "sortie de testssl.sh illisible : aucun resultat n'a pu etre "
                "lu (ce n'est PAS « aucun probleme »).")
        for r in lignes:
            ident = r.get("id", "")
            if ident not in self.INTERESSANTS:
                continue
            gravite, playbook = self.INTERESSANTS[ident]
            if str(r.get("severity", "")).upper() in {"OK", "INFO"}:
                continue
            obs.ajouter(
                code=f"tls.{ident}",
                gravite=gravite,
                resume=r.get("finding", ident),
                playbook_suggere=playbook,
            )


@registre.inscrire
class EntetesWeb(Outil):
    """Outil en Python pur : pas de conteneur, pas de binaire."""

    nom = "entetes_securite"
    description = (
        "Verifie la presence et la valeur des en-tetes de securite HTTP "
        "d'un site : CSP, HSTS, X-Frame-Options, Referrer-Policy."
    )
    schema = CIBLE_DOMAINE
    image = ""  # non applicable
    delai = 30

    ATTENDUS = {
        "content-security-policy": ("moyenne", "Aucune politique de contenu (CSP)"),
        "strict-transport-security": ("elevee", "HSTS absent : degradation vers HTTP possible"),
        "x-content-type-options": ("faible", "x-content-type-options absent"),
        "referrer-policy": ("faible", "Referrer-Policy absent"),
        "x-frame-options": ("moyenne", "Protection contre l'inclusion en cadre absente"),
    }

    def commande(self, **params):  # non utilise
        return []

    def executer(self, *, organisation, cible: str, **params) -> Observation:
        self._verifier_perimetre(organisation, cible)
        obs = Observation(outil=self.nom, cible=cible)
        url = cible if cible.startswith("http") else f"https://{cible}"
        try:
            with httpx.Client(timeout=self.delai, follow_redirects=True) as c:
                rep = c.get(url)
        except httpx.HTTPError as exc:
            obs.ajouter(code="http.injoignable", gravite="info", resume=str(exc))
            return obs

        presents = {k.lower() for k in rep.headers}
        for entete, (gravite, resume) in self.ATTENDUS.items():
            if entete not in presents:
                obs.ajouter(
                    code=f"entete.{entete}",
                    gravite=gravite,
                    resume=resume,
                    playbook_suggere="app.en-tetes-http",
                )
        if "server" in presents:
            obs.ajouter(
                code="entete.server",
                gravite="faible",
                resume="L'en-tete Server divulgue la version du logiciel",
                valeur=rep.headers["server"],
                playbook_suggere="app.en-tetes-http",
            )
        obs.code_sortie = rep.status_code
        return obs

    def analyser(self, sortie: str, obs: Observation) -> None:  # non utilise
        return


@registre.inscrire
class ReputationLocale(Outil):
    """Consultation de la base d'indicateurs. Aucune preuve requise :
    on lit notre propre base, pas l'infrastructure de quelqu'un."""

    nom = "reputation_indicateur"
    description = (
        "Consulte la reputation connue d'une adresse IP, d'un domaine, "
        "d'une URL ou d'une empreinte de fichier."
    )
    schema = {
        "type": "object",
        "properties": {"cible": {"type": "string"}},
        "required": ["cible"],
        "additionalProperties": False,
    }
    exige_preuve = False
    delai = 5

    def commande(self, **params):
        return []

    def executer(self, *, organisation, cible: str, **params) -> Observation:
        from modules.reputation.models import Indicateur
        from modules.reputation.views import deviner_type

        obs = Observation(outil=self.nom, cible=cible)
        type_ind = deviner_type(cible)
        if type_ind is None:
            obs.ajouter(code="forme.invalide", gravite="info",
                        resume="Valeur non reconnue comme indicateur")
            return obs

        # Valeurs stockees en minuscules, lues en egalite exacte : iexact
        # casse l'index (lecon mesuree du 15/09/2026).
        ind = Indicateur.objects.filter(type=type_ind, valeur=cible.lower()).first()
        if ind is None:
            obs.ajouter(code="reputation.inconnu", gravite="info",
                        resume="Aucun renseignement connu sur cette valeur")
            return obs

        gravite = {"malveillant": "elevee", "suspect": "moyenne"}.get(ind.verdict, "info")
        obs.ajouter(
            code=f"reputation.{ind.verdict}",
            gravite=gravite,
            resume=f"{cible} : {ind.get_verdict_display()} (score {ind.score:.2f})",
            categories=ind.categories,
            sources=sorted(ind.sources),
            fraicheur_jours=ind.fraicheur_jours,
        )
        return obs

    def analyser(self, sortie: str, obs: Observation) -> None:
        return


# Groupes exposes au modele selon la tache (mecanisme 2 : routeur par tache).
GROUPES = {
    "triage": ["reputation_indicateur"],
    "audit_surface": ["scan_vulnerabilites", "verifier_tls", "entetes_securite"],
    "enquete": ["reputation_indicateur", "entetes_securite", "verifier_tls"],
}


def definitions_pour(tache: str) -> list[dict]:
    return registre.definitions(seulement=GROUPES.get(tache))


__all__ = ["registre", "definitions_pour", "GROUPES", "settings"]
