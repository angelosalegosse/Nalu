"""Les onze parametres reglables du modele Nalu, et rien d'autre.

Aucune constante en dur ailleurs dans le projet. Chaque valeur est suivie de la
phrase qui la justifie : ce fichier est ce qu'un prospect lit pour comprendre les
hypotheses du produit sans lire le code.

Le modele est gele (`frozen`) et valide par Pydantic a l'import : une valeur hors
bornes fait echouer le chargement du module, pas un calcul trois etapes plus loin.
"""

from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NaluConfig(BaseModel):
    """Parametres du modele. Immuable, valide a la construction."""

    # `use_attribute_docstrings` : la phrase qui justifie chaque valeur vit juste
    # sous elle et devient sa `description` Pydantic, donc un test peut exiger
    # qu'aucun parametre ne soit ajoute sans justification.
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)

    # --- Bornes de dates (2 parametres) ---------------------------------------

    year_start: int = Field(default=2022, ge=1979, le=2100)
    """Premiere annee pleine ou Open-Meteo sert la PARTITION de houle
    (`swell_wave_*`) : mesure spot par spot le 2026-08-02, janvier 2022 est complet
    sur les 20. Avant, seule la mer totale (`wave_*`) existe, via ERA5-Ocean."""

    year_end: int = Field(default=2025, ge=1979, le=2100)
    """Derniere annee civile complete disponible : inclure une annee partielle
    biaiserait mecaniquement les mois qu'elle ne couvre pas."""

    # --- Geometrie cotiere (2 parametres) -------------------------------------

    open_ocean_km: float = Field(default=500.0, gt=0.0, le=20_000.0)
    """Portee d'un rayon au-dela de laquelle on considere qu'il donne sur l'ocean
    ouvert : une houle longue se forme sur des fetchs de cet ordre de grandeur."""

    ray_step_deg: float = Field(default=2.0, gt=0.0, le=90.0)
    """Pas angulaire du lancer de rayons : 180 rayons par spot, assez fin pour ne
    pas manquer une passe cotiere, assez grossier pour rester instantane."""

    # --- Qualite des donnees (1 parametre) ------------------------------------

    null_alert_ratio: float = Field(default=0.05, ge=0.0, le=1.0)
    """Au-dela de 5 % d'heures manquantes sur un couple spot-annee, la climatologie
    n'est plus representative et le pipeline doit alerter plutot que moyenner."""

    # --- Dispersion intra-mois (1 parametre) ----------------------------------

    fortnight_gap_points: float = Field(default=20.0, ge=0.0, le=100.0)
    """Ecart en points de P_surf entre les deux quinzaines d'un mois au-dela duquel
    la moyenne mensuelle masque une bascule de saison et doit etre signalee."""

    # --- Axe prix (2 parametres) ----------------------------------------------

    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    """Devise unique du produit : melanger des devises rendrait le rang prix
    incomparable d'une destination a l'autre."""

    origin_iata: str = Field(default="PAR", pattern=r"^[A-Z]{3}$")
    """Code ville IATA de Paris, tous aeroports confondus : l'origine unique est une
    hypothese assumee du produit, pas une limite technique."""

    # --- Seuils de couverture des prix (2 parametres) -------------------------

    coverage_two_axis_min: int = Field(default=16, ge=0)
    """A partir de 16 spots couverts sur 20, le produit garde ses deux axes tels que
    specifies : la couverture est jugee suffisante pour que le rang prix ait un sens."""

    coverage_restricted_min: int = Field(default=10, ge=0)
    """En dessous de 10 spots couverts, l'axe prix est abandonne et le produit devient
    un calendrier de saisonnalite mono-axe. Repli decide a froid, avant la mesure."""

    # --- Cache du commentaire LLM (1 parametre) -------------------------------

    llm_alpha_decimals: int = Field(default=1, ge=0, le=6)
    """Arrondi d'alpha servant de cle de cache du commentaire Gemini : au dixieme, le
    curseur ne declenche pas un appel a chaque pixel parcouru."""

    @model_validator(mode="after")
    def _check_coherence(self) -> "NaluConfig":
        if self.year_end < self.year_start:
            raise ValueError(f"year_end ({self.year_end}) < year_start ({self.year_start})")
        if self.coverage_restricted_min > self.coverage_two_axis_min:
            raise ValueError(
                f"coverage_restricted_min ({self.coverage_restricted_min}) doit rester "
                f"sous coverage_two_axis_min ({self.coverage_two_axis_min})"
            )
        return self

    @property
    def years(self) -> range:
        """Les annees d'archive couvertes, bornes incluses."""
        return range(self.year_start, self.year_end + 1)


CONFIG: Final[NaluConfig] = NaluConfig()
"""Instance unique. Importer `CONFIG`, ne jamais reconstruire un `NaluConfig` en
dehors des tests : deux configurations divergentes produiraient deux classements."""


# ─── Specification de la source, figee ici ────────────────────────────────────
#
# Ce ne sont pas des parametres reglables du modele — les onze sont au-dessus — mais
# la definition exacte de ce qu'on demande a Open-Meteo. Elle vit ici pour que la
# variable de houle retenue soit impossible a changer par inadvertance.

SWELL_HEIGHT: Final[str] = "swell_wave_height"
"""LA variable de hauteur du modele. Surtout PAS `wave_height`, qui agrege la mer du
vent : du clapot serait compte comme surfable. Verifie par test."""

SWELL_DIRECTION: Final[str] = "swell_wave_direction"
SWELL_PERIOD: Final[str] = "swell_wave_period"

MARINE_HOURLY: Final[tuple[str, ...]] = (
    SWELL_HEIGHT,
    SWELL_DIRECTION,
    SWELL_PERIOD,
    "wave_height",
    "wave_direction",
    "wave_period",
    "wind_wave_height",
)
"""Les trois premieres alimentent le modele. Les quatre suivantes ne servent QU'A
l'affichage et au diagnostic : elles permettent de montrer l'ecart entre houle et mer
totale sans jamais entrer dans le score."""

WEATHER_HOURLY: Final[tuple[str, ...]] = ("wind_speed_10m", "wind_direction_10m")
"""Vent a 10 m, seule hauteur servie par l'archive et convention meteo standard."""

WEATHER_DAILY: Final[tuple[str, ...]] = ("sunrise", "sunset")
"""Fenetre diurne reelle, par spot et par jour. Un spot au-dela de 50 degres de
latitude doit avoir nettement moins d'heures surfables en decembre qu'en juin."""

MARINE_URL: Final[str] = "https://marine-api.open-meteo.com/v1/marine"
ARCHIVE_URL: Final[str] = "https://archive-api.open-meteo.com/v1/archive"

QUOTA_PER_MINUTE: Final[int] = 600
QUOTA_PER_HOUR: Final[int] = 5_000
QUOTA_PER_DAY: Final[int] = 10_000
"""Plafonds du palier gratuit Open-Meteo, en unites PONDEREES et non en requetes :
`(variables / 10) x (jours / 14) x localisations`. Grouper les spots reduit la
latence, pas la consommation."""

MAX_LOCATIONS_PER_REQUEST: Final[int] = 25
"""Au-dela, la reponse groupee devient lourde a decouper pour un gain nul de quota."""
