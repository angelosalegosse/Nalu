"""La validation externe doit être capable d'échouer, sinon elle ne valide rien.

Ces tests portent sur la MÉTRIQUE, pas sur son résultat. Un test qui exigerait que
le modèle réussisse transformerait le premier échec en incitation à retoucher les
seuils du modèle — exactement ce que la révision d'ingénierie interdit.
"""

import polars as pl
import pytest

from nalu.validation import (
    REFERENCE_PATH,
    SEUIL_ACCORD_MIN,
    charger_reference,
    confronter,
    ecart_a_la_fenetre,
    ecart_mois,
    pic_calcule,
    table_de_confrontation,
)


def climatologie(pics: dict[str, int], plat: tuple[str, ...] = ()) -> pl.DataFrame:
    """Une climatologie synthétique : `p_surf` maximal au mois demandé."""
    lignes = []
    for spot, pic in pics.items():
        for mois in range(1, 13):
            valeur = 0.0 if spot in plat else (0.5 if mois == pic else 0.1)
            lignes.append({"spot_id": spot, "month": mois, "p_surf": valeur})
    return pl.DataFrame(
        lignes,
        schema={"spot_id": pl.String, "month": pl.Int8, "p_surf": pl.Float64},
    )


# ─── Distance circulaire : le bug le plus probable de ce fichier ───────────────


def test_l_ecart_entre_decembre_et_janvier_vaut_un_mois() -> None:
    """Un écart linéaire dirait 11 et déclarerait faux tout spot à cheval sur l'année."""
    assert ecart_mois(12, 1) == 1


def test_l_ecart_est_symetrique() -> None:
    assert ecart_mois(1, 12) == ecart_mois(12, 1)


def test_l_ecart_maximal_vaut_six_mois() -> None:
    assert ecart_mois(1, 7) == 6
    assert max(ecart_mois(a, b) for a in range(1, 13) for b in range(1, 13)) == 6


def test_un_mois_est_a_distance_nulle_de_lui_meme() -> None:
    assert all(ecart_mois(m, m) == 0 for m in range(1, 13))


def test_un_mois_dans_la_fenetre_est_a_distance_nulle() -> None:
    assert ecart_a_la_fenetre(11, [10, 11, 12]) == 0


def test_la_distance_a_une_fenetre_franchit_le_passage_par_janvier() -> None:
    assert ecart_a_la_fenetre(2, [11, 12, 1]) == 1


def test_une_fenetre_vide_est_une_erreur_et_non_un_accord() -> None:
    """Renvoyer 0 sur une fenêtre vide compterait une absence de source comme un succès."""
    with pytest.raises(ValueError):
        ecart_a_la_fenetre(5, [])


# ─── Pic calculé ───────────────────────────────────────────────────────────────


def test_le_pic_est_le_mois_de_p_surf_maximal() -> None:
    resultat = pic_calcule(climatologie({"a": 7}))
    assert resultat["pic_mois"][0] == 7
    assert resultat["pic_defini"][0]


def test_un_spot_entierement_nul_n_a_pas_de_pic_defini() -> None:
    """Sinon un `argmax` arbitraire serait compté comme une saison."""
    resultat = pic_calcule(climatologie({"a": 7}, plat=("a",)))
    assert not resultat["pic_defini"][0]


# ─── Confrontation ─────────────────────────────────────────────────────────────


REFERENCE_JOUET = pl.DataFrame(
    {
        "spot_id": ["juste", "rate", "muet"],
        "saison_publiee": [[6, 7, 8], [6, 7, 8], [6, 7, 8]],
        "source_saison": ["https://exemple"] * 3,
        "wsl_ct_mois": [[7], [], []],
        "note": [None, None, None],
    }
)


def test_un_pic_dans_la_fenetre_est_un_accord() -> None:
    table = table_de_confrontation(climatologie({"juste": 7}), REFERENCE_JOUET)
    assert table["accord_saison"][0]
    assert table["ecart_mois"][0] == 0


