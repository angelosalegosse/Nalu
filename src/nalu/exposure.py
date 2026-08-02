"""Calcul des fenêtres d'exposition à la houle, par lancer de rayons.

    `uv run python -m nalu.exposure`

Régénère `data/exposure_windows.yaml` à partir de `data/spots.yaml` et des côtes
Natural Earth. C'est la seule étape du projet qui a besoin du réseau pour autre
chose que l'ingestion : une fois le fichier écrit, plus rien n'en dépend.

Le calcul est déterministe. Relancé sur les mêmes entrées, il produit un fichier
identique — ce qui rend tout changement de fenêtre visible dans un diff, et donc
imputable soit à un déplacement de coordonnée, soit à un changement de paramètre.
"""

import argparse
import sys
from pathlib import Path

import yaml
from shapely.geometry import Point

from nalu.coastline import CACHE_DIR, load_land
from nalu.config import CONFIG
from nalu.geo import arc_span, compute_exposure_window
from nalu.spots import SPOTS_PATH, WINDOWS_PATH, Spot, load_raw_spots

ENTETE = """\
# FICHIER GÉNÉRÉ — ne pas éditer à la main.
#
#   uv run python -m nalu.exposure
#
# Fenêtres d'exposition à la houle, obtenues par lancer de rayons depuis chaque spot
# sur les polygones de côtes Natural Earth (domaine public). Un secteur est retenu
# quand le rayon atteint {reach:.0f} km d'océan ouvert sans rencontrer la terre ; la
# fenêtre est la plus longue plage circulaire de secteurs retenus.
#
# Pas angulaire : {step} degrés ({rayons} rayons par spot).
#
# Ces valeurs sont CALCULÉES, pas déclarées. Pour en remplacer une, renseigner
# `swell_dir_override` dans data/spots.yaml — `override_reason` devient alors
# obligatoire.
"""


def calculer(spots: list[Spot], cache_dir: Path = CACHE_DIR) -> dict[str, dict[str, float]]:
    """Fenêtre d'exposition de chaque spot. Lève si un spot n'a aucun rayon libre."""
    terre = load_land(cache_dir)

    fenetres: dict[str, dict[str, float]] = {}
    fermes: list[str] = []
    for spot in spots:
        # Diagnostic explicite : « posé dans les terres » et « fond de baie fermée »
        # se corrigent différemment, et sans le dire on cherche au mauvais endroit.
        if terre.contains(Point(spot.lon, spot.lat)):
            fermes.append(f"{spot.id} (coordonnée DANS les terres — la déplacer au large)")
            continue
        fenetre = compute_exposure_window(spot.lat, spot.lon, terre)
        if fenetre is None:
            fermes.append(f"{spot.id} (aucun rayon libre — baie fermée ?)")
            continue
        debut, fin = fenetre
        fenetres[spot.id] = {
            "swell_dir_min": round(debut, 1),
            "swell_dir_max": round(fin, 1),
            "arc_deg": round(arc_span(debut, fin), 1),
        }

    if fermes:
        raise ValueError(
            "fenêtre d'exposition impossible à calculer pour :\n  - "
            + "\n  - ".join(fermes)
            + "\nVérifier lat/lon avant d'envisager un swell_dir_override."
        )
    return fenetres


def ecrire(fenetres: dict[str, dict[str, float]], chemin: Path = WINDOWS_PATH) -> None:
    entete = ENTETE.format(
        reach=CONFIG.open_ocean_km,
        step=CONFIG.ray_step_deg,
        rayons=int(360 / CONFIG.ray_step_deg),
    )
    corps = yaml.safe_dump(
        {"windows": fenetres}, allow_unicode=True, sort_keys=True, default_flow_style=False
    )
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(entete + corps, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--spots", type=Path, default=SPOTS_PATH)
    parseur.add_argument("--out", type=Path, default=WINDOWS_PATH)
    parseur.add_argument("--cache", type=Path, default=CACHE_DIR)
    args = parseur.parse_args(argv)

    spots = load_raw_spots(args.spots)
    print(f"{len(spots)} spots, {int(360 / CONFIG.ray_step_deg)} rayons chacun...")

    fenetres = calculer(spots, args.cache)
    ecrire(fenetres, args.out)

    a_cheval = sum(1 for f in fenetres.values() if f["swell_dir_max"] < f["swell_dir_min"])
    print(f"écrit {args.out} — {len(fenetres)} fenêtres, {a_cheval} à cheval sur 0 degré")
    for spot in spots:
        f = fenetres[spot.id]
        print(
            f"  {spot.id:<24} {f['swell_dir_min']:>5.1f} -> {f['swell_dir_max']:>5.1f}"
            f"   ({f['arc_deg']:>5.1f} deg)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
