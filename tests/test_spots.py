"""Référentiel des spots : validation stricte et résolution des fenêtres.

Le référentiel est l'actif central du produit. Une valeur manquante ou incohérente
doit faire échouer le chargement, jamais produire un score plausible et faux.
"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from nalu.geo import arc_span, in_arc
from nalu.spots import (
    SPOTS_PATH,
    WINDOWS_PATH,
    Spot,
    load_raw_spots,
    load_spots,
    load_windows,
)

NOMBRE_DE_SPOTS = 20

VALIDE = {
    "id": "spot-temoin",
    "name": "Spot témoin",
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


def spot_avec(**remplacements: object) -> dict[str, object]:
    return VALIDE | remplacements


def spot_sans(cle: str) -> dict[str, object]:
    return {k: v for k, v in VALIDE.items() if k != cle}


# --- Validation d'un spot isolé -----------------------------------------------


def test_le_spot_temoin_est_valide() -> None:
    assert Spot.model_validate(VALIDE).id == "spot-temoin"


@pytest.mark.parametrize("cle", sorted(VALIDE))
def test_tout_attribut_manquant_fait_echouer(cle: str) -> None:
    """Aucune valeur par défaut : un défaut silencieux produit un score indétectable."""
    with pytest.raises(ValidationError):
        Spot.model_validate(spot_sans(cle))


@pytest.mark.parametrize(
    ("champ", "valeur"),
    [
        ("level", "pro"),
        ("bottom", "sand"),
        ("confidence", "excellente"),
        ("airport_iata", "BI"),
        ("airport_iata", "biq"),
        ("airport_iata", "BIQX"),
        ("lat", 91.0),
        ("lat", -91.0),
        ("lon", 181.0),
        ("id", "Spot Temoin"),
        ("swell_period_min", 0.0),
        ("wind_dir_offshore_min", 360.0),
        ("source", "n/a"),
    ],
)
def test_valeurs_hors_domaine_refusees(champ: str, valeur: object) -> None:
    with pytest.raises(ValidationError):
        Spot.model_validate(spot_avec(**{champ: valeur}))


def test_hauteur_max_sous_la_min_est_refusee() -> None:
    with pytest.raises(ValidationError, match="hs_offshore_max"):
        Spot.model_validate(spot_avec(hs_offshore_min=3.0, hs_offshore_max=1.0))


def test_seuil_de_vent_offshore_sous_le_onshore_est_refuse() -> None:
    """Un offshore est toléré plus fort qu'un onshore, jamais l'inverse."""
    with pytest.raises(ValidationError, match="wind_speed_max_offshore"):
        Spot.model_validate(spot_avec(wind_speed_max_offshore=5.0, wind_speed_max_onshore=9.0))


def test_override_sans_raison_est_refuse() -> None:
    """La fenêtre est calculée ; la remplacer exige de dire pourquoi."""
    with pytest.raises(ValidationError, match="override_reason"):
        Spot.model_validate(spot_avec(swell_dir_override=[200.0, 260.0]))


def test_raison_sans_override_est_refusee() -> None:
    with pytest.raises(ValidationError, match="swell_dir_override"):
        Spot.model_validate(spot_avec(override_reason="parce que"))


def test_override_avec_raison_est_accepte() -> None:
    spot = Spot.model_validate(
        spot_avec(swell_dir_override=[200.0, 260.0], override_reason="houle enroulée")
    )
    assert spot.swell_dir_override == (200.0, 260.0)


def test_un_attribut_inconnu_est_refuse() -> None:
    with pytest.raises(ValidationError):
        Spot.model_validate(spot_avec(tide_window="mid"))


# --- Chargement du référentiel réel -------------------------------------------


def test_le_referentiel_contient_vingt_spots() -> None:
    assert len(load_raw_spots()) == NOMBRE_DE_SPOTS


def test_les_identifiants_sont_uniques() -> None:
    ids = [s.id for s in load_raw_spots()]
    assert len(set(ids)) == len(ids)


def test_chaque_spot_porte_sa_source_et_sa_confiance() -> None:
    """Les seuils déterminent entièrement le résultat : ils doivent être auditables."""
    for spot in load_raw_spots():
        assert spot.source.startswith("http"), spot.id
        assert spot.confidence in {"low", "medium", "high"}, spot.id


def test_les_identifiants_de_doublon_sont_signales(tmp_path: Path) -> None:
    entrees = [VALIDE, spot_avec(name="Autre")]
    chemin = tmp_path / "spots.yaml"
    chemin.write_text(yaml.safe_dump(entrees), encoding="utf-8")
    with pytest.raises(ValueError, match="double"):
        load_raw_spots(chemin)


# --- Résolution des fenêtres d'exposition -------------------------------------


def test_toutes_les_fenetres_se_resolvent() -> None:
    resolus = load_spots()
    assert len(resolus) == NOMBRE_DE_SPOTS
    for r in resolus:
        assert 0.0 <= r.swell_dir_min < 360.0
        assert 0.0 <= r.swell_dir_max <= 360.0


def test_l_origine_de_chaque_fenetre_est_tracable() -> None:
    origines = {r.window_source for r in load_spots()}
    assert origines <= {"calculee", "override"}


def test_un_override_prime_sur_la_fenetre_calculee() -> None:
    calculees = load_windows()
    for resolu in load_spots():
        if resolu.spot.swell_dir_override is None:
            continue
        assert resolu.window_source == "override"
        assert (resolu.swell_dir_min, resolu.swell_dir_max) == resolu.spot.swell_dir_override
        # La fenêtre calculée reste écrite dans le fichier généré : l'override doit
        # rester lisible comme un écart, pas effacer ce que la géométrie disait.
        assert resolu.id in calculees


def test_au_moins_trois_fenetres_sont_a_cheval_sur_zero() -> None:
    """Sans ce cas dans le référentiel réel, `in_arc` n'est jamais exercé en aval."""
    a_cheval = [r.id for r in load_spots() if r.swell_dir_max < r.swell_dir_min]
    assert len(a_cheval) >= 3, a_cheval