def test_un_pic_hors_fenetre_est_un_echec_avec_son_ecart() -> None:
    table = table_de_confrontation(climatologie({"rate": 1}), REFERENCE_JOUET)
    assert not table["accord_saison"][0]
    assert table["ecart_mois"][0] == 5


def test_un_spot_sans_pic_compte_comme_un_echec_et_non_une_exclusion() -> None:
    """Écarter après coup les spots qui échouent est la façon la plus courante de
    faire dire à une validation ce qu'on veut lui faire dire."""
    table = table_de_confrontation(climatologie({"muet": 1}, plat=("muet",)), REFERENCE_JOUET)

    assert not table["accord_saison"][0]
    assert table["ecart_mois"][0] is None

    verdict = confronter(climatologie({"muet": 1}, plat=("muet",)), REFERENCE_JOUET)
    assert verdict.spots_total == 1
    assert verdict.spots_en_accord == 0
    assert verdict.spots_sans_pic == ("muet",)


def test_la_metrique_sait_echouer() -> None:
    """Contre-épreuve : une métrique qui réussit toujours ne mesure rien."""
    verdict = confronter(climatologie({"rate": 1}), REFERENCE_JOUET)
    assert not verdict.reussi


def test_la_metrique_sait_reussir() -> None:
    verdict = confronter(climatologie({"juste": 7}), REFERENCE_JOUET)
    assert verdict.reussi
    assert verdict.accord_saison == 1.0


def test_l_accord_wsl_tolere_un_mois_de_periode_d_attente() -> None:
    """Une épreuve a 10 à 14 jours de fenêtre et peut déborder sur le mois voisin."""
    table = table_de_confrontation(climatologie({"juste": 8}), REFERENCE_JOUET)
    assert table["accord_wsl"][0]


def test_l_accord_wsl_est_nul_quand_le_spot_n_accueille_pas_d_epreuve() -> None:
    table = table_de_confrontation(climatologie({"rate": 7}), REFERENCE_JOUET)
    assert table["accord_wsl"][0] is None


# ─── Le référentiel lui-même ───────────────────────────────────────────────────


def test_le_referentiel_couvre_les_vingt_spots() -> None:
    assert charger_reference().height == 20


def test_chaque_spot_du_referentiel_porte_une_source() -> None:
    reference = charger_reference()
    sans_source = reference.filter(
        pl.col("source_saison").is_null() | (pl.col("source_saison").str.len_chars() == 0)
    )
    assert sans_source.is_empty(), sans_source["spot_id"].to_list()


def test_les_sources_sont_des_url() -> None:
    reference = charger_reference()
    assert reference["source_saison"].str.starts_with("https://").all()


def test_les_mois_du_referentiel_sont_valides() -> None:
    for ligne in charger_reference().iter_rows(named=True):
        assert ligne["saison_publiee"], f"{ligne['spot_id']} sans saison publiée"
        for mois in list(ligne["saison_publiee"]) + list(ligne["wsl_ct_mois"]):
            assert 1 <= mois <= 12, f"{ligne['spot_id']} : mois {mois} invalide"


def test_les_fenetres_publiees_ne_couvrent_pas_toute_l_annee() -> None:
    """Une fenêtre de douze mois rendrait l'accord automatique sur ce spot."""
    for ligne in charger_reference().iter_rows(named=True):
        assert len(set(ligne["saison_publiee"])) <= 7, (
            f"{ligne['spot_id']} : fenêtre trop large pour valider quoi que ce soit"
        )


def test_le_referentiel_correspond_aux_spots_du_produit() -> None:
    from nalu.spots import load_raw_spots

    attendus = {s.id for s in load_raw_spots()}
    assert set(charger_reference()["spot_id"].to_list()) == attendus


def test_le_seuil_declare_reste_falsifiable() -> None:
    """Un seuil de 0 % ou de 100 % ne serait pas une validation."""
    assert 0.5 < SEUIL_ACCORD_MIN < 1.0


def test_le_referentiel_est_versionne() -> None:
    """Son historique git est ce qui prouve qu'il précède la mesure."""
    assert REFERENCE_PATH.exists()
