"""Ingestion Open-Meteo : quota pondéré, parsing, ré-entrance, intégrité du cache.

Aucun test ne touche le réseau. Les réponses sont des doublures qui imitent la forme
FlatBuffers du client officiel — c'est le parsing qui est à nous, pas le transport.
"""

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from nalu.config import (
    CONFIG,
    MARINE_HOURLY,
    QUOTA_PER_DAY,
    SWELL_HEIGHT,
    WEATHER_DAILY,
    WEATHER_HOURLY,
)
from nalu.ingest.openmeteo import (
    CacheIncomplet,
    QuotaDepasse,
    QuotaLedger,
    _trame_horaire,
    _trame_journaliere,
    chemin_horaire,
    chemin_journalier,
    heures_attendues,
    ingerer,
    jours_attendus,
    poids_requete,
    verify_cache_integrity,
)
from nalu.spots import Spot

# --- Doublures de réponse ------------------------------------------------------


class FausseVariable:
    def __init__(self, valeurs: np.ndarray) -> None:
        self._valeurs = valeurs

    def ValuesAsNumpy(self) -> np.ndarray:
        return self._valeurs

    def ValuesInt64AsNumpy(self) -> np.ndarray:
        return self._valeurs


class FauxBloc:
    def __init__(self, debut: int, pas: int, colonnes: list[np.ndarray]) -> None:
        self._debut = debut
        self._pas = pas
        self._colonnes = colonnes

    def Time(self) -> int:
        return self._debut

    def TimeEnd(self) -> int:
        return self._debut + self._pas * len(self._colonnes[0])

    def Interval(self) -> int:
        return self._pas

    def Variables(self, i: int) -> FausseVariable:
        return FausseVariable(self._colonnes[i])

    def VariablesLength(self) -> int:
        return len(self._colonnes)


class FausseReponse:
    def __init__(self, horaire: FauxBloc | None, journalier: FauxBloc | None) -> None:
        self._horaire = horaire
        self._journalier = journalier

    def Hourly(self) -> FauxBloc | None:
        return self._horaire

    def Daily(self) -> FauxBloc | None:
        return self._journalier


DEBUT_2022 = int(datetime(2022, 1, 1, tzinfo=UTC).timestamp())


def reponse_marine(heures: int, trous: tuple[int, ...] = ()) -> FausseReponse:
    colonnes = []
    for rang in range(len(MARINE_HOURLY)):
        valeurs = np.full(heures, 1.0 + rang, dtype=np.float32)
        for trou in trous:
            valeurs[trou] = np.nan
        colonnes.append(valeurs)
    return FausseReponse(FauxBloc(DEBUT_2022, 3600, colonnes), None)


def reponse_meteo(heures: int, jours: int) -> FausseReponse:
    horaire = FauxBloc(
        DEBUT_2022,
        3600,
        [np.full(heures, 5.0, dtype=np.float32) for _ in WEATHER_HOURLY],
    )
    journalier = FauxBloc(
        DEBUT_2022,
        86_400,
        [
            np.array(
                [DEBUT_2022 + j * 86_400 + (25_200 if i == 0 else 64_800) for j in range(jours)],
                dtype=np.int64,
            )
            for i in range(len(WEATHER_DAILY))
        ],
    )
    return FausseReponse(horaire, journalier)


class FauxClient:
    """Compte les appels et sert des réponses de la bonne forme."""

    def __init__(self, heures: int, jours: int, trous: tuple[int, ...] = ()) -> None:
        self.heures = heures
        self.jours = jours
        self.trous = trous
        self.appels: list[str] = []

    def weather_api(self, url: str, params: dict) -> list[FausseReponse]:
        self.appels.append(url)
        nb = len(params["latitude"])
        if "marine" in url:
            return [reponse_marine(self.heures, self.trous) for _ in range(nb)]
        return [reponse_meteo(self.heures, self.jours) for _ in range(nb)]


SPOT_TEMOIN = Spot.model_validate(
    {
        "id": "spot-temoin",
        "name": "Témoin",
        "country": "France",
        "lat": 43.0,
        "lon": -1.5,
        "airport_iata": "BIQ",
        "swell_period_min": 10.0,
        "hs_offshore_min": 1.0,
        "hs_offshore_max": 3.0,
        "wind_dir_offshore_min": 45.0,
        "wind_dir_offshore_max": 135.0,
        "wind_speed_max_offshore": 14.0,
        "wind_speed_max_onshore": 7.0,
        "level": "expert",
        "bottom": "beach",
        "source": "https://example.org/guide",
        "confidence": "medium",
    }
)


# --- La variable de houle ------------------------------------------------------


