"""Positions des astres (etape 6bis du plan Kimi).

Calcul REEL, deterministe, hors ligne : longitudes ecliptiques
geocentriques du Soleil, de la Lune et des huit planetes a une date
donnee, par elements kepleriens moyens.

  - Planetes : elements et taux seculaires du JPL (table 1, valide
    1800-2050) — https://ssd.jpl.nasa.gov/planets/approx_pos.html
  - Lune : theorie simplifiee aux termes principaux (precision ~0,5 deg).

Ce module rend des DEGRES, rien d'autre. Toute interpretation
(astrologique ou autre) est hors de son perimetre et hors du perimetre
de MAEL : aucun verdict d'audit ne depend de ces positions (teste dans
tests_humeur.py).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

J2000 = 2451545.0          # jour julien de l'epoque J2000.0

# Elements kepleriens moyens (J2000) et taux par siecle julien, JPL
# table 1 : (a [UA], e, I [deg], L [deg], longitude du perihelie [deg],
# longitude du noeud ascendant [deg]), chacun (valeur, taux).
_ELEMENTS = {
    "mercure": ((0.38709927, 0.00000037), (0.20563593, 0.00001906),
                (7.00497902, -0.00594749), (252.25032350, 149472.67411175),
                (77.45779628, 0.16047689), (48.33076593, -0.12534081)),
    "venus":   ((0.72333566, 0.00000390), (0.00677672, -0.00004107),
                (3.39467605, -0.00078890), (181.97909950, 58517.81538729),
                (131.60246718, 0.00268329), (76.67984255, -0.27769418)),
    # Barycentre Terre-Lune : a cette precision (~degre), c'est la Terre.
    "terre":   ((1.00000261, 0.00000562), (0.01671123, -0.00004392),
                (-0.00001531, -0.01294668), (100.46457166, 35999.37244981),
                (102.93768193, 0.32327364), (0.0, 0.0)),
    "mars":    ((1.52371034, 0.00001847), (0.09339410, 0.00007882),
                (1.84969142, -0.00813131), (-4.55343205, 19140.30268499),
                (-23.94362959, 0.44441088), (49.55953891, -0.29257343)),
    "jupiter": ((5.20288700, -0.00011607), (0.04838624, -0.00013253),
                (1.30439695, -0.00183714), (34.39644051, 3034.74612775),
                (14.72847983, 0.21252668), (100.47390909, 0.20469106)),
    "saturne": ((9.53667594, -0.00125060), (0.05386179, -0.00050991),
                (2.48599187, 0.00193609), (49.95424423, 1222.49362201),
                (92.59887831, -0.41897216), (113.66242448, -0.28867794)),
    "uranus":  ((19.18916464, -0.00196176), (0.04725744, -0.00004397),
                (0.77263783, -0.00242939), (313.23810451, 428.48202785),
                (170.95427630, 0.40805281), (74.01692503, 0.04240589)),
    "neptune": ((30.06992276, 0.00026291), (0.00859048, 0.00005105),
                (1.77004347, 0.00035372), (-55.12002969, 218.45945325),
                (44.96476227, -0.32241464), (131.78422574, -0.00508664)),
}

CORPS = ("soleil", "lune", "mercure", "venus", "mars", "jupiter",
         "saturne", "uranus", "neptune")


def jour_julien(quand: datetime) -> float:
    """Jour julien d'un datetime (UTC). Formule standard du calendrier
    gregorien ; TT/UTC ignores (une minute ne change rien au degre pres)."""
    if quand.tzinfo is None:
        quand = quand.replace(tzinfo=timezone.utc)
    quand = quand.astimezone(timezone.utc)
    a, m = quand.year, quand.month
    if m <= 2:
        a, m = a - 1, m + 12
    b = 2 - a // 100 + a // 400
    jour = (quand.day
            + (quand.hour + (quand.minute + quand.second / 60.0) / 60.0) / 24.0)
    return (int(365.25 * (a + 4716)) + int(30.6001 * (m + 1)) + jour + b
            - 1524.5)


def _resoudre_kepler(M: float, e: float) -> float:
    """Anomalie excentrique E telle que E - e.sin E = M (Newton, radians)."""
    E = M + e * math.sin(M)
    for _ in range(10):
        E -= (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
    return E


def _heliocentrique(nom: str, T: float) -> tuple[float, float, float]:
    """Position heliocentrique (UA) dans l'ecliptique et equinoxe J2000."""
    (a0, da), (e0, de), (i0, di), (L0, dL), (p0, dp), (o0, do) = _ELEMENTS[nom]
    a = a0 + da * T
    e = e0 + de * T
    i = math.radians(i0 + di * T)
    L = L0 + dL * T
    peri = p0 + dp * T
    noeud = o0 + do * T
    w = math.radians(peri - noeud)            # argument du perihelie
    M = math.radians((L - peri + 180) % 360 - 180)
    E = _resoudre_kepler(M, e)
    xp = a * (math.cos(E) - e)                # plan de l'orbite
    yp = a * math.sqrt(1 - e * e) * math.sin(E)
    cw, sw = math.cos(w), math.sin(w)
    cn, sn = math.cos(math.radians(noeud)), math.sin(math.radians(noeud))
    ci, si = math.cos(i), math.sin(i)
    x = (cw * cn - sw * sn * ci) * xp + (-sw * cn - cw * sn * ci) * yp
    y = (cw * sn + sw * cn * ci) * xp + (-sw * sn + cw * cn * ci) * yp
    z = (sw * si) * xp + (cw * si) * yp
    return x, y, z


