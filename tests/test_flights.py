"""Sources de prix : protocole, repli, et sonde de couverture.

Aucun test ne touche le réseau. Le repli est la propriété la plus importante ici :
sans lui, une panne de Travelpayouts casserait une démo devant un client.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from nalu.config import CONFIG
from nalu.ingest.flights import (
    SCHEMA,
    BasculeError,
    Couverture,
    SnapshotSource,
    SourceAvecRepli,
    TravelpayoutsSource,
    chemin_snapshot,
    collect,
    dernier_snapshot,
    mois_horizon,
    probe,
    spearman,
    trame_vide,
)

MOIS = [date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1)]
DESTINATIONS = ["DPS", "TRU"]


class SourceFactice:
    """Implémentation minimale du protocole, pour la substitution."""

    def __init__(self, prix: dict[tuple[str, date], float] | None = None, nom: str = "factice"):
        self.prix = prix or {}
        self.nom = nom
        self.appels = 0

    def monthly_prices(self, destinations: list[str], mois: list[date]) -> pl.DataFrame:
        self.appels += 1
        trame = trame_vide(destinations, mois, datetime(2026, 8, 2, tzinfo=UTC))
        return trame.with_columns(
            pl.struct("airport_iata", "month")
            .map_elements(
                lambda s: self.prix.get((s["airport_iata"], s["month"])),
                return_dtype=pl.Float64,
            )
            .alias("price_eur")
        )


class SourceQuiEchoue:
    nom = "live-en-panne"

    def __init__(self, erreur: Exception) -> None:
        self.erreur = erreur

    def monthly_prices(self, destinations: list[str], mois: list[date]) -> pl.DataFrame:
        raise self.erreur


# --- Squelette : aucune destination ne disparaît -------------------------------


def test_le_squelette_couvre_toutes_les_paires() -> None:
    trame = trame_vide(DESTINATIONS, MOIS, datetime(2026, 8, 2, tzinfo=UTC))
    assert trame.height == len(DESTINATIONS) * len(MOIS)
    assert dict(trame.schema) == SCHEMA


def test_une_destination_sans_prix_est_presente_avec_null_pas_absente() -> None:
    """Un spot absent du jeu de données disparaîtrait silencieusement du classement."""
    source = SourceFactice({("DPS", MOIS[0]): 710.0})
    trame = source.monthly_prices(DESTINATIONS, MOIS)

    assert set(trame["airport_iata"].unique()) == set(DESTINATIONS)
    tru = trame.filter(pl.col("airport_iata") == "TRU")
    assert tru.height == len(MOIS)
    assert tru["price_eur"].null_count() == len(MOIS)
    assert 0.0 not in tru["price_eur"].to_list()


# --- Substitution des implémentations du protocole -----------------------------


def test_les_deux_implementations_sont_substituables(tmp_path: Path) -> None:
    """Changer de fournisseur doit coûter un fichier, pas une refonte."""
    attendu = {("DPS", MOIS[0]): 710.0}
    live = SourceFactice(attendu, nom="live")
    trame, chemin = collect(DESTINATIONS, live, MOIS, tmp_path / "flights_2026-08-02.parquet")

    snapshot = SnapshotSource(chemin)
    relu = snapshot.monthly_prices(DESTINATIONS, MOIS)

    assert relu.sort("airport_iata", "month")["price_eur"].to_list() == (
        trame.sort("airport_iata", "month")["price_eur"].to_list()
    )
    assert dict(relu.schema) == SCHEMA


# --- Repli ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "erreur",
    [
        BasculeError("HTTP 401 : jeton refusé"),
        BasculeError("HTTP 503 : Travelpayouts indisponible"),
        RuntimeError("réseau coupé"),
    ],
)
def test_le_repli_se_declenche_et_avertit(erreur: Exception, tmp_path: Path) -> None:
    _, chemin = collect(
        DESTINATIONS,
        SourceFactice({("DPS", MOIS[0]): 710.0}),
        MOIS,
        tmp_path / "flights_2026-08-02.parquet",
    )
    source = SourceAvecRepli(SourceQuiEchoue(erreur), SnapshotSource(chemin))

    trame = source.monthly_prices(DESTINATIONS, MOIS)

    assert trame.height == len(DESTINATIONS) * len(MOIS)
    assert trame["price_eur"].null_count() == len(DESTINATIONS) * len(MOIS) - 1
    assert source.avertissements and "repli" in source.avertissements[0]


@pytest.mark.disable_socket
def test_sans_jeton_aucun_appel_reseau_n_est_emis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le jeton est optionnel : son absence ne doit jamais toucher le réseau."""
    monkeypatch.delenv("TRAVELPAYOUTS_TOKEN", raising=False)
    monkeypatch.setattr("nalu.ingest.flights.jeton", lambda: None)

    with pytest.raises(BasculeError, match="TRAVELPAYOUTS_TOKEN"):
        TravelpayoutsSource(token=None).monthly_prices(DESTINATIONS, MOIS)


# --- Codes HTTP ----------------------------------------------------------------


