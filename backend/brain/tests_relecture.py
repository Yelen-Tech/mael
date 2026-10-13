"""Tests de la relecture des fiches (18/09/2026).

Defauts trouves en relisant, et garde-fous pour qu'ils ne reviennent pas :
variable de gabarit inconnue remplacee par du vide (« find / », « /grub.cfg »),
liste d'algorithmes forts d'un seul referentiel, titres muets sur les
fichiers vises, risques restes en anglais.
"""
import re

from brain.bibliotheque.importeurs import rendu_jinja


def _fiches():
    from brain import bibliotheque
    return list(bibliotheque.toutes())


def test_variable_inconnue_marquee_dans_le_gabarit_seulement():
    texte = ("title: 'Droits de {{{ sshd_config_dir }}}'\n"
             "template:\n    name: file_permissions\n"
             "    vars:\n        filepath: '{{{ chemin_inconnu }}}/'\n"
             "        mode: '{{{ sshd_config_dir }}}'\n"
             "platform: machine\n"
             "note: '{{{ autre_inconnue }}}'\n")
    rendu = rendu_jinja.rendre(texte, {"product": "ubuntu2404",
                                       "sshd_config_dir": "/etc/ssh/d"})
    assert rendu_jinja.INCONNUE + "chemin_inconnu" in rendu
    assert "mode: '/etc/ssh/d'" in rendu
    # Hors du gabarit : texte explicatif, la macro est simplement retiree.
    assert "note: ''" in rendu and "autre_inconnue" not in rendu


def test_aucune_fiche_ne_vise_un_chemin_vide():
    """Symptome du defaut : chemin du gabarit rendu vide -> racine."""
    for f in _fiches():
        for o in f.observer:
            c = o.commande
            assert not re.search(r"\bfind / -maxdepth 1 ", c), (f.id, c)
            assert not re.search(r"stat -c '[^']*' /[\w.-]+ ", c), (f.id, c)
            assert rendu_jinja.INCONNUE not in c, (f.id, c)


def test_titre_dit_quels_fichiers_sont_vises():
    from brain.bibliotheque.importeurs.gabarits_cac import _motif_lisible
    assert _motif_lisible(r"^.*\.pub$") == "*.pub"
    assert _motif_lisible("^.*_key$") == "*_key"
    assert _motif_lisible("^.*$") == ""
    assert _motif_lisible("^(cron.allow)$") == "motif ^(cron.allow)$"
    assert _motif_lisible(r"^.*audit(\.rules|d\.conf)$") == \
        "*audit.rules, *auditd.conf"
    titres = {f.id: f.titre for f in _fiches()}
    assert titres["cac-file-permissions-sshd-pub-key"] == \
        "Droits des fichiers *.pub de /etc/ssh/ (0644 au plus)"


def test_kex_forts_union_des_referentiels():
    """sntrup761 est dans la liste CIS Ubuntu 24.04 / Debian 12 et active
    par defaut : il ne doit pas etre signale faible."""
    f = next(f for f in _fiches() if f.id == "cac-sshd-use-strong-kex")
    assert "sntrup761x25519-sha512@openssh.com" in f.observer[0].commande


def test_risques_traduits_coherents():
    from brain.bibliotheque.importeurs import complianceascode as cac
    traduits = cac.risques_fr()
    par_regle = {f.source.regle: f for f in _fiches()
                 if f.source and f.source.origine == "complianceascode"}
    orphelines = [r for r in traduits if r not in par_regle]
    assert not orphelines, orphelines[:5]
    for regle, texte in traduits.items():
        risque = par_regle[regle].controles[0].risque
        assert risque == texte, regle


def test_fiche_relue_a_un_risque_en_francais():
    from brain.bibliotheque.importeurs import complianceascode as cac
    traduits = set(cac.risques_fr())
    lexique = {p for p, v in cac.lexique().items() if v.get("risque")}
    for f in _fiches():
        if f.etat != "verifie" or not f.source or \
                f.source.origine != "complianceascode":
            continue
        param = next((m for m in lexique if m.lower() in f.mots_cles), None)
        assert f.source.regle in traduits or param, f.id


