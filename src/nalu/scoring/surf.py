"""Surfabilité horaire : confronter la houle du large à ce qu'un spot sait en faire.

    DIAGRAMME — arbre de décision (à vérifier dans tout commit modifiant ce fichier)

    une heure h, un spot s
            |
            v
    +---------------------------------------------+
    | h est-elle entre le lever et le coucher ?    |  join_asof sur le lever :
    | (fenetre reelle, en UTC)                     |  a Teahupo'o le coucher tombe
    +---------------------------------------------+  le LENDEMAIN en UTC
        non -> NON SURFABLE            oui
                                        |
    +---------------------------------------------+
    | swell_wave_direction dans la fenetre du spot |  in_arc(), passage par 0 degre
    +---------------------------------------------+
        non -> NON SURFABLE            oui
                                        |
    +---------------------------------------------+
    | swell_wave_period >= swell_period_min        |  une houle courte est du clapot
    +---------------------------------------------+
        non -> NON SURFABLE            oui
                                        |
    +---------------------------------------------+
    | hs_offshore_min <= swell_wave_height         |  hauteur SIGNIFICATIVE AU LARGE,
    |                 <= hs_offshore_max           |  pas une taille de vague au pic
    +---------------------------------------------+
        non -> NON SURFABLE            oui
                                        |
    +---------------------------------------------+
    | vent_ok :                                    |
    |   SI direction dans secteur offshore         |
    |      ALORS vitesse < max_offshore            |  JAMAIS un OU : un offshore de
    |      SINON vitesse < max_onshore             |  45 noeuds est insurfable
    +---------------------------------------------+
        non -> NON SURFABLE            oui -> SURFABLE

**Aucune boucle ligne à ligne.** Tout est expression polars, vérifié par un test de
performance qui échouerait sur une implémentation naïve.

`in_arc` n'est pas réimplémenté ici : il est importé de `nalu.geo`, unique lieu de la
règle du passage par 0 degré.
"""

from pathlib import Path

import polars as pl

from nalu.config import CONFIG, SWELL_DIRECTION, SWELL_HEIGHT, SWELL_PERIOD
from nalu.geo import in_arc_expr
from nalu.ingest.openmeteo import SNAPSHOT_DIR
from nalu.spots import SpotResolu, load_spots

HORAIRE_GLOB = "hourly/**/*.parquet"
JOURNALIER_GLOB = "daily/**/*.parquet"

VENT_VITESSE = "wind_speed_10m"
VENT_DIRECTION = "wind_direction_10m"


def table_des_spots(spots: list[SpotResolu]) -> pl.DataFrame:
    """Les seuils du référentiel, mis à plat pour une jointure sur `spot_id`.

    Passer par une table plutôt que par un dictionnaire de constantes est ce qui rend
    le calcul vectorisé : chaque ligne horaire porte les seuils de son spot.
    """
    return pl.DataFrame(
        {
            "spot_id": [r.id for r in spots],
            "swell_dir_min": [r.swell_dir_min for r in spots],
            "swell_dir_max": [r.swell_dir_max for r in spots],
            "swell_peak_period_min": [r.spot.swell_peak_period_min for r in spots],
            "hs_offshore_min": [r.spot.hs_offshore_min for r in spots],
            "hs_offshore_max": [r.spot.hs_offshore_max for r in spots],
            "wind_dir_offshore_min": [r.spot.wind_dir_offshore_min for r in spots],
            "wind_dir_offshore_max": [r.spot.wind_dir_offshore_max for r in spots],
            "wind_speed_max_offshore": [r.spot.wind_speed_max_offshore for r in spots],
            "wind_speed_max_onshore": [r.spot.wind_speed_max_onshore for r in spots],
        },
        schema_overrides={"spot_id": pl.String},
    )


