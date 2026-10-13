"""Outils LOCAUX : ils lisent un dossier de la machine auditee.

Le dossier est monte en LECTURE SEULE sur /cible (voir base.chemin_local_valide :
absolu, sans « .. », hors /proc /sys /dev /run). Aucun outil n'ecrit sur la
machine ; le conteneur lui-meme est --read-only, seul un tmpfs en memoire
recoit les caches.

  VulnerabilitesPaquets  Trivy   failles connues (CVE) des paquets installes
                                 (Apache 2.0)
  SecretsExposes         gitleaks cles et mots de passe oublies dans des
                                 fichiers, MASQUES dans le resultat (MIT)
  Antivirus              ClamAV  fichiers malveillants connus (GPL v2 : image
                                 officielle non modifiee, source disponible
                                 aupres du projet ClamAV)
"""
from __future__ import annotations

import json

from .base import Observation, Outil, OutilEchoue, registre

CIBLE_LOCALE = {
    "type": "object",
    "properties": {
        "cible": {"type": "string",
                  "description": "Chemin absolu sur la machine auditee "
                                 "(ex. « / », « /var/www »)"},
    },
    "required": ["cible"],
    "additionalProperties": False,
}


@registre.inscrire
class VulnerabilitesPaquets(Outil):
    nom = "vulnerabilites_paquets"
    description = (
        "Liste les failles connues (CVE) des paquets installes sur la machine "
        "auditee (paquets du systeme et des langages), avec la version qui "
        "corrige. Complete l'audit de configuration : les fiches verifient "
        "les reglages, cet outil verifie les logiciels."
    )
    schema = {
        "type": "object",
        "properties": {
            **CIBLE_LOCALE["properties"],
            "seulement_corrigeables": {
                "type": "boolean", "default": True,
                "description": "Ne remonter que les failles qui ont un correctif"},
        },
        "required": ["cible"],
        "additionalProperties": False,
    }
    image = "aquasec/trivy"               # figee par images.lock (@sha256)
    portee = "locale"
    # Base de vulnerabilites telechargee UNE fois par la preparation
    # (python -m brain.tools --preparer) dans un volume nomme : le scan ne
    # telecharge rien et marche hors ligne (offre sur site). Avant : la base
    # etait retelechargee a chaque scan et le delai sautait (19/09/2026).
    reseau = "none"
    volumes = {"mael-trivy-cache": "/cache"}
    tmpfs = {"/tmp": "1g"}
    memoire = "2g"
    delai = 1800
    # Commande de la preparation (appelee par brain.tools --preparer).
    PREPARATION = ["--cache-dir", "/cache", "image", "--download-db-only",
                   "--no-progress"]
    # Preuve que la base est bien dans le volume : Trivy la date.
    VERIFICATION = ["--cache-dir", "/cache", "version", "--format", "json"]
    VERIFICATION_ATTENDU = "NextUpdate"   # la base est la, et elle est datee
    MAX_DETAILLES = 60    # au-dela : compte par gravite (message court)

    GRAVITES = {"CRITICAL": "critique", "HIGH": "elevee", "MEDIUM": "moyenne",
                "LOW": "faible", "UNKNOWN": "info"}

    def commande(self, *, cible: str, seulement_corrigeables: bool = True
                 ) -> list[str]:
        args = ["rootfs", "--scanners", "vuln", "--format", "json", "--quiet",
                "--cache-dir", "/cache", "--skip-db-update", "--offline-scan",
                "--timeout", "25m"]
        if seulement_corrigeables:
            args.append("--ignore-unfixed")
        return [*args, cible]

    def analyser(self, sortie: str, obs: Observation) -> None:
        debut = sortie.find("{")
        if debut == -1:
            return
        try:
            rapport = json.loads(sortie[debut: sortie.rfind("}") + 1])
        except json.JSONDecodeError:
            return
        # Piege constate le 20/09/2026, premier scan reel reussi : si le
        # dossier vise n'est pas une racine reconnaissable (il manque
        # /etc/lsb-release, /etc/os-release...), Trivy rend « famille : none »
        # et ZERO faille, sans erreur. Zero faille et « je n'ai pas su lire
        # cette machine » ne sont pas la meme phrase : la seconde doit se
        # dire, sinon on rassure a tort.
        famille = ((rapport.get("Metadata") or {}).get("OS") or {}).get(
            "Family", "none")
        if famille in ("", "none") and not (rapport.get("Results") or []):
            raise OutilEchoue(
                "systeme non reconnu sur la cible : ni /etc/os-release ni "
                "/etc/lsb-release exploitables. Aucune conclusion possible "
                "(ce n'est PAS « aucune faille »).")
        vulns = []
        for res in rapport.get("Results") or []:
            for v in res.get("Vulnerabilities") or []:
                vulns.append(v)
        ordre = list(self.GRAVITES)
        vulns.sort(key=lambda v: ordre.index(v.get("Severity", "UNKNOWN"))
                   if v.get("Severity") in ordre else len(ordre))
        comptes: dict[str, int] = {}
        for i, v in enumerate(vulns):
            gravite = self.GRAVITES.get(v.get("Severity", "UNKNOWN"), "info")
            if i < self.MAX_DETAILLES:
                obs.ajouter(
                    code=str(v.get("VulnerabilityID", "CVE-inconnue")),
                    gravite=gravite,
                    resume=f"{v.get('PkgName')} {v.get('InstalledVersion')} : "
                           f"{v.get('VulnerabilityID')}",
                    paquet=v.get("PkgName"),
                    version=v.get("InstalledVersion"),
                    corrigee_en=v.get("FixedVersion") or "",
                    titre=str(v.get("Title", ""))[:160])
            else:
                comptes[gravite] = comptes.get(gravite, 0) + 1
        if comptes:
            obs.ajouter(code="cve.autres", gravite=min(
                comptes, key=["critique", "elevee", "moyenne", "faible",
                              "info"].index),
                resume=f"{sum(comptes.values())} failles de plus : "
                       + ", ".join(f"{n} {g}" for g, n in comptes.items()),
                par_gravite=comptes)