def _longitude_lune(T: float) -> float:
    """Longitude ecliptique geocentrique de la Lune, termes principaux."""
    Lp = 218.3164477 + 481267.88123421 * T    # longitude moyenne
    D = 297.8501921 + 445267.1114034 * T      # elongation moyenne au Soleil
    Ms = math.radians(357.5291092 + 35999.0502909 * T)   # anomalie du Soleil
    Mm = math.radians(134.9633964 + 477198.8675055 * T)  # anomalie de la Lune
    F = math.radians(93.2720950 + 483202.0175233 * T)    # argument de latitude
    d2 = math.radians(2 * (297.8501921 + 445267.1114034 * T))
    D = math.radians(D)
    correction = (
        6.289 * math.sin(Mm)
        - 1.274 * math.sin(Mm - 2 * D)          # evection
        + 0.658 * math.sin(d2)                  # variation
        - 0.186 * math.sin(Ms)                  # equation annuelle
        - 0.114 * math.sin(2 * F)
        - 0.059 * math.sin(2 * Mm - 2 * D)
        - 0.057 * math.sin(Mm - 2 * D + Ms)
        + 0.053 * math.sin(Mm + 2 * D)
        + 0.046 * math.sin(2 * D - Ms)
        + 0.041 * math.sin(Mm - Ms)
        - 0.035 * math.sin(D)                   # equation parallactique
        - 0.031 * math.sin(Mm + Ms)
        + 0.011 * math.sin(Mm - 4 * D)
    )
    return (Lp + correction) % 360.0


def longitude_ecliptique(corps: str, quand: datetime) -> float:
    """Longitude ecliptique geocentrique (degres, 0-360) d'un corps.

    `corps` : un nom de CORPS. Precision : ~0,01 deg (Soleil, planetes
    vives), ~0,5 deg (Lune) — tres suffisant pour l'usage (etape 8)."""
    corps = corps.lower()
    T = (jour_julien(quand) - J2000) / 36525.0
    if corps == "lune":
        return _longitude_lune(T)
    xt, yt, _ = _heliocentrique("terre", T)
    if corps == "soleil":
        return math.degrees(math.atan2(-yt, -xt)) % 360.0
    if corps not in _ELEMENTS:
        raise ValueError(f"corps inconnu : {corps} (attendu : "
                         f"{', '.join(CORPS)})")
    x, y, _ = _heliocentrique(corps, T)
    return math.degrees(math.atan2(y - yt, x - xt)) % 360.0


def positions(quand: datetime) -> dict[str, float]:
    """Toutes les longitudes ecliptiques geocentriques a une date."""
    return {corps: longitude_ecliptique(corps, quand) for corps in CORPS}