class FausseReponseHttp:
    def __init__(self, code: int, charge: dict | None = None) -> None:
        self.status_code = code
        self._charge = charge or {}

    def json(self) -> dict:
        return self._charge

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.mark.parametrize(("code", "motif"), [(401, "401"), (500, "500"), (503, "503")])
def test_les_codes_d_erreur_deviennent_une_bascule(
    code: int, motif: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("httpx.get", lambda *a, **k: FausseReponseHttp(code))
    with pytest.raises(BasculeError, match=motif):
        TravelpayoutsSource(token="factice").monthly_prices(["DPS"], MOIS)


def test_une_reponse_200_alimente_les_mois_de_l_horizon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    charge = {
        "success": True,
        "data": {
            "2026-09": {"price": 710},
            "2026-10": {"price": 802},
            "2027-05": {"price": 500},  # hors horizon : doit être ignoré
        },
    }
    monkeypatch.setattr("httpx.get", lambda *a, **k: FausseReponseHttp(200, charge))

    trame = TravelpayoutsSource(token="factice").monthly_prices(["DPS"], MOIS)

    prix = dict(zip(trame["month"].to_list(), trame["price_eur"].to_list(), strict=True))
    assert prix[date(2026, 9, 1)] == 710.0
    assert prix[date(2026, 10, 1)] == 802.0
    assert prix[date(2026, 11, 1)] is None


# --- Corrélation de rangs ------------------------------------------------------


def test_spearman_sur_une_relation_monotone_parfaite() -> None:
    assert spearman([1.0, 2.0, 3.0], [10.0, 20.0, 30.0]) == pytest.approx(1.0)
    assert spearman([1.0, 2.0, 3.0], [30.0, 20.0, 10.0]) == pytest.approx(-1.0)


def test_spearman_gere_les_ex_aequo_et_les_series_constantes() -> None:
    assert spearman([1.0, 1.0, 2.0], [5.0, 5.0, 9.0]) == pytest.approx(1.0)
    assert spearman([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) == 0.0


# --- Décision produit ----------------------------------------------------------


@pytest.mark.parametrize(
    ("couverts", "attendu"),
    [
        (20, "deux-axes"),
        (16, "deux-axes"),
        (15, "referentiel-restreint"),
        (10, "referentiel-restreint"),
        (9, "mono-axe"),
        (0, "mono-axe"),
    ],
)
def test_les_seuils_de_decision_suivent_la_config(couverts: int, attendu: str) -> None:
    """Repli décidé à froid le 2026-08-02, avant de connaître le résultat."""
    par_destination = {f"D{i:02d}": (1 if i < couverts else 0) for i in range(20)}
    couverture = Couverture(par_destination, 0.0, date(2026, 8, 2))
    assert couverture.couverts == couverts
    assert couverture.decision == attendu


def test_les_seuils_viennent_bien_de_la_config() -> None:
    assert CONFIG.coverage_two_axis_min == 16
    assert CONFIG.coverage_restricted_min == 10


def test_la_sonde_compte_les_mois_et_correle_avec_la_popularite() -> None:
    source = SourceFactice(
        {("DPS", m): 700.0 for m in MOIS} | {("TRU", MOIS[0]): 900.0}
    )
    trame = source.monthly_prices(DESTINATIONS, MOIS)

    couverture = probe(trame, popularite={"DPS": 3, "TRU": 1})

    assert couverture.par_destination == {"DPS": 3, "TRU": 1}
    assert couverture.couverts == 2
    assert couverture.correlation_popularite == pytest.approx(1.0)


# --- Horizon et nommage --------------------------------------------------------


def test_l_horizon_est_deterministe_et_passe_l_annee() -> None:
    mois = mois_horizon(date(2026, 11, 15), nombre=4)
    assert mois == [date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1)]


def test_le_snapshot_est_date() -> None:
    assert chemin_snapshot(date(2026, 8, 2)).name == "flights_2026-08-02.parquet"


def test_le_dernier_snapshot_est_le_plus_recent(tmp_path: Path) -> None:
    for jour in ["2026-07-01", "2026-08-02", "2026-06-15"]:
        (tmp_path / f"flights_{jour}.parquet").write_bytes(b"x")
    assert dernier_snapshot(tmp_path).name == "flights_2026-08-02.parquet"


def test_aucun_snapshot_renvoie_none(tmp_path: Path) -> None:
    assert dernier_snapshot(tmp_path) is None


# --- Le snapshot réel, hors ligne ----------------------------------------------


@pytest.mark.disable_socket
def test_le_snapshot_versionne_se_lit_sans_reseau() -> None:
    """Protège la promesse centrale : la démo tourne depuis le dépôt."""
    from nalu.spots import load_raw_spots

    destinations = sorted({s.airport_iata for s in load_raw_spots()})
    trame = SnapshotSource().monthly_prices(destinations, mois_horizon(date(2026, 8, 1)))

    assert set(trame["airport_iata"].unique()) == set(destinations)
    assert trame["price_eur"].is_not_null().any()
