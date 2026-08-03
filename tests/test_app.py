"""Dashboard : les figures se construisent, hors ligne, sur les données réelles.

Un test de fumée, pas un test de rendu. Il attrape ce qui casse le plus souvent —
une colonne renommée, un fichier absent — sans prétendre juger l'apparence.
"""

import plotly.graph_objects as go
import polars as pl
import pytest

from nalu import app
from nalu.app import (
    AIDES_COLONNES,
    CLAIR,
    COL_PRIX,
    MOIS,
    MOIS_COURT,
    SANS_PRIX,
    SOMBRE,
    carte,
    saisonnalite,
)
from nalu.coastline import CONTOUR_PATH
from nalu.paths import RACINE
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
def test_les_deux_classes_de_marqueurs_sont_nommees_dans_une_legende(tableau) -> None:
    """Sans legende, un anneau gris se lit comme une mauvaise vague, pas comme un trou.

    Defaut trouve en ouvrant la page : le visiteur voyait onze anneaux et neuf disques
    sans qu'aucun element de la figure ne dise que la difference est une COUVERTURE DE
    DONNEES. Le trait de cote, lui, n'a rien a nommer et doit rester hors legende.
    """
    contour = pl.read_parquet(CONTOUR_PATH)
    figure = carte(classement(tableau, 1, 0.5), contour, CLAIR)

    nommees = [t for t in figure.data if t.showlegend]
    assert len(nommees) == 2, "les deux classes de marqueurs, et elles seules"
    assert {t.name for t in nommees} == {"prix connu", "prix non couvert"}
    # Un clic de legende masque la serie chez Plotly : effacer onze spots par megarde,
    # sans indice pour les retablir, coute plus que le filtre ne rapporte.
    assert figure.layout.legend.itemclick is False


@pytest.mark.disable_socket
@pytest.mark.parametrize("palette", [CLAIR, SOMBRE], ids=["clair", "sombre"])
def test_la_saisonnalite_couvre_les_douze_mois(tableau, palette: dict) -> None:
    serie = tableau.filter(pl.col("spot_id") == "uluwatu").sort("month")
    figure = saisonnalite(serie, mois_actif=8, c=palette)

    assert isinstance(figure, go.Figure)
    assert len(figure.data[0].x) == 12
    # Le mois actif est mis en avant : deux teintes distinctes sur les barres.
    assert len(set(figure.data[0].marker.color)) == 2


# ─── Les douze mois doivent rester DOUZE une fois abreges ─────────────────────
#
# Regression faillie le 2026-08-03, attrapee en regardant l'axe et non la suite : les
# libelles venaient d'une troncature a longueur fixe de `MOIS`. A quatre lettres elle
# donnait « avri », « octo », « nove », « déce », qui se lisent comme des fautes ; la
# corriger a trois lettres faisait collisionner « juin » et « juillet » sur « jui », et
# l'axe perdait un mois SANS QUE RIEN N'ECHOUE. Aucune longueur ne marche : il faut des
# abreviations posees. Ce test est la pour que la troncature ne revienne pas.


def test_les_abreviations_de_mois_sont_douze_et_toutes_distinctes() -> None:
    """Une collision ferait disparaitre un mois de l'axe, en silence."""
    assert len(MOIS_COURT) == 12
    assert len(set(MOIS_COURT)) == 12, "deux mois abreges pareil : l'axe perd une barre"


def test_chaque_abreviation_ouvre_bien_son_mois() -> None:
    """Elles sont posees a la main : rien ne garantit qu'elles designent le bon mois."""
    for long, court in zip(MOIS, MOIS_COURT, strict=True):
        assert long.startswith(court), (long, court)


# ─── La colonne des prix : ni « None », ni un tri faux ─────────────────────────
#
# `st.dataframe` peint « None » pour une valeur absente — la valeur Python brute, sur
# quatorze des vingt lignes. Verifie sur Streamlit 1.59.1 : ni `NumberColumn` ni son
# `format` ne la suppriment, seule une colonne de TEXTE le permet. Mais du texte se
# trie alphabetiquement, et les prix vont de 67 a 2299 € : sans alignement a droite,
# « 2299 € » passerait avant « 67 € » et un clic sur l'en-tete donnerait un ordre faux.


@pytest.fixture(scope="module")
def affichage(tableau) -> pl.DataFrame:
    return app.table_affichee(classement(tableau, 1, 0.5))


