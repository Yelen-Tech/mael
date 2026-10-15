"""Etape 5 du pipeline : evaluation deterministe des ecarts (le code juge).

Une fiche dit ce qui est attendu ; une commande de lecture a ete executee ;
le CODE lit sa sortie et decide, sans modele :

  conforme     -- la sortie montre la valeur attendue ;
  ecart        -- la sortie montre autre chose (gravite de la fiche) ;
  indetermine  -- la sortie ne permet pas de conclure (vide, droits
                  insuffisants, fichier absent...), avec la raison.

Le modele (qwen2.5:3b) n'est plus juge : il recoit les verdicts et n'explique
que les ecarts. Un petit modele lit mal « 0644 » contre « 0640 » ; le code,
non.

Chaque controle d'une fiche peut porter une liste `evaluation` :

    evaluation:
      - commande: 0            # index dans « observer »
        lecteur: stat          # comment lire la sortie (cf. LECTEURS)
        champ: groupe          # selon le lecteur
        comparateur: dans      # cf. LECTEURS[lecteur]
        attendu: [root]

Plusieurs entrees = plusieurs preuves (valeur active ET persistante) : un seul
ecart suffit a mettre le controle en ecart ; il n'est conforme que si toutes
ses preuves observees le sont (les autres restent « a observer »).

Seule la sortie standard est lue (stderr = bruit : « Permission denied »...).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache

# Niveau de conformite par defaut d'un client (decide le 17/09/2026) :
# CIS niveau 1 + ANSSI intermediaire. Une fiche plus exigeante n'est pas
# mesuree : ce n'est pas un ecart au regard du niveau retenu.
NIVEAU_DEFAUT = (1, "intermediaire")

# Ecarts detailles au modele (petit modele : message court) ; les autres
# sont comptes et restent visibles pour l'humain (/ecarts).
MAX_ECARTS_MODELE = 4
_RANG_GRAVITE = {"critique": 0, "elevee": 1, "élevée": 1, "moyenne": 2,
                 "faible": 3}


# Ligne emise par une commande de detection quand le fichier lu est illisible
# (droits root manquants) : sans elle, « aucune ligne » passerait pour
# « conforme ». Ex. : awk ... /etc/shadow || echo 'SENTINELLE:ILLISIBLE'
ILLISIBLE = "SENTINELLE:ILLISIBLE"
# Ligne emise quand le composant vise n'est pas installe (GNOME, chrony,
# postfix, SSSD...) : la regle est sans objet, pas en ecart.
SANS_OBJET = "SENTINELLE:SANS_OBJET"
# Substituee a la sortie quand la commande n'a pas pu s'executer (binaire
# introuvable 127, non executable 126, delai depasse 124) : une sortie vide
# serait sinon jugee (« aucune valeur » = faux ecart). Signale en revue interne
# (banc, 19/09/2026) ; le terminal avait le meme defaut.
IMPOSSIBLE = "SENTINELLE:IMPOSSIBLE"
CODES_IMPOSSIBLES = {124, 126, 127}


def sortie_a_juger(code: int | None, stdout: str) -> str:
    """Ce que le code doit juger : la sortie standard, ou le marqueur
    IMPOSSIBLE si la commande n'a pas pu s'executer."""
    return IMPOSSIBLE if code in CODES_IMPOSSIBLES else (stdout or "")


def _marqueur(lignes: list[str]) -> "Lecture | None":
    """Lecture imposee par un marqueur de commande, sinon None."""
    propres = {l.strip() for l in lignes}
    if IMPOSSIBLE in propres:
        return Lecture(STATUT.INDETERMINE, "commande impossible",
                       "commande introuvable ou interrompue sur ce systeme : "
                       "rien a juger")
    if SANS_OBJET in propres:
        return Lecture(STATUT.INDETERMINE, "sans objet",
                       "composant non installe : la regle ne s'applique pas")
    if ILLISIBLE in propres:
        return Lecture(STATUT.INDETERMINE, "fichier illisible",
                       "lecture impossible sans les droits root (sudo)")
    return None


class STATUT(str, Enum):
    CONFORME = "conforme"
    ECART = "ecart"
    INDETERMINE = "indetermine"


# lecteur -> comparateurs admis. Le validateur de fiches s'y refere.
LECTEURS: dict[str, set[str]] = {
    "valeur": {"egal"},                      # 1re ligne (sysctl -n)
    # lignes [fichier:]cle = valeur ; « defaut » = valeur quand rien n'est
    # ecrit (defaut du module), « accepte » = valeurs admises en plus.
    # « sep: espace » pour les fichiers « CLE valeur » (login.defs) ;
    # « umask » = au moins aussi restrictif (bits).
    "affectations": {"toutes_egales", "au_plus", "au_moins", "entre", "umask",
                     "droits_au_plus"},
    "stat": {"droits_au_plus", "dans"},      # « mode proprietaire groupe chemin »
    "dpkg": {"installe", "absent"},          # dpkg-query -W -f='${binary:Package} ${Status}'
    "systemctl": {"actif", "inactif"},       # is-enabled puis is-active
    "modprobe": {"interdit"},                # grep -R dans modprobe.d
    "aucune_ligne": {"vide"},                # lsmod | grep -w : rien = conforme
    "findmnt": {"option_presente", "monte"}, # findmnt -kn : options en dernier
    "fstab": {"option_presente"},            # ligne de /etc/fstab : 4e colonne
    "kconfig": {"egal"},                     # CONFIG_X=y / # CONFIG_X is not set
    "cmdline": {"egal", "au_moins", "absent"},   # /proc/cmdline
    "grub": {"egal", "au_moins", "absent"},      # GRUB_CMDLINE_LINUX="..."
    "sshd_t": {"egal", "dans", "max", "maxstartups", "fichier"},  # sshd -T
    # auditctl -l ou /etc/audit/rules.d : surveillance d'un chemin (-w),
    # appels systeme (-S, b32 ET b64), execution d'une commande (path=, x).
    "audit": {"surveille", "appels", "execution"},
    "pam": {"arguments"},                    # lignes d'un module de /etc/pam.d
    "sudo_defaults": {"option", "au_plus"},  # lignes « Defaults » de sudoers
    "lignes": {"presente", "vide"},          # une ligne (hors commentaire) ?
}


@dataclass
class Lecture:
    """Resultat d'une preuve : statut, ce que le code a lu, pourquoi."""
    statut: STATUT
    constate: str
    motif: str = ""


