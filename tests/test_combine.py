"""Score en rangs centiles : bornes du curseur et invariance aux extrêmes.

`test_ajouter_un_prix_aberrant_ne_change_pas_l_ordre` est le test qui PROUVE le
passage aux rangs. Sans lui, « les rangs sont insensibles aux extrêmes » n'est
qu'une affirmation.
"""

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from nalu.scoring.combine import (
    RANG_SANS_PRIX,
    appliquer_alpha,
    classement,
    construire_tableau,
    rang_centile,
)

NOMBRE_DE_COUPLES = 240


def rangs_de(prix: list[float | None]) -> list[float]:
    return (
        pl.DataFrame({"price_eur": prix}, schema={"price_eur": pl.Float64})
        .with_columns(rang_centile("price_eur", descendant=True).alias("r"))["r"]
        .to_list()
    )


def ordre_de(rangs: list[float]) -> list[int]:
    """Indices triés du mieux classé au moins bien. C'est l'ordre qui doit être stable."""
    return sorted(range(len(rangs)), key=lambda i: (-rangs[i], i))


# --- Invariance aux extrêmes : LE test ----------------------------------------


@settings(max_examples=300, deadline=None)
@given(
    prix=st.lists(
        st.floats(50, 2000, allow_nan=False, allow_infinity=False),
        min_size=3,
        max_size=30,
        unique=True,
    ),
    facteur=st.floats(10, 10_000, allow_nan=False),
)
def test_ajouter_un_prix_aberrant_ne_change_pas_l_ordre(
    prix: list[float], facteur: float
) -> None:
    """La preuve du passage aux rangs centiles.

    Un billet à 1 800 € tassait, en min-max, tous les autres dans les quinze derniers
    pourcents et rendait le curseur inerte sur la moitié de sa course. Le rang ne
    connaît que l'ordre : une valeur aberrante prend un rang, elle n'écrase personne.
    """
    avant = ordre_de(rangs_de(prix))
    aberrant = max(prix) * facteur
    apres_rangs = rangs_de([*prix, aberrant])[: len(prix)]
    assert ordre_de(apres_rangs) == avant


def test_le_min_max_aurait_ete_ecrase_par_l_aberrant() -> None:
    """Contre-épreuve : ce que la normalisation min-max aurait fait.

    Ce test ne protège pas le code, il documente la raison de la décision. Il échoue
    si quelqu'un remet une normalisation min-max sans s'en rendre compte.
    """
    prix = [100.0, 200.0, 300.0]

    def min_max(valeurs: list[float]) -> list[float]:
        bas, haut = min(valeurs), max(valeurs)
        return [1 - (v - bas) / (haut - bas) for v in valeurs]

    serre = min_max(prix)
    ecrase = min_max([*prix, 100_000.0])[: len(prix)]

    # L'ordre survit, mais l'ÉCHELLE s'effondre : les trois premiers deviennent
    # indiscernables, et le curseur n'a plus de prise sur eux.
    assert serre[0] - serre[2] == pytest.approx(1.0)
    assert ecrase[0] - ecrase[2] < 0.01

    # Les rangs, eux, conservent tout l'écart.
    rangs = rangs_de([*prix, 100_000.0])[: len(prix)]
    assert rangs[0] - rangs[2] == pytest.approx(2 / 3, abs=0.01)


# --- Cas limites des rangs -----------------------------------------------------


def test_des_prix_tous_identiques_donnent_le_meme_rang() -> None:
    """Aucune division par zéro, et personne n'est avantagé arbitrairement."""
    rangs = rangs_de([500.0, 500.0, 500.0])
    assert rangs[0] == rangs[1] == rangs[2]


def test_les_ex_aequo_partagent_le_rang_moyen() -> None:
    rangs = rangs_de([100.0, 200.0, 200.0, 300.0])
    assert rangs[1] == rangs[2]
    assert rangs[0] > rangs[1] > rangs[3]


def test_un_seul_prix_couvert_recoit_le_rang_maximal() -> None:
    rangs = rangs_de([500.0, None, None])
    assert rangs[0] == pytest.approx(1.0)
    assert rangs[1] is None and rangs[2] is None


def test_le_moins_cher_obtient_le_rang_le_plus_eleve() -> None:
    rangs = rangs_de([100.0, 500.0, 900.0])
    assert rangs[0] > rangs[1] > rangs[2]
    assert rangs[0] == pytest.approx(1.0)
    assert rangs[2] == pytest.approx(0.0)