@pytest.mark.disable_socket
def test_un_spot_sans_prix_n_affiche_jamais_none(affichage) -> None:
    """C'est LE defaut visible : la valeur Python brute sur la moitie des lignes."""
    cases = affichage[COL_PRIX].to_list()

    assert "None" not in cases
    assert None not in cases
    assert SANS_PRIX in cases, "aucun spot non couvert : le test ne prouve plus rien"


@pytest.mark.disable_socket
def test_le_tri_alphabetique_des_prix_reste_l_ordre_numerique(affichage) -> None:
    """La colonne est du TEXTE : c'est l'alignement a droite qui sauve l'ordre."""
    connus = [c for c in affichage[COL_PRIX].to_list() if c != SANS_PRIX]
    valeurs = [float(c.replace("€", "").strip()) for c in connus]

    assert sorted(connus) == [c for _, c in sorted(zip(valeurs, connus, strict=True))]


@pytest.mark.disable_socket
def test_les_spots_sans_prix_se_rangent_en_fin_de_tri(affichage) -> None:
    """Un prix absent n'est pas le moins cher : il ne doit pas ouvrir le classement."""
    cases = sorted(affichage[COL_PRIX].to_list())

    assert cases[-1] == SANS_PRIX
    assert cases[0] != SANS_PRIX


# ─── Les colonnes doivent etre LISIBLES, et chacune expliquee ─────────────────
#
# Le tableau est la preuve du produit : illisible, il ne prouve rien. Les en-tetes
# portaient les noms internes du modele — « P_surf % », « rang Q » — qu'un lecteur qui
# n'a pas ouvert `combine.py` ne peut pas decoder. L'explication complete vit dans
# l'infobulle de l'en-tete, donc une colonne SANS entree d'aide perd son explication
# sans que rien ne le signale a l'ecran : l'infobulle disparait, c'est tout.


@pytest.mark.disable_socket
def test_chaque_colonne_affichee_porte_son_explication(affichage) -> None:
    """C'est LA regression silencieuse : renommer une colonne lui retire son infobulle."""
    manquantes = [nom for nom in affichage.columns if nom not in AIDES_COLONNES]

    assert not manquantes, f"colonnes sans aide de lecture : {manquantes}"


@pytest.mark.disable_socket
def test_aucune_aide_ne_designe_une_colonne_disparue(affichage) -> None:
    """Une aide orpheline ne s'affiche nulle part : elle ment sur ce que la page dit."""
    orphelines = [nom for nom in AIDES_COLONNES if nom not in affichage.columns]

    assert not orphelines, f"aides sans colonne : {orphelines}"


@pytest.mark.disable_socket
def test_le_guide_replie_nomme_chaque_colonne_du_tableau(affichage) -> None:
    """Une legende qui nomme une colonne absente est pire que pas de legende.

    Arrive : le guide annoncait « Taille relative » quand l'en-tete disait deja
    « Taille ». Les libelles sont desormais interpoles depuis les memes constantes, et
    ce test verifie qu'aucune colonne n'est passee sous silence.
    """
    guide = app.guide_de_lecture()
    absentes = [nom for nom in affichage.columns if nom not in guide]

    assert not absentes, f"colonnes que le guide ne nomme pas : {absentes}"


@pytest.mark.disable_socket
def test_aucun_en_tete_ne_porte_un_nom_de_variable(affichage) -> None:
    """« P_surf % », « rank_q » : des noms de code poses devant un lecteur.

    Le souligne est la marque de fabrique des identifiants du modele et n'apparait
    jamais dans un libelle francais. C'est un garde-fou grossier, et c'est voulu : il
    coute une ligne et attrape le retour en arriere le plus probable.
    """
    fautifs = [nom for nom in affichage.columns if "_" in nom]

    assert not fautifs, f"noms de variables en en-tete : {fautifs}"


def test_aucune_chaine_seule_au_niveau_module_de_l_app() -> None:
    """La « magie » de Streamlit PEINT toute expression laissee seule sur sa ligne.

    `app.py` est le script execute, pas un module importe comme les autres : une
    docstring posee sous une constante — la forme employee partout ailleurs dans le
    depot, et notamment dans `combine.py` — devient un paragraphe affiche EN HAUT DE LA
    PAGE, au-dessus du titre. Vu a l'ecran le 2026-08-04 avec `ECART_EGALITE`, et aucun
    des 308 tests ne pouvait le voir : le module s'importe parfaitement.

    D'ou la regle, verifiee ici : dans ce fichier les constantes se documentent en
    COMMENTAIRE. La docstring du module elle-meme est la seule exception legitime.
    """
    import ast

    source = (RACINE / "src" / "nalu" / "app.py").read_text(encoding="utf-8")
    corps = ast.parse(source).body

    fautives = [
        noeud.lineno
        for noeud in corps[1:]  # [0] est la docstring du module, la seule permise
        if isinstance(noeud, ast.Expr) and isinstance(noeud.value, ast.Constant)
    ]

    assert not fautives, (
        f"chaine seule au niveau module, lignes {fautives} : Streamlit l'affichera"
    )