@dataclass
class Verdict:
    fiche: str
    titre: str
    controle: str
    statut: STATUT
    constate: str
    attendu: str
    gravite: str = ""
    risque: str = ""
    action: str = ""
    commande: str = ""
    motif: str = ""
    a_observer: list[str] = field(default_factory=list)  # preuves restantes
    playbook: str | None = None        # correction disponible (etape 2.6)
    parametres: dict = field(default_factory=dict)

    @property
    def cle(self) -> str:
        return f"{self.fiche}#{self.controle}"


# --------------------------------------------------------------------------- #
# Outils de lecture
# --------------------------------------------------------------------------- #
def _lignes(sortie: str) -> list[str]:
    return [l.rstrip() for l in (sortie or "").splitlines() if l.strip()]


def _sans_prefixe_fichier(ligne: str) -> str:
    """grep -R prefixe chaque ligne par « chemin: »."""
    m = re.match(r"^/[^:\s]*:(.*)$", ligne)
    return m.group(1) if m else ligne


def _liste(attendu) -> list[str]:
    if attendu is None:
        return []
    if isinstance(attendu, (list, tuple, set)):
        return [str(a) for a in attendu]
    return [str(attendu)]


def _meme_valeur(lu: str, attendu: str) -> bool:
    a, b = " ".join(str(lu).split()), " ".join(str(attendu).split())
    if a.lower() == b.lower():
        return True
    try:
        return int(a) == int(b)
    except ValueError:
        return False


def _entier(texte) -> int | None:
    try:
        return int(str(texte).strip())
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Lecteurs : (sortie, spec) -> Lecture
# --------------------------------------------------------------------------- #
def _lire_valeur(sortie, spec) -> Lecture:
    lignes = _lignes(sortie)
    if not lignes:
        return Lecture(STATUT.INDETERMINE, "aucune sortie",
                       "parametre inconnu de ce noyau, ou lecture impossible")
    brut = lignes[0]
    if " = " in brut:                     # « sysctl cle » sans -n
        brut = brut.split(" = ", 1)[1]
    attendu = _liste(spec.get("attendu"))[0]
    if _meme_valeur(brut, attendu):
        return Lecture(STATUT.CONFORME, brut.strip())
    return Lecture(STATUT.ECART, brut.strip())


def _conforme_valeur(valeur, spec) -> bool:
    """Comparaison d'une valeur lue selon le comparateur de la spec."""
    if str(valeur) in _liste(spec.get("accepte")):
        return True
    comparateur = spec.get("comparateur", "toutes_egales")
    attendus = spec.get("attendu")
    if comparateur in {"toutes_egales", "egal"}:
        # « syslog|single|halt » : valeurs admises par le referentiel
        return any(_meme_valeur(valeur, a)
                   for a in str(_liste(attendus)[0]).split("|"))
    if comparateur == "droits_au_plus":
        try:
            return int(str(valeur), 8) & ~int(str(_liste(attendus)[0]), 8) == 0
        except ValueError:
            return False
    if comparateur == "umask":
        # conforme si au moins les memes bits sont retires (027 couvre 022)
        try:
            lu, voulu = int(str(valeur), 8), int(str(_liste(attendus)[0]), 8)
        except ValueError:
            return False
        return lu & voulu == voulu
    n = _entier(valeur)
    if n is None:
        return False
    if comparateur == "entre":
        mini, maxi = (list(attendus) + [None, None])[:2]
        return ((mini is None or n >= int(mini))
                and (maxi is None or n <= int(maxi)))
    borne = int(_liste(attendus)[0])
    return n <= borne if comparateur == "au_plus" else n >= borne


def _texte_attendu(spec) -> str:
    c, a = spec.get("comparateur"), spec.get("attendu")
    if c == "entre":
        mini, maxi = (list(a) + [None, None])[:2]
        return (f"entre {mini} et {maxi}" if mini is not None and maxi is not None
                else f"au moins {mini}" if mini is not None else f"au plus {maxi}")
    return {"au_plus": "au plus ", "au_moins": "au moins ",
            "umask": "umask au moins aussi strict que "}.get(c, "") + str(
        _liste(a)[0] if a is not None else "")