def test_le_modele_utilise_swell_wave_height_jamais_wave_height() -> None:
    """`wave_height` agrège la mer du vent : du clapot serait compté comme surfable."""
    assert SWELL_HEIGHT == "swell_wave_height"
    assert SWELL_HEIGHT != "wave_height"


def test_wave_height_reste_ingere_mais_seulement_pour_l_affichage() -> None:
    """Il sert à montrer l'écart houle / mer totale, jamais à décider."""
    assert "wave_height" in MARINE_HOURLY
    assert MARINE_HOURLY[0] == SWELL_HEIGHT


# --- Quota pondéré -------------------------------------------------------------


def test_le_poids_suit_la_formule_publiee() -> None:
    """(variables / 10) x (jours / 14) x localisations."""
    assert poids_requete(10, 14, 1) == pytest.approx(1.0)
    assert poids_requete(7, 365, 20) == pytest.approx(0.7 * (365 / 14) * 20)


def test_grouper_les_spots_ne_reduit_pas_le_quota() -> None:
    """Le groupage divise les allers-retours HTTP, pas la consommation."""
    groupe = poids_requete(7, 365, 20)
    separe = sum(poids_requete(7, 365, 1) for _ in range(20))
    assert groupe == pytest.approx(separe)


class Horloge:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_le_ledger_met_en_pause_avant_le_plafond_par_minute() -> None:
    horloge = Horloge()
    dormi: list[float] = []

    def dormir(secondes: float) -> None:
        dormi.append(secondes)
        horloge.t += secondes

    ledger = QuotaLedger(horloge=horloge, dormir=dormir)
    ledger.reserver(500.0)
    assert dormi == []
    ledger.reserver(200.0)  # 700 > 600/min : doit attendre la sortie de fenêtre
    assert dormi and dormi[0] == pytest.approx(60.0)
    assert ledger.total == pytest.approx(700.0)
    assert ledger.attente_totale == pytest.approx(60.0)


def test_le_ledger_refuse_de_franchir_le_plafond_journalier() -> None:
    """Attendre ne sert à rien à ce stade : il faut reprendre demain, et le dire.

    On avance l'horloge d'une heure entre chaque réservation pour vider la fenêtre
    horaire : seul le plafond du jour peut alors se déclencher.
    """
    horloge = Horloge()
    ledger = QuotaLedger(horloge=horloge, dormir=lambda _: None)

    consomme = 0.0
    while consomme + 4_000.0 <= QUOTA_PER_DAY:
        ledger.reserver(4_000.0)
        consomme += 4_000.0
        horloge.t += 3_700.0  # la fenêtre horaire se vide, celle du jour non

    with pytest.raises(QuotaDepasse, match="journalier"):
        ledger.reserver(4_000.0)
    assert ledger.total == pytest.approx(consomme)


def test_le_ledger_refuse_une_requete_plus_lourde_que_le_plafond_horaire() -> None:
    ledger = QuotaLedger(horloge=Horloge(), dormir=lambda _: None)
    with pytest.raises(QuotaDepasse):
        ledger.reserver(9_000.0)


def test_le_remplissage_reel_tient_sous_le_plafond_journalier() -> None:
    jours = sum(jours_attendus(a) for a in CONFIG.years)
    marine = poids_requete(len(MARINE_HOURLY), jours, 20)
    meteo = poids_requete(len(WEATHER_HOURLY) + len(WEATHER_DAILY), jours, 20)
    assert marine + meteo < QUOTA_PER_DAY


# --- Parsing -------------------------------------------------------------------


def test_la_trame_horaire_a_le_bon_schema_et_le_bon_nombre_de_lignes() -> None:
    trame = _trame_horaire("uluwatu", reponse_marine(48), MARINE_HOURLY)
    assert trame.height == 48
    assert trame.columns == ["spot_id", "time", *MARINE_HOURLY]
    assert trame["time"].dtype == pl.Datetime("us", "UTC")
    assert all(trame[v].dtype == pl.Float32 for v in MARINE_HOURLY)


def test_un_trou_produit_null_et_surtout_pas_zero() -> None:
    """Une hauteur de houle à 0 et une donnée absente ne veulent pas dire la même chose."""
    trame = _trame_horaire("uluwatu", reponse_marine(24, trous=(3, 7)), MARINE_HOURLY)
    colonne = trame[SWELL_HEIGHT]
    assert colonne.null_count() == 2
    assert colonne[3] is None
    assert 0.0 not in colonne.drop_nulls().to_list()
    # Et surtout : aucun NaN résiduel, qui contaminerait toute moyenne en aval.
    assert not colonne.is_nan().any()


def test_la_trame_journaliere_convertit_les_instants_solaires() -> None:
    trame = _trame_journaliere("uluwatu", reponse_meteo(48, 2), WEATHER_DAILY)
    assert trame.height == 2
    assert trame["sunrise"].dtype == pl.Datetime("us", "UTC")
    assert trame["sunset"][0] > trame["sunrise"][0]


