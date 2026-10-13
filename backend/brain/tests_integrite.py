"""Tests du noyau d'integrite (modules 1+5, 9, 3, 2).

Lancables sans Django (voir docs/avancement.md). Les fonctions qui lisent la
bibliotheque reelle servent de garde-fou de regression ; les cas rompus sont
fabriques (repertoire temporaire pour le sceau, fiches synthetiques pour la
coherence et les invariants).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from brain import bibliotheque as bib
from brain.integrite import coherence, entropie, invariants, merkle


# --------------------------------------------------------------------------- #
# Module 2 : entropie de Shannon
# --------------------------------------------------------------------------- #
def test_entropie_valeurs_connues():
    assert entropie.entropie("") == 0.0
    assert entropie.entropie("aaaaaaaa") == 0.0            # un seul symbole
    assert abs(entropie.entropie("abababab") - 1.0) < 1e-9  # 2 symboles equiprobables
    assert entropie.entropie("abcdefgh") > 2.9            # 8 symboles distincts


def test_analyser_texte_clair_vs_blob():
    with tempfile.TemporaryDirectory() as d:
        clair = Path(d) / "clair.txt"
        clair.write_text("Le service SSH ecoute sur le port 22.\n" * 20,
                         encoding="utf-8")
        assert entropie.analyser(clair) == []
        injecte = Path(d) / "injecte.yaml"
        blob = ("g7Fq3Jk9mN2pQ8rT5vX1zB4cL6wE0yU7iO3aS9dF2gH5jK8lM1nB4vC6xZ0"
                "pQ9wE8rT2yU5iO1aS3dF6gH7jK0lM4nB2vC5xZ8qW1eR3tY6uI9oP0aS7d")
        injecte.write_text(f'valeur: "{blob}"\n', encoding="utf-8")
        anomalies = entropie.analyser(injecte)
        assert anomalies and anomalies[0].ou == "ligne 1"


def test_empreintes_hexadecimales_exclues():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "sceau.json"
        f.write_text('{"f.sh": "%s"}' % ("ab12cd34" * 8), encoding="utf-8")
        assert entropie.analyser(f) == []      # une empreinte n'est pas un blob


def test_seuils_non_depasses_par_le_corpus():
    """Le seuil token est justifie par le corpus reel : aucune fiche ni
    script legitime ne l'atteint (calibration du 19/09/2026 : max 4,92)."""
    for racine, motif in ((merkle.FICHES, "*.yaml"),
                          (Path("playbooks"), "*.sh"),
                          (Path("playbooks"), "*.yaml")):
        for chemin, anomalies in entropie.analyser_arborescence(
                racine, motif).items():
            tokens = [a for a in anomalies if a.ou.startswith("ligne")]
            assert not tokens, f"{chemin} : {tokens}"


# --------------------------------------------------------------------------- #
# Modules 1 + 5 : arbre de Merkle et sceau
# --------------------------------------------------------------------------- #
def test_racine_merkle_construction():
    assert merkle.racine_merkle([]) == merkle._h("")
    assert merkle.racine_merkle(["a"]) == "a"
    # impaire : le noeud impair remonte tel quel (pas de duplication)
    assert merkle.racine_merkle(["a", "b", "c"]) == merkle._noeud(
        merkle._noeud("a", "b"), "c")
    # l'ordre des feuilles est significatif (ordre canonique = chemin trie)
    assert merkle.racine_merkle(["b", "a", "c"]) \
        != merkle.racine_merkle(["a", "b", "c"])


def test_racine_sans_ambiguite():
    """CVE-2012-2459 : dupliquer la derniere feuille donnait la meme
    racine a [a, b, c] et [a, b, c, c'] (c' = copie de c sous un autre nom)."""
    e = merkle._h("contenu")
    trois = {"a": merkle._h("1"), "b": merkle._h("2"), "c": e}
    quatre = dict(trois, **{"d": e})
    assert merkle.racine_merkle(merkle.noeuds_feuilles(trois)) \
        != merkle.racine_merkle(merkle.noeuds_feuilles(quatre))