def _lire_affectations(sortie, spec) -> Lecture:
    cle = str(spec.get("champ") or "")
    marque = _marqueur(_lignes(sortie))
    if marque:
        return marque
    separateur = r"\s+" if spec.get("sep") == "espace" else r"\s*=\s*"
    valeurs = []
    for ligne in _lignes(sortie):
        contenu = _sans_prefixe_fichier(ligne).strip()
        if contenu.startswith(("#", ";")):
            continue
        contenu = re.sub(r"^(export|readonly|declare\s+-\w+)\s+", "", contenu)
        m = re.match(rf"^{re.escape(cle)}{separateur}(.*?)\s*(#.*)?$", contenu)
        if m:
            valeur = m.group(1).strip().strip('"').strip("'")
            valeur = re.sub(r"^u?int\d+\s+", "", valeur)   # dconf : uint32 900
            valeurs.append((ligne, valeur))
    if valeurs and spec.get("precedence") == "sysctl":
        valeurs, ecrasees = _sysctl_effective(valeurs)
    else:
        ecrasees = []
    if not valeurs:
        if spec.get("defaut") is not None:
            defaut = str(spec["defaut"])
            statut = (STATUT.CONFORME if _conforme_valeur(defaut, spec)
                      else STATUT.ECART)
            return Lecture(statut, f"{cle} non defini (defaut : {defaut})",
                           f"attendu {_texte_attendu(spec)}")
        return Lecture(STATUT.ECART, "aucune valeur persistante",
                       f"{cle} n'est fixe dans aucun fichier : la valeur ne "
                       f"survit pas au redemarrage")
    fausses = [l for l, v in valeurs if not _conforme_valeur(v, spec)]
    if fausses:
        return Lecture(STATUT.ECART, "; ".join(fausses[:3]),
                       f"attendu {_texte_attendu(spec)}")
    return Lecture(STATUT.CONFORME, "; ".join(l for l, _ in valeurs[:3])
                   + (f" (l'emporte sur : {'; '.join(ecrasees[:2])})"
                      if ecrasees else ""))


# Ordre de systemd-sysctl / sysctl --system : fichiers tries par NOM, a nom
# egal le repertoire le plus prioritaire masque les autres ; /etc/sysctl.conf
# (lien 99-sysctl.conf sur Debian/Ubuntu) passe en dernier. La derniere
# affectation l'emporte.
_SYSCTL_DOSSIERS = ("/etc/sysctl.d/", "/run/sysctl.d/", "/usr/local/lib/sysctl.d/",
                    "/usr/lib/sysctl.d/", "/lib/sysctl.d/")


def _sysctl_effective(valeurs):
    """[(ligne, valeur)] -> ([la valeur appliquee au demarrage], [ecrasees]).
    Releve a la relecture du 19/09/2026 : exiger que TOUTES les lignes
    soient justes signalait un ecart perpetuel quand un fichier du systeme
    (/usr/lib/sysctl.d/50-default.conf...) garde une autre valeur, meme
    apres une correction effective -> retour arriere a tort."""
    retenus = {}                 # nom de fichier -> (priorite, [(ligne, v)])
    for ligne, valeur in valeurs:
        chemin = ligne.split(":", 1)[0] if ":" in ligne else ""
        if chemin == "/etc/sysctl.conf":
            nom, prio = "￿", 0              # toujours en dernier
        else:
            prio = next((i for i, d in enumerate(_SYSCTL_DOSSIERS)
                         if chemin.startswith(d)), len(_SYSCTL_DOSSIERS))
            nom = chemin.rsplit("/", 1)[-1]
        if nom == "99-sysctl.conf" and prio == 0:
            nom = "￿"                        # lien vers /etc/sysctl.conf
        actuel = retenus.get(nom)
        if actuel is None or prio < actuel[0]:
            retenus[nom] = (prio, [(ligne, valeur)])
        elif prio == actuel[0]:
            actuel[1].append((ligne, valeur))
    ordre = [lv for nom in sorted(retenus) for lv in retenus[nom][1]]
    if not ordre:
        return [], []
    return [ordre[-1]], [l for l, v in ordre[:-1] if v != ordre[-1][1]]


_COLONNES_STAT = {"droits": 0, "proprietaire": 1, "groupe": 2}


def _lire_stat(sortie, spec) -> Lecture:
    col = _COLONNES_STAT[spec.get("champ", "droits")]
    comparateur = spec.get("comparateur")
    attendus = _liste(spec.get("attendu"))
    lus, ecarts = [], []
    for ligne in _lignes(sortie):
        parties = ligne.split(None, 3)
        if len(parties) < 4 or not re.fullmatch(r"[0-7]{1,4}", parties[0]):
            continue                              # bruit (message d'erreur)
        valeur, chemin = parties[col], parties[3]
        lus.append(f"{chemin} {valeur}")
        if comparateur == "droits_au_plus":
            permis = int(attendus[0], 8)
            if int(valeur, 8) & ~permis:
                ecarts.append(f"{chemin} en {valeur} (au plus {attendus[0]})")
        elif valeur not in attendus:
            ecarts.append(f"{chemin} : {valeur} (attendu "
                          f"{' ou '.join(attendus)})")
    if not lus:
        return Lecture(STATUT.INDETERMINE, "aucune ligne",
                       "fichier absent, ou illisible sans les droits root")
    if ecarts:
        return Lecture(STATUT.ECART, "; ".join(ecarts[:5])
                       + (f" (+{len(ecarts) - 5})" if len(ecarts) > 5 else ""))
    return Lecture(STATUT.CONFORME, f"{len(lus)} fichier(s) conforme(s)"
                   if len(lus) > 1 else lus[0])


def _lire_dpkg(sortie, spec) -> Lecture:
    noms = set(_liste(spec.get("attendu")))
    installes = set()
    for ligne in _lignes(sortie):
        parties = ligne.split()
        if parties and "ok installed" in ligne:
            installes.add(parties[0].split(":")[0])   # paquet:amd64
    trouves = sorted(installes & noms) if noms else sorted(installes)
    if spec.get("comparateur") == "installe":
        if trouves:
            return Lecture(STATUT.CONFORME, f"{', '.join(trouves)} installe")
        return Lecture(STATUT.ECART, f"{' / '.join(sorted(noms))} absent")
    if trouves:
        return Lecture(STATUT.ECART, f"{', '.join(trouves)} installe")
    return Lecture(STATUT.CONFORME, f"{' / '.join(sorted(noms))} absent")