def test_le_guide_de_lecture_pointe_sur_une_section_qui_existe() -> None:
    """La page renvoie au README pour le guide complet. Un lien mort ne se voit pas.

    L'ancre est derivee du titre par GitHub : minuscules, ponctuation retiree, espaces
    en tirets. Renommer la section casserait le lien SANS rien casser d'autre — ni un
    test, ni le rendu — et un prospect tomberait en haut du README.
    """
    import re
    import unicodedata

    readme = (RACINE / "README.md").read_text(encoding="utf-8")
    ancres = set()
    for titre in re.findall(r"^#{2,3} (.+)$", readme, flags=re.MULTILINE):
        propre = "".join(
            c
            for c in titre.lower()
            if c.isalnum() or c in " -" or unicodedata.category(c).startswith("L")
        )
        ancres.add(propre.replace(" ", "-"))

    attendue = app.GUIDE_URL.split("#", 1)[1]
    assert attendue in ancres, f"ancre absente du README : {attendue}"


# ─── « Pourquoi ce spot est-il premier avec 0,7 % ? » ──────────────────────────
#
# Ponta Preta sort 1re en janvier a alpha = 0,5 avec 0,7 % d'heures surfables. Sans
# explication le lecteur conclut que le classement est casse ; il ne l'est pas, c'est le
# billet a 301 € qui porte le score. Le score etant EXACTEMENT la somme des deux termes,
# les comparer ne demande aucune estimation.


@pytest.mark.parametrize(
    ("rang_q", "rang_prix", "alpha", "attendu"),
    [
        (0.326, 0.768, 0.5, "prix"),  # Ponta Preta, janvier — le cas qui a motive ceci
        (0.992, 0.0, 0.5, "houle"),  # La Graviere : tres bonne houle, aucun prix
        (0.5, 0.5, 0.5, "autant"),  # les deux a parts strictement egales
        (0.1, 0.9, 1.0, "houle"),  # alpha = 1 : le prix ne pese plus rien
        (0.9, 0.1, 0.0, "prix"),  # alpha = 0 : la houle ne pese plus rien
    ],
)
def test_le_podium_nomme_ce_qui_porte_le_rang(
    rang_q: float, rang_prix: float, alpha: float, attendu: str
) -> None:
    assert attendu in app.moteur_du_rang(rang_q, rang_prix, alpha)


def test_le_terme_dominant_du_score_est_bien_celui_annonce() -> None:
    """La phrase doit suivre le calcul, pas une intuition sur les rangs bruts.

    A alpha = 0,9 un rang prix de 1,0 pese 0,1 quand un rang houle de 0,3 pese 0,27 :
    lire les rangs bruts designerait le prix, et ce serait faux.
    """
    assert "houle" in app.moteur_du_rang(0.3, 1.0, 0.9)


# ─── La sparkline du podium ───────────────────────────────────────────────────


@pytest.mark.disable_socket
def test_l_etincelle_couvre_les_douze_mois(tableau) -> None:
    serie = tableau.filter(pl.col("spot_id") == "uluwatu").sort("month")
    figure = app.etincelle(serie, mois_actif=1, c=CLAIR)

    assert len(figure.data[0].x) == 12
    assert len(set(figure.data[0].marker.color)) == 2, "le mois choisi doit ressortir"


@pytest.mark.disable_socket
def test_l_etincelle_porte_une_ligne_de_base(tableau) -> None:
    """Sans elle, un mois a zero se lit comme une donnee manquante.

    Elle est dessinee comme une FORME : `showline` sur l'axe ne produit rien dans
    cette configuration, verifie dans le DOM ou le groupe d'axe restait vide. Ce test
    existe parce que la difference est invisible a la lecture du code.
    """
    serie = tableau.filter(pl.col("spot_id") == "ponta-preta").sort("month")
    if serie.height == 0:  # le referentiel a bouge : prendre n'importe quel spot
        serie = tableau.filter(pl.col("spot_id") == tableau["spot_id"][0]).sort("month")
    figure = app.etincelle(serie, mois_actif=1, c=CLAIR)

    lignes = [f for f in figure.layout.shapes if f.type == "line" and f.y0 == 0 and f.y1 == 0]
    assert len(lignes) == 1, "la ligne de base a disparu"