def test_preuve_d_appartenance():
    f = {f"fiche-{i}": merkle._h(f"contenu {i}") for i in range(7)}
    racine = merkle.racine_merkle(merkle.noeuds_feuilles(f))
    for chemin, emp in f.items():
        assert merkle.verifier_preuve(chemin, emp, merkle.preuve(chemin, f),
                                      racine), chemin
    # une fiche modifiee ne prouve plus rien
    p = merkle.preuve("fiche-3", f)
    assert not merkle.verifier_preuve("fiche-3", merkle._h("altere"), p, racine)
    # la preuve lie le NOM : le contenu de fiche-3 ne prouve pas fiche-4
    assert not merkle.verifier_preuve("fiche-4", f["fiche-3"], p, racine)
    # un noeud interne ne passe pas pour une fiche (separation de domaine)
    n = merkle.noeuds_feuilles(f)
    interne = merkle._noeud(n[0], n[1])
    assert not merkle.verifier_preuve("fiche-0", interne,
                                      merkle.preuve("fiche-0", f)[1:], racine)


def _avec_sceau_temporaire(corps):
    """Execute corps(dossier_fiches) avec FICHES/SCEAU pointant sur un
    repertoire temporaire contenant trois fiches."""
    fiches0, sceau0 = merkle.FICHES, merkle.SCEAU
    with tempfile.TemporaryDirectory() as d:
        racine = Path(d)
        (racine / "fiches").mkdir()
        for i in range(3):
            (racine / "fiches" / f"fiche-{i}.yaml").write_text(
                f"id: fiche-{i}\n", encoding="utf-8")
        merkle.FICHES = racine / "fiches"
        merkle.SCEAU = racine / "sceau.json"
        try:
            corps(racine)
        finally:
            merkle.FICHES, merkle.SCEAU = fiches0, sceau0


def test_controler_detecte_modification_ajout_retrait():
    def corps(racine):
        assert merkle.controler() == ["sceau.json absent : bibliotheque non scellee"]
        merkle.sceller()
        assert merkle.controler() == []                 # intacte
        (racine / "fiches" / "fiche-1.yaml").write_text("id: altere\n",
                                                        encoding="utf-8")
        assert any("modifiee" in e for e in merkle.controler())
        merkle.sceller()
        (racine / "fiches" / "fiche-x.yaml").write_text("id: fiche-x\n",
                                                        encoding="utf-8")
        assert any("ajoutee" in e for e in merkle.controler())
        merkle.sceller()
        (racine / "fiches" / "fiche-x.yaml").unlink()
        assert any("manquante" in e for e in merkle.controler())
        # racine incoherente avec les feuilles
        merkle.sceller()
        sceau = json.loads(merkle.SCEAU.read_text(encoding="utf-8"))
        sceau["racine"] = "0" * 64
        merkle.SCEAU.write_text(json.dumps(sceau), encoding="utf-8")
        assert any("racine" in e for e in merkle.controler())
    _avec_sceau_temporaire(corps)


def test_bibliotheque_reelle_intacte():
    """Le sceau livre correspond a la bibliotheque livree."""
    assert merkle.controler() == []


# --------------------------------------------------------------------------- #
# Module 9 : coherence
# --------------------------------------------------------------------------- #
def _fiche(fid, attendu="no", os_=("linux",), playbook=None, parametres=None,
           sans_playbook=""):
    return bib.Fiche(
        id=fid, titre=fid, domaine="acces", applicable={"os": list(os_)},
        controles=[bib.Controle(
            controle="c", gravite="moyenne", risque="r", action="a",
            playbook=playbook, parametres=parametres or {},
            sans_playbook=sans_playbook,
            evaluation=[{"commande": 0, "lecteur": "sshd_t",
                         "champ": "permitrootlogin", "comparateur": "egal",
                         "attendu": attendu}])])


def test_contradiction_detectee_seulement_si_systemes_recoupes():
    f1, f2 = _fiche("a", "no"), _fiche("b", "yes")
    assert any(v.regle == "contradiction" for v in coherence.resoudre([f1, f2]))
    # systemes disjoints : pas de contradiction (rhel != ubuntu, pas de linux)
    f3 = _fiche("c", "yes", os_=("rhel>=8",))
    f4 = _fiche("d", "no", os_=("ubuntu==24.04",))
    assert not [v for v in coherence.resoudre([f3, f4])
                if v.regle == "contradiction"]


