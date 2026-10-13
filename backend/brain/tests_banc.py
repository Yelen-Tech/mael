"""Tests du banc d'essai Linux (point 4, partie F).

Tout passe par ExecuteurFactice : aucun Docker requis. La suite complete
existante doit rester verte.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from banc.executeurs import ExecuteurFactice, Resultat
from banc.fiches import executer_fiche
from banc.playbooks import _COMMANDE_SNAPSHOT, aller_retour
from brain import bibliotheque as bib
from brain.contexte import depuis_declaration
from brain.tools.base import OutilEchoue, OutilRefuse, image_figee

CTX = depuis_declaration("ubuntu:22.04")


def _fiche_sysctl():
    return next(f for f in bib.toutes() if f.id == "cac-sysctl-fs-protected-fifos")


# --------------------------------------------------------------------------- #
# Execution des fiches
# --------------------------------------------------------------------------- #
def test_fiche_conforme_ecart_illisible():
    fiche = _fiche_sysctl()
    obs0, obs1 = (o.commande for o in fiche.observer)

    conforme = ExecuteurFactice({
        obs0: (0, "2\n", ""),
        obs1: (0, "/etc/sysctl.d/99-mael.conf:fs.protected_fifos = 2\n", ""),
    })
    r = executer_fiche(conforme, fiche, CTX)
    assert r["defauts"] == []
    assert all(v["statut"] == "conforme" for v in r["verdicts"]), r["verdicts"]

    ecart = ExecuteurFactice({obs0: (0, "0\n", ""), obs1: (0, "", "")})
    r = executer_fiche(ecart, fiche, CTX)
    assert any(v["statut"] == "ecart" for v in r["verdicts"]), r["verdicts"]

    # illisible sans les droits root : le marqueur, jamais un faux ecart
    illisible = ExecuteurFactice({obs0: (0, "SENTINELLE:ILLISIBLE\n", ""),
                                  obs1: (0, "SENTINELLE:ILLISIBLE\n", "")})
    r = executer_fiche(illisible, fiche, CTX)
    assert all(v["statut"] == "indetermine" for v in r["verdicts"]), \
        r["verdicts"]

    # binaire absent : commande impossible, PAS un defaut de fiche, et
    # verdict indetermine -- jamais un faux ecart (Debian 12 sans ufw)
    absent = ExecuteurFactice()
    r = executer_fiche(absent, fiche, CTX)
    assert any("127" in d for d in r["impossibles"])
    assert r["defauts"] == []
    assert all(v["statut"] == "indetermine" for v in r["verdicts"]),         r["verdicts"]


def test_commande_non_lecture_jamais_executee():
    fiche = bib.Fiche(id="fabriquee", titre="t", domaine="systeme",
                      observer=[bib.CommandeObserv("rm -rf / --no-preserve-root")])
    ex = ExecuteurFactice()
    r = executer_fiche(ex, fiche, CTX)
    assert r["verdicts"] == []
    assert any("non LECTURE" in d for d in r["defauts"])
    assert ex.journal == []             # rien n'a ete execute


def test_balayage_du_disque_a_son_propre_delai():
    """« find / » ne doit pas tomber sur le delai commun du banc : sur une
    machine lente, le delai depasse etait lu comme un defaut de fiche."""
    from banc.fiches import DELAI_BALAYAGE, delai_pour
    assert delai_pour("find / -xdev -type d -perm -0002 -print") == DELAI_BALAYAGE
    assert delai_pour("stat -c %a /etc/passwd") is None

    fiche = bib.Fiche(id="fabriquee-find", titre="t", domaine="systeme",
                      observer=[bib.CommandeObserv(
                          "find / -xdev -type f -perm -4000 2>/dev/null")])
    ex = ExecuteurFactice()
    executer_fiche(ex, fiche, CTX)
    assert ex.delais == [DELAI_BALAYAGE]


def test_delai_depasse_n_est_pas_un_defaut_de_fiche():
    fiche = _fiche_sysctl()
    obs0, obs1 = (o.commande for o in fiche.observer)
    lent = ExecuteurFactice({obs0: (124, "", "delai depasse (120 s)"),
                             obs1: (124, "", "delai depasse (120 s)")})
    r = executer_fiche(lent, fiche, CTX)
    assert r["defauts"] == []
    assert any("delai depasse" in d for d in r["impossibles"])
    assert all(v["statut"] == "indetermine" for v in r["verdicts"]),         r["verdicts"]


# --------------------------------------------------------------------------- #
# Aller-retour des playbooks
# --------------------------------------------------------------------------- #
class FacticeEtat(ExecuteurFactice):
    """Factice a etat : les scripts font evoluer le snapshot, comme un vrai
    conteneur. simulation_casse / revenir_casse simulent des playbooks
    defectueux."""

    def __init__(self, simulation_casse=False, revenir_casse=False):
        super().__init__()
        self.etat = "avant"
        self.simulation_casse = simulation_casse
        self.revenir_casse = revenir_casse

    def executer(self, argv, racine=True):
        self.journal.append((list(argv), racine))
        if argv[:2] == ["bash", "-c"]:
            cmd = argv[2]
            if cmd == _COMMANDE_SNAPSHOT:
                return Resultat(0, f"snapshot:{self.etat}\n", "")
            if cmd == "sysctl -n fs.protected_fifos":
                return Resultat(0, "2\n" if self.etat == "applique" else "0\n",
                                "")
            if cmd.startswith("grep -Rs"):
                out = ("/etc/sysctl.d/99-mael.conf:fs.protected_fifos = 2\n"
                       if self.etat == "applique" else "")
                return Resultat(0, out, "")
            return Resultat(0, "", "")
        script = argv[1] if len(argv) > 1 else ""
        if "appliquer" in script:
            if "--simulation" in argv:
                if self.simulation_casse:
                    self.etat = "applique"
            else:
                self.etat = "applique"
        elif "revenir" in script and not self.revenir_casse:
            self.etat = "avant"
        return Resultat(0, "", "")


def test_aller_retour_complet_heureux():
    # vraie_machine : le factice joue une VM (noyau reel), sinon un
    # playbook sysctl est renvoye « a tester en VM » sans etre execute
    r = aller_retour(FacticeEtat(), "infra.sysctl", "ubuntu:22.04",
                     vraie_machine=True)
    assert r["ok"], r["ecarts"]
    etapes = [e["etape"] for e in r["etapes"]]
    assert etapes == ["detecter", "appliquer --simulation", "appliquer",
                      "verifier", "re-mesure", "revenir"]


def test_simulation_qui_modifie_est_detectee():
    r = aller_retour(FacticeEtat(simulation_casse=True),
                     "infra.sysctl", "ubuntu:22.04", vraie_machine=True)
    assert not r["ok"]
    assert any("--simulation a modifie" in e for e in r["ecarts"])


def test_retour_arriere_incomplet_est_detecte():
    r = aller_retour(FacticeEtat(revenir_casse=True),
                     "infra.sysctl", "ubuntu:22.04", vraie_machine=True)
    assert not r["ok"]
    assert any("etat d'origine non restaure" in e for e in r["ecarts"])


# --------------------------------------------------------------------------- #
# Images figees (partie E)
# --------------------------------------------------------------------------- #
def test_image_latest_refusee():
    try:
        image_figee("projectdiscovery/nuclei:latest")
        raise AssertionError("latest aurait du etre refuse")
    except OutilRefuse:
        pass


def test_image_hors_verrou_refusee():
    try:
        image_figee("inconnu/outil:1.0")
        raise AssertionError("une image hors verrou aurait du etre refusee")
    except OutilRefuse:
        pass


def test_image_figee_via_verrou():
    with tempfile.TemporaryDirectory() as d:
        lock = Path(d) / "images.lock"
        digest = "sha256:" + "ab" * 32
        lock.write_text(json.dumps({"repo/outil": f"repo/outil@{digest}"}),
                        encoding="utf-8")
        assert image_figee("repo/outil", lock) == f"repo/outil@{digest}"
        # A_RESOUDRE : epingle connue mais pas resolue -> echec, pas refus
        lock.write_text(json.dumps({"repo/autre": "repo/autre@sha256:A_RESOUDRE"}),
                        encoding="utf-8")
        try:
            image_figee("repo/autre", lock)
            raise AssertionError("A_RESOUDRE aurait du echouer")
        except OutilEchoue:
            pass


def test_images_embarquees_sont_dans_le_verrou():
    """nuclei et testssl ne portent plus :latest et ont une entree de verrou."""
    from brain.tools import inspection
    verrou = json.loads((Path(inspection.__file__).with_name("images.lock"))
                        .read_text(encoding="utf-8"))
    for classe in (inspection.ScanVuln, inspection.VerifTls):
        assert not classe.image.endswith(":latest")
        assert classe.image in verrou
        assert "@sha256:" in verrou[classe.image]


def test_commande_impossible_indeterminee():
    """Binaire introuvable (127) ou delai depasse (124) : la sortie vide
    n'est jamais jugee (c'etait un faux ecart : « aucune valeur »)."""
    from brain.bibliotheque import ecarts
    spec = dict(lecteur="affectations", comparateur="toutes_egales",
                champ="fs.protected_fifos", attendu="2", precedence="sysctl")
    for code in (124, 126, 127):
        r = ecarts.lire(ecarts.sortie_a_juger(code, ""), spec)
        assert r.statut is ecarts.STATUT.INDETERMINE, code
    # code 0 ou 1 (grep sans resultat) : la sortie est bien jugee
    assert ecarts.lire(ecarts.sortie_a_juger(1, ""), spec).statut \
        is ecarts.STATUT.ECART