_DEMARRAGE = {"enabled", "enabled-runtime", "disabled", "masked",
              "masked-runtime", "static", "indirect", "alias", "generated",
              "transient", "linked", "linked-runtime"}
_EXECUTION = {"active", "inactive", "failed", "activating", "deactivating",
              "reloading", "unknown"}


def _lire_systemctl(sortie, spec) -> Lecture:
    demarrage = execution = None
    for ligne in _lignes(sortie):
        mot = ligne.strip().lower()
        if mot in _DEMARRAGE and demarrage is None:
            demarrage = mot
        elif mot in _EXECUTION and execution is None:
            execution = mot
    if demarrage is None and execution is None:
        return Lecture(STATUT.INDETERMINE, "aucune sortie",
                       "systemctl indisponible (pas de systemd ?)")
    lu = f"{demarrage or 'service absent'} / {execution or '?'}"
    if spec.get("comparateur") == "actif":
        if (demarrage in {"enabled", "enabled-runtime", "static", "alias",
                          "generated", "indirect"}
                and execution == "active"):
            return Lecture(STATUT.CONFORME, lu)
        return Lecture(STATUT.ECART, lu)
    if (demarrage in {"enabled", "enabled-runtime", "linked", "linked-runtime"}
            or execution in {"active", "activating", "reloading"}):
        return Lecture(STATUT.ECART, lu)
    return Lecture(STATUT.CONFORME, lu)


def _lire_modprobe(sortie, spec) -> Lecture:
    mod = str(spec.get("champ") or "")
    # modprobe confond « - » et « _ » dans les noms de modules.
    motif_mod = "[-_]".join(re.escape(p) for p in re.split(r"[-_]", mod))
    install = blacklist = False
    for ligne in _lignes(sortie):
        contenu = _sans_prefixe_fichier(ligne).strip()
        if contenu.startswith("#"):
            continue
        if re.match(rf"^install\s+{motif_mod}\s+/(usr/)?bin/(false|true)\b",
                    contenu):
            install = True
        if re.match(rf"^blacklist\s+{motif_mod}\s*$", contenu):
            blacklist = True
    if install and blacklist:
        return Lecture(STATUT.CONFORME, f"install {mod} /bin/false + blacklist")
    manque = [x for x, ok in (("install /bin/false", install),
                              ("blacklist", blacklist)) if not ok]
    return Lecture(STATUT.ECART, f"manque : {', '.join(manque)}")


def _lire_aucune_ligne(sortie, spec) -> Lecture:
    lignes = _lignes(sortie)
    if lignes:
        return Lecture(STATUT.ECART, lignes[0].strip()[:120])
    return Lecture(STATUT.CONFORME, "aucune ligne")


def _lire_findmnt(sortie, spec) -> Lecture:
    option = str(spec.get("attendu"))
    lignes = _lignes(sortie)
    if spec.get("comparateur") == "monte":
        if lignes:
            return Lecture(STATUT.CONFORME, "partition separee : "
                           + " ".join(lignes[0].split()[:3]))
        return Lecture(STATUT.ECART, "pas de partition separee")
    if not lignes:
        return Lecture(STATUT.INDETERMINE, "pas de montage separe",
                       "le point de montage n'est pas une partition separee : "
                       "voir la regle de partition dediee")
    options = lignes[0].split()[-1].split(",")
    if option in options:
        return Lecture(STATUT.CONFORME, f"{option} actif")
    return Lecture(STATUT.ECART, f"options actives : {','.join(options)}")


def _lire_fstab(sortie, spec) -> Lecture:
    option = str(spec.get("attendu"))
    for ligne in _lignes(sortie):
        champs = ligne.split()
        if ligne.lstrip().startswith("#") or len(champs) < 4:
            continue
        if option in champs[3].split(","):
            return Lecture(STATUT.CONFORME, f"{option} dans /etc/fstab")
        return Lecture(STATUT.ECART, f"/etc/fstab : {champs[3]}")
    return Lecture(STATUT.INDETERMINE, "aucune ligne dans /etc/fstab",
                   "montage non declare dans /etc/fstab (systemd .mount ?)")


def _lire_kconfig(sortie, spec) -> Lecture:
    config = str(spec.get("champ"))
    noms = _liste(spec.get("noms")) or [config]   # anciens et nouveaux noms
    attendu = _liste(spec.get("attendu"))[0]
    archis = _liste(spec.get("architectures"))
    archi = None
    for ligne in _lignes(sortie):
        l = ligne.strip()
        m = re.match(r"# Linux/(\S+) ", l)
        if m:
            archi = m.group(1)
            continue
        for nom in noms:
            if l == f"# {nom} is not set":
                lu = "n"
            elif l.startswith(f"{nom}="):
                lu = l.split("=", 1)[1].strip('"')
            else:
                continue
            statut = STATUT.CONFORME if lu == attendu else STATUT.ECART
            return Lecture(statut, f"{nom}={lu}")
    if archi is None:
        return Lecture(STATUT.INDETERMINE, "configuration illisible",
                       "/boot/config du noyau absent ou illisible")
    if archis and archi not in archis:
        return Lecture(STATUT.INDETERMINE, "sans objet",
                       f"option propre a {', '.join(archis)} ; noyau {archi}")
    if attendu == "n":
        # Option qui n'existe pas dans ce noyau : elle ne peut pas y etre
        # compilee (ex. CONFIG_DEVKMEM, retiree en 5.13).
        return Lecture(STATUT.CONFORME, f"{config} inexistante (noyau {archi})")
    return Lecture(STATUT.INDETERMINE, "option inconnue de ce noyau",
                   f"{config} absente du noyau {archi} (renommee ou retiree ?)")