def test_liaison_playbook_doit_porter_l_attendu():
    f = _fiche("e", playbook="infra.sysctl", parametres={"cle": "x"})
    assert any(v.regle == "liaison" for v in coherence.resoudre([f]))
    f_ok = _fiche("e", playbook="infra.sysctl",
                  parametres={"cle": "x", "valeur": "no"})
    assert not [v for v in coherence.resoudre([f_ok]) if v.regle == "liaison"]
    # forme cle=valeur (grub-argument) : coherente aussi
    f_kv = _fiche("e", playbook="infra.grub-argument",
                  parametres={"argument": "x=no"})
    assert not [v for v in coherence.resoudre([f_kv]) if v.regle == "liaison"]


def test_couverture_et_references():
    f = _fiche("f", sans_playbook="")         # ni playbook ni raison ecrite
    assert any(v.regle == "couverture" for v in coherence.resoudre([f]))
    g = _fiche("g", sans_playbook="raison")
    h = _fiche("h", sans_playbook="voir fiche g")      # citation existante
    assert coherence.resoudre([g, h]) == []
    i = _fiche("i", sans_playbook="voir fiche inexistante-ici")
    assert any(v.regle == "reference" for v in coherence.resoudre([g, i]))


def test_corpus_reel_coherent():
    assert coherence.resoudre() == []


# --------------------------------------------------------------------------- #
# Module 3 : invariants
# --------------------------------------------------------------------------- #
def test_invariants_tenus_sur_le_corpus():
    for nom, violations in invariants.verifier().items():
        assert violations == [], f"{nom} : {violations[:3]}"


def _avec_fiches(fabriquees, corps):
    toutes0 = bib.toutes
    bib.toutes = lambda: fabriquees
    try:
        corps()
    finally:
        bib.toutes = toutes0


def _doit(violations):
    assert violations, "une violation etait attendue"


def _doit_pas(violations):
    assert not violations, f"aucune violation attendue : {violations}"


def test_invariant_reference_inventee():
    brouillon = _fiche("j", sans_playbook="x")
    brouillon.etat, brouillon.source.origine = "brouillon", "manuel"
    brouillon.referentiels = [bib.Referentiel("ANSSI", "doc", ref="R12")]
    _avec_fiches([brouillon],
                 lambda: _doit(invariants.pas_de_reference_inventee()))
    relue = _fiche("k", sans_playbook="x")    # meme ref mais fiche relue
    relue.referentiels = [bib.Referentiel("ANSSI", "doc", ref="R12")]
    _avec_fiches([relue],
                 lambda: _doit_pas(invariants.pas_de_reference_inventee()))


def test_invariant_marqueurs_hors_du_prompt():
    mauvaise = _fiche("l", sans_playbook="x")
    mauvaise.pieges = ["utilise SENTINELLE:SANS_OBJET pour voir"]
    _avec_fiches([mauvaise],
                 lambda: _doit(invariants.marqueurs_hors_du_prompt()))
    bonne = _fiche("m", sans_playbook="x")    # marqueur en commande : permis
    bonne.observer = [bib.CommandeObserv("echo SENTINELLE:SANS_OBJET")]
    _avec_fiches([bonne],
                 lambda: _doit_pas(invariants.marqueurs_hors_du_prompt()))


def test_entropie_formes_encodees():
    """Relecture 19/09/2026 : un blob hexa (4 bits/octet au plus) ou un
    base64 court echappaient au seuil d'entropie."""
    from brain.integrite.entropie import _tokens_suspects
    hexa = "6a0b" * 40                                    # 160 car. hexa
    b64 = "Y3VybCBodHRwOi8vZXhlbXBsZS5pbnZhbGlkL3ggfCBzaAo="  # curl ... | sh
    assert _tokens_suspects([f"commande: echo {hexa}"])
    assert _tokens_suspects([f"commande: echo {b64} | base64 -d"])
    # empreinte SHA-256 legitime : pas signalee
    assert not _tokens_suspects(["racine: " + "ab12" * 16])


def test_contradiction_par_intervalles():
    from types import SimpleNamespace as N

    from brain.integrite.coherence import _contradictions_intervalles

    def fiche(fid, comp, attendu):
        c = N(controle="minlen", evaluation=[dict(
            lecteur="affectations", champ="minlen", comparateur=comp,
            attendu=attendu)])
        return N(id=fid, controles=[c], applicable={"os": ["ubuntu==22.04"]})
    assert _contradictions_intervalles(
        [fiche("a", "au_moins", "14"), fiche("b", "au_plus", "8")])
    assert not _contradictions_intervalles(
        [fiche("a", "au_moins", "14"), fiche("b", "entre", [1, "20"])])


