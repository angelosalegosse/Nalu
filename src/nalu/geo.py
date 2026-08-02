r"""Geometrie angulaire et lancer de rayons cotier.

    DIAGRAMME — lancer de rayons (a verifier dans tout commit modifiant ce fichier)

                                N (0 deg)
                                    |
              \         \       \   |   /       /         /
               \         \       \  |  /       /         /
                \         \       \ | /       /         /        OCEAN
                 \         \       \|/       /         /
    ~~~~~~~~~~~~~~+~~~~~~~~~+~~~~~~~ * ~~~~~~+~~~~~~~~~+~~~~~~~~~~~~~~~
    ##############|#########|######/ | \#####|#########|###############
    ############################/   spot  \##########################
    ################################################################ TERRE

    Un rayon par pas de `ray_step_deg`, de longueur `open_ocean_km`.
      rayon sans intersection avec la terre  -> secteur EXPOSE
      rayon coupant la terre                 -> secteur BLOQUE
    La plus longue plage circulaire de secteurs exposes donne la fenetre
    [swell_dir_min, swell_dir_max] du spot.

    Convention d'arc : un arc va de `start` vers `end` dans le sens HORAIRE
    (sens des relevements croissants). L'arc [350, 10] traverse donc le nord et
    mesure 20 degres ; l'arc [10, 350] mesure 340 degres. Les deux bornes sont
    INCLUSES. C'est le passage par 0 degre qui est le bug le plus probable du
    projet : `in_arc` est l'unique implementation de cette regle dans tout le
    projet, aucun autre module ne la reecrit.
"""

import math
from collections.abc import Sequence

from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from nalu.config import CONFIG

# Rayon volumetrique moyen de la Terre (IUGG). Constante physique, pas un
# parametre du modele : elle n'a rien a faire dans `config.py`.
EARTH_RADIUS_KM = 6371.0088

_FULL_TURN = 360.0


def normalize_bearing(angle: float) -> float:
    """Ramene un relevement dans [0, 360). `normalize_bearing(-10) == 350`."""
    return angle % _FULL_TURN


def arc_span(start: float, end: float) -> float:
    """Amplitude horaire de l'arc `start` -> `end`, dans [0, 360].

    Un arc degenere (`start == end`) mesure 0. Un arc dont l'amplitude brute
    atteint ou depasse un tour complet mesure 360.
    """
    if end - start >= _FULL_TURN:
        return _FULL_TURN
    return (end - start) % _FULL_TURN


def in_arc(angle: float, start: float, end: float) -> bool:
    """`angle` appartient-il a l'arc horaire allant de `start` a `end` ?

    Unique implementation du passage de fenetre par 0 degre dans le projet.

    - Bornes incluses : `in_arc(10, 10, 50)` et `in_arc(50, 10, 50)` sont vrais.
    - Passage par 0 : `in_arc(0, 350, 10)` est vrai, `in_arc(180, 350, 10)` est faux.
    - Arc complet : toute amplitude brute >= 360 accepte tout, `in_arc(x, 0, 360)`.
    - Arc degenere : `start == end` n'accepte que cette direction exacte.

    Les angles hors [0, 360) sont acceptes et normalises.
    """
    if end - start >= _FULL_TURN:
        return True
    offset = (angle - start) % _FULL_TURN
    return offset <= arc_span(start, end)


def bearing_grid(step_deg: float | None = None) -> list[float]:
    """Grille reguliere de relevements a partir du nord, dans [0, 360)."""
    step = CONFIG.ray_step_deg if step_deg is None else step_deg
    if step <= 0.0:
        raise ValueError(f"pas angulaire invalide : {step}")
    count = round(_FULL_TURN / step)
    if not math.isclose(count * step, _FULL_TURN):
        raise ValueError(f"le pas angulaire {step} ne divise pas 360 degres")
    return [i * step for i in range(count)]


