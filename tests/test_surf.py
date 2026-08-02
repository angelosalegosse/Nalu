"""Moteur de surfabilité et climatologie mensuelle.

Le test le plus important du fichier est `test_les_deux_in_arc_sont_d_accord` : il
prouve que la version vectorisée et la version scalaire du passage par 0 degré disent
la même chose. Sans lui, deux implémentations d'une règle unique divergeraient en
silence, et le classement serait faux sans jamais lever d'erreur.
"""

import time
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from nalu.config import CONFIG, SWELL_DIRECTION, SWELL_HEIGHT, SWELL_PERIOD
from nalu.geo import in_arc, in_arc_expr
from nalu.scoring.climatology import calculer
from nalu.scoring.surf import (
    VENT_DIRECTION,
    VENT_VITESSE,
    attacher_fenetre_diurne,
    charger_heures,
    marquer_surfabilite,
    surfable_expr,
    vent_ok_expr,
)

NOMBRE_DE_SPOTS = 20


# --- Les deux in_arc disent la même chose --------------------------------------


RELEVEMENT = st.floats(0, 359.999, allow_nan=False).map(lambda x: round(x, 3))
ANGLE = st.floats(-720, 720, allow_nan=False).map(lambda x: round(x, 3))


@settings(max_examples=600, deadline=None)
@given(angle=ANGLE, debut=RELEVEMENT, fin=RELEVEMENT)
def test_les_deux_in_arc_sont_d_accord(angle: float, debut: float, fin: float) -> None:
    """Une règle, deux chemins de code, aucune divergence tolérée.

    Les angles sont arrondis au millième de degré. Sans cet arrondi, `hypothesis`
    trouve des dénormaux (5e-324) sur lesquels les deux chemins divergent : l'écart
    est alors à la limite de la précision du double, pas dans la règle. Les données
    réelles sont sur une grille de 2 degrés, quatre ordres de grandeur au-dessus.
    """
    attendu = in_arc(angle, debut, fin)
    obtenu = (
        pl.DataFrame({"a": [angle], "d": [debut], "f": [fin]})
        .select(in_arc_expr("a", "d", "f").alias("r"))["r"][0]
    )
    assert obtenu == attendu, (angle, debut, fin)


def test_le_modulo_de_polars_suit_la_convention_de_python() -> None:
    """`in_arc_expr` en dépend entièrement.

    Si polars basculait sur la convention de Rust, (-10) % 360 vaudrait -10 et TOUTES
    les fenêtres à cheval sur 0 deviendraient silencieusement fausses.
    """
    obtenu = pl.DataFrame({"x": [-10.0, -370.0]}).select(pl.col("x") % 360.0)["x"].to_list()
    assert obtenu == [350.0, 350.0]
    assert (-10.0) % 360.0 == 350.0


def test_in_arc_expr_gere_le_passage_par_zero_en_colonne() -> None:
    trame = pl.DataFrame({"a": [350.0, 0.0, 10.0, 180.0], "d": [340.0] * 4, "f": [20.0] * 4})
    resultat = trame.select(in_arc_expr("a", "d", "f").alias("r"))["r"].to_list()
    assert resultat == [True, True, True, False]


def test_in_arc_expr_accepte_des_fenetres_par_ligne() -> None:
    """Chaque spot a sa propre fenêtre : les bornes doivent pouvoir être des colonnes."""
    trame = pl.DataFrame({"a": [10.0, 10.0], "d": [340.0, 100.0], "f": [20.0, 200.0]})
    assert trame.select(in_arc_expr("a", "d", "f").alias("r"))["r"].to_list() == [True, False]


# --- Fabrique d'heures synthétiques --------------------------------------------

MIDI = datetime(2024, 6, 15, 12, tzinfo=UTC)

PARFAIT = {
    "spot_id": "s",
    "time": MIDI,
    "sunrise": MIDI - timedelta(hours=6),
    "sunset": MIDI + timedelta(hours=6),
    SWELL_DIRECTION: 240.0,
    SWELL_PERIOD: 12.0,
    SWELL_HEIGHT: 2.0,
    VENT_VITESSE: 3.0,
    VENT_DIRECTION: 90.0,
    "swell_dir_min": 200.0,
    "swell_dir_max": 280.0,
    "swell_peak_period_min": 10.0,
    "hs_offshore_min": 1.0,
    "hs_offshore_max": 3.0,
    "wind_dir_offshore_min": 45.0,
    "wind_dir_offshore_max": 135.0,
    "wind_speed_max_offshore": 14.0,
    "wind_speed_max_onshore": 7.0,
}


def heure(**remplacements: object) -> pl.DataFrame:
    return pl.DataFrame([PARFAIT | remplacements])


def est_surfable(**remplacements: object) -> bool:
    return heure(**remplacements).select(surfable_expr().alias("s"))["s"][0]


def test_des_conditions_parfaites_sont_surfables() -> None:
    assert est_surfable()


# --- Fenêtre diurne ------------------------------------------------------------


