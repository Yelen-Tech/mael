"""Tests de l'humeur de MAEL (etape 8 du plan).

Le point central teste ici n'est pas l'humeur elle-meme — c'est
l'INVARIANT : elle ne peut rien decider. Aucun module de securite ne la
connait, et les verdicts ne dependent pas de la date.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from brain import humeur


def _utc(y, m, d, h=12):
    return datetime(y, m, d, h, tzinfo=timezone.utc)


def test_humeur_deterministe_et_complete():
    quand = _utc(2026, 9, 20)
    a, b = humeur.humeur(quand), humeur.humeur(quand)
    assert a == b                                     # meme date, meme humeur
    assert a.tonalite in {t for t, _ in humeur.TONALITES}
    assert 0.0 <= a.phase_lunaire < 360.0
    assert a.planete == "mars"                        # valeur par defaut
    assert a.ne_le == "2026-09-15"                    # naissance memorisee


def test_humeur_varie_sur_un_mois():
    """« Des sauts d'humeur » : sur une lunaison, plusieurs tonalites."""
    debut = _utc(2026, 9, 1)
    tonalites = {humeur.humeur(debut + timedelta(days=j)).tonalite
                 for j in range(30)}
    assert len(tonalites) >= 2
    assert tonalites <= {t for t, _ in humeur.TONALITES}


def test_naissance_et_planete_configurables():
    h = humeur.humeur(_utc(2026, 9, 20), naissance="2026-09-19",
                      planete="venus")
    assert h.ne_le == "2026-09-19" and h.planete == "venus"
    # et par l'environnement (lu a l'appel, pas a l'import)
    ancien = dict(os.environ)
    try:
        os.environ["BRAIN_NAISSANCE"] = "2026-09-20"
        os.environ["BRAIN_PLANETE"] = "jupiter"
        h = humeur.humeur(_utc(2026, 9, 20))
        assert h.ne_le == "2026-09-20" and h.planete == "jupiter"
    finally:
        os.environ.clear()
        os.environ.update(ancien)
    # une date ou une planete boiteuse est refusee, jamais devinee
    for mauvais in ({"BRAIN_NAISSANCE": "bientot"},
                    {"BRAIN_PLANETE": "pluton"}):
        ancien = dict(os.environ)
        try:
            os.environ.update(mauvais)
            humeur.humeur(_utc(2026, 9, 20))
            raise AssertionError(f"accepte : {mauvais}")
        except ValueError:
            pass
        finally:
            os.environ.clear()
            os.environ.update(ancien)


def test_ligne_honnete():
    texte = humeur.ligne(_utc(2026, 9, 20))
    assert "sans effet sur l'audit" in texte      # l'artifice est assume
    assert "mars" in texte.lower()


def test_humeur_hors_des_decisions_de_securite():
    """Ni le garde-fou, ni les ecarts, ni les playbooks, ni le fondement,
    ni la bibliotheque ne connaissent l'humeur ou les astres : le code de
    securite ne lit jamais ces modules."""
    import brain.bibliotheque.ecarts as ecarts
    import brain.fondement as fondement
    import brain.garde.commandes as garde
    import brain.playbooks as playbooks
    for module in (garde, ecarts, playbooks, fondement):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "humeur" not in source, module.__name__
        assert "astres" not in source, module.__name__


def test_verdicts_identiques_quelle_que_soit_la_date():
    """Le meme commandement donne le meme verdict a deux dates opposees —
    l'humeur a beau changer, la securite ne bouge pas."""
    from brain.garde import NIVEAU, classer
    for commande in ("cat /etc/shadow", "rm -rf /", "sysctl kernel.kptr_restrict"):
        assert classer(commande).niveau is classer(commande).niveau
    assert classer("rm -rf /").niveau is NIVEAU.INTERDIT
    assert classer("cat /etc/os-release").niveau is NIVEAU.LECTURE
