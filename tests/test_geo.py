"""`geo.py` : le passage de fenetre par 0 degre, et le lancer de rayons.

`in_arc` est l'unique implementation du passage par zero dans le projet. C'est le
bug le plus probable de Nalu : il est teste ici sur le passage par zero, les bornes
incluses, l'arc complet et l'arc degenere.
"""

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st
from shapely.geometry import Polygon, box

from nalu.config import CONFIG
from nalu.geo import (
    arc_span,
    bearing_grid,
    cast_rays,
    compute_exposure_window,
    in_arc,
    normalize_bearing,
    ray_endpoint,
    ray_is_open,
    widest_arc,
)

# --- normalize_bearing --------------------------------------------------------


@pytest.mark.parametrize(
    ("angle", "attendu"),
    [(0.0, 0.0), (360.0, 0.0), (370.0, 10.0), (-10.0, 350.0), (-360.0, 0.0), (720.5, 0.5)],
)
def test_normalize_bearing(angle: float, attendu: float) -> None:
    assert normalize_bearing(angle) == pytest.approx(attendu)


# --- in_arc : passage par 0 degre ---------------------------------------------


@pytest.mark.parametrize("angle", [350.0, 355.0, 0.0, 5.0, 10.0])
def test_in_arc_passage_par_zero_dedans(angle: float) -> None:
    """L'arc [350, 10] traverse le nord et mesure 20 degres, pas 340."""
    assert in_arc(angle, 350.0, 10.0)


@pytest.mark.parametrize("angle", [11.0, 180.0, 349.0, 200.0])
def test_in_arc_passage_par_zero_dehors(angle: float) -> None:
    assert not in_arc(angle, 350.0, 10.0)


def test_in_arc_arc_complementaire_traverse_bien_le_sud() -> None:
    """L'arc [10, 350] est le complementaire : il mesure 340 degres."""
    assert arc_span(10.0, 350.0) == pytest.approx(340.0)
    assert in_arc(180.0, 10.0, 350.0)
    assert not in_arc(0.0, 10.0, 350.0)


# --- in_arc : bornes incluses -------------------------------------------------


def test_in_arc_bornes_incluses() -> None:
    assert in_arc(10.0, 10.0, 50.0)
    assert in_arc(50.0, 10.0, 50.0)
    assert not in_arc(9.9, 10.0, 50.0)
    assert not in_arc(50.1, 10.0, 50.0)


def test_in_arc_bornes_incluses_a_cheval_sur_zero() -> None:
    assert in_arc(350.0, 350.0, 10.0)
    assert in_arc(10.0, 350.0, 10.0)


# --- in_arc : arc complet -----------------------------------------------------


@pytest.mark.parametrize("angle", [0.0, 90.0, 180.0, 270.0, 359.9])
def test_in_arc_arc_complet_accepte_tout(angle: float) -> None:
    assert in_arc(angle, 0.0, 360.0)


def test_in_arc_arc_complet_depuis_une_origine_quelconque() -> None:
    assert all(in_arc(a, 210.0, 570.0) for a in range(0, 360, 15))


def test_arc_span_d_un_arc_complet_vaut_360() -> None:
    assert arc_span(0.0, 360.0) == pytest.approx(360.0)
    assert arc_span(210.0, 570.0) == pytest.approx(360.0)


# --- in_arc : arc degenere ----------------------------------------------------


def test_in_arc_arc_degenere_n_accepte_que_sa_direction() -> None:
    """`start == end` designe une direction unique, pas le cercle entier."""
    assert in_arc(90.0, 90.0, 90.0)
    assert not in_arc(90.1, 90.0, 90.0)
    assert not in_arc(270.0, 90.0, 90.0)
    assert arc_span(90.0, 90.0) == pytest.approx(0.0)


# --- in_arc : angles non normalises -------------------------------------------


def test_in_arc_normalise_ses_entrees() -> None:
    assert in_arc(-10.0, 350.0, 10.0)
    assert in_arc(370.0, 350.0, 10.0)


@given(
    angle=st.integers(min_value=-720, max_value=720),
    start=st.integers(min_value=0, max_value=359),
    span=st.integers(min_value=1, max_value=359),
)
def test_in_arc_deux_arcs_complementaires_couvrent_le_cercle(
    angle: int, start: int, span: int
) -> None:
    """Propriete : tout relevement appartient a l'arc, a son complementaire, ou aux deux."""
    end = start + span
    assert in_arc(angle, start, end) or in_arc(angle, end, start)


# --- bearing_grid -------------------------------------------------------------


def test_bearing_grid_utilise_le_pas_de_la_config() -> None:
    grille = bearing_grid()
    assert len(grille) == int(360 / CONFIG.ray_step_deg)
    assert grille[0] == 0.0
    assert max(grille) < 360.0


def test_bearing_grid_refuse_un_pas_qui_ne_divise_pas_le_tour() -> None:
    with pytest.raises(ValueError, match="ne divise pas"):
        bearing_grid(7.0)


