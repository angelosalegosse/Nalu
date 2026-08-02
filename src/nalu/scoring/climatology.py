"""Climatologie mensuelle : 700 000 heures deviennent 240 probabilités.

    DIAGRAMME — agrégation (à vérifier dans tout commit modifiant ce fichier)

    701 280 heures (20 spots x 4 ans)
              |
              |  surf.py : is_daylight, is_surfable
              v
    +--------------------------------+   +--------------------------------+
    | groupe (spot, mois)            |   | groupe (spot, mois, quinzaine) |
    |                                |   |  quinzaine 1 : jours 1 a 15    |
    | P_surf = surfables / diurnes   |   |  quinzaine 2 : jours 16 a fin  |
    +--------------------------------+   +--------------------------------+
              |                                        |
              |  240 lignes                            |  480 lignes
              |  (20 spots x 12 mois)                  |
              +---------------- ecart ------------------+
                                  |
                                  v
                    ecart > `fortnight_gap_points` ?
                    -> `dispersion_alert` = vrai

    Un mois moyen a 40 % peut cacher 70 % puis 10 %. Quelqu'un qui pose la seconde
    quinzaine tombe alors sur un spot mort, et la moyenne mensuelle ne l'aura pas
    averti. C'est la raison d'etre de la seconde sortie.

`Q(s,m) = P_surf(s,m)` — une PROBABILITÉ PURE, sans pondération. L'intensité est
calculée et affichée mais **n'entre pas dans le score** : on n'additionne pas une
probabilité et une grandeur non bornée.
"""

import sys
from pathlib import Path

import polars as pl

from nalu.config import CONFIG, SWELL_HEIGHT
from nalu.ingest.openmeteo import SNAPSHOT_DIR, verify_cache_integrity
from nalu.paths import DATA
from nalu.scoring.surf import charger_heures, marquer_surfabilite

SCORES_DIR = DATA / "scores"
CLIMATOLOGIE_PATH = SCORES_DIR / "climatology.parquet"
QUINZAINES_PATH = SCORES_DIR / "fortnights.parquet"

JOUR_DE_BASCULE = 15
"""Frontière des deux quinzaines. Un mois se coupe au 15 : ce n'est pas un paramètre du
modèle mais la définition même de « quinzaine », d'où sa place ici et non dans config."""


def _agregats() -> list[pl.Expr]:
    return [
        pl.col("is_daylight").sum().alias("hours_daylight"),
        pl.col("is_surfable").sum().alias("hours_surfable"),
        # Hauteur moyenne sur les SEULES heures surfables : la moyenne de tout
        # mélangerait les heures où le spot ne marche pas.
        pl.when(pl.col("is_surfable"))
        .then(pl.col(SWELL_HEIGHT))
        .mean()
        .alias("mean_swell_height"),
    ]


def _p_surf() -> pl.Expr:
    """Heures surfables sur heures diurnes. Zéro heure diurne donne 0, jamais null."""
    return (
        pl.when(pl.col("hours_daylight") > 0)
        .then(pl.col("hours_surfable") / pl.col("hours_daylight"))
        .otherwise(0.0)
        .alias("p_surf")
    )


def _intensite(spots: pl.DataFrame) -> pl.Expr:
    """Hauteur moyenne ramenée sur [hs_offshore_min, hs_offshore_max] du spot.

    Colonne INFORMATIVE. Elle n'entre pas dans le score, et le test le vérifie.
    """
    del spots  # les seuils arrivent par jointure, la signature documente la dépendance
    etendue = pl.col("hs_offshore_max") - pl.col("hs_offshore_min")
    return (
        pl.when(pl.col("mean_swell_height").is_null() | (etendue <= 0))
        .then(0.0)
        .otherwise(
            ((pl.col("mean_swell_height") - pl.col("hs_offshore_min")) / etendue).clip(0.0, 1.0)
        )
        .alias("intensity")
    )


def calculer(heures: pl.DataFrame | None = None) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Renvoie (climatologie mensuelle, quinzaines). Aucune boucle, que des expressions."""
    from nalu.scoring.surf import table_des_spots
    from nalu.spots import load_spots

    heures = marquer_surfabilite(heures if heures is not None else charger_heures())
    seuils = table_des_spots(load_spots()).select(
        "spot_id", "hs_offshore_min", "hs_offshore_max"
    )

    marque = heures.with_columns(
        pl.col("time").dt.month().alias("month"),
        pl.when(pl.col("time").dt.day() <= JOUR_DE_BASCULE)
        .then(1)
        .otherwise(2)
        .alias("fortnight"),
    )

    mensuel = (
        marque.group_by("spot_id", "month")
        .agg(_agregats())
        .join(seuils, on="spot_id", how="left")
        .with_columns(_p_surf())
        .with_columns(_intensite(seuils))
        .with_columns(pl.col("p_surf").alias("q"))
        .select(
            "spot_id",
            "month",
            "p_surf",
            "q",
            "intensity",
            "hours_surfable",
            "hours_daylight",
        )
        .sort("spot_id", "month")
    )

    quinzaines = (
        marque.group_by("spot_id", "month", "fortnight")
        .agg(_agregats())
        .with_columns(_p_surf())
        .select("spot_id", "month", "fortnight", "p_surf", "hours_surfable", "hours_daylight")
        .sort("spot_id", "month", "fortnight")
    )

    ecarts = (
        quinzaines.pivot(on="fortnight", index=["spot_id", "month"], values="p_surf")
        .rename({"1": "p_surf_q1", "2": "p_surf_q2"})
        .with_columns(
            ((pl.col("p_surf_q1") - pl.col("p_surf_q2")).abs() * 100).alias("dispersion_gap")
        )
        .with_columns(
            (pl.col("dispersion_gap") > CONFIG.fortnight_gap_points).alias("dispersion_alert")
        )
        .select("spot_id", "month", "dispersion_gap", "dispersion_alert")
    )

    return mensuel.join(ecarts, on=["spot_id", "month"], how="left"), quinzaines


def ecrire(mensuel: pl.DataFrame, quinzaines: pl.DataFrame, racine: Path = SCORES_DIR) -> None:
    racine.mkdir(parents=True, exist_ok=True)
    for trame, chemin in (
        (mensuel, racine / CLIMATOLOGIE_PATH.name),
        (quinzaines, racine / QUINZAINES_PATH.name),
    ):
        provisoire = chemin.with_suffix(".partiel")
        trame.write_parquet(provisoire, compression="zstd")
        provisoire.replace(chemin)


def main(argv: list[str] | None = None) -> int:
    del argv
    # Un cache partiel produirait un classement faux et parfaitement plausible.
    verify_cache_integrity()
    print(f"cache vérifié — {SNAPSHOT_DIR}")

    mensuel, quinzaines = calculer()
    ecrire(mensuel, quinzaines)

    alertes = mensuel.filter("dispersion_alert")
    print(f"{mensuel.height} lignes mensuelles, {quinzaines.height} lignes de quinzaine")
    print(f"p_surf de {mensuel['p_surf'].min():.3f} à {mensuel['p_surf'].max():.3f}")
    print(f"{alertes.height} mois signalés en dispersion intra-mois")

    print("\nMeilleur mois par spot :")
    meilleurs = (
        mensuel.sort("p_surf", descending=True)
        .group_by("spot_id")
        .first()
        .sort("p_surf", descending=True)
    )
    for ligne in meilleurs.iter_rows(named=True):
        print(
            f"  {ligne['spot_id']:<24} mois {ligne['month']:>2}  "
            f"p_surf {ligne['p_surf']:.3f}  intensité {ligne['intensity']:.2f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