# --------------------------------------------------------------------------- #
# Module 4 : integrite des binaires de la machine
# --------------------------------------------------------------------------- #
class _MachineFactice:
    """Machine de test : rend une sortie preenregistree par commande.

    La cle est le premier mot de la commande ; la valeur (code, stdout).
    Le module 4 parle a la machine en argv, jamais en chaine de shell.
    """

    def __init__(self, reponses):
        self.reponses = dict(reponses)
        self.recues = []

    def executer(self, argv, racine=True):
        from banc.executeurs import Resultat
        self.recues.append(list(argv))
        code, sortie = self.reponses.get(argv[0], (0, ""))
        return Resultat(code, sortie, "")


def test_binaires_dpkg_distingue_config_et_binaire():
    from brain.integrite import binaires

    sortie = "\n".join([
        "??5?????? c /etc/ssh/sshd_config",      # durcissement : normal
        "??5??????   /usr/bin/ls",               # binaire remplace : GRAVE
        "missing     /usr/share/doc/bash/NEWS.gz",   # image mince : bruit
        "missing     /usr/sbin/sshd",            # binaire disparu : GRAVE
        "??5?????? c /etc/sysctl.conf",
    ])
    m = _MachineFactice({"dpkg": (1, sortie)})
    mods = binaires.modifications(m, "debian")
    fichiers = [x.fichier for x in mods]
    assert "/usr/share/doc/bash/NEWS.gz" not in fichiers   # bruit ecarte
    graves = {x.fichier for x in mods if x.grave}
    assert graves == {"/usr/bin/ls", "/usr/sbin/sshd"}, graves
    config = [x for x in mods if x.fichier == "/etc/ssh/sshd_config"][0]
    assert config.conffile and not config.grave
    assert "empreinte differente du paquet" in str(config)


def test_binaires_derive_entre_deux_releves():
    from brain.integrite import binaires

    reference = {"/usr/bin/sudo": "a" * 64, "/usr/bin/ps": "b" * 64,
                 "/usr/bin/who": "c" * 64}
    mesure = {"/usr/bin/sudo": "a" * 64, "/usr/bin/ps": "d" * 64,
              "/usr/local/bin/mael-agent": "e" * 64}
    ecarts = binaires.derive(reference, mesure)
    assert any("ps" in e and "CHANGEE" in e for e in ecarts)
    assert any("who" in e and "DISPARU" in e for e in ecarts)
    assert any("mael-agent" in e and "APPARU" in e for e in ecarts)
    assert not any("sudo" in e for e in ecarts)      # inchange : silence
    assert binaires.derive(reference, reference) == []


def test_binaires_sans_paquet_et_fusion_usr():
    from brain.integrite import binaires

    connus = " /bin/ls\n /usr/sbin/sshd\n /usr/bin/sudo\n"   # dpkg : /bin/ls
    presents = "/usr/bin/ls\n/usr/sbin/sshd\n/usr/local/bin/implant\n"
    m = _MachineFactice({"dpkg-query": (0, connus), "find": (0, presents)})
    intrus = binaires.sans_paquet(m)
    # /usr/bin/ls revendique sous /bin/ls : la fusion de /usr ne fabrique
    # pas un faux intrus
    assert intrus == ["/usr/local/bin/implant"], intrus


def test_binaires_empreintes_ignore_les_absents():
    from brain.integrite import binaires

    sortie = ("d3b07384d113edec49eaa6238ad5ff00" * 2 + "  /usr/bin/ls\n"
              "sha256sum: /usr/bin/absent: No such file or directory\n")
    m = _MachineFactice({"sha256sum": (1, sortie)})
    releve = binaires.empreintes(m, ["/usr/bin/ls", "/usr/bin/absent"])
    assert list(releve) == ["/usr/bin/ls"]