# --- Le curseur ----------------------------------------------------------------


@pytest.fixture(scope="module")
def tableau() -> pl.DataFrame:
    return construire_tableau()


@pytest.mark.disable_socket
def test_le_tableau_contient_les_240_couples(tableau: pl.DataFrame) -> None:
    assert tableau.height == NOMBRE_DE_COUPLES


@pytest.mark.disable_socket
def test_a_alpha_zero_le_premier_est_le_billet_le_moins_cher(tableau: pl.DataFrame) -> None:
    for mois in range(1, 13):
        classe = classement(tableau, mois, alpha=0.0)
        couverts = classe.filter(~pl.col("price_missing"))
        if not couverts.height:
            continue
        assert classe["price_eur"][0] == couverts["price_eur"].min(), mois


@pytest.mark.disable_socket
def test_a_alpha_un_le_premier_est_la_meilleure_houle(tableau: pl.DataFrame) -> None:
    for mois in range(1, 13):
        classe = classement(tableau, mois, alpha=1.0)
        attendu = tableau.filter(pl.col("month") == mois)["q"].max()
        assert classe["q"][0] == pytest.approx(attendu), mois


@pytest.mark.disable_socket
def test_le_curseur_reordonne_vraiment(tableau: pl.DataFrame) -> None:
    """Si les deux bornes donnaient le même ordre, le curseur serait décoratif."""
    prix_d_abord = classement(tableau, 8, 0.0)["spot_id"].to_list()
    houle_d_abord = classement(tableau, 8, 1.0)["spot_id"].to_list()
    assert prix_d_abord != houle_d_abord


@pytest.mark.disable_socket
def test_un_alpha_hors_bornes_est_refuse(tableau: pl.DataFrame) -> None:
    for alpha in (-0.1, 1.1):
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            appliquer_alpha(tableau, alpha)


# --- Spots non couverts --------------------------------------------------------


@pytest.mark.disable_socket
def test_un_spot_sans_prix_reste_affiche_avec_un_rang_nul(tableau: pl.DataFrame) -> None:
    """Le retirer laisserait le biais de couverture décider du contenu du produit."""
    absents = tableau.filter("price_missing")
    assert absents.height > 0
    assert absents["rank_price"].to_list() == [RANG_SANS_PRIX] * absents.height
    assert absents["price_eur"].null_count() == absents.height


@pytest.mark.disable_socket
def test_les_vingt_spots_sont_presents_chaque_mois(tableau: pl.DataFrame) -> None:
    for mois in range(1, 13):
        assert tableau.filter(pl.col("month") == mois).height == 20, mois


# --- Portée de la normalisation ------------------------------------------------


def test_les_rangs_portent_sur_le_corpus_entier_pas_par_groupe() -> None:
    """Un rang calculé par mois rendrait les scores incomparables d'un mois à l'autre.

    Jeu construit pour que les deux méthodes divergent : le mois 2 est bien plus cher
    que le mois 1, ce qu'un rang par groupe effacerait complètement.
    """
    trame = pl.DataFrame(
        {
            "month": [1, 1, 2, 2],
            "price_eur": [100.0, 200.0, 1000.0, 2000.0],
        }
    )
    global_ = trame.with_columns(rang_centile("price_eur", descendant=True).alias("r"))
    par_groupe = trame.with_columns(
        rang_centile("price_eur", descendant=True).over("month").alias("r")
    )

    # Par groupe, le billet a 1000 € recoit le meme rang que celui a 100 € : faux.
    assert par_groupe["r"].to_list() == [1.0, 0.0, 1.0, 0.0]
    # Globalement, l'ordre reel est conserve.
    assert global_["r"].to_list() == [1.0, pytest.approx(2 / 3), pytest.approx(1 / 3), 0.0]


# --- Promesse hors ligne -------------------------------------------------------


@pytest.mark.disable_socket
def test_la_chaine_complete_tourne_sans_reseau() -> None:
    """Le critère central de l'epic, enfin testé de bout en bout.

    Configuration, référentiel, climatologie, prix, rangs, score : toute la chaîne
    depuis le dépôt, sans un octet de réseau. Un appel accidentel lève ici.
    """
    complet = construire_tableau()
    classe = classement(complet, mois=8, alpha=0.5)

    assert classe.height == 20
    assert classe["score"].is_not_null().all()
    assert classe["score"].min() >= 0.0
    assert classe["score"].max() <= 1.0
    assert classe["rang"][0] == 1