def ray_endpoint(
    lat: float, lon: float, bearing_deg: float, distance_km: float
) -> tuple[float, float]:
    """Point atteint depuis (`lat`, `lon`) en suivant `bearing_deg` sur `distance_km`.

    Formule de destination sur grand cercle. Le resultat est renvoye en degres,
    longitude ramenee dans [-180, 180).
    """
    delta = distance_km / EARTH_RADIUS_KM
    theta = math.radians(normalize_bearing(bearing_deg))
    phi1 = math.radians(lat)
    lambda1 = math.radians(lon)

    sin_phi2 = math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta)
    phi2 = math.asin(max(-1.0, min(1.0, sin_phi2)))
    lambda2 = lambda1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * sin_phi2,
    )
    lon2 = (math.degrees(lambda2) + 180.0) % _FULL_TURN - 180.0
    return math.degrees(phi2), lon2


def _ray_segments(lat: float, lon: float, lat2: float, lon2: float) -> list[LineString]:
    """Segments planaires (lon, lat) du rayon, coupes a l'antimeridien si besoin.

    Sans cette coupe, un rayon partant de 179 degres est vu par shapely comme
    traversant toute la planete en sens inverse, et croiserait tous les continents.
    """
    delta = lon2 - lon
    if delta > 180.0:
        lon2 -= _FULL_TURN
    elif delta < -180.0:
        lon2 += _FULL_TURN

    if -180.0 <= lon2 <= 180.0:
        return [LineString([(lon, lat), (lon2, lat2)])]

    edge = 180.0 if lon2 > 180.0 else -180.0
    ratio = (edge - lon) / (lon2 - lon)
    lat_cross = lat + ratio * (lat2 - lat)
    return [
        LineString([(lon, lat), (edge, lat_cross)]),
        LineString([(-edge, lat_cross), (lon2 - 2.0 * edge, lat2)]),
    ]


def ray_is_open(
    lat: float,
    lon: float,
    bearing_deg: float,
    land: BaseGeometry,
    reach_km: float | None = None,
) -> bool:
    """Le rayon issu du spot atteint-il l'ocean ouvert sans rencontrer la terre ?"""
    reach = CONFIG.open_ocean_km if reach_km is None else reach_km
    lat2, lon2 = ray_endpoint(lat, lon, bearing_deg, reach)
    return not any(segment.intersects(land) for segment in _ray_segments(lat, lon, lat2, lon2))


def cast_rays(
    lat: float,
    lon: float,
    land: BaseGeometry,
    reach_km: float | None = None,
    step_deg: float | None = None,
) -> list[bool]:
    """Un booleen par relevement de `bearing_grid`, vrai si le secteur est expose."""
    return [
        ray_is_open(lat, lon, bearing, land, reach_km)
        for bearing in bearing_grid(step_deg)
    ]


def widest_arc(
    open_flags: Sequence[bool], step_deg: float | None = None
) -> tuple[float, float] | None:
    """Plus longue plage circulaire de secteurs exposes, en (start, end) inclus.

    Renvoie `None` si aucun rayon n'est libre (spot en fond de baie ferme), et
    `(0, 360)` si tous le sont (ile en plein ocean) : cet encodage est exactement
    celui que `in_arc` interprete comme un arc complet.
    """
    grid = bearing_grid(step_deg)
    if len(open_flags) != len(grid):
        raise ValueError(f"{len(open_flags)} secteurs pour une grille de {len(grid)}")
    if not any(open_flags):
        return None
    if all(open_flags):
        return 0.0, _FULL_TURN

    size = len(grid)
    best_start, best_len = 0, 0
    current_start, current_len = None, 0
    # Deux tours : une plage a cheval sur l'index 0 est ainsi vue d'un seul tenant.
    for i in range(2 * size):
        if open_flags[i % size]:
            if current_len == 0:
                current_start = i
            current_len += 1
            if current_len > best_len:
                best_len, best_start = current_len, current_start
        else:
            current_len = 0

    step = grid[1] - grid[0]
    start = grid[best_start % size]
    return start, start + (best_len - 1) * step


def compute_exposure_window(
    lat: float,
    lon: float,
    land: BaseGeometry,
    reach_km: float | None = None,
    step_deg: float | None = None,
) -> tuple[float, float] | None:
    """Fenetre d'exposition a la houle d'un spot, CALCULEE et non declaree.

    Renvoie `(swell_dir_min, swell_dir_max)` ou `None` si aucun rayon n'est libre.
    Deterministe : memes entrees, meme sortie, aucun alea.
    """
    return widest_arc(cast_rays(lat, lon, land, reach_km, step_deg), step_deg)
