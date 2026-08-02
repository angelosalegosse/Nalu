"""Polygones de côtes Natural Earth, en cache local.

Natural Earth est dans le domaine public : aucune restriction d'usage, aucune
attribution obligatoire. C'est la raison pour laquelle il est préféré ici à toute
source sous licence, dans un projet qui vise 0 EUR et une vitrine publique.

Le fichier est téléchargé une fois dans `data/raw/` (ignoré par git) puis relu
depuis le disque. Il ne sert qu'à **régénérer** les fenêtres d'exposition ; une
fois écrites dans `data/spots.yaml`, plus rien ne dépend de lui à l'exécution.
C'est ce qui permet à la démo de tourner sans réseau.

Deux jeux sont fusionnés :
  - `ne_10m_land`           : les masses continentales et les îles principales ;
  - `ne_10m_minor_islands`  : les petites îles, absentes du premier. Sans elles,
                              un spot comme Teahupo'o ou Cloudbreak se retrouve en
                              plein océan et reçoit un arc complet, donc faux.
"""

import json
from pathlib import Path

import shapely
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from nalu.net import use_system_trust_store

# Miroir GitHub officiel du projet Natural Earth. Le site naturalearthdata.com sert
# des ZIP de shapefiles, qui demanderaient un lecteur GDAL ; le miroir expose le
# meme contenu en GeoJSON, lisible avec la bibliotheque standard.
BASE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson"
JEUX = ("ne_10m_land", "ne_10m_minor_islands")

CACHE_DIR = Path("data/raw/natural_earth")


def download(jeu: str, cache_dir: Path = CACHE_DIR) -> Path:
    """Télécharge un jeu Natural Earth s'il n'est pas déjà en cache. Ré-entrant."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cible = cache_dir / f"{jeu}.geojson"
    if cible.exists() and cible.stat().st_size > 0:
        return cible

    import httpx

    use_system_trust_store()
    with httpx.stream("GET", f"{BASE_URL}/{jeu}.geojson", follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        # Ecriture via un fichier temporaire : une interruption reseau ne doit pas
        # laisser un GeoJSON tronque en cache, qui serait relu comme valide.
        provisoire = cible.with_suffix(".partiel")
        with provisoire.open("wb") as f:
            for bloc in r.iter_bytes():
                f.write(bloc)
    provisoire.replace(cible)
    return cible


CONTOUR_PATH = Path("data/world_outline.parquet")
CONTOUR_JEU = "ne_110m_land"
CONTOUR_TOLERANCE_DEG = 0.35
"""Simplification de Douglas-Peucker du trait de côte d'illustration. À 0,35 degré le
fichier tombe sous 40 Ko tout en restant lisible à l'échelle du planisphère."""


def exporter_contour_mondial(
    chemin: Path = CONTOUR_PATH, cache_dir: Path = CACHE_DIR
) -> Path:
    """Écrit un planisphère simplifié, versionné, pour le fond de carte du dashboard.

    Pourquoi ce détour : `scatter_geo` de Plotly télécharge sa topologie depuis un CDN.
    Sur une démo qui doit tourner **sans réseau**, la carte resterait vide. Natural
    Earth est déjà une dépendance du projet et est dans le domaine public : on en tire
    un tracé local une fois pour toutes.
    """
    import polars as pl

    source = download(CONTOUR_JEU, cache_dir)
    with source.open(encoding="utf-8") as f:
        collection = json.load(f)

    lons: list[float | None] = []
    lats: list[float | None] = []
    for entite in collection["features"]:
        geometrie = shape(entite["geometry"]).simplify(CONTOUR_TOLERANCE_DEG)
        morceaux = getattr(geometrie, "geoms", [geometrie])
        for morceau in morceaux:
            x, y = morceau.exterior.coords.xy
            lons.extend([round(v, 3) for v in x] + [None])  # None coupe le trait
            lats.extend([round(v, 3) for v in y] + [None])

    chemin.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"lon": lons, "lat": lats}).write_parquet(chemin, compression="zstd")
    return chemin


def load_land(cache_dir: Path = CACHE_DIR, jeux: tuple[str, ...] = JEUX) -> BaseGeometry:
    """Géométrie unique de toutes les terres émergées, préparée pour l'intersection.

    `shapely.prepare` construit un index spatial interne : sans lui, chaque rayon
    testerait toutes les côtes du globe une par une.
    """
    geometries = []
    for jeu in jeux:
        chemin = download(jeu, cache_dir)
        with chemin.open(encoding="utf-8") as f:
            collection = json.load(f)
        geometries.extend(shape(entite["geometry"]) for entite in collection["features"])

    terre = unary_union(geometries)
    shapely.prepare(terre)
    return terre
