"""Ingestion Open-Meteo : houle, vent et fenêtre diurne, en un seul module.

    DIAGRAMME — flux d'ingestion (à vérifier dans tout commit modifiant ce fichier)

      data/spots.yaml (20 spots)
              |
              v
      +-------------------+   lot de 25 max        +----------------------+
      | pour chaque annee |----------------------->| QuotaLedger          |
      | 2022..2025        |   poids calcule AVANT  | (variables/10)       |
      +-------------------+   d'emettre            | x (jours/14)         |
              |                                    | x localisations      |
              |  <-------- pause auto si le -------| plafonds 600/min,    |
              |            plafond horaire         | 5000/h, 10000/j      |
              |            serait franchi          +----------------------+
              v
      +---------------------------+        +---------------------------+
      | marine-api /v1/marine     |        | archive-api /v1/archive   |
      | 7 variables horaires      |        | vent 10 m + sunrise/sunset|
      +---------------------------+        +---------------------------+
              |                                    |
              +----------------+-------------------+
                               v
              une reponse groupee -> ECLATEE par spot
                               v
      data/snapshots/openmeteo/hourly/{spot}/{annee}.parquet   <- COMMITE
      data/snapshots/openmeteo/daily /{spot}/{annee}.parquet   <- COMMITE
                               |
                               v
                   verify_cache_integrity()
                   8760 h par annee, 8784 en bissextile.
                   Toute anomalie ECHOUE en nommant le spot ET l'annee.

Le cache parquet n'est pas une optimisation, c'est un livrable : sans lui, la démo
publique ne fonctionne pas. Ne jamais le supprimer dans un script de nettoyage.

Un cache partiel est le mode de défaillance le plus dangereux du projet : le scoring
tournerait sur des données incomplètes et produirait un classement faux, plausible et
impossible à distinguer d'un classement correct. D'où `verify_cache_integrity()`, qui
échoue et ne se contente jamais d'un avertissement.
"""

import argparse
import calendar
import sys
import time
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from nalu.config import (
    ARCHIVE_URL,
    CONFIG,
    MARINE_HOURLY,
    MARINE_URL,
    MAX_LOCATIONS_PER_REQUEST,
    QUOTA_PER_DAY,
    QUOTA_PER_HOUR,
    QUOTA_PER_MINUTE,
    WEATHER_DAILY,
    WEATHER_HOURLY,
)
from nalu.net import use_system_trust_store
from nalu.paths import DATA
from nalu.spots import Spot, load_raw_spots

SNAPSHOT_DIR = DATA / "snapshots" / "openmeteo"
HTTP_CACHE = DATA / "raw" / "http_cache"

# Unite de pondération du quota : Open-Meteo facture par tranche de 10 variables et
# de 14 jours. Ces deux diviseurs viennent de sa documentation, pas d'un réglage.
VARIABLES_PAR_UNITE = 10
JOURS_PAR_UNITE = 14


def heures_attendues(annee: int) -> int:
    """8760 heures, 8784 les années bissextiles. Sert de contrat d'intégrité."""
    return (366 if calendar.isleap(annee) else 365) * 24


def jours_attendus(annee: int) -> int:
    return 366 if calendar.isleap(annee) else 365


def poids_requete(nb_variables: int, nb_jours: int, nb_localisations: int) -> float:
    """Poids pondéré d'une requête, selon la formule publiée par Open-Meteo.

    Grouper les spots divise le nombre d'allers-retours HTTP, **pas** le quota : le
    poids est multiplié par le nombre de localisations.
    """
    return (
        (nb_variables / VARIABLES_PAR_UNITE)
        * (nb_jours / JOURS_PAR_UNITE)
        * nb_localisations
    )


class QuotaDepasse(RuntimeError):
    """Le plafond journalier serait franchi. Attendre ne sert à rien, il faut reprendre demain."""


