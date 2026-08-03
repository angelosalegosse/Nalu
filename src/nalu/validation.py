"""Validation externe : confronter le pic calculé à ce que le monde du surf publie.

    DIAGRAMME — la métrique est déclarée avant d'être mesurée
    (à vérifier dans tout commit modifiant ce fichier)

        data/scores/climatology.parquet        data/validation_seasons.yaml
        (240 lignes, p_surf par spot x mois)   (ECRIT AVANT toute mesure)
                     |                                      |
                     v                                      v
              pic_calcule()                        charger_reference()
              mois du p_surf max                   (a) mois d'epreuve WSL
                     |                             (b) haute saison publiee
                     |                                      |
                     +------------------+-------------------+
                                        v
                               confronter()
                     accord binaire + ecart circulaire en mois
                                        |
                                        v
                            SEUIL_ACCORD_MIN (declare ici)
                            notebook 02, verdict honnete

**Pourquoi ce fichier existe plutôt qu'un bloc de code dans le notebook.** Un
notebook s'édite pendant qu'on le lit, et une métrique qui vit dans une cellule peut
être réécrite après avoir vu son résultat sans que personne ne le voie. Ici, la
métrique et son seuil sont du code testé, versionné, et daté par git. C'est la
différence entre valider et ajuster.

**Rien de ce fichier n'entre dans le modèle.** Il mesure, il ne corrige pas.
"""

from dataclasses import dataclass

import polars as pl
import yaml

from nalu.paths import DATA

REFERENCE_PATH = DATA / "validation_seasons.yaml"


# ─── Le seuil, déclaré AVANT la mesure ─────────────────────────────────────────

SEUIL_ACCORD_MIN = 0.70
"""Part minimale de spots dont le pic calculé tombe dans la haute saison publiée
pour que le modèle soit déclaré en accord avec les sources externes : **14 spots
sur 20**.

Pourquoi 70 % et pas 90 % : le modèle a trois angles morts connus et assumés — pas
de marée, maille ERA5 à 50 km, et des seuils sourcés spot par spot avec une
confiance variable. Exiger la quasi-perfection reviendrait à garantir l'échec, donc
à justifier un ajustement des seuils, c'est-à-dire exactement ce que cette validation
doit interdire.

Pourquoi pas 50 % : un accord d'une chance sur deux est ce que produirait le hasard
sur des fenêtres de cette largeur. Un seuil non falsifiable ne vaut rien.
"""

SEUIL_ECART_MEDIAN_MAX = 1.0
"""Écart médian maximal admis, en mois, entre le pic calculé et la fenêtre publiée.
Un modèle peut manquer la fenêtre de peu sur plusieurs spots sans être faux ; il
devient faux s'il se trompe de saison. Un mois est la limite de ce que la résolution
mensuelle du produit permet de distinguer."""

TOLERANCE_WSL_MOIS = 1
"""Une épreuve WSL a une période d'attente de 10 à 14 jours et peut déborder sur le
mois voisin. Comparer au mois exact serait plus sévère que la réalité de la source."""


@dataclass(frozen=True)
class Verdict:
    """Le résultat de la confrontation, chiffres bruts compris."""

    accord_saison: float
    ecart_median: float
    accord_wsl: float | None
    spots_total: int
    spots_en_accord: int
    spots_sans_pic: tuple[str, ...]

    @property
    def reussi(self) -> bool:
        """Les deux conditions déclarées plus haut, ni l'une ni l'autre seule."""
        return (
            self.accord_saison >= SEUIL_ACCORD_MIN
            and self.ecart_median <= SEUIL_ECART_MEDIAN_MAX
        )


# ─── Chargement ────────────────────────────────────────────────────────────────


def charger_reference(chemin=None) -> pl.DataFrame:
    """Le référentiel de validation, tel qu'écrit avant toute mesure."""
    chemin = chemin if chemin is not None else REFERENCE_PATH
    brut = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    return pl.DataFrame(
        {
            "spot_id": [e["id"] for e in brut],
            "saison_publiee": [list(e["saison_publiee"]) for e in brut],
            "source_saison": [e["source_saison"] for e in brut],
            "wsl_ct_mois": [list(e.get("wsl_ct_mois") or []) for e in brut],
            "note": [e.get("note") for e in brut],
        }
    )


# ─── Distance circulaire ───────────────────────────────────────────────────────


def ecart_mois(a: int, b: int) -> int:
    """Distance cyclique entre deux mois, en mois. Décembre et janvier sont à 1.

    Un écart linéaire dirait 11, ce qui ferait passer un modèle juste pour faux
    sur tous les spots dont la saison est à cheval sur l'année.
    """
    brut = abs(a - b)
    return min(brut, 12 - brut)


