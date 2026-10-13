"""Tests du calcul des positions des astres (etape 6bis).

Les dates de reference sont des configurations publiques et verifiables
(ephemerides JPL/IMCCE) : le calcul est REEL et doit les retrouver a la
precision annoncee (~degre ; ~quelques degres pour la Lune simplifiee).
"""
from __future__ import annotations

from datetime import datetime, timezone

from brain import astres


def _utc(y, m, d, h=0, minute=0):
    return datetime(y, m, d, h, minute, tzinfo=timezone.utc)


def _ecart(a: float, b: float) -> float:
    """Distance angulaire signee entre deux longitudes (degres, ±180)."""
    return (a - b + 180) % 360 - 180


def test_jour_julien_j2000():
    assert abs(astres.jour_julien(_utc(2000, 1, 1, 12)) - 2451545.0) < 1e-9
    # 1er janvier 2025, 00:00 UTC : 2460676.5 (ephemerides standards)
    assert abs(astres.jour_julien(_utc(2025, 1, 1)) - 2460676.5) < 1e-9


def test_soleil_aux_reperes_annuels():
    # J2000 : longitude moyenne du Soleil ~280,46 deg
    assert abs(_ecart(astres.longitude_ecliptique("soleil",
                                                  _utc(2000, 1, 1, 12)),
                      280.46)) < 1.0
    # Equinoxe de printemps 2000 : 20 mars 07:35 UTC -> 0 deg
    assert abs(_ecart(astres.longitude_ecliptique("soleil",
                                                  _utc(2000, 3, 20, 7, 35)),
                      0.0)) < 1.5
    # Solstice d'ete 2000 : 21 juin 01:48 UTC -> 90 deg
    assert abs(_ecart(astres.longitude_ecliptique("soleil",
                                                  _utc(2000, 6, 21, 1, 48)),
                      90.0)) < 1.5


def test_lune_nouvelle_et_pleine():
    # Nouvelle lune : 6 janvier 2000, 18:14 UTC -> conjonction
    quand = _utc(2000, 1, 6, 18, 14)
    diff = _ecart(astres.longitude_ecliptique("lune", quand),
                  astres.longitude_ecliptique("soleil", quand))
    assert abs(diff) < 2.5
    # Pleine lune (eclipse totale) : 21 janvier 2000, 04:40 UTC -> opposition
    quand = _utc(2000, 1, 21, 4, 40)
    diff = _ecart(astres.longitude_ecliptique("lune", quand),
                  astres.longitude_ecliptique("soleil", quand))
    assert abs(abs(diff) - 180) < 3.0


def test_mars_en_opposition():
    # Grande opposition de Mars : 28 aout 2003, ~18:00 UTC -> Mars et le
    # Soleil a 180 deg l'un de l'autre
    quand = _utc(2003, 8, 28, 18)
    diff = _ecart(astres.longitude_ecliptique("mars", quand),
                  astres.longitude_ecliptique("soleil", quand))
    assert abs(abs(diff) - 180) < 4.0


def test_positions_completes_et_bornees():
    quand = _utc(2026, 9, 20, 12)
    pos = astres.positions(quand)
    assert set(pos) == set(astres.CORPS)
    for corps, longitude in pos.items():
        assert 0.0 <= longitude < 360.0, corps


def test_determinisme():
    quand = _utc(2026, 9, 20, 12)
    assert astres.positions(quand) == astres.positions(quand)


def test_corps_inconnu_refuse():
    try:
        astres.longitude_ecliptique("pluton", _utc(2026, 1, 1))
    except ValueError as e:
        assert "pluton" in str(e)
    else:
        raise AssertionError("un corps inconnu doit etre refuse")