@registre.inscrire
class FaillesDepot(VulnerabilitesPaquets):
    """Trivy sur un DEPOT de code (13/10/2026, `mael audit`) : les failles
    connues des DEPENDANCES declarees (requirements.txt, poetry.lock,
    package-lock.json, go.sum, pom.xml, composer.lock, Cargo.lock...) et les
    erreurs de CONFIGURATION (Dockerfile, Kubernetes, Terraform, Compose).
    Meme base hors ligne que VulnerabilitesPaquets (volume mael-trivy-cache),
    meme enfermement (--network none, lecture seule)."""
    nom = "failles_depot"
    description = (
        "Liste les failles connues (CVE) des dependances d'un depot de code "
        "et ses erreurs de configuration (Dockerfile, Kubernetes, Terraform), "
        "avec la version qui corrige."
    )

    def commande(self, *, cible: str, seulement_corrigeables: bool = True
                 ) -> list[str]:
        args = ["fs", "--scanners", "vuln,misconfig", "--format", "json",
                "--quiet", "--cache-dir", "/cache", "--skip-db-update",
                "--skip-java-db-update", "--skip-check-update",
                "--offline-scan", "--timeout", "25m"]
        if seulement_corrigeables:
            args.append("--ignore-unfixed")
        return [*args, cible]

    def analyser(self, sortie: str, obs: Observation) -> None:
        debut = sortie.find("{")
        if debut == -1:
            raise OutilEchoue("Trivy n'a rendu aucun rapport (ce n'est PAS "
                              "« aucune faille »)")
        try:
            rapport = json.loads(sortie[debut: sortie.rfind("}") + 1])
        except json.JSONDecodeError as e:
            raise OutilEchoue(f"rapport Trivy illisible : {e}") from e
        resultats = rapport.get("Results") or []
        lus = sorted({r.get("Target", "") for r in resultats})
        obs.ajouter(code="depot.lu", gravite="info",
                    resume=f"{len(lus)} fichier(s) de dependances ou de "
                           f"configuration lus", fichiers=lus[:40])
        vulns = []
        for res in resultats:
            for v in res.get("Vulnerabilities") or []:
                vulns.append((res.get("Target", ""), v))
        ordre = list(self.GRAVITES)
        vulns.sort(key=lambda tv: ordre.index(tv[1].get("Severity"))
                   if tv[1].get("Severity") in ordre else len(ordre))
        comptes: dict[str, int] = {}
        for i, (cible_f, v) in enumerate(vulns):
            gravite = self.GRAVITES.get(v.get("Severity", "UNKNOWN"), "info")
            if i < self.MAX_DETAILLES:
                obs.ajouter(
                    code=str(v.get("VulnerabilityID", "CVE-inconnue")),
                    gravite=gravite,
                    resume=f"{v.get('PkgName')} {v.get('InstalledVersion')} "
                           f": {v.get('VulnerabilityID')} ({cible_f})",
                    fichier=cible_f, paquet=v.get("PkgName"),
                    version=v.get("InstalledVersion"),
                    corrigee_en=v.get("FixedVersion") or "",
                    titre=str(v.get("Title", ""))[:160])
            else:
                comptes[gravite] = comptes.get(gravite, 0) + 1
        if comptes:
            obs.ajouter(code="cve.autres", gravite=min(
                comptes, key=["critique", "elevee", "moyenne", "faible",
                              "info"].index),
                resume=f"{sum(comptes.values())} failles de plus : "
                       + ", ".join(f"{n} {g}" for g, n in comptes.items()),
                par_gravite=comptes)
        for res in resultats:
            for m in res.get("Misconfigurations") or []:
                if m.get("Status", "FAIL") != "FAIL":
                    continue
                ligne = (m.get("CauseMetadata") or {}).get("StartLine")
                obs.ajouter(
                    code=str(m.get("AVDID") or m.get("ID") or "config"),
                    gravite=self.GRAVITES.get(m.get("Severity", "UNKNOWN"),
                                              "info"),
                    resume=f"{m.get('Title', 'configuration')} "
                           f"({res.get('Target', '')}"
                           + (f":{ligne}" if ligne else "") + ")",
                    fichier=res.get("Target", ""), ligne=ligne,
                    message=str(m.get("Message", ""))[:200],
                    correction=str(m.get("Resolution", ""))[:200])