def _comparer_arguments(jetons: list[str], spec) -> Lecture:
    arg = str(spec.get("champ"))
    attendu = spec.get("attendu")
    trouves = [j for j in jetons if j == arg or j.startswith(arg + "=")]
    if spec.get("comparateur") == "absent":
        if trouves:
            return Lecture(STATUT.ECART, trouves[-1])
        return Lecture(STATUT.CONFORME, f"{arg} absent")
    if not trouves:
        return Lecture(STATUT.ECART, f"{arg} absent")
    dernier = trouves[-1]                 # le dernier l'emporte
    if attendu in (None, ""):
        return Lecture(STATUT.CONFORME, dernier)
    valeur = dernier.split("=", 1)[1] if "=" in dernier else ""
    if spec.get("comparateur") == "au_moins":
        lu, mini = _entier(valeur), _entier(attendu)
        ok = lu is not None and mini is not None and lu >= mini
    else:
        ok = valeur == str(attendu)
    return Lecture(STATUT.CONFORME if ok else STATUT.ECART, dernier)


def _lire_cmdline(sortie, spec) -> Lecture:
    lignes = _lignes(sortie)
    if not lignes:
        return Lecture(STATUT.INDETERMINE, "aucune sortie",
                       "/proc/cmdline illisible")
    return _comparer_arguments(lignes[0].split(), spec)


def _lire_grub(sortie, spec) -> Lecture:
    jetons = []
    vues = False
    for ligne in _lignes(sortie):
        m = re.match(r'^\s*GRUB_CMDLINE_LINUX(?:_DEFAULT)?=(["\']?)(.*)\1\s*$',
                     _sans_prefixe_fichier(ligne))
        if m:
            vues = True
            jetons += m.group(2).split()
    if not vues:
        return Lecture(STATUT.INDETERMINE, "aucune ligne GRUB_CMDLINE_LINUX",
                       "/etc/default/grub absent (autre chargeur ?)")
    return _comparer_arguments(jetons, spec)


def _lire_sshd_t(sortie, spec) -> Lecture:
    cle = str(spec.get("champ") or "").lower()
    valeur = None
    for ligne in _lignes(sortie):
        parties = ligne.strip().split(None, 1)
        if parties and parties[0].lower() == cle:
            valeur = parties[1].strip() if len(parties) > 1 else ""
            break                             # sshd -T : une ligne par cle
    if valeur is None:
        return Lecture(STATUT.INDETERMINE, "aucune ligne",
                       "sshd -T exige les droits root (sudo), ou directive "
                       "inconnue de cette version d'OpenSSH")
    lu = f"{cle} {valeur}"
    comparateur = spec.get("comparateur", "egal")
    attendus = _liste(spec.get("attendu"))
    if comparateur == "egal":
        ok = _meme_valeur(valeur, attendus[0])
    elif comparateur == "dans":
        ok = any(_meme_valeur(valeur, a) for a in attendus)
    elif comparateur == "max":
        n, maxi = _entier(valeur), _entier(attendus[0])
        ok = n is not None and maxi is not None and 1 <= n <= maxi
    elif comparateur == "maxstartups":
        lus = (valeur.split(":") + [None, None])[:3]
        att = (attendus[0].split(":") + [None, None])[:3]
        try:
            ok = (int(lus[0]) <= int(att[0]) and int(lus[1]) >= int(att[1])
                  and int(lus[2]) <= int(att[2]))
        except (TypeError, ValueError):
            ok = False
    else:                                      # fichier de banniere
        ok = valeur.lower() != "none" and valeur.startswith("/")
    return Lecture(STATUT.CONFORME if ok else STATUT.ECART, lu)


_OPERATEUR_F = re.compile(r"^([A-Za-z_]+)(<=|>=|!=|=|<|>|&=|&)(.*)$")


def _regles_audit(sortie) -> tuple[list[dict], bool]:
    """Regles d'audit (format auditctl -l et fichiers rules.d). Rend
    (regles, sortie_non_vide)."""
    regles = []
    lignes = _lignes(sortie)
    for ligne in lignes:
        contenu = _sans_prefixe_fichier(ligne).strip()
        if not contenu.startswith("-"):
            continue                              # « No rules », bruit
        jetons = contenu.split()
        r = {"watch": None, "perms": "", "action": "", "syscalls": set(),
             "F": []}
        i = 0
        while i < len(jetons):
            t = jetons[i]
            v = jetons[i + 1] if i + 1 < len(jetons) else ""
            if t == "-w":
                r["watch"] = v
            elif t == "-p":
                r["perms"] = v
            elif t in {"-a", "-A"}:
                r["action"] = v
            elif t == "-S":
                r["syscalls"].update(v.split(","))
            elif t in {"-F", "-C"}:              # -C euid!=uid : comparaison
                m = _OPERATEUR_F.match(v)
                if m:
                    r["F"].append((m.group(1), m.group(2), m.group(3)))
            else:
                i += 1
                continue
            i += 2
        regles.append(r)
    return regles, bool(lignes)


def _champ_f(regle, cle):
    return [v for k, op, v in regle["F"] if k == cle and op == "="]


def _meme_chemin(a, b) -> bool:
    return (a or "").rstrip("/") == (b or "").rstrip("/")