def test_binaires_jamais_de_commande_qui_ecrit():
    from brain.integrite import binaires

    m = _MachineFactice({})
    for argv in (["rm", "-rf", "/"], ["chmod", "777", "/etc/shadow"]):
        try:
            binaires._lecture(m, argv)
        except ValueError as e:
            assert "non LECTURE" in str(e)
        else:
            raise AssertionError(f"commande acceptee : {argv}")
    assert m.recues == []          # rien n'a ete envoye a la machine


# --------------------------------------------------------------------------- #
# Module 6 : infiltration LD_PRELOAD et hooks
# --------------------------------------------------------------------------- #
class _MachineShell:
    """Machine de test pour le module 6 : les commandes arrivent en
    « bash -c », on repond sur un fragment reconnaissable."""

    def __init__(self, reponses):
        self.reponses = dict(reponses)
        self.recues = []

    def executer(self, argv, racine=True, delai=None):
        from banc.executeurs import Resultat
        self.recues.append(list(argv))
        commande = argv[2] if len(argv) > 2 else ""
        for fragment, (code, sortie) in self.reponses.items():
            if fragment in commande:
                return Resultat(code, sortie, "")
        return Resultat(1, "", "")          # rien a dire : fichier absent


_MACHINE_SAINE = {
    "cat /etc/ld.so.preload": (1, ""),
    "grep -a -l -s": (1, ""),
    "(LD_PRELOAD|LD_AUDIT)=\" /etc/environment": (1, ""),
    "cat /etc/ld.so.conf": (0, "include /etc/ld.so.conf.d/*.conf\n"
                               "/usr/lib/x86_64-linux-gnu\n"),
    "lsmod": (0, "Module Size Used\nxfs 1 0\n"),
    "ls -d /.dockerenv": (2, ""),
    "cat /proc/1/cgroup": (0, "0::/init.scope\n"),
}


def test_infiltration_machine_saine():
    from brain.integrite import infiltration

    r = infiltration.controler(_MachineShell(_MACHINE_SAINE))
    assert r["graves"] == [], r["graves"]
    assert any("tenu" in c and "ld.so.preload" in c for c in r["constats"])


def test_infiltration_preload_global_est_grave():
    from brain.integrite import infiltration

    reponses = dict(_MACHINE_SAINE)
    reponses["cat /etc/ld.so.preload"] = (0, "/usr/local/lib/libmechant.so\n")
    r = infiltration.controler(_MachineShell(reponses))
    assert len(r["graves"]) == 1
    assert "libmechant.so" in r["graves"][0]
    assert "TOUS les programmes" in r["graves"][0]


def test_infiltration_declaration_systeme_est_grave():
    from brain.integrite import infiltration

    reponses = dict(_MACHINE_SAINE)
    reponses["(LD_PRELOAD|LD_AUDIT)=\" /etc/environment"] = (
        0, "/etc/environment:LD_PRELOAD=/opt/discret/libcache.so\n")
    r = infiltration.controler(_MachineShell(reponses))
    assert any("libcache.so" in g for g in r["graves"]), r["graves"]


def test_infiltration_processus_se_verifie_ne_se_condamne_pas():
    from brain.integrite import infiltration

    reponses = dict(_MACHINE_SAINE)
    reponses["grep -a -l -s"] = (0, "/proc/412/environ\n")
    reponses["/proc/412/comm"] = (0, "nginx\n")
    reponses["/proc/412/environ"] = (0, "LD_PRELOAD=/usr/lib/libjemalloc.so\n")
    r = infiltration.controler(_MachineShell(reponses))
    assert r["graves"] == []                   # un processus isole : pas grave
    assert any("412" in c and "nginx" in c and "jemalloc" in c
               for c in r["a_verifier"]), r["a_verifier"]


def test_infiltration_chemin_ajoute_signale():
    from brain.integrite import infiltration

    reponses = dict(_MACHINE_SAINE)
    reponses["cat /etc/ld.so.conf"] = (0, "/usr/lib/x86_64-linux-gnu\n"
                                          "/opt/discret/lib\n")
    r = infiltration.controler(_MachineShell(reponses))
    assert any("/opt/discret/lib" in c for c in r["a_verifier"])
    assert not any("x86_64-linux-gnu" in c for c in r["a_verifier"])