@registre.inscrire
class SecretsExposes(Outil):
    nom = "secrets_exposes"
    description = (
        "Cherche des secrets oublies dans les fichiers d'un dossier (cles "
        "d'API, cles privees, mots de passe dans du code ou de la "
        "configuration). Les secrets trouves sont MASQUES : seuls le fichier, "
        "la ligne et le type de secret sont rapportes."
    )
    schema = CIBLE_LOCALE
    image = "zricethezav/gitleaks"        # figee par images.lock (@sha256)
    portee = "locale"
    reseau = "none"
    delai = 900

    def commande(self, *, cible: str) -> list[str]:
        # --redact : la valeur du secret n'apparait JAMAIS dans la sortie.
        return ["dir", cible, "--report-format", "json",
                "--report-path", "-", "--redact", "--no-banner",
                "--exit-code", "0", "--log-level", "error"]

    def analyser(self, sortie: str, obs: Observation) -> None:
        debut = sortie.find("[")
        if debut == -1:
            return
        try:
            constats = json.loads(sortie[debut: sortie.rfind("]") + 1])
        except json.JSONDecodeError:
            return
        for r in constats:
            fichier = str(r.get("File", "")).removeprefix("/cible")
            # Ni « Secret » ni « Match » : meme masques, ils restent hors du
            # constat (le brut reste en base pour l'analyste).
            obs.ajouter(code=f"secret.{r.get('RuleID', 'inconnu')}",
                        gravite="elevee",
                        resume=f"Secret possible ({r.get('RuleID')}) dans "
                               f"{fichier}:{r.get('StartLine')}",
                        fichier=fichier, ligne=r.get("StartLine"),
                        regle=r.get("RuleID"))


@registre.inscrire
class Antivirus(Outil):
    nom = "antivirus"
    description = (
        "Analyse un dossier de la machine auditee avec ClamAV et rapporte les "
        "fichiers reconnus comme malveillants."
    )
    schema = CIBLE_LOCALE
    image = "clamav/clamav"               # figee par images.lock (@sha256)
    portee = "locale"
    reseau = "none"       # signatures embarquees dans l'image figee
    entrypoint = "clamscan"
    codes_succes = frozenset({0, 1})     # 1 = fichier malveillant trouve
    tmpfs = {"/tmp": "512m"}
    memoire = "3g"        # clamscan charge ~1,5 Go de signatures
    delai = 3600

    def commande(self, *, cible: str) -> list[str]:
        return ["--recursive", "--infected", "--no-summary",
                "--cross-fs=no", "--max-filesize=100M", cible]

    def analyser(self, sortie: str, obs: Observation) -> None:
        # « aucun fichier malveillant » avec des signatures vieilles de six
        # mois n'est pas la meme phrase qu'avec des signatures du jour.
        # L'image est figee par empreinte (offre sur site, sans Internet) :
        # l'age des signatures se DIT, il ne se cache pas (20/09/2026).
        if "virus database is older than" in sortie.lower():
            obs.ajouter(
                code="signatures.anciennes", gravite="info",
                resume="signatures ClamAV vieilles de plus de 7 jours : "
                       "l'absence de detection vaut pour ces signatures, "
                       "pas pour les menaces parues depuis")
        for ligne in sortie.splitlines():
            ligne = ligne.strip()
            if not ligne.endswith(" FOUND") or ": " not in ligne:
                continue
            fichier, signature = ligne[: -len(" FOUND")].rsplit(": ", 1)
            fichier = fichier.removeprefix("/cible")
            obs.ajouter(code="malveillant", gravite="critique",
                        resume=f"Fichier malveillant : {fichier} ({signature})",
                        fichier=fichier, signature=signature)