class QuotaLedger:
    """Compte le poids consommé et met en pause avant de franchir un plafond.

    Un remplissage à froid doit toujours se terminer en annonçant sa durée, jamais se
    faire couper sans explication.
    """

    def __init__(self, horloge=time.monotonic, dormir=time.sleep) -> None:
        self._horloge = horloge
        self._dormir = dormir
        self._entrees: list[tuple[float, float]] = []
        self.total = 0.0
        self.attente_totale = 0.0

    def _consomme_depuis(self, fenetre_s: float) -> float:
        limite = self._horloge() - fenetre_s
        return sum(poids for instant, poids in self._entrees if instant > limite)

    def _attente_pour(self, poids: float, fenetre_s: float, plafond: int) -> float:
        """Combien de temps attendre pour que `poids` tienne sous `plafond`."""
        maintenant = self._horloge()
        recents = sorted(
            (i, p) for i, p in self._entrees if i > maintenant - fenetre_s
        )
        cumul = sum(p for _, p in recents)
        if cumul + poids <= plafond:
            return 0.0
        # On laisse sortir les entrées les plus anciennes de la fenêtre, une à une,
        # jusqu'à ce que la place soit suffisante.
        for instant, p in recents:
            cumul -= p
            if cumul + poids <= plafond:
                return max(0.0, instant + fenetre_s - maintenant)
        return max(0.0, recents[-1][0] + fenetre_s - maintenant) if recents else 0.0

    def reserver(self, poids: float) -> float:
        """Attend si nécessaire, puis enregistre la consommation. Renvoie l'attente."""
        if poids > QUOTA_PER_HOUR:
            raise QuotaDepasse(
                f"une seule requête pèse {poids:.0f} unités, au-dessus du plafond "
                f"horaire de {QUOTA_PER_HOUR}. Réduire le lot ou la plage de dates."
            )
        if self._consomme_depuis(86_400) + poids > QUOTA_PER_DAY:
            raise QuotaDepasse(
                f"plafond journalier de {QUOTA_PER_DAY} unités atteint "
                f"({self.total:.0f} consommées). Reprendre demain : le cache déjà "
                "écrit sera conservé et l'ingestion repartira de là."
            )

        attente = max(
            self._attente_pour(poids, 60, QUOTA_PER_MINUTE),
            self._attente_pour(poids, 3600, QUOTA_PER_HOUR),
        )
        if attente > 0:
            print(f"    pause quota {attente:.0f} s (plafond horaire approché)")
            self._dormir(attente)
            self.attente_totale += attente

        self._entrees.append((self._horloge(), poids))
        self.total += poids
        return attente


def creer_client():
    """Client officiel Open-Meteo, avec cache HTTP et reprise sur erreur.

    Aucun client HTTP ni backoff maison : le transport FlatBuffers du client officiel
    se charge en zero-copy vers numpy, ce qui compte sur 700 000 lignes.
    """
    import openmeteo_requests
    import requests_cache
    from retry_requests import retry

    use_system_trust_store()
    HTTP_CACHE.parent.mkdir(parents=True, exist_ok=True)
    session = retry(
        requests_cache.CachedSession(str(HTTP_CACHE), expire_after=-1),
        retries=5,
        backoff_factor=2,
    )
    return openmeteo_requests.Client(session=session)


def _index_horaire(bloc) -> pl.Series:
    debut = datetime.fromtimestamp(bloc.Time(), tz=UTC)
    fin = datetime.fromtimestamp(bloc.TimeEnd(), tz=UTC)
    return pl.datetime_range(
        debut, fin, timedelta(seconds=bloc.Interval()), closed="left", eager=True
    ).alias("time")


def _trame_horaire(spot_id: str, reponse, variables: Sequence[str]) -> pl.DataFrame:
    bloc = reponse.Hourly()
    colonnes: dict[str, object] = {"time": _index_horaire(bloc)}
    for i, nom in enumerate(variables):
        colonnes[nom] = bloc.Variables(i).ValuesAsNumpy()
    trame = pl.DataFrame(colonnes)
    return trame.select(
        pl.lit(spot_id).alias("spot_id"),
        pl.col("time"),
        # NaN n'est PAS null en polars, et une moyenne sur NaN vaut NaN. Une donnée
        # absente doit rester absente, jamais devenir 0 ni contaminer un agrégat.
        *[pl.col(n).cast(pl.Float32).fill_nan(None) for n in variables],
    )