def test_infiltration_modules_noyau_jamais_juges_en_conteneur():
    from brain.integrite import infiltration

    reponses = dict(_MACHINE_SAINE)
    reponses["ls -d /.dockerenv"] = (2, "/.dockerenv\n")   # code 2 : un des
    # deux chemins manque, c'est la SORTIE qui prouve le conteneur
    constats = infiltration.modules_noyau(_MachineShell(reponses))
    assert len(constats) == 1
    assert constats[0].niveau == infiltration.A_VERIFIER
    assert "HOTE" in constats[0].detail


def test_infiltration_jamais_de_commande_qui_ecrit():
    from brain.integrite import infiltration

    m = _MachineShell({})
    try:
        infiltration._lire(m, "rm -rf /etc/ld.so.preload")
    except ValueError as e:
        assert "non LECTURE" in str(e)
    else:
        raise AssertionError("commande d'ecriture acceptee")
    assert m.recues == []


# --------------------------------------------------------------------------- #
# Module 8 : controle de derive d'etat
# --------------------------------------------------------------------------- #
def _etat(**rubriques):
    from brain.integrite.derive_etat import RUBRIQUES
    plein = {nom: [] for nom in RUBRIQUES}
    plein.update(rubriques)
    return {"date": "2026-09-20T00:00:00+00:00", "systeme": "essai",
            "rubriques": plein}


def test_derive_etat_photographie_toutes_les_rubriques():
    from brain.integrite import derive_etat

    m = _MachineShell({"dpkg-query": (0, "bash 5.1\n"),
                       "cut -d: -f1,3,4,7": (0, "root:0:0:/bin/bash\n")})
    etat = derive_etat.photographier(m, "essai")
    assert set(etat["rubriques"]) == set(derive_etat.RUBRIQUES)
    assert etat["rubriques"]["paquets"] == ["bash 5.1"]
    assert etat["systeme"] == "essai" and etat["date"]


def test_derive_etat_machine_stable():
    from brain.integrite import derive_etat

    etat = _etat(paquets=["bash 5.1"], comptes=["root:0:0:/bin/bash"])
    comparaison = derive_etat.comparer(etat, etat)
    assert comparaison["stable"]
    assert derive_etat.resumer(comparaison) == ["etat identique : aucune derive"]


def test_derive_etat_compte_uid_zero_est_grave():
    from brain.integrite import derive_etat

    avant = _etat(comptes=["root:0:0:/bin/bash"])
    apres = _etat(comptes=["root:0:0:/bin/bash", "secours:0:1000:/bin/bash",
                           "sauvegarde:1001:1001:/usr/sbin/nologin"])
    c = derive_etat.comparer(avant, apres)
    graves = [m["ligne"] for m in c["graves"]]
    assert graves == ["secours:0:1000:/bin/bash"], graves
    # un compte ordinaire se verifie, il ne se condamne pas
    assert any("sauvegarde" in m["ligne"] for m in c["a_verifier"])


def test_derive_etat_suid_apparu_grave_disparu_non():
    from brain.integrite import derive_etat

    avant = _etat(suid=["/usr/bin/sudo", "/usr/bin/passwd"])
    apres = _etat(suid=["/usr/bin/sudo", "/usr/local/bin/shell-discret"])
    c = derive_etat.comparer(avant, apres)
    assert [m["ligne"] for m in c["graves"]] == ["/usr/local/bin/shell-discret"]
    # un SUID qui DISPARAIT est un durcissement, pas une alerte
    assert any(m["ligne"] == "/usr/bin/passwd" and m["sens"] == "disparu"
               for m in c["a_verifier"])


def test_derive_etat_preload_dans_le_noyau_est_grave():
    from brain.integrite import derive_etat

    avant = _etat(noyau=["Linux 5.15"])
    apres = _etat(noyau=["Linux 5.15", "/usr/local/lib/libmechant.so"])
    c = derive_etat.comparer(avant, apres)
    assert any("libmechant" in m["ligne"] for m in c["graves"])


def test_derive_etat_fichier_modifie_compte_une_fois():
    from brain.integrite import derive_etat

    avant = _etat(fichiers=["aaa  /etc/passwd", "bbb  /etc/hosts"])
    apres = _etat(fichiers=["ccc  /etc/passwd", "bbb  /etc/hosts",
                            "ddd  /etc/cron.d/zz"])
    c = derive_etat.comparer(avant, apres)
    fichiers = [(m["sens"], m["ligne"]) for m in c["mouvements"]
                if m["rubrique"] == "fichiers"]
    assert ("modifie", "/etc/passwd") in fichiers
    assert ("apparu", "/etc/cron.d/zz") in fichiers
    assert not any(l == "/etc/hosts" for _, l in fichiers)   # inchange
    assert len(fichiers) == 2          # jamais un + et un - pour le meme
    resume = derive_etat.resumer(c)
    assert any("~ /etc/passwd" in l for l in resume)