# ─── Les polices doivent etre AUTO-HEBERGEES et presentes ─────────────────────
#
# Une URL fautive ou distante ne leve jamais : la page retombe en silence sur une
# fonte systeme. Le defaut serait donc invisible en local, et visible seulement le
# jour d'une demo sans reseau — exactement ce que la promesse hors ligne protege.


def test_chaque_police_declaree_existe_dans_le_depot() -> None:
    import tomllib

    config = tomllib.loads((RACINE / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    faces = config["theme"]["fontFaces"]

    assert faces, "aucune police declaree : le theme typographique est perdu"
    for face in faces:
        chemin = RACINE / "src" / "nalu" / face["url"].replace("app/static/", "static/")
        assert chemin.exists(), f"police absente du depot : {face['url']}"


def test_aucune_police_n_est_chargee_depuis_un_cdn() -> None:
    """Une police distante casse la demo hors ligne, et seulement celle-la."""
    import tomllib

    config = tomllib.loads((RACINE / ".streamlit" / "config.toml").read_text(encoding="utf-8"))

    for face in config["theme"]["fontFaces"]:
        assert not face["url"].startswith(("http://", "https://")), face["url"]
    for cle in ("font", "headingFont"):
        assert "http" not in config["theme"][cle], cle


def test_le_service_de_fichiers_statiques_est_actif() -> None:
    """Sans lui, `app/static/` ne repond pas et les polices tombent en silence."""
    import tomllib

    config = tomllib.loads((RACINE / ".streamlit" / "config.toml").read_text(encoding="utf-8"))

    assert config["server"]["enableStaticServing"] is True


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


# ─── Le theme de la figure doit suivre celui de la PAGE ────────────────────────
#
# Bug vu sur l'instance deployee le 2026-08-03, par un visiteur en mode sombre :
# un rectangle NOIR au milieu d'une page claire. `.streamlit/config.toml` epingle
# `theme.base = "light"` et impose un `backgroundColor`, donc la page est peinte en
# clair pour tout le monde ; `palette()` suivait `st.context.theme`, qui rapporte la
# preference du NAVIGATEUR. Un visiteur en mode sombre recevait donc la palette
# SOMBRE (#1a1a19) posee sur une page #fcfcfb.


def test_la_palette_suit_la_base_epinglee_et_non_le_navigateur() -> None:
    """C'est LA regression : base epinglee en clair -> palette claire, toujours."""
    import streamlit as st

    base = st.get_option("theme.base")
    assert base == "light", "ce test suppose la base epinglee de config.toml"
    assert app.palette() is CLAIR


def test_un_visiteur_en_mode_sombre_recoit_quand_meme_la_palette_claire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LE cas qui produisait le rectangle noir, et le seul qui distingue le correctif.

    Sans navigateur, `st.context.theme` est absent et l'ancienne implementation
    renvoyait CLAIR par defaut : elle aurait passe les autres tests. Il faut donc
    simuler explicitement un visiteur en mode sombre pour que le test morde.
    """
    import streamlit as st

    class _Theme:
        type = "dark"

    class _Contexte:
        theme = _Theme()

    monkeypatch.setattr(st, "context", _Contexte(), raising=False)

    # La base reste epinglee en clair par config.toml : c'est elle qui doit gagner.
    assert st.get_option("theme.base") == "light"
    assert app.palette() is CLAIR, (
        "un visiteur en mode sombre recevait une figure sombre sur une page claire"
    )


def test_la_palette_de_la_page_et_celle_de_la_figure_ont_la_meme_surface() -> None:
    """La surface de la figure doit etre exactement le fond de la page.

    C'est l'invariant que le rectangle noir violait, et il se verifie sans navigateur.
    """
    import streamlit as st

    assert app.palette()["surface"] == st.get_option("theme.backgroundColor")


def test_sans_base_epinglee_on_retombe_sur_la_preference_du_navigateur(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retirer l'epingle de config.toml doit reactiver le suivi automatique."""
    import streamlit as st

    monkeypatch.setattr(st, "get_option", lambda _cle: None)

    class _Theme:
        type = "dark"

    class _Contexte:
        theme = _Theme()

    monkeypatch.setattr(st, "context", _Contexte(), raising=False)
    assert app.palette() is SOMBRE

    _Theme.type = "light"
    assert app.palette() is CLAIR