def est_diurne_expr() -> pl.Expr:
    """L'heure tombe dans la fenêtre diurne réelle du spot.

    Les DEUX bornes sont testées. Le `join_asof` sur le lever garantit déjà que le
    lever précède l'heure, mais s'appuyer sur cette garantie créerait un couplage
    invisible : toute autre façon de construire la trame compterait alors les heures
    d'avant l'aube comme diurnes. Le test l'a trouvé, la borne reste explicite.
    """
    return (
        pl.col("sunrise").is_not_null()
        & pl.col("sunset").is_not_null()
        & (pl.col("time") >= pl.col("sunrise"))
        & (pl.col("time") <= pl.col("sunset"))
    )


def vent_ok_expr() -> pl.Expr:
    """Seuil de vent DÉPENDANT DU SECTEUR, jamais un OU.

    Un OU déclarerait surfable un vent offshore de 45 nœuds : il hache la mer, empêche
    de ramer et souffle la lèvre. Le seuil offshore vaut environ le double du onshore,
    ce qui traduit qu'un offshore modéré améliore la vague quand un onshore la détruit.
    """
    offshore = in_arc_expr(
        VENT_DIRECTION, "wind_dir_offshore_min", "wind_dir_offshore_max"
    )
    return (
        pl.when(offshore)
        .then(pl.col(VENT_VITESSE) < pl.col("wind_speed_max_offshore"))
        .otherwise(pl.col(VENT_VITESSE) < pl.col("wind_speed_max_onshore"))
    )


def seuil_periode_moyenne_expr() -> pl.Expr:
    """Convertit le seuil de période DE PIC du référentiel en période MOYENNE.

    Open-Meteo ne sert que la période moyenne : `swell_wave_peak_period` est vide,
    vérifié le 2026-08-02. Comparer un seuil de pic à une période moyenne rend un spot
    artificiellement mort — aux Maldives, aucune heure ne passait un seuil de 13 s
    alors que la période moyenne y plafonne à 8,4 s au neuvième décile.
    """
    return pl.col("swell_peak_period_min") * CONFIG.peak_to_mean_period_ratio


def surfable_expr() -> pl.Expr:
    """La conjonction complète. Toute donnée manquante rend l'heure non surfable."""
    return (
        est_diurne_expr()
        & in_arc_expr(SWELL_DIRECTION, "swell_dir_min", "swell_dir_max")
        & (pl.col(SWELL_PERIOD) >= seuil_periode_moyenne_expr())
        & (pl.col(SWELL_HEIGHT) >= pl.col("hs_offshore_min"))
        & (pl.col(SWELL_HEIGHT) <= pl.col("hs_offshore_max"))
        & vent_ok_expr()
    ).fill_null(False)


def attacher_fenetre_diurne(heures: pl.DataFrame, jours: pl.DataFrame) -> pl.DataFrame:
    """Rattache chaque heure au lever de soleil qui la précède, par spot.

    Une jointure sur la date calendaire serait FAUSSE : à Teahupo'o (UTC-10), le
    coucher du 1er janvier tombe le 2 janvier en UTC. `join_asof` en arrière sur le
    lever règle le cas sans exception ni découpage manuel.
    """
    return heures.sort("spot_id", "time").join_asof(
        jours.select("spot_id", "sunrise", "sunset").sort("spot_id", "sunrise"),
        left_on="time",
        right_on="sunrise",
        by="spot_id",
        strategy="backward",
    )


def charger_heures(racine: Path = SNAPSHOT_DIR) -> pl.DataFrame:
    """Le cache horaire complet, fenêtre diurne et seuils du spot attachés."""
    heures = pl.read_parquet(racine / HORAIRE_GLOB)
    jours = pl.read_parquet(racine / JOURNALIER_GLOB)
    return attacher_fenetre_diurne(heures, jours).join(
        table_des_spots(load_spots()), on="spot_id", how="left"
    )


def marquer_surfabilite(heures: pl.DataFrame) -> pl.DataFrame:
    """Ajoute `is_daylight` et `is_surfable`. Ne réduit rien, n'agrège rien."""
    return heures.with_columns(
        est_diurne_expr().fill_null(False).alias("is_daylight"),
        surfable_expr().alias("is_surfable"),
    )
