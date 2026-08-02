"""Référentiel des spots : modèle Pydantic et chargement validé.

Ce n'est pas un fichier de configuration, c'est l'actif central du produit. ERA5
donne la houle du large à 50 km de maille : sans les caractéristiques du spot, le
score se réduit à une hauteur de vague, ce qu'un surfeur démonte en dix secondes.

    Le référentiel est réparti sur DEUX fichiers, volontairement.

    data/spots.yaml              CURÉ À LA MAIN. Identité, position, seuils,
                                 `source` et `confidence`. Chaque ligne est
                                 défendable devant quelqu'un qui connaît le sujet.

    data/exposure_windows.yaml   GÉNÉRÉ par `python -m nalu.exposure`. Les fenêtres
                                 de houle, obtenues par lancer de rayons sur les
                                 côtes Natural Earth.

    Les mélanger dans un seul fichier rendrait illisible tout diff : on ne saurait
    plus si une valeur a été jugée ou calculée. La fenêtre calculée est la valeur
    PAR DÉFAUT ; un spot peut la remplacer par `swell_dir_override`, mais alors
    `override_reason` devient obligatoire.

**Aucune valeur par défaut sur une métadonnée de spot.** Un défaut silencieux
produit un score faux et indétectable : mieux vaut refuser de charger.
"""

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

SPOTS_PATH = Path("data/spots.yaml")
WINDOWS_PATH = Path("data/exposure_windows.yaml")

Degre = Annotated[float, Field(ge=0.0, lt=360.0)]

DegreFin = Annotated[float, Field(ge=0.0, le=360.0)]
"""Borne de fin d'un arc. 360 y est admis, et uniquement pour encoder l'arc complet
d'une île en plein océan — la seule forme que `in_arc` accepte comme cercle entier."""


class Niveau(StrEnum):
    INTERMEDIAIRE = "intermediate"
    CONFIRME = "advanced"
    EXPERT = "expert"


class Fond(StrEnum):
    RECIF = "reef"
    SABLE = "beach"
    POINTE = "point"


class Confiance(StrEnum):
    """Fiabilité des seuils. Un prospect doit pouvoir distinguer ce qui est sourcé
    finement de ce qui est une estimation raisonnable."""

    BASSE = "low"
    MOYENNE = "medium"
    HAUTE = "high"


class Spot(BaseModel):
    """Un spot du référentiel. Tous les attributs sont obligatoires."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)

    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    name: str = Field(min_length=1)
    country: str = Field(min_length=1)
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    airport_iata: str = Field(pattern=r"^[A-Z]{3}$")

    swell_period_min: float = Field(gt=0.0, le=30.0)
    """Période de pic minimale, en secondes, sous laquelle la houle est trop courte."""

    hs_offshore_min: float = Field(gt=0.0, le=20.0)
    """Hauteur significative AU LARGE, en mètres, sous laquelle le spot ne marche pas."""

    hs_offshore_max: float = Field(gt=0.0, le=20.0)
    """Hauteur significative AU LARGE au-delà de laquelle le spot ferme ou devient
    hors de portée du niveau annoncé."""

    wind_dir_offshore_min: Degre
    """Début du secteur de vent offshore (celui qui creuse la vague), en degrés d'où
    vient le vent."""

    wind_dir_offshore_max: Degre
    """Fin du secteur de vent offshore. Peut être inférieur au début : la fenêtre
    passe alors par 0 degré, cas géré par `in_arc`."""

    wind_speed_max_offshore: float = Field(gt=0.0, le=40.0)
    """Vitesse maximale tolérée quand le vent est offshore, en m/s. Au-delà, il hache
    la mer, empêche de ramer et souffle la lèvre."""

    wind_speed_max_onshore: float = Field(gt=0.0, le=40.0)
    """Vitesse maximale tolérée hors secteur offshore, en m/s. Environ la moitié du
    seuil offshore : un onshore modéré suffit à détruire la surface."""

    level: Niveau
    bottom: Fond

    source: str = Field(min_length=8)
    """D'où viennent les seuils. Ces valeurs déterminent entièrement le résultat :
    un prospect qui demande d'où elles sortent doit trouver la réponse ici."""

    confidence: Confiance

    swell_dir_override: tuple[Degre, DegreFin] | None = None
    """Remplace la fenêtre calculée par lancer de rayons. Renseigné sous la forme
    `[min, max]` ; impose alors `override_reason`."""

    override_reason: str | None = None
    """Pourquoi la géométrie seule ne suffit pas ici. Obligatoire dès qu'il y a un
    override : un override sans justification est une valeur inventée."""

    @model_validator(mode="after")
    def _coherence(self) -> Self:
        if self.hs_offshore_max <= self.hs_offshore_min:
            raise ValueError(
                f"{self.id}: hs_offshore_max ({self.hs_offshore_max}) doit dépasser "
                f"hs_offshore_min ({self.hs_offshore_min})"
            )
        if self.wind_speed_max_offshore <= self.wind_speed_max_onshore:
            raise ValueError(
                f"{self.id}: wind_speed_max_offshore ({self.wind_speed_max_offshore}) doit "
                f"dépasser wind_speed_max_onshore ({self.wind_speed_max_onshore}) — un vent "
                "offshore est toléré plus fort qu'un onshore, jamais l'inverse"
            )
        if self.swell_dir_override is not None and not self.override_reason:
            raise ValueError(
                f"{self.id}: swell_dir_override renseigné sans override_reason. La fenêtre "
                "est calculée par lancer de rayons ; la remplacer exige de dire pourquoi"
            )
        if self.override_reason and self.swell_dir_override is None:
            raise ValueError(
                f"{self.id}: override_reason renseigné sans swell_dir_override"
            )
        return self


