"""Score combiné : croiser la qualité de houle et le prix du billet.

    DIAGRAMME — des 240 couples au score alpha (à vérifier dans tout commit)

    climatology.parquet            flights_AAAA-MM-JJ.parquet
    240 lignes (20 spots x 12 mois)   240 lignes (20 IATA x 12 mois)
              |                                  |
              |  Q = P_surf                      |  price_eur, parfois null
              v                                  v
              +----------------+-----------------+
                               |  jointure spot -> aeroport, mois -> mois
                               v
                    240 couples spot x mois
                               |
              +----------------+-----------------+
              v                                  v
      rang_centile(Q)                    rang_centile(-prix)
      sur les 240 couples                sur les 240 couples
      1 = meilleure houle                1 = billet le moins cher
              |                                  |   spot sans prix -> rang 0,
              +----------------+-----------------+   AFFICHE et marque
                               v
        Score = a * rang(Q) + (1-a) * rang(-prix)
                               |
              a = 1 -----------+----------- a = 0
        la meilleure vague           le billet le moins cher

**Rangs centiles, JAMAIS de normalisation min-max.** Un seul billet à 1 800 €
tassait tous les autres dans les quinze derniers pourcents et rendait le curseur
inerte sur la moitié de sa course. Le rang est insensible aux extrêmes par
construction, et rend commensurables une probabilité et un prix en euros — deux
grandeurs qu'on ne peut pas additionner autrement.

Les rangs sont calculés UNE FOIS. Déplacer le curseur ne fait plus qu'une
combinaison linéaire en mémoire : aucun appel réseau, aucune relecture de parquet.
"""

from datetime import date
from pathlib import Path

import polars as pl

from nalu.ingest.flights import SnapshotSource, dernier_snapshot, mois_horizon
from nalu.scoring.climatology import CLIMATOLOGIE_PATH
from nalu.spots import load_spots

RANG_SANS_PRIX = 0.0
"""Un spot sans prix reçoit le rang le plus bas. Il n'est pas retiré : le faire
laisserait le biais de couverture décider du contenu du produit."""


def rang_centile(colonne: str, descendant: bool = False) -> pl.Expr:
    """Rang centile dans [0, 1] sur toute la colonne, ex aequo au rang moyen.

    `descendant=True` donne le rang le plus élevé à la plus PETITE valeur : c'est ce
    qu'on veut pour le prix, où le moins cher doit être le mieux classé.
    """
    rang = pl.col(colonne).rank(method="average", descending=descendant)
    valides = pl.col(colonne).is_not_null().sum()
    centile = pl.when(valides > 1).then((rang - 1) / (valides - 1)).otherwise(1.0)
    # Une valeur absente garde un rang ABSENT. La remplacer ici par 1.0 donnerait le
    # meilleur rang possible a un spot dont on ignore le prix : c'est l'appelant qui
    # decide quoi en faire, explicitement, via `RANG_SANS_PRIX`.
    return pl.when(pl.col(colonne).is_null()).then(None).otherwise(centile)


def table_prix(chemin: Path | None = None) -> pl.DataFrame:
    """Les prix du snapshot, ramenés au mois calendaire 1-12.

    L'horizon de 12 mois contient chaque mois calendaire exactement une fois, ce qui
    rend la correspondance non ambiguë.
    """
    source = SnapshotSource(chemin) if chemin else SnapshotSource()
    destinations = sorted({r.spot.airport_iata for r in load_spots()})
    reference = source.chemin.stem.removeprefix("flights_") if source.chemin else None
    depart = date.fromisoformat(reference) if reference else None

    prix = source.monthly_prices(destinations, mois_horizon(depart))
    return prix.select(
        "airport_iata",
        pl.col("month").dt.month().alias("month"),
        "price_eur",
        "collected_at",
    )


def table_spots() -> pl.DataFrame:
    resolus = load_spots()
    return pl.DataFrame(
        {
            "spot_id": [r.id for r in resolus],
            "name": [r.spot.name for r in resolus],
            "country": [r.spot.country for r in resolus],
            "lat": [r.spot.lat for r in resolus],
            "lon": [r.spot.lon for r in resolus],
            "airport_iata": [r.spot.airport_iata for r in resolus],
            "level": [str(r.spot.level) for r in resolus],
            "bottom": [str(r.spot.bottom) for r in resolus],
            "confidence": [str(r.spot.confidence) for r in resolus],
            "source": [r.spot.source for r in resolus],
        }
    )


def construire_tableau(
    climatologie: pl.DataFrame | None = None,
    prix: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Les 240 couples, rangs compris. Tout ce que le curseur consommera est ici."""
    climatologie = (
        climatologie if climatologie is not None else pl.read_parquet(CLIMATOLOGIE_PATH)
    )
    prix = prix if prix is not None else table_prix()

    tableau = (
        climatologie.join(table_spots(), on="spot_id", how="left")
        .join(prix, on=["airport_iata", "month"], how="left")
        .with_columns(
            rang_centile("q").alias("rank_q"),
            # `descending=True` : le billet le moins cher obtient le rang 1.
            rang_centile("price_eur", descendant=True).alias("rank_price"),
        )
        .with_columns(
            pl.col("rank_price").fill_null(RANG_SANS_PRIX),
            pl.col("price_eur").is_null().alias("price_missing"),
        )
    )
    return tableau.sort("spot_id", "month")


def appliquer_alpha(tableau: pl.DataFrame, alpha: float) -> pl.DataFrame:
    """Combinaison linéaire des deux rangs. C'est TOUT ce que fait le curseur.

    `alpha = 1` : la meilleure vague. `alpha = 0` : le billet le moins cher.
    """
    if not 0.0 <= alpha <= 1.0:
        raise ValueError(f"alpha doit rester dans [0, 1], reçu {alpha}")
    return tableau.with_columns(
        (alpha * pl.col("rank_q") + (1.0 - alpha) * pl.col("rank_price")).alias("score")
    )


def classement(tableau: pl.DataFrame, mois: int, alpha: float) -> pl.DataFrame:
    """Le classement d'un mois donné, du meilleur au moins bon."""
    return (
        appliquer_alpha(tableau.filter(pl.col("month") == mois), alpha)
        .sort("score", descending=True)
        .with_row_index("rang", offset=1)
    )


def fraicheur_du_snapshot(chemin: Path | None = None) -> tuple[date | None, int]:
    """Date de collecte des prix et nombre de jours écoulés.

    Personne ne lit les journaux sur une instance publique : si les prix datent,
    l'interface doit le dire elle-même.
    """
    chemin = chemin or dernier_snapshot()
    if chemin is None:
        return None, -1
    jour = date.fromisoformat(chemin.stem.removeprefix("flights_"))
    return jour, (date.today() - jour).days