def _lire_audit(sortie, spec) -> Lecture:
    regles, non_vide = _regles_audit(sortie)
    if not regles:
        if non_vide:
            return Lecture(STATUT.ECART, "aucune regle d'audit chargee")
        return Lecture(STATUT.INDETERMINE, "aucune sortie",
                       "auditctl -l et /etc/audit/rules.d exigent les droits "
                       "root (sudo), ou auditd n'est pas installe")
    comparateur, champ = spec.get("comparateur"), str(spec.get("champ"))
    if comparateur == "surveille":
        voulus = set(str(spec.get("attendu") or "wa"))
        for r in regles:
            cible = (_meme_chemin(r["watch"], champ)
                     or any(_meme_chemin(v, champ)
                            for v in _champ_f(r, "path") + _champ_f(r, "dir")))
            perms = set(r["perms"] or "".join(_champ_f(r, "perm")))
            if cible and voulus <= perms:
                return Lecture(STATUT.CONFORME, f"{champ} surveille "
                               f"(-p {''.join(sorted(perms))})")
        return Lecture(STATUT.ECART, f"aucune surveillance de {champ} "
                       f"(-w {champ} -p {''.join(sorted(voulus))})")
    if comparateur == "execution":
        for r in regles:
            perms = set(r["perms"] or "".join(_champ_f(r, "perm")))
            chemins = [r["watch"]] + _champ_f(r, "path")
            if any(_meme_chemin(c, champ) for c in chemins) and "x" in perms:
                return Lecture(STATUT.CONFORME, f"execution de {champ} auditee")
        return Lecture(STATUT.ECART, f"execution de {champ} non auditee")
    # appels systeme : chaque groupe d'options exige une regle b32 ET b64
    manques = []
    for groupe in spec.get("options") or [[]]:
        archs = set()
        trouve = False
        for r in regles:
            if r["action"] not in {"always,exit", "exit,always"}:
                continue
            if champ not in r["syscalls"]:
                continue
            jetons = {f"{k}{op}{v}" for k, op, v in r["F"]}
            if not set(groupe) <= jetons:
                continue
            trouve = True
            archs.update(_champ_f(r, "arch"))
        libelle = f"{champ}" + (f" ({', '.join(groupe)})" if groupe else "")
        if not trouve:
            manques.append(f"aucune regle pour {libelle}")
        elif archs and not {"b32", "b64"} <= archs:
            manque = sorted({"b32", "b64"} - archs)[0]
            manques.append(f"regle arch={manque} manquante pour {libelle}")
    if manques:
        return Lecture(STATUT.ECART, "; ".join(manques))
    return Lecture(STATUT.CONFORME, f"appel {champ} audite")


def _lire_pam(sortie, spec) -> Lecture:
    module = str(spec.get("champ"))
    exigences = spec.get("attendu") or []
    lignes_module = []
    for ligne in _lignes(sortie):
        contenu = _sans_prefixe_fichier(ligne).strip()
        if contenu.startswith("#"):
            continue
        contenu = re.sub(r"\[[^\]]*\]", "ctrl", contenu)   # [success=1 ...]
        jetons = contenu.split()
        pos = next((i for i, j in enumerate(jetons)
                    if j.rsplit("/", 1)[-1] == module), None)
        if pos is not None:
            lignes_module.append(jetons[pos + 1:])
    if not lignes_module:
        return Lecture(STATUT.ECART, f"{module} absent")
    raisons = []
    for args in lignes_module:
        valeurs = {}
        for a in args:
            k, _, v = a.partition("=")
            valeurs[k] = v if "=" in a else None
        manque = []
        for e in exigences:
            nom = e["nom"]
            if e.get("absent"):
                if nom in valeurs:
                    manque.append(f"{nom} present (interdit)")
                continue
            if nom not in valeurs:
                manque.append(f"{nom} absent")
                continue
            if e.get("valeur") is None:
                continue
            sous_spec = {"comparateur": e.get("operation", "egal"),
                         "attendu": e["valeur"]}
            if not _conforme_valeur(valeurs[nom], sous_spec):
                manque.append(f"{nom}={valeurs[nom]} (attendu "
                              f"{_texte_attendu(sous_spec)})")
        if not manque:
            return Lecture(STATUT.CONFORME, f"{module} " + " ".join(args)[:100])
        raisons.append("; ".join(manque))
    return Lecture(STATUT.ECART, f"{module} : {raisons[0]}")


def _lire_sudo_defaults(sortie, spec) -> Lecture:
    option = str(spec.get("champ"))
    attendu = spec.get("attendu")
    etat, valeur, vues = None, None, False
    for ligne in _lignes(sortie):
        contenu = _sans_prefixe_fichier(ligne).strip()
        m = re.match(r"^Defaults\s+(.*)$", contenu)   # global seulement
        if not m:
            continue
        vues = True
        for element in re.split(r",(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)",
                                m.group(1)):
            element = element.strip()
            nie = element.startswith("!")
            nom, _, v = element.lstrip("!").partition("=")
            nom = nom.strip().rstrip("+-")
            if nom != option:
                continue
            etat = not nie
            valeur = v.strip().strip('"') if v else None
    if not vues:
        return Lecture(STATUT.INDETERMINE, "aucune ligne Defaults",
                       "/etc/sudoers est lisible par root seulement (sudo)")
    if spec.get("comparateur") == "au_plus":
        lu = valeur if etat else spec.get("defaut")
        n, maxi = _entier(lu if lu is not None else ""), _entier(attendu)
        if n is None:
            return Lecture(STATUT.ECART, f"Defaults {option} absent")
        ok = maxi is not None and 0 <= n <= maxi
        return Lecture(STATUT.CONFORME if ok else STATUT.ECART,
                       f"{option}={lu}" + ("" if etat else " (defaut)"))
    if not etat:
        return Lecture(STATUT.ECART, f"Defaults {option} absent"
                       if etat is None else f"Defaults !{option}")
    if attendu not in (None, "") and not _meme_valeur(valeur or "", attendu):
        return Lecture(STATUT.ECART, f"Defaults {option}={valeur}")
    return Lecture(STATUT.CONFORME, f"Defaults {option}"
                   + (f"={valeur}" if valeur else ""))