class SpotResolu(BaseModel):
    """Un spot et sa fenêtre de houle effective, prêt pour le calcul de surfabilité."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    spot: Spot
    swell_dir_min: Degre
    swell_dir_max: DegreFin
    window_source: str
    """`calculee` ou `override`. Rend traçable, ligne par ligne, l'origine de la fenêtre."""

    @property
    def id(self) -> str:
        return self.spot.id


def _charger_yaml(chemin: Path) -> object:
    if not chemin.exists():
        raise FileNotFoundError(f"référentiel absent : {chemin}")
    with chemin.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_raw_spots(chemin: Path = SPOTS_PATH) -> list[Spot]:
    """Charge et valide `data/spots.yaml`, sans les fenêtres d'exposition."""
    brut = _charger_yaml(chemin)
    if not isinstance(brut, list) or not brut:
        raise ValueError(f"{chemin} doit contenir une liste non vide de spots")

    spots = [Spot.model_validate(entree) for entree in brut]

    doublons = {s.id for s in spots if [x.id for x in spots].count(s.id) > 1}
    if doublons:
        raise ValueError(f"identifiants de spot en double : {sorted(doublons)}")
    return spots


def load_windows(chemin: Path = WINDOWS_PATH) -> dict[str, tuple[float, float]]:
    """Charge les fenêtres générées par `python -m nalu.exposure`."""
    brut = _charger_yaml(chemin)
    if not isinstance(brut, dict) or "windows" not in brut:
        raise ValueError(f"{chemin} doit contenir une clé `windows`")
    return {
        spot_id: (float(valeur["swell_dir_min"]), float(valeur["swell_dir_max"]))
        for spot_id, valeur in brut["windows"].items()
    }


def load_spots(
    spots_path: Path = SPOTS_PATH, windows_path: Path = WINDOWS_PATH
) -> list[SpotResolu]:
    """Charge le référentiel complet, fenêtre d'exposition résolue par spot.

    Échoue en nommant le spot fautif si sa fenêtre manque : un référentiel
    partiellement résolu produirait un classement faux et parfaitement plausible.
    """
    spots = load_raw_spots(spots_path)
    fenetres = load_windows(windows_path)

    resolus = []
    for spot in spots:
        if spot.swell_dir_override is not None:
            debut, fin = spot.swell_dir_override
            origine = "override"
        else:
            if spot.id not in fenetres:
                raise ValueError(
                    f"aucune fenêtre d'exposition pour le spot « {spot.id} » dans "
                    f"{windows_path}. Régénérer avec `uv run python -m nalu.exposure`"
                )
            debut, fin = fenetres[spot.id]
            origine = "calculee"
        resolus.append(
            SpotResolu(
                spot=spot, swell_dir_min=debut, swell_dir_max=fin, window_source=origine
            )
        )
    return resolus