# --- ray_endpoint -------------------------------------------------------------


def test_ray_endpoint_plein_nord_monte_en_latitude() -> None:
    lat, lon = ray_endpoint(0.0, 0.0, 0.0, 500.0)
    assert lat == pytest.approx(500.0 / 6371.0088 * 180.0 / math.pi, rel=1e-6)
    assert lon == pytest.approx(0.0, abs=1e-9)


def test_ray_endpoint_plein_est_depuis_l_equateur() -> None:
    lat, lon = ray_endpoint(0.0, 0.0, 90.0, 500.0)
    assert lat == pytest.approx(0.0, abs=1e-9)
    assert lon > 4.0


def test_ray_endpoint_reste_dans_les_bornes_de_longitude() -> None:
    """Un rayon partant du bord de l'antimeridien ne doit pas sortir de [-180, 180)."""
    _, lon = ray_endpoint(0.0, 179.5, 90.0, 500.0)
    assert -180.0 <= lon < 180.0


# --- lancer de rayons ---------------------------------------------------------

# Cote rectiligne : la terre occupe tout ce qui est au sud de la latitude -0.5.
COTE_DROITE = box(-20.0, -20.0, 20.0, -0.5)


def test_ray_is_open_vers_le_large() -> None:
    assert ray_is_open(0.0, 0.0, 0.0, COTE_DROITE)


def test_ray_is_open_vers_la_terre() -> None:
    assert not ray_is_open(0.0, 0.0, 180.0, COTE_DROITE)


def test_fenetre_calculee_sur_une_cote_droite() -> None:
    """La fenetre doit contenir le large et exclure l'interieur des terres."""
    fenetre = compute_exposure_window(0.0, 0.0, COTE_DROITE)
    assert fenetre is not None
    start, end = fenetre
    assert in_arc(0.0, start, end)
    assert in_arc(90.0, start, end)
    assert in_arc(270.0, start, end)
    assert not in_arc(180.0, start, end)
    assert 150.0 < arc_span(start, end) < 210.0


def test_fenetre_d_une_ile_en_plein_ocean_est_l_arc_complet() -> None:
    terre_lointaine = box(100.0, 40.0, 110.0, 50.0)
    fenetre = compute_exposure_window(0.0, 0.0, terre_lointaine)
    assert fenetre == (0.0, 360.0)
    assert all(in_arc(a, *fenetre) for a in range(0, 360, 10))


def test_aucun_rayon_libre_renvoie_none() -> None:
    """Spot en fond de baie fermee : le pipeline doit pouvoir le detecter, pas deviner."""
    assert compute_exposure_window(0.0, 0.0, box(-5.0, -5.0, 5.0, 5.0)) is None


def test_le_calcul_est_deterministe() -> None:
    premier = compute_exposure_window(0.0, 0.0, COTE_DROITE)
    second = compute_exposure_window(0.0, 0.0, COTE_DROITE)
    assert premier == second


def test_le_rayon_ne_traverse_pas_la_planete_a_l_antimeridien() -> None:
    """Sans coupe a 180 degres, ce rayon vers l'est croiserait tout l'hemisphere oppose."""
    # Le rayon part de 179 degres vers l'est : il franchit 180 et ressort a -176,5.
    # L'obstacle est a -179/-178, donc SUR le trajet reel, mais hors du segment
    # naif [-176,5 ; 179] qu'un shapely sans coupe verrait.
    obstacle = box(-179.0, -1.0, -178.0, 1.0)
    assert not ray_is_open(0.0, 179.0, 90.0, obstacle)
    assert ray_is_open(0.0, 179.0, 270.0, obstacle)  # vers l'ouest : rien avant 500 km


# --- widest_arc ---------------------------------------------------------------


def test_widest_arc_retient_la_plus_longue_plage_a_cheval_sur_zero() -> None:
    """Une plage qui enjambe l'index 0 doit etre vue d'un seul tenant."""
    pas = 90.0
    # Secteurs 270 et 0 ouverts, 90 et 180 fermes.
    fenetre = widest_arc([True, False, False, True], step_deg=pas)
    assert fenetre == (270.0, 360.0)
    assert in_arc(0.0, *fenetre)
    assert in_arc(270.0, *fenetre)
    assert not in_arc(90.0, *fenetre)


def test_widest_arc_sur_un_seul_secteur_est_degenere() -> None:
    assert widest_arc([False, True, False, False], step_deg=90.0) == (90.0, 90.0)


def test_widest_arc_refuse_une_taille_incoherente() -> None:
    with pytest.raises(ValueError, match="secteurs"):
        widest_arc([True, False], step_deg=90.0)


def test_cast_rays_est_aligne_sur_la_grille() -> None:
    triangle = Polygon([(-1.0, -1.0), (1.0, -1.0), (0.0, -0.2)])
    secteurs = cast_rays(0.0, 0.0, triangle)
    assert len(secteurs) == len(bearing_grid())
    assert secteurs[0] is True  # plein nord