# --- Ré-entrance ---------------------------------------------------------------


def test_le_remplissage_ecrit_les_deux_fichiers(tmp_path: Path) -> None:
    client = FauxClient(heures=heures_attendues(2022), jours=jours_attendus(2022))
    requetes, ledger = ingerer([SPOT_TEMOIN], [2022], tmp_path, client=client)

    assert requetes == 2  # marine + archive
    assert ledger.total > 0
    assert chemin_horaire(SPOT_TEMOIN.id, 2022, tmp_path).exists()
    assert chemin_journalier(SPOT_TEMOIN.id, 2022, tmp_path).exists()


def test_un_cache_complet_n_emet_aucun_appel(tmp_path: Path) -> None:
    """Promesse de ré-entrance : relancé sur cache complet, zéro réseau."""
    client = FauxClient(heures=heures_attendues(2022), jours=jours_attendus(2022))
    ingerer([SPOT_TEMOIN], [2022], tmp_path, client=client)
    client.appels.clear()

    requetes, _ = ingerer([SPOT_TEMOIN], [2022], tmp_path, client=client)
    assert requetes == 0
    assert client.appels == []


def test_supprimer_un_fichier_redeclenche_ce_spot_et_lui_seul(tmp_path: Path) -> None:
    autre = SPOT_TEMOIN.model_copy(update={"id": "autre-spot"})
    client = FauxClient(heures=heures_attendues(2022), jours=jours_attendus(2022))
    ingerer([SPOT_TEMOIN, autre], [2022], tmp_path, client=client)

    chemin_horaire(autre.id, 2022, tmp_path).unlink()
    client.appels.clear()
    requetes, _ = ingerer([SPOT_TEMOIN, autre], [2022], tmp_path, client=client)

    # Deux endpoints, une seule localisation : le spot déjà en cache n'est pas redemandé.
    assert requetes == 2
    assert len(client.appels) == 2


# --- Intégrité du cache : la lacune critique -----------------------------------


def test_un_cache_complet_passe(tmp_path: Path) -> None:
    client = FauxClient(heures=heures_attendues(2022), jours=jours_attendus(2022))
    ingerer([SPOT_TEMOIN], [2022], tmp_path, client=client)
    verify_cache_integrity([SPOT_TEMOIN], [2022], tmp_path)  # ne lève pas


def test_un_fichier_absent_echoue_en_nommant_le_coupable(tmp_path: Path) -> None:
    client = FauxClient(heures=heures_attendues(2022), jours=jours_attendus(2022))
    ingerer([SPOT_TEMOIN], [2022], tmp_path, client=client)
    chemin_horaire(SPOT_TEMOIN.id, 2022, tmp_path).unlink()

    with pytest.raises(CacheIncomplet) as erreur:
        verify_cache_integrity([SPOT_TEMOIN], [2022], tmp_path)
    assert SPOT_TEMOIN.id in str(erreur.value)
    assert "2022" in str(erreur.value)


def test_un_fichier_tronque_echoue_en_nommant_le_coupable(tmp_path: Path) -> None:
    """Le mode de défaillance le plus dangereux : un cache partiel silencieux."""
    client = FauxClient(heures=heures_attendues(2022), jours=jours_attendus(2022))
    ingerer([SPOT_TEMOIN], [2022], tmp_path, client=client)

    chemin = chemin_horaire(SPOT_TEMOIN.id, 2022, tmp_path)
    pl.read_parquet(chemin).head(4_000).write_parquet(chemin)

    with pytest.raises(CacheIncomplet) as erreur:
        verify_cache_integrity([SPOT_TEMOIN], [2022], tmp_path)
    assert SPOT_TEMOIN.id in str(erreur.value)
    assert "4000" in str(erreur.value)
    assert "8760" in str(erreur.value)


def test_une_annee_bissextile_attend_bien_8784_heures() -> None:
    assert heures_attendues(2024) == 8784
    assert heures_attendues(2023) == 8760
    assert jours_attendus(2024) == 366


# --- Le cache réel, hors ligne -------------------------------------------------


@pytest.mark.disable_socket
def test_le_cache_versionne_est_complet_et_se_lit_sans_reseau() -> None:
    """Protège la promesse centrale : la démo tourne depuis le dépôt, sans réseau."""
    verify_cache_integrity()


@pytest.mark.disable_socket
def test_le_cache_reel_ne_contient_ni_nan_ni_zero_suspect() -> None:
    trame = pl.read_parquet(chemin_horaire("uluwatu", 2024))
    assert trame.height == heures_attendues(2024)
    assert not trame[SWELL_HEIGHT].is_nan().any()
    assert trame[SWELL_HEIGHT].min() > 0.0