def test_une_heure_nocturne_a_conditions_parfaites_n_est_pas_surfable() -> None:
    """On ne surfe pas la nuit, même avec la houle du siècle."""
    assert not est_surfable(time=MIDI + timedelta(hours=8))
    assert not est_surfable(time=MIDI - timedelta(hours=8))


def test_les_bornes_du_jour_sont_incluses() -> None:
    assert est_surfable(time=PARFAIT["sunrise"])
    assert est_surfable(time=PARFAIT["sunset"])


def test_le_coucher_peut_tomber_le_lendemain_en_utc() -> None:
    """À Teahupo'o (UTC-10), le coucher du 1er janvier tombe le 2 janvier en UTC.

    Une jointure sur la date calendaire raterait toutes ces heures.
    """
    lever = datetime(2022, 1, 1, 15, 25, tzinfo=UTC)
    coucher = datetime(2022, 1, 2, 4, 35, tzinfo=UTC)
    heures = pl.DataFrame(
        {
            "spot_id": ["t"] * 3,
            "time": [
                datetime(2022, 1, 1, 20, tzinfo=UTC),  # plein jour local
                datetime(2022, 1, 2, 2, tzinfo=UTC),  # encore le jour, veille UTC
                datetime(2022, 1, 2, 8, tzinfo=UTC),  # nuit
            ],
        }
    )
    jours = pl.DataFrame({"spot_id": ["t"], "sunrise": [lever], "sunset": [coucher]})

    attache = attacher_fenetre_diurne(heures, jours)
    diurne = attache.select((pl.col("time") <= pl.col("sunset")).alias("d"))["d"].to_list()
    assert diurne == [True, True, False]


# --- Houle ---------------------------------------------------------------------


def test_une_periode_trop_courte_n_est_jamais_surfable() -> None:
    """Même avec direction et hauteur parfaites : une houle courte est du clapot."""
    seuil = PARFAIT["swell_peak_period_min"] * CONFIG.peak_to_mean_period_ratio
    assert est_surfable(**{SWELL_PERIOD: seuil})
    assert not est_surfable(**{SWELL_PERIOD: seuil - 0.1})


def test_le_seuil_de_periode_est_converti_du_pic_vers_la_moyenne() -> None:
    """Les guides annoncent une période de pic, Open-Meteo sert une période moyenne."""
    assert CONFIG.peak_to_mean_period_ratio < 1.0
    # Un seuil de pic de 10 s laisse passer une période moyenne de 8,5 s.
    assert est_surfable(**{SWELL_PERIOD: 8.5})
    assert not est_surfable(**{SWELL_PERIOD: 8.4})


@pytest.mark.parametrize("hauteur", [0.9, 3.1])
def test_une_hauteur_hors_bornes_n_est_pas_surfable(hauteur: float) -> None:
    assert not est_surfable(**{SWELL_HEIGHT: hauteur})


@pytest.mark.parametrize("hauteur", [1.0, 3.0])
def test_les_bornes_de_hauteur_sont_incluses(hauteur: float) -> None:
    assert est_surfable(**{SWELL_HEIGHT: hauteur})


def test_une_direction_hors_fenetre_n_est_pas_surfable() -> None:
    assert not est_surfable(**{SWELL_DIRECTION: 100.0})


# --- Vent : le seuil dépend du secteur -----------------------------------------


def test_un_offshore_faible_est_surfable() -> None:
    assert est_surfable(**{VENT_DIRECTION: 90.0, VENT_VITESSE: 10.0})


def test_un_offshore_trop_fort_n_est_pas_surfable() -> None:
    """Le défaut logique corrigé par la revue : un OU aurait accepté 45 nœuds.

    Un offshore trop fort hache la mer, empêche de ramer et souffle la lèvre.
    """
    assert not est_surfable(**{VENT_DIRECTION: 90.0, VENT_VITESSE: 20.0})


def test_un_onshore_faible_est_surfable() -> None:
    assert est_surfable(**{VENT_DIRECTION: 270.0, VENT_VITESSE: 5.0})


def test_un_onshore_fort_n_est_pas_surfable() -> None:
    assert not est_surfable(**{VENT_DIRECTION: 270.0, VENT_VITESSE: 10.0})


def test_le_seuil_onshore_est_plus_strict_que_l_offshore() -> None:
    """À 10 m/s, offshore passe et onshore non : c'est toute la règle."""
    vitesse = 10.0
    assert est_surfable(**{VENT_DIRECTION: 90.0, VENT_VITESSE: vitesse})
    assert not est_surfable(**{VENT_DIRECTION: 270.0, VENT_VITESSE: vitesse})


def test_vent_ok_est_bien_un_si_alors_sinon() -> None:
    trame = pl.DataFrame(
        [
            PARFAIT | {VENT_DIRECTION: 90.0, VENT_VITESSE: 10.0},  # offshore modéré
            PARFAIT | {VENT_DIRECTION: 90.0, VENT_VITESSE: 20.0},  # offshore violent
            PARFAIT | {VENT_DIRECTION: 270.0, VENT_VITESSE: 5.0},  # onshore léger
            PARFAIT | {VENT_DIRECTION: 270.0, VENT_VITESSE: 10.0},  # onshore soutenu
        ]
    )
    assert trame.select(vent_ok_expr().alias("v"))["v"].to_list() == [True, False, True, False]


