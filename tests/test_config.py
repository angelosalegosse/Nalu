"""`config.py` : toutes les valeurs dans leurs bornes des le chargement.

Une configuration incoherente doit faire echouer l'import, pas un calcul trois
etapes plus loin dans le pipeline.
"""

import pytest
from pydantic import ValidationError

from nalu.config import CONFIG, NaluConfig


def test_les_onze_parametres_existent() -> None:
    """Le compte est verifie : ajouter un parametre sans le justifier doit se voir."""
    assert len(NaluConfig.model_fields) == 11


def test_chaque_parametre_porte_sa_justification() -> None:
    """La phrase qui justifie la valeur est l'actif auditable du fichier."""
    for name, field in NaluConfig.model_fields.items():
        assert field.description, f"{name} n'a pas de justification"


def test_les_valeurs_par_defaut_sont_dans_leurs_bornes() -> None:
    assert CONFIG.year_start <= CONFIG.year_end
    assert CONFIG.open_ocean_km > 0.0
    assert 0.0 < CONFIG.ray_step_deg <= 90.0
    assert 0.0 <= CONFIG.null_alert_ratio <= 1.0
    assert 0.0 <= CONFIG.fortnight_gap_points <= 100.0
    assert len(CONFIG.currency) == 3
    assert len(CONFIG.origin_iata) == 3
    assert CONFIG.coverage_restricted_min <= CONFIG.coverage_two_axis_min
    assert CONFIG.llm_alpha_decimals >= 0


def test_les_annees_couvrent_dix_saisons_pleines() -> None:
    assert list(CONFIG.years) == list(range(2015, 2025))
    assert len(CONFIG.years) == 10


def test_la_config_est_gelee() -> None:
    """Deux configurations divergentes produiraient deux classements."""
    with pytest.raises(ValidationError):
        CONFIG.year_start = 2000  # type: ignore[misc]


def test_une_annee_de_fin_anterieure_est_refusee() -> None:
    with pytest.raises(ValidationError):
        NaluConfig(year_start=2020, year_end=2015)


def test_des_seuils_de_couverture_inverses_sont_refuses() -> None:
    with pytest.raises(ValidationError):
        NaluConfig(coverage_two_axis_min=8, coverage_restricted_min=12)


def test_un_pas_angulaire_nul_est_refuse() -> None:
    with pytest.raises(ValidationError):
        NaluConfig(ray_step_deg=0.0)


def test_une_devise_mal_formee_est_refusee() -> None:
    with pytest.raises(ValidationError):
        NaluConfig(currency="euro")


def test_un_parametre_inconnu_est_refuse() -> None:
    """`extra=forbid` : une constante en dur ne peut pas se glisser ici par erreur."""
    with pytest.raises(ValidationError):
        NaluConfig(seuil_invente=3)