def test_les_fenetres_a_cheval_contiennent_bien_le_nord() -> None:
    for resolu in load_spots():
        if resolu.swell_dir_max < resolu.swell_dir_min:
            assert in_arc(0.0, resolu.swell_dir_min, resolu.swell_dir_max), resolu.id


def test_aucune_fenetre_degeneree_ou_pleine() -> None:
    """Un arc nul ou complet signale une coordonnée fausse, pas un spot réel."""
    for resolu in load_spots():
        span = arc_span(resolu.swell_dir_min, resolu.swell_dir_max)
        assert 0.0 < span < 360.0, f"{resolu.id}: arc de {span} degrés"


def test_une_fenetre_manquante_echoue_en_nommant_le_spot(tmp_path: Path) -> None:
    """Un référentiel partiellement résolu produirait un classement faux et plausible."""
    fenetres = yaml.safe_load(WINDOWS_PATH.read_text(encoding="utf-8"))
    orphelin = next(
        s.id for s in load_raw_spots() if s.swell_dir_override is None
    )
    del fenetres["windows"][orphelin]
    ampute = tmp_path / "windows.yaml"
    ampute.write_text(yaml.safe_dump(fenetres), encoding="utf-8")

    with pytest.raises(ValueError, match=orphelin):
        load_spots(SPOTS_PATH, ampute)


# --- Promesse hors ligne -------------------------------------------------------


@pytest.mark.disable_socket
def test_le_referentiel_se_charge_sans_reseau() -> None:
    """Protège la promesse centrale : la démo tourne depuis le dépôt, sans réseau."""
    assert len(load_spots()) == NOMBRE_DE_SPOTS