def ecart_a_la_fenetre(mois: int, fenetre: list[int]) -> int:
    """0 si le mois est dans la fenêtre, sinon la distance au mois le plus proche."""
    if not fenetre:
        raise ValueError("fenêtre vide : aucune référence à confronter")
    if mois in fenetre:
        return 0
    return min(ecart_mois(mois, m) for m in fenetre)


# ─── Pic calculé ───────────────────────────────────────────────────────────────


def pic_calcule(climatologie: pl.DataFrame) -> pl.DataFrame:
    """Le mois de `p_surf` maximal par spot, et si ce pic a seulement un sens.

    `pic_defini` est faux quand `p_surf` est nul sur les douze mois : il n'y a alors
    pas de pic, seulement une égalité. Le distinguer est ce qui empêche de compter
    un `argmax` arbitraire comme une réussite ou un échec de saison.
    """
    return (
        climatologie.sort("spot_id", "month")
        .group_by("spot_id")
        .agg(
            pl.col("month").sort_by("p_surf", descending=True).first().alias("pic_mois"),
            pl.col("p_surf").max().alias("p_surf_max"),
        )
        .with_columns((pl.col("p_surf_max") > 0.0).alias("pic_defini"))
        .sort("spot_id")
    )


# ─── Confrontation ─────────────────────────────────────────────────────────────


def table_de_confrontation(
    climatologie: pl.DataFrame, reference: pl.DataFrame | None = None
) -> pl.DataFrame:
    """Une ligne par spot : pic calculé, fenêtres publiées, accord et écart.

    C'est la table que le notebook affiche telle quelle. Elle contient les échecs
    autant que les réussites : un tableau qui ne montrerait que les seconds ne
    serait pas une validation.
    """
    reference = reference if reference is not None else charger_reference()
    table = pic_calcule(climatologie).join(reference, on="spot_id", how="inner")

    accords, ecarts, accords_wsl = [], [], []
    for ligne in table.iter_rows(named=True):
        # Un spot sans pic défini compte comme un ÉCHEC, et non comme une exclusion.
        # Décidé avant la mesure : écarter après coup les spots qui échouent est la
        # façon la plus courante de faire dire à une validation ce qu'on veut.
        if not ligne["pic_defini"]:
            accords.append(False)
            ecarts.append(None)
            accords_wsl.append(None if not ligne["wsl_ct_mois"] else False)
            continue

        mois = ligne["pic_mois"]
        ecart = ecart_a_la_fenetre(mois, ligne["saison_publiee"])
        accords.append(ecart == 0)
        ecarts.append(ecart)
        accords_wsl.append(
            ecart_a_la_fenetre(mois, ligne["wsl_ct_mois"]) <= TOLERANCE_WSL_MOIS
            if ligne["wsl_ct_mois"]
            else None
        )

    return table.with_columns(
        pl.Series("accord_saison", accords, dtype=pl.Boolean),
        pl.Series("ecart_mois", ecarts, dtype=pl.Int64),
        pl.Series("accord_wsl", accords_wsl, dtype=pl.Boolean),
    ).select(
        "spot_id", "pic_mois", "p_surf_max", "pic_defini",
        "saison_publiee", "accord_saison", "ecart_mois",
        "wsl_ct_mois", "accord_wsl", "source_saison", "note",
    )


def confronter(
    climatologie: pl.DataFrame, reference: pl.DataFrame | None = None
) -> Verdict:
    """Le verdict global, à confronter aux seuils déclarés en tête de ce fichier."""
    table = table_de_confrontation(climatologie, reference)
    total = table.height
    en_accord = int(table["accord_saison"].sum())

    # L'écart médian n'a de sens que sur les spots ayant un pic. Les spots sans pic
    # sont déjà comptés comme des échecs dans `accord_saison` : les compter deux fois
    # dans l'écart écraserait la médiane sans rien apprendre de plus.
    ecarts = table.filter(pl.col("ecart_mois").is_not_null())["ecart_mois"]
    wsl = table.filter(pl.col("accord_wsl").is_not_null())["accord_wsl"]

    return Verdict(
        accord_saison=en_accord / total if total else 0.0,
        ecart_median=float(ecarts.median()) if ecarts.len() else float("inf"),
        accord_wsl=float(wsl.mean()) if wsl.len() else None,
        spots_total=total,
        spots_en_accord=en_accord,
        spots_sans_pic=tuple(
            table.filter(~pl.col("pic_defini"))["spot_id"].to_list()
        ),
    )