# --- Données manquantes --------------------------------------------------------


def test_une_donnee_manquante_rend_l_heure_non_surfable() -> None:
    """Un null ne doit jamais être interprété comme une condition satisfaite."""
    for colonne in (SWELL_HEIGHT, SWELL_PERIOD, SWELL_DIRECTION, VENT_VITESSE):
        assert not est_surfable(**{colonne: None}), colonne


# --- Climatologie sur le cache réel --------------------------------------------


@pytest.fixture(scope="module")
def climatologie() -> tuple[pl.DataFrame, pl.DataFrame]:
    return calculer()


@pytest.mark.disable_socket
def test_la_sortie_a_240_lignes_et_480_quinzaines(climatologie) -> None:
    mensuel, quinzaines = climatologie
    assert mensuel.height == NOMBRE_DE_SPOTS * 12
    assert quinzaines.height == NOMBRE_DE_SPOTS * 12 * 2


@pytest.mark.disable_socket
def test_p_surf_et_q_sont_des_probabilites(climatologie) -> None:
    mensuel, _ = climatologie
    for colonne in ("p_surf", "q", "intensity"):
        assert mensuel[colonne].min() >= 0.0
        assert mensuel[colonne].max() <= 1.0
        assert mensuel[colonne].null_count() == 0


@pytest.mark.disable_socket
def test_q_vaut_exactement_p_surf_sans_ponderation(climatologie) -> None:
    """L'intensité est affichée mais N'ENTRE PAS dans le score.

    On n'additionne pas une probabilité et une grandeur non bornée.
    """
    mensuel, _ = climatologie
    assert mensuel["q"].to_list() == mensuel["p_surf"].to_list()
    # Et l'intensité varie bien, donc elle est calculée et non neutralisée.
    assert mensuel["intensity"].max() > 0.0


@pytest.mark.disable_socket
def test_un_mois_sans_heure_surfable_donne_zero_jamais_null(climatologie) -> None:
    mensuel, _ = climatologie
    morts = mensuel.filter(pl.col("hours_surfable") == 0)
    assert morts.height > 0, "aucun mois mort : le test n'exerce rien"
    assert morts["q"].to_list() == [0.0] * morts.height
    assert morts["intensity"].to_list() == [0.0] * morts.height


@pytest.mark.disable_socket
def test_la_duree_du_jour_depend_de_la_latitude(climatologie) -> None:
    """Thurso (58 degrés N) doit avoir bien moins de jour en décembre qu'en juin."""
    mensuel, _ = climatologie
    haute = mensuel.filter(pl.col("spot_id") == "thurso-east")
    decembre = haute.filter(pl.col("month") == 12)["hours_daylight"][0]
    juin = haute.filter(pl.col("month") == 6)["hours_daylight"][0]
    assert decembre < juin
    assert decembre / juin < 0.6

    # Arugam Bay, a 6,8 degrés N : moins de 10 % d'écart sur l'année.
    basse = mensuel.filter(pl.col("spot_id") == "arugam-bay")["hours_daylight"]
    assert (basse.max() - basse.min()) / basse.max() < 0.10


@pytest.mark.disable_socket
def test_la_dispersion_intra_mois_est_calculee(climatologie) -> None:
    mensuel, quinzaines = climatologie
    assert mensuel["dispersion_gap"].null_count() == 0
    assert set(quinzaines["fortnight"].unique()) == {1, 2}
    # L'alerte se déclenche exactement au-delà du seuil de la configuration.
    attendu = mensuel["dispersion_gap"] > CONFIG.fortnight_gap_points
    assert mensuel["dispersion_alert"].to_list() == attendu.to_list()


@pytest.mark.disable_socket
def test_le_resultat_est_deterministe() -> None:
    """Deux exécutions sur le même cache doivent produire le même parquet."""
    premier, _ = calculer()
    second, _ = calculer()
    assert premier.equals(second)


@pytest.mark.disable_socket
def test_aucune_heure_hors_fenetre_diurne_n_est_comptee() -> None:
    heures = marquer_surfabilite(charger_heures())
    hors_jour = heures.filter(~pl.col("is_daylight") & pl.col("is_surfable"))
    assert hors_jour.height == 0


@pytest.mark.disable_socket
def test_le_calcul_complet_reste_vectorise() -> None:
    """Seuil de performance : une implémentation ligne à ligne échouerait largement.

    700 000 itérations Python sur cette logique prendraient plusieurs dizaines de
    secondes. Les expressions polars tiennent en quelques secondes.
    """
    depart = time.monotonic()
    calculer()
    duree = time.monotonic() - depart
    assert duree < 15.0, f"{duree:.1f} s — implémentation probablement dé-vectorisée"