def _trame_journaliere(spot_id: str, reponse, variables: Sequence[str]) -> pl.DataFrame:
    bloc = reponse.Daily()
    debut = datetime.fromtimestamp(bloc.Time(), tz=UTC)
    fin = datetime.fromtimestamp(bloc.TimeEnd(), tz=UTC)
    dates = pl.datetime_range(
        debut, fin, timedelta(seconds=bloc.Interval()), closed="left", eager=True
    ).alias("date")
    colonnes: dict[str, object] = {"date": dates}
    for i, nom in enumerate(variables):
        horodatages = bloc.Variables(i).ValuesInt64AsNumpy()
        colonnes[nom] = pl.Series(nom, horodatages, dtype=pl.Int64)
    trame = pl.DataFrame(colonnes)
    return trame.select(
        pl.lit(spot_id).alias("spot_id"),
        pl.col("date"),
        # `sunrise` / `sunset` sont des instants UTC, servis en secondes Unix.
        *[
            pl.from_epoch(pl.col(n), time_unit="s").dt.replace_time_zone("UTC").alias(n)
            for n in variables
        ],
    )


def chemin_horaire(spot_id: str, annee: int, racine: Path = SNAPSHOT_DIR) -> Path:
    return racine / "hourly" / spot_id / f"{annee}.parquet"


def chemin_journalier(spot_id: str, annee: int, racine: Path = SNAPSHOT_DIR) -> Path:
    return racine / "daily" / spot_id / f"{annee}.parquet"


def _manquants(spots: Sequence[Spot], annee: int, racine: Path) -> list[Spot]:
    """Spots dont le cache de cette année est absent ou vide. Rend l'ingestion ré-entrante."""
    return [
        s
        for s in spots
        if not (
            chemin_horaire(s.id, annee, racine).exists()
            and chemin_horaire(s.id, annee, racine).stat().st_size > 0
            and chemin_journalier(s.id, annee, racine).exists()
            and chemin_journalier(s.id, annee, racine).stat().st_size > 0
        )
    ]


def _ecrire(trame: pl.DataFrame, chemin: Path) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    provisoire = chemin.with_suffix(".partiel")
    trame.write_parquet(provisoire, compression="zstd")
    provisoire.replace(chemin)


def ingerer(
    spots: Sequence[Spot] | None = None,
    annees: Iterable[int] | None = None,
    racine: Path = SNAPSHOT_DIR,
    client=None,
    ledger: QuotaLedger | None = None,
) -> tuple[int, QuotaLedger]:
    """Remplit le cache parquet. Ré-entrant : ce qui est déjà écrit n'est pas redemandé.

    Renvoie le nombre de requêtes réellement émises et le journal de quota.
    """
    spots = list(spots if spots is not None else load_raw_spots())
    annees = list(annees if annees is not None else CONFIG.years)
    ledger = ledger or QuotaLedger()
    requetes = 0

    for annee in annees:
        a_faire = _manquants(spots, annee, racine)
        if not a_faire:
            print(f"  {annee} : cache complet, aucun appel")
            continue

        debut, fin = f"{annee}-01-01", f"{annee}-12-31"
        nb_jours = jours_attendus(annee)

        for depart in range(0, len(a_faire), MAX_LOCATIONS_PER_REQUEST):
            lot = a_faire[depart : depart + MAX_LOCATIONS_PER_REQUEST]
            if client is None:
                client = creer_client()

            commun = {
                "latitude": [s.lat for s in lot],
                "longitude": [s.lon for s in lot],
                "start_date": debut,
                "end_date": fin,
                "timezone": "UTC",
            }

            poids = poids_requete(len(MARINE_HOURLY), nb_jours, len(lot))
            ledger.reserver(poids)
            print(f"  {annee} marine  : {len(lot)} spots, poids {poids:.0f}")
            marine = client.weather_api(
                MARINE_URL, params=commun | {"hourly": list(MARINE_HOURLY)}
            )
            requetes += 1

            poids = poids_requete(
                len(WEATHER_HOURLY) + len(WEATHER_DAILY), nb_jours, len(lot)
            )
            ledger.reserver(poids)
            print(f"  {annee} archive : {len(lot)} spots, poids {poids:.0f}")
            meteo = client.weather_api(
                ARCHIVE_URL,
                params=commun
                | {"hourly": list(WEATHER_HOURLY), "daily": list(WEATHER_DAILY)},
            )
            requetes += 1

            for spot, rep_marine, rep_meteo in zip(lot, marine, meteo, strict=True):
                horaire = _trame_horaire(spot.id, rep_marine, MARINE_HOURLY).join(
                    _trame_horaire(spot.id, rep_meteo, WEATHER_HOURLY).drop("spot_id"),
                    on="time",
                    how="left",
                )
                _ecrire(horaire, chemin_horaire(spot.id, annee, racine))
                _ecrire(
                    _trame_journaliere(spot.id, rep_meteo, WEATHER_DAILY),
                    chemin_journalier(spot.id, annee, racine),
                )

    return requetes, ledger


