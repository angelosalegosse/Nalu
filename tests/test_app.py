"""Dashboard : les figures se construisent, hors ligne, sur les données réelles.

Un test de fumée, pas un test de rendu. Il attrape ce qui casse le plus souvent —
une colonne renommée, un fichier absent — sans prétendre juger l'apparence.
"""

import plotly.graph_objects as go
import polars as pl
import pytest

from nalu import app
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


# ─── Le planisphère ne doit pas déborder de sa boîte ───────────────────────────
#
# Bug trouvé le 2026-08-03 en ouvrant la page à 1920 px, pas par la suite de tests :
# un `max-height` posé sur le même élément qu'un `aspect-ratio` entrait en conflit
# avec lui. Le navigateur tranchait en rétrécissant la LARGEUR de la boîte (1255 px)
# pendant que Plotly dessinait son SVG à la taille du parent (1760 px). Tout le tiers
# droit de la carte était coupé — Japon, est de l'Australie, Nouvelle-Zélande, et
# deux marqueurs de spots purement invisibles.
#
# Mesures avant correction :  1280 -> 0 px de debordement | 1440 -> 25 | 1920 -> 505
#                             2560 -> 1145
# Apres :                     0 px a toutes ces largeurs, mobile compris.


def test_le_plafond_de_la_carte_porte_sur_la_largeur_pas_la_hauteur() -> None:
    """C'est LA regression. `max-height` reintroduit, la carte se fait couper."""
    css = app.style_planisphere()

    assert "max-width" in css
    assert "max-height" not in css, (
        "un max-height sur l'element porteur de l'aspect-ratio recoupe la carte"
    )


def test_le_plafond_de_largeur_est_coherent_avec_le_rapport_de_forme() -> None:
    """Les deux plafonds doivent decrire la MEME boite, sinon l'un contredit l'autre."""
    attendu = round(app.CARTE_HAUTEUR_MAX * app.CARTE_LON_SPAN / app.CARTE_LAT_SPAN)

    assert attendu == app.CARTE_LARGEUR_MAX


def test_le_rapport_de_forme_du_css_est_celui_des_axes_de_la_figure() -> None:
    """Le CSS et la figure doivent parler de la meme carte."""
    css = app.style_planisphere()

    assert f"aspect-ratio: {app.CARTE_LON_SPAN} / {app.CARTE_LAT_SPAN}" in css
    assert app.CARTE_LON[1] - app.CARTE_LON[0] == app.CARTE_LON_SPAN
    assert app.CARTE_LAT[1] - app.CARTE_LAT[0] == app.CARTE_LAT_SPAN


def test_la_hauteur_de_la_carte_reste_sous_son_plafond_a_toute_largeur() -> None:
    """La hauteur etant derivee, on peut la calculer sans navigateur."""
    for largeur in (390, 768, 1280, 1440, 1920, 2560):
        effective = min(largeur, app.CARTE_LARGEUR_MAX)
        hauteur = effective * app.CARTE_LAT_SPAN / app.CARTE_LON_SPAN
        assert hauteur <= app.CARTE_HAUTEUR_MAX + 1, (largeur, hauteur)