def test_risque_traduit_une_seule_fois(tmp_path=None):
    import tempfile
    from pathlib import Path

    from brain.bibliotheque.importeurs import complianceascode as cac
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "r.yaml"
        p.write_text("risques:\n  - regles: [a, b]\n    risque: x\n"
                     "  - regles: [b]\n    risque: y\n", encoding="utf-8")
        try:
            cac.risques_fr.__wrapped__(p)
            assert False, "doublon non signale"
        except ValueError:
            pass


def test_registres_sans_cle_en_double():
    """YAML garde la DERNIERE cle en double sans rien dire : une exclusion
    ou une recette serait perdue en silence."""
    from pathlib import Path

    import yaml

    class _Strict(yaml.SafeLoader):
        pass

    def _mapping(loader, node, deep=False):
        cles = [loader.construct_object(k, deep=deep) for k, _ in node.value]
        doublons = {c for c in cles if cles.count(c) > 1}
        assert not doublons, (node.start_mark.line, sorted(doublons))
        return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)

    _Strict.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)
    dossier = Path(__file__).parent / "bibliotheque" / "importeurs"
    for nom in ("recettes_cac.yaml", "lexique_sshd.yaml", "risques_fr.yaml",
                "relectures_complianceascode.yaml"):
        yaml.load((dossier / nom).read_text(encoding="utf-8"), Loader=_Strict)


def test_exclusions_et_recursion_de_la_source():
    """Releve a la relecture du 19/09/2026 : excluded_files et
    recursive@produit etaient ignores -> wtmp (0664 exige ailleurs) signale
    en ecart par la regle « tous les fichiers de /var/log en 0640 »."""
    f = next(f for f in _fiches()
             if f.source and f.source.regle == "permissions_local_var_log")
    c = f.controles[0]
    assert "! -name '[bw]tmp'" in f.observer[0].commande
    assert "-maxdepth" not in f.observer[0].commande        # recursif
    assert c.parametres["recursif"] == "oui"
    assert "lastlog" in c.parametres["exclure"].split(",")


def test_root_verrouille_accepte():
    f = next(f for f in _fiches()
             if f.source and f.source.regle == "ensure_root_access_controlled")
    assert "/^[$!*]/" in f.observer[0].commande


def test_erreur_source_arp_filter_corrigee():
    """ComplianceAsCode 0.1.82 cite arp_filter pour ANSSI R12 sans fixer la
    valeur (defaut 0) alors que R12 demande 1."""
    f = next(f for f in _fiches() if f.source
             and f.source.regle == "sysctl_net_ipv4_conf_all_arp_filter")
    assert f.controles[0].parametres == {
        "cle": "net.ipv4.conf.all.arp_filter", "valeur": "1"}
    assert any("corrigee par MAEL" in p for p in f.pieges)


def test_plateforme_de_la_source_appliquee():
    """« iptables-persistent absent » ne vaut que si ufw est installe
    (platform: package[ufw]) : sinon /corriger retirerait le paquet qui
    recharge les regles d'une machine sous iptables."""
    from brain.bibliotheque.importeurs.complianceascode import gardes_plateforme
    assert gardes_plateforme("package[ufw]") == [
        "dpkg -s ufw >/dev/null 2>&1 || echo 'SENTINELLE:SANS_OBJET'"]
    assert "&&" in gardes_plateforme("not package[nftables]")[0]
    # Paquet de base, nom Debian incertain : jamais garde.
    assert gardes_plateforme("package[shadow-utils]") == []
    assert gardes_plateforme("package[ufw] or package[nftables]") == []
    f = next(f for f in _fiches() if f.source
             and f.source.regle == "package_iptables-persistent_removed")
    assert f.observer[0].commande.startswith("dpkg -s ufw ")


def test_marqueur_sans_objet_pour_tous_les_lecteurs():
    from brain.bibliotheque.ecarts import STATUT, lire
    for spec in (dict(lecteur="dpkg", comparateur="absent", attendu=["x"]),
                 dict(lecteur="systemctl", comparateur="actif"),
                 dict(lecteur="stat", champ="droits",
                      comparateur="droits_au_plus", attendu="0600")):
        r = lire("SENTINELLE:SANS_OBJET\nx install ok installed\n", spec)
        assert r.statut is STATUT.INDETERMINE and r.constate == "sans objet"