# ─── Intégrité du cache ────────────────────────────────────────────────────────


class CacheIncomplet(RuntimeError):
    """Le cache ne couvre pas ce qu'il prétend couvrir. Le scoring ne doit pas démarrer."""


def verify_cache_integrity(
    spots: Sequence[Spot] | None = None,
    annees: Iterable[int] | None = None,
    racine: Path = SNAPSHOT_DIR,
) -> None:
    """Échoue en nommant le spot ET l'année dès qu'une pièce manque ou est tronquée.

    À exécuter avant tout scoring. Un avertissement ne suffirait pas : il serait
    ignoré, et le classement produit serait faux sans que rien ne le signale.
    """
    spots = list(spots if spots is not None else load_raw_spots())
    annees = list(annees if annees is not None else CONFIG.years)

    anomalies: list[str] = []
    for spot in spots:
        for annee in annees:
            for chemin, attendu, quoi in (
                (chemin_horaire(spot.id, annee, racine), heures_attendues(annee), "heures"),
                (chemin_journalier(spot.id, annee, racine), jours_attendus(annee), "jours"),
            ):
                if not chemin.exists():
                    anomalies.append(f"{spot.id} {annee} : {quoi} — fichier absent ({chemin})")
                    continue
                lignes = pl.scan_parquet(chemin).select(pl.len()).collect().item()
                if lignes != attendu:
                    anomalies.append(
                        f"{spot.id} {annee} : {lignes} {quoi} au lieu de {attendu}"
                    )

    if anomalies:
        raise CacheIncomplet(
            f"cache incomplet, {len(anomalies)} anomalie(s) :\n  - "
            + "\n  - ".join(anomalies)
            + "\nRelancer `uv run python -m nalu.ingest.openmeteo` pour compléter."
        )


def rapport_nuls(
    spots: Sequence[Spot] | None = None,
    annees: Iterable[int] | None = None,
    racine: Path = SNAPSHOT_DIR,
) -> list[str]:
    """Colonnes dépassant le seuil d'alerte de nuls. Avertit, ne fait pas échouer."""
    spots = list(spots if spots is not None else load_raw_spots())
    annees = list(annees if annees is not None else CONFIG.years)

    alertes = []
    for spot in spots:
        for annee in annees:
            chemin = chemin_horaire(spot.id, annee, racine)
            if not chemin.exists():
                continue
            trame = pl.read_parquet(chemin)
            for colonne in trame.columns:
                if colonne in {"spot_id", "time"}:
                    continue
                part = trame[colonne].null_count() / len(trame)
                if part > CONFIG.null_alert_ratio:
                    alertes.append(f"{spot.id} {annee} {colonne} : {part:.1%} de nuls")
    return alertes


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description="Ingestion Open-Meteo")
    parseur.add_argument("--racine", type=Path, default=SNAPSHOT_DIR)
    parseur.add_argument("--verify-only", action="store_true")
    args = parseur.parse_args(argv)

    spots = load_raw_spots()
    annees = list(CONFIG.years)
    print(f"{len(spots)} spots x {len(annees)} années ({annees[0]}-{annees[-1]})")

    if not args.verify_only:
        depart = time.monotonic()
        requetes, ledger = ingerer(spots, annees, args.racine)
        duree = time.monotonic() - depart
        print(
            f"\n{requetes} requêtes émises, {ledger.total:.0f} unités de quota, "
            f"{duree:.0f} s dont {ledger.attente_totale:.0f} s de pause"
        )

    verify_cache_integrity(spots, annees, args.racine)
    print("intégrité du cache : OK")

    for alerte in rapport_nuls(spots, annees, args.racine):
        print(f"  AVERTISSEMENT {alerte}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
