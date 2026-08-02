"""Dashboard : les figures se construisent, hors ligne, sur les données réelles.

Un test de fumée, pas un test de rendu. Il attrape ce qui casse le plus souvent —
une colonne renommée, un fichier absent — sans prétendre juger l'apparence.
"""

import plotly.graph_objects as go
import polars as pl
import pytest

from nalu.app import CLAIR, SOMBRE, carte, saisonnalite
from nalu.coastline import CONTOUR_PATH
from nalu.scoring.combine import classement, construire_tableau


@pytest.fixture(scope="module")
def tableau() -> pl.DataFrame:
    return construire_tableau()


@pytest.mark.disable_socket
def test_le_planisphere_est_versionne_donc_lisible_sans_reseau() -> None:
    """`scatter_geo` de Plotly télécharge sa topologie : la carte serait vide."""
    assert CONTOUR_PATH.exists()
    contour = pl.read_parquet(CONTOUR_PATH)
    assert contour.height > 500
    assert contour["lon"].min() >= -180.0
    assert contour["lat"].max() <= 90.0


@pytest.mark.disable_socket
@pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
def test_la_carte_se_construit_dans_les_deux_themes(tableau, palette: dict) -> None:
    contour = pl.read_parquet(CONTOUR_PATH)
    figure = carte(classement(tableau, 8, 0.5), contour, palette)

    assert isinstance(figure, go.Figure)
    # Trait de côte + spots couverts + spots non couverts.
    assert len(figure.data) == 3


@pytest.mark.disable_socket
def test_la_carte_distingue_les_spots_non_couverts(tableau) -> None:
    """Ils doivent être VISIBLES et distincts, jamais retirés de la carte."""
    contour = pl.read_parquet(CONTOUR_PATH)
    classe = classement(tableau, 1, 0.5)
    figure = carte(classe, contour, CLAIR)

    non_couverts = [t for t in figure.data if t.marker.symbol == "circle-open"]
    assert len(non_couverts) == 1
    assert len(non_couverts[0].x) == classe["price_missing"].sum()
    # Le trait du symbole ouvert ne doit pas être la couleur du fond, sinon il
    # disparaît. Défaut réel, trouvé en regardant le rendu.
    assert non_couverts[0].marker.color != CLAIR["surface"]


@pytest.mark.disable_socket
@pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
def test_la_saisonnalite_couvre_les_douze_mois(tableau, palette: dict) -> None:
    serie = tableau.filter(pl.col("spot_id") == "uluwatu").sort("month")
    figure = saisonnalite(serie, mois_actif=8, c=palette)

    assert isinstance(figure, go.Figure)
    assert len(figure.data[0].x) == 12
    # Le mois actif est mis en avant : deux teintes distinctes sur les barres.
    assert len(set(figure.data[0].marker.color)) == 2
