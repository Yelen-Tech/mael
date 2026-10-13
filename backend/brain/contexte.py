"""Contexte de la machine auditee et applicabilite des fiches (etape 2.4.2).

Avec des milliers de fiches, la meme question (« ssh autorise root ? ») n'a
pas la meme reponse sur Ubuntu 22.04, RHEL 9 ou Alpine. On identifie donc le
systeme AVANT de chercher, puis on ne donne au modele que les fiches et les
variantes de commandes qui s'y appliquent.

Sources du contexte, de la plus sure a la moins sure :
  1. detection sur la machine (commandes de LECTURE : /etc/os-release,
     services en cours) ;
  2. declaration de l'operateur (`--systeme ubuntu:22.04`) ;
  3. indice dans le perimetre (« serveur-web (Ubuntu 22.04) »).
Contexte inconnu -> on ne filtre rien (on prefere trop de savoir que pas
assez), et on le dit.

Pur Python, deterministe, sans reseau.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Callable

# Commandes de detection : doivent rester des LECTURES (verifie en test).
CMD_OS = "cat /etc/os-release"
CMD_SERVICES = ("systemctl list-units --type=service --state=running "
                "--no-pager --plain --no-legend")

# ID de /etc/os-release -> famille (celle des variantes de fiches).
_FAMILLES = {
    "debian": "debian", "ubuntu": "debian", "linuxmint": "debian",
    "raspbian": "debian", "kali": "debian",
    "rhel": "rhel", "centos": "rhel", "rocky": "rhel", "almalinux": "rhel",
    "fedora": "rhel", "ol": "rhel", "oracle": "rhel", "amzn": "rhel",
    "sles": "suse", "suse": "suse", "opensuse": "suse",
    "opensuse-leap": "suse", "opensuse-tumbleweed": "suse",
    "alpine": "alpine", "arch": "arch", "manjaro": "arch",
}
# Rebuilds binaires de RHEL : une fiche « rhel>=8 » s'applique a Rocky 8.
_COMPATIBLES_RHEL = {"centos", "rocky", "almalinux", "ol", "oracle"}
# Normalisation des noms de /etc/os-release vers ceux du schema des fiches.
_ALIAS_OS = {"ol": "oracle", "opensuse-leap": "opensuse",
             "opensuse-tumbleweed": "opensuse"}

# Unite systemd -> nom de service canonique (celui des fiches).
_SERVICES = {
    "ssh": "openssh", "sshd": "openssh",
    "nginx": "nginx", "apache2": "apache", "httpd": "apache",
    "postgresql": "postgresql", "mysql": "mysql", "mysqld": "mysql",
    "mariadb": "mysql", "redis": "redis", "redis-server": "redis",
    "mongod": "mongodb", "docker": "docker", "containerd": "docker",
    "fail2ban": "fail2ban", "postfix": "postfix", "exim4": "exim",
    "dovecot": "dovecot", "bind9": "bind", "named": "bind",
    "vsftpd": "vsftpd", "proftpd": "proftpd", "smbd": "samba",
    "auditd": "auditd", "rsyslog": "rsyslog", "ufw": "ufw",
    "firewalld": "firewalld", "nftables": "nftables",
}


@dataclass
class Contexte:
    os_id: str | None = None          # ubuntu, rhel, rocky, alpine...
    version: str | None = None        # 22.04, 9.3...
    famille: str | None = None        # debian | rhel | suse | alpine | arch
    services: list[str] = field(default_factory=list)
    services_connus: bool = False     # False = pas detectes (on ne filtre pas)
    origine: str = "inconnu"          # detection | operateur | perimetre

    @property
    def connu(self) -> bool:
        return self.os_id is not None

    def libelle(self) -> str:
        if not self.connu:
            return "systeme inconnu (aucun filtrage des fiches)"
        s = f"{self.os_id} {self.version or ''}".strip()
        s += f" (famille {self.famille or '?'}, source : {self.origine})"
        if self.services_connus:
            s += " ; services : " + (", ".join(self.services) or "aucun")
        return s

    def en_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def depuis_dict(cls, d: dict | None) -> "Contexte":
        return cls(**d) if d else cls()


# --------------------------------------------------------------------------- #
# Analyse
# --------------------------------------------------------------------------- #
def _nom_os(os_id: str) -> str:
    return _ALIAS_OS.get(os_id, os_id)


def analyser_os_release(texte: str) -> Contexte:
    valeurs = {}
    for ligne in (texte or "").splitlines():
        m = re.match(r'^\s*([A-Z_]+)\s*=\s*"?([^"]*)"?\s*$', ligne)
        if m:
            valeurs[m.group(1)] = m.group(2).strip()
    os_id = (valeurs.get("ID") or "").lower() or None
    if os_id is None:
        return Contexte()
    famille = _FAMILLES.get(os_id)
    if famille is None:
        for parent in (valeurs.get("ID_LIKE") or "").lower().split():
            if parent in _FAMILLES:
                famille = _FAMILLES[parent]
                break
    return Contexte(os_id=_nom_os(os_id), version=valeurs.get("VERSION_ID"),
                    famille=famille, origine="detection")


def analyser_services(texte: str) -> list[str]:
    trouves = set()
    for ligne in (texte or "").splitlines():
        m = re.match(r"^\s*([\w@.-]+)\.service\b", ligne)
        if m:
            unite = m.group(1).split("@", 1)[0]
            if unite in _SERVICES:
                trouves.add(_SERVICES[unite])
    return sorted(trouves)


def depuis_declaration(texte: str, origine: str = "operateur") -> Contexte:
    """« ubuntu:22.04 », « Ubuntu 22.04 », « serveur (RHEL 9) »..."""
    bas = (texte or "").lower()
    noms = sorted(_FAMILLES, key=len, reverse=True)   # opensuse-leap avant suse
    for nom in noms:
        m = re.search(rf"(?<![a-z]){re.escape(nom)}(?![a-z])[\s:_-]*"
                      rf"(\d+(?:\.\d+)*)?", bas)
        if m:
            return Contexte(os_id=_nom_os(nom), version=m.group(1),
                            famille=_FAMILLES[nom], origine=origine)
    return Contexte()


def detecter(executer: Callable[[str], str | None]) -> Contexte:
    """Detecte le contexte avec une fonction qui execute une commande de
    lecture et rend sa sortie (None si impossible)."""
    ctx = analyser_os_release(executer(CMD_OS) or "")
    sortie = executer(CMD_SERVICES)
    if sortie is not None and ".service" in sortie:
        ctx.services = analyser_services(sortie)
        ctx.services_connus = True
    return ctx


# --------------------------------------------------------------------------- #
# Applicabilite
# --------------------------------------------------------------------------- #
def _version(v: str | None) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def _respecte(version: str | None, operateur: str | None,
              borne: str | None) -> bool:
    if not operateur:
        return True
    if not version:
        return True            # version inconnue : on ne peut pas exclure
    a, b = _version(version), _version(borne)
    # Comparaison sur la precision de la borne : 22.04.3 >= 22.04.
    a = a[:len(b)] if len(a) >= len(b) else a + (0,) * (len(b) - len(a))
    return {">=": a >= b, "<=": a <= b, "==": a == b, ">": a > b,
            "<": a < b}[operateur]


_RE_SPEC = re.compile(r"^([a-z0-9_.+-]+?)\s*(>=|<=|==|>|<)?\s*(\d+(?:\.\d+)*)?$")


def _spec(texte: str) -> tuple[str, str | None, str | None]:
    m = _RE_SPEC.match(str(texte).strip().lower())
    if not m:
        return str(texte).lower(), None, None
    return m.group(1), m.group(2), m.group(3)


def os_applicable(specs: list[str], ctx: Contexte) -> bool:
    if not ctx.connu or not specs:
        return True
    for s in specs:
        nom, op, borne = _spec(s)
        if nom == "linux":
            return True
        if nom == ctx.os_id and _respecte(ctx.version, op, borne):
            return True
        if (nom == "rhel" and ctx.os_id in _COMPATIBLES_RHEL | {"oracle"}
                and _respecte(ctx.version, op, borne)):
            return True
        # Nom de famille sans version (« debian ») : couvre les derivees.
        if op is None and _FAMILLES.get(nom) == nom == ctx.famille:
            return True
    return False


def services_applicables(specs: list[str], ctx: Contexte) -> bool:
    if not specs or not ctx.services_connus:
        return True
    presents = set(ctx.services)
    return any(_spec(s)[0] in presents for s in specs)


def applicable(fiche, ctx: Contexte | None) -> tuple[bool, str]:
    """(applicable, raison si ecartee)."""
    if ctx is None or not ctx.connu:
        return True, ""
    specs_os = fiche.applicable.get("os", [])
    if not os_applicable(specs_os, ctx):
        return False, f"systeme hors champ ({', '.join(specs_os)})"
    specs_srv = fiche.applicable.get("services", [])
    if not services_applicables(specs_srv, ctx):
        return False, f"service absent ({', '.join(specs_srv)})"
    return True, ""


def commande_pour(observation, ctx: Contexte | None) -> str:
    """La variante de la famille detectee, sinon la commande par defaut."""
    if ctx is not None and ctx.famille in observation.variantes:
        return observation.variantes[ctx.famille]
    return observation.commande