def test_derive_etat_jamais_de_commande_qui_ecrit():
    from brain.integrite import derive_etat

    m = _MachineShell({})
    try:
        derive_etat._lire(m, "rm -rf /etc")
    except ValueError as e:
        assert "non LECTURE" in str(e)
    else:
        raise AssertionError("commande d'ecriture acceptee")
    assert m.recues == []


# --------------------------------------------------------------------------- #
# Module 7 : isolation seccomp-BPF et namespaces
# --------------------------------------------------------------------------- #
_ENFERME = ["docker", "run", "--rm", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--memory", "1g", "--pids-limit", "256", "image@sha256:x"]


def test_isolation_conteneur_conforme():
    from brain.integrite import isolation
    assert isolation.exigences_conteneur(_ENFERME) == []


def test_isolation_refuse_chaque_relachement():
    from brain.integrite import isolation

    cas = {
        "seccomp": _ENFERME + ["--security-opt", "seccomp=unconfined"],
        "privilegie": _ENFERME + ["--privileged"],
        "espaces de noms": _ENFERME + ["--pid", "host"],
        "socket docker": _ENFERME + ["--mount",
                                     "type=bind,source=/var/run/docker.sock,"
                                     "target=/var/run/docker.sock"],
    }
    for attendu, argv in cas.items():
        manques = isolation.exigences_conteneur(argv)
        assert any(m.startswith(attendu) for m in manques), (attendu, manques)

    # et les garanties retirees une a une
    for retire, mot in (("--read-only", "lecture seule"),
                        ("--pids-limit", "processus"),
                        ("--memory", "memoire")):
        argv = [a for i, a in enumerate(_ENFERME)
                if a != retire and _ENFERME[i - 1] != retire]
        manques = isolation.exigences_conteneur(argv)
        assert any(m.startswith(mot) for m in manques), (retire, manques)

    # --cap-drop autre chose que ALL ne compte pas
    argv = [("NET_RAW" if a == "ALL" else a) for a in _ENFERME]
    assert any(m.startswith("capacites")
               for m in isolation.exigences_conteneur(argv))


def test_isolation_option_collee_reconnue():
    """--pid=host doit etre vu comme --pid host."""
    from brain.integrite import isolation
    manques = isolation.exigences_conteneur(_ENFERME + ["--network=host"])
    assert any("espaces de noms" in m for m in manques), manques


def test_isolation_mesure_les_processus_sans_filtre():
    from brain.integrite import isolation

    reponses = {
        "^Seccomp:": (0, "/proc/1/status:Seccomp:\t2\n"
                         "/proc/412/status:Seccomp:\t0\n"
                         "/proc/900/status:Seccomp:\t2\n"),
        "/proc/412/comm": (0, "vieux-demon\n"),
        "ls -l /proc/1/ns": (0, "pid pid:[4026532383]\nnet net:[4026532385]\n"),
    }
    mesure = isolation.mesurer(_MachineShell(reponses))
    assert mesure["repartition"]["filtre BPF"] == 2
    assert mesure["repartition"]["aucun filtre"] == 1
    assert mesure["sans_filtre"] == ["412 (vieux-demon)"]
    assert mesure["sans_filtre_total"] == 1
    assert any("pid:[" in l for l in mesure["espaces_de_noms_pid1"])


def test_isolation_chaque_outil_de_mael_est_enferme():
    """Le contrat vaut pour les outils REELS du produit, pas pour un exemple."""
    import os
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    try:
        django.setup()
    except Exception:                       # deja configure
        pass
    from brain.integrite import isolation
    from brain.tools import registre

    for nom, outil in registre._outils.items():
        if not outil.image:
            continue
        manques = isolation.exigences_conteneur(
            outil.arguments_docker("image@sha256:x", ["--aide"]))
        assert manques == [], f"{nom} : {manques}"