def _lire_lignes(sortie, spec) -> Lecture:
    utiles = [l for l in _lignes(sortie)
              if not _sans_prefixe_fichier(l).strip().startswith("#")]
    marque = _marqueur(utiles)
    if marque:
        return marque
    presente = spec.get("comparateur") == "presente"
    if utiles:
        extrait = "; ".join(l.strip() for l in utiles[:3])[:160]
        if len(utiles) > 3:
            extrait += f" (+{len(utiles) - 3})"
        return Lecture(STATUT.CONFORME if presente else STATUT.ECART, extrait)
    return Lecture(STATUT.ECART if presente else STATUT.CONFORME,
                   "aucune ligne")


_LECTEURS = {
    "valeur": _lire_valeur, "affectations": _lire_affectations,
    "stat": _lire_stat, "dpkg": _lire_dpkg, "systemctl": _lire_systemctl,
    "modprobe": _lire_modprobe, "aucune_ligne": _lire_aucune_ligne,
    "findmnt": _lire_findmnt, "fstab": _lire_fstab, "kconfig": _lire_kconfig,
    "cmdline": _lire_cmdline, "grub": _lire_grub, "sshd_t": _lire_sshd_t,
    "audit": _lire_audit, "pam": _lire_pam,
    "sudo_defaults": _lire_sudo_defaults, "lignes": _lire_lignes,
}
assert set(_LECTEURS) == set(LECTEURS)


def lire(sortie: str, spec: dict) -> Lecture:
    """Applique une entree d'evaluation a une sortie de commande."""
    # Marqueurs (composant absent, fichier illisible) : valables pour TOUS
    # les lecteurs (gardes de plateforme ajoutees a la relecture 19/09/2026).
    marque = _marqueur(_lignes(sortie))
    if marque:
        return marque
    try:
        return _LECTEURS[spec["lecteur"]](sortie, spec)
    except Exception as exc:  # noqa: BLE001 -- jamais de plantage d'audit
        return Lecture(STATUT.INDETERMINE, "lecture impossible",
                       f"sortie inattendue ({type(exc).__name__})")


def valider_spec(spec, nb_observer: int) -> list[str]:
    """Erreurs d'une entree d'evaluation (utilise par schema.valider)."""
    if not isinstance(spec, dict):
        return ["entree d'evaluation : dictionnaire attendu"]
    erreurs = []
    lecteur = spec.get("lecteur")
    if lecteur not in LECTEURS:
        return [f"lecteur « {lecteur} » inconnu"]
    comparateur = spec.get("comparateur")
    if comparateur not in LECTEURS[lecteur]:
        erreurs.append(f"comparateur « {comparateur} » invalide pour "
                       f"{lecteur} ({sorted(LECTEURS[lecteur])})")
    i = spec.get("commande")
    if not isinstance(i, int) or not 0 <= i < nb_observer:
        erreurs.append(f"commande #{i} : hors de « observer »")
    inconnus = set(spec) - {"commande", "lecteur", "comparateur", "champ",
                            "attendu", "defaut", "accepte", "options",
                            "sep", "noms", "architectures", "precedence"}
    if inconnus:
        erreurs.append(f"champs inconnus {sorted(inconnus)}")
    if lecteur in {"affectations", "stat", "modprobe", "kconfig", "cmdline",
                   "grub", "sshd_t", "audit", "pam", "sudo_defaults"} \
            and not spec.get("champ"):
        erreurs.append(f"« champ » requis pour {lecteur}")
    if lecteur == "stat" and spec.get("champ") not in _COLONNES_STAT:
        erreurs.append(f"champ stat « {spec.get('champ')} » inconnu")
    if (lecteur not in {"aucune_ligne", "cmdline", "grub", "systemctl",
                        "modprobe", "audit", "sudo_defaults", "lignes",
                        "pam"}          # pam sans exigence = module present
            and comparateur != "monte"
            and spec.get("attendu") in (None, "", [])):
        erreurs.append("« attendu » manquant")
    return erreurs


# --------------------------------------------------------------------------- #
# De la commande executee aux verdicts
# --------------------------------------------------------------------------- #
def normaliser_commande(cmd: str) -> str:
    """Forme canonique pour reconnaitre une commande de fiche malgre les
    variations d'un modele : sudo, redirection d'erreurs, espaces."""
    c = " ".join((cmd or "").split())
    c = re.sub(r"(^|[|;&]\s*)sudo\s+(-\S+\s+)*", r"\1", c)
    c = re.sub(r"\s*2>\s*/dev/null", "", c)
    c = re.sub(r"^sysctl\s+(?!-)(\S+)$", r"sysctl -n \1", c)
    return c.strip().rstrip(";").strip()


@lru_cache(maxsize=1)
def _index_commandes() -> dict[str, list[tuple]]:
    """commande canonique -> [(fiche, index dans observer)], pour les seules
    fiches qui portent une evaluation sur cette commande."""
    from brain import bibliotheque
    index: dict[str, list[tuple]] = {}
    for fiche in bibliotheque.toutes():
        if fiche.etat == "obsolete":
            continue
        utiles = {e.get("commande") for c in fiche.controles
                  for e in (c.evaluation or [])}
        for i, obs in enumerate(fiche.observer):
            if i in utiles:
                index.setdefault(normaliser_commande(obs.commande), []) \
                    .append((fiche, i))
    return index


def fiches_evaluables() -> int:
    from brain import bibliotheque
    return sum(1 for f in bibliotheque.toutes()
               if any(c.evaluation for c in f.controles))


def evaluer_fiche(fiche, sorties: dict[int, str], commande: str = ""
                  ) -> list[Verdict]:
    """Verdicts des controles d'une fiche a partir des sorties disponibles
    ({index observer: stdout}). Un controle sans preuve observee est omis."""
    verdicts = []
    for c in fiche.controles:
        lectures, restantes = [], []
        for spec in c.evaluation or []:
            i = spec["commande"]
            if i in sorties:
                lectures.append(lire(sorties[i], spec))
            else:
                restantes.append(fiche.observer[i].commande)
        if not lectures:
            continue
        ecarts = [l for l in lectures if l.statut is STATUT.ECART]
        indets = [l for l in lectures if l.statut is STATUT.INDETERMINE]
        if ecarts:
            statut, retenue = STATUT.ECART, ecarts[0]
        elif indets:
            statut, retenue = STATUT.INDETERMINE, indets[0]
        else:
            statut, retenue = STATUT.CONFORME, lectures[0]
        verdicts.append(Verdict(
            fiche=fiche.id, titre=fiche.titre, controle=c.controle,
            statut=statut, constate=retenue.constate, attendu=c.bon,
            gravite=c.gravite, risque=c.risque, action=c.action,
            commande=commande, motif=retenue.motif,
            a_observer=restantes if statut is STATUT.CONFORME else [],
            playbook=c.playbook, parametres=dict(c.parametres or {})))
    return verdicts


def evaluer_commande(cmd: str, stdout: str, contexte=None,
                     niveau: tuple | None = NIVEAU_DEFAUT) -> list[Verdict]:
    """Toutes les fiches evaluables par cette commande (une meme commande,
    ex. « cat /proc/cmdline », peut en juger plusieurs). Sont ignorees les
    fiches non applicables au systeme audite et celles au-dessus du niveau
    de conformite du client (niveau=None : tout mesurer)."""
    from brain.contexte import applicable

    from .taxonomie import dans_le_niveau
    verdicts = []
    for fiche, i in _index_commandes().get(normaliser_commande(cmd), []):
        if contexte is not None and not applicable(fiche, contexte)[0]:
            continue
        if niveau is not None and not dans_le_niveau(fiche.taxonomie, *niveau):
            continue
        verdicts += evaluer_fiche(fiche, {i: stdout}, commande=cmd)
    return verdicts


def message_modele(verdicts: list[Verdict]) -> str:
    """Ce que le modele recoit : les verdicts sont DONNES, il n'explique que
    les ecarts. Les conformes sont resumes en une ligne."""
    ecarts = sorted((v for v in verdicts if v.statut is STATUT.ECART),
                    key=lambda v: _RANG_GRAVITE.get(v.gravite, 9))
    conformes = [v for v in verdicts if v.statut is STATUT.CONFORME]
    indets = [v for v in verdicts if v.statut is STATUT.INDETERMINE]
    lignes = ["[evaluation du code] Verdicts etablis par comparaison "
              "deterministe avec les fiches. Ne les rejuge pas."]
    for v in ecarts[:MAX_ECARTS_MODELE]:
        correction = (f" Correction disponible : playbook {v.playbook} "
                      f"(l'humain la lance avec /corriger)." if v.playbook
                      else " Pas de playbook : correction manuelle.")
        lignes.append(f"- ECART [{v.gravite}] {v.titre} : constate « "
                      f"{v.constate} », attendu « {v.attendu} ». "
                      f"Action : {v.action}{correction}")
    if len(ecarts) > MAX_ECARTS_MODELE:
        reste = ecarts[MAX_ECARTS_MODELE:]
        lignes.append(f"- {len(reste)} autre(s) ECART(s) moins graves, "
                      f"memorises et visibles par l'humain (/ecarts) : "
                      + ", ".join(v.titre for v in reste[:8])
                      + (" ..." if len(reste) > 8 else ""))
    if conformes:
        lignes.append(f"- CONFORME ({len(conformes)}) : "
                      + "; ".join(v.titre for v in conformes[:6])
                      + (" ..." if len(conformes) > 6 else ""))
    for v in indets:
        lignes.append(f"- INDETERMINE {v.titre} : {v.motif}")
    if ecarts:
        lignes.append("Explique chaque ECART au format Constat / Risque / "
                      "Gravite / Action, en gardant la gravite donnee. Ne "
                      "commente pas les conformes.")
    elif indets:
        lignes.append("Rien n'est conclu : indique a l'humain ce qui manque "
                      "(ex. relancer avec sudo).")
    else:
        lignes.append("Aucun ecart sur ce point : dis-le en une phrase.")
    return "\n".join(lignes)


def rapport() -> str:
    """Couverture : quelles fiches le code sait juger, avec quels lecteurs."""
    from collections import Counter

    from brain import bibliotheque
    fiches = bibliotheque.toutes()
    lecteurs, sans = Counter(), []
    for f in fiches:
        specs = [e for c in f.controles for e in (c.evaluation or [])]
        if not specs:
            sans.append(f.id)
        lecteurs.update(e["lecteur"] for e in specs)
    lignes = [f"Fiches jugeables par le code : {len(fiches) - len(sans)} / "
              f"{len(fiches)}",
              f"Commandes distinctes reconnues : {len(_index_commandes())}",
              "Preuves par lecteur :"]
    lignes += [f"  {n:4}  {l}" for l, n in lecteurs.most_common()]
    if sans:
        lignes.append("Sans evaluation (le modele lit seul) : " + ", ".join(sans))
    return "\n".join(lignes)


if __name__ == "__main__":
    print(rapport())
