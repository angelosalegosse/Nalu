"""Dashboard Nalu — le moment où le prospect déplace le curseur lui-même.

    uv run streamlit run src/nalu/app.py

Tout est précalculé au chargement : déplacer le curseur ne déclenche **aucun appel
réseau et aucune relecture de parquet**, seulement une combinaison linéaire de deux
rangs déjà calculés. C'est ce qui rend le geste instantané, et c'est ce qui permet à
la démo de tourner devant un client sans connexion.
"""

from datetime import date

import plotly.graph_objects as go
import polars as pl
import streamlit as st

from nalu.coastline import CONTOUR_PATH
from nalu.config import CONFIG
from nalu.llm.commentary import MODELE, commenter
from nalu.palette import CLAIR, SOMBRE
from nalu.scoring.climatology import QUINZAINES_PATH
from nalu.scoring.combine import classement as classer
from nalu.scoring.combine import construire_tableau, fraicheur_du_snapshot

MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]

# Abréviations POSÉES, jamais tronquées. Couper `MOIS` à longueur fixe échoue des deux
# côtés : à quatre lettres on obtient « avri », « octo », « nove », « déce », qui se
# lisent comme des fautes ; à trois, « juin » et « juillet » se confondent tous deux en
# « jui » et l'axe perd un mois — vu à l'écran, pas dans les tests.
MOIS_COURT = [
    "janv", "févr", "mars", "avr", "mai", "juin",
    "juil", "août", "sept", "oct", "nov", "déc",
]

# La palette vit dans `nalu/palette.py` : les notebooks de l'issue #9 peignent les
# mêmes graphiques et ne doivent pas charger Streamlit pour connaître un bleu.

# Cadrage du planisphère. Les bornes de latitude coupent l'Antarctique et le haut de
# l'Arctique, où le référentiel n'a aucun spot : les garder écraserait la bande utile.
# Ces quatre valeurs servent DEUX fois — les axes de la figure et le rapport de forme
# du CSS. Les dériver l'une de l'autre est le seul moyen qu'elles ne divergent pas.
CARTE_LON = (-180.0, 180.0)
CARTE_LAT = (-58.0, 74.0)
CARTE_LON_SPAN = CARTE_LON[1] - CARTE_LON[0]
CARTE_LAT_SPAN = CARTE_LAT[1] - CARTE_LAT[0]

# Plafond sur grand écran : au-delà, la carte pousse le tableau — qui est le vrai
# sujet de la page — sous la ligne de flottaison.
#
# Le plafond porte sur la LARGEUR, jamais sur la hauteur. La hauteur est la dimension
# DÉRIVÉE (`aspect-ratio` la calcule depuis la largeur) ; la brider crée un conflit que
# le navigateur tranche en rétrécissant la largeur du bloc, tandis que Plotly continue
# de dessiner son SVG à la taille du conteneur parent. Résultat mesuré à 1920 px avec
# un `max-height` : boîte de 1255 px, SVG de 1760 px, et **tout le tiers droit de la
# carte coupé** — Japon, est de l'Australie, Nouvelle-Zélande, plus deux marqueurs de
# spots devenus invisibles. Brider la largeur fait rétrécir les deux ensemble.
CARTE_HAUTEUR_MAX = 460
CARTE_LARGEUR_MAX = round(CARTE_HAUTEUR_MAX * CARTE_LON_SPAN / CARTE_LAT_SPAN)

# La police des FIGURES doit être celle de la PAGE. Par défaut Plotly dessine en
# « Open Sans » pendant que Streamlit compose en « Source Sans » : deux typographies
# sur un même écran, mesuré dans le DOM le 2026-08-03. La palette était déjà partagée
# entre le dashboard et les notebooks ; la police ne l'était pas.
POLICE_FIGURE = '"Source Sans", sans-serif'

# Hauteur d'une ligne et de l'en-tête de `st.dataframe`, en pixels. Mesurées dans le
# DOM le 2026-08-03 : le tableau par défaut plafonne à 400 px, soit dix lignes sur
# vingt, derrière un défilement interne que rien ne signale. Ces deux valeurs servent
# à le dimensionner sur son contenu réel.
LIGNE_TABLEAU = 35
EN_TETE_TABLEAU = 38

# Ce que porte la case prix d'un spot non couvert. Un tiret cadratin, jamais « None ».
SANS_PRIX = "—"

# ─── Les libellés du tableau, et ce qu'ils veulent dire ───────────────────────
#
# Les noms internes du modèle — `p_surf`, `q`, `rank_q` — sont ceux du code, et ils
# doivent le rester : c'est ce qui rend le classement traçable jusqu'au parquet. Mais
# un lecteur qui n'a pas lu `combine.py` ne peut pas deviner ce que « P_surf % » compte,
# et le tableau est la PREUVE du produit : illisible, il ne prouve rien.
#
# D'où la règle : un libellé court en français, et l'explication complète dans l'aide de
# colonne (`st.column_config`, l'infobulle « ? » de l'en-tête). Rien n'est retiré, rien
# n'est simplifié — le chiffre affiché est exactement le même.
#
# Ces libellés sont des CONSTANTES parce qu'ils servent TROIS fois : la sélection
# polars, la table d'aides, et les tests. Un libellé changé au seul endroit de la
# sélection laisserait une colonne sans explication, et rien ne le signalerait à
# l'écran — l'infobulle disparaîtrait simplement. Un test le vérifie.
COL_RANG = "Rang"
COL_SPOT = "Spot"
COL_PAYS = "Pays"
COL_SURFABLE = "Surfable %"
COL_RANG_Q = "Rang qualité"
COL_PRIX = "Prix A/R"
COL_RANG_PRIX = "Rang prix"
COL_SCORE = "Score"
# Ces trois-là sont volontairement COURTS, et c'est une contrainte de largeur mesurée,
# pas un goût. À 1440 px, rail compris, la boîte du tableau fait 978 px. Avec « Heures
# surfables », « Heures de jour » et « Taille relative » le contenu demandait 1193 px,
# et les deux dernières colonnes — dont « Signalement », qui porte le « prix non
# couvert » cité partout ailleurs — passaient derrière un défilement horizontal.
#
# Mesures successives du contenu, à 978 px de boîte : 1193 px → 1091 avec ces libellés
# courts → 1057 après le retrait de la colonne `Q`. Le sens complet vit dans
# l'infobulle, qui elle ne coûte aucune largeur.
COL_HEURES_SURF = "Heures OK"
COL_HEURES_JOUR = "Heures jour"
COL_INTENSITE = "Taille"
COL_SIGNALEMENT = "Signalement"

AIDE_SURFABLE = (
    "Part des heures de JOUR du mois où la houle, sa période et le vent sont "
    "simultanément dans les seuils de ce spot. Moyenne sur les quatre années "
    "2022-2025. C'est `p_surf` dans le code, et le Q de la formule du score : "
    "la même valeur, en pourcentage plutôt qu'en probabilité de 0 à 1."
)

AIDES_COLONNES: dict[str, str] = {
    COL_RANG: "Position dans le classement de ce mois, au réglage actuel du curseur. "
    "Le tableau est trié par Score.",
    COL_SPOT: "Le spot de surf. Les vingt sont sourcés un par un dans `data/spots.yaml`.",
    COL_PAYS: "Pays du spot. L'aéroport desservi est celui du référentiel, pas le plus proche.",
    COL_SURFABLE: AIDE_SURFABLE,
    COL_RANG_Q: "Rang centile de « Surfable % » parmi les 240 couples spot × mois. "
    "1 = la meilleure houle du référentiel, 0 = la moins bonne. "
    "Un rang, jamais une échelle min-max : un extrême ne doit pas écraser les autres. "
    "C'est cette valeur, et non le pourcentage brut, qui entre dans le score.",
    COL_PRIX: "Aller-retour le moins cher relevé pour ce mois au départ de Paris. "
    "« — » : aucun prix pour cette route, ce n'est pas un prix nul.",
    COL_RANG_PRIX: "Rang centile du prix parmi les 240 couples. 1 = le billet le moins "
    "cher. Un spot sans prix reçoit 0 : c'est une limite connue et assumée, pas un "
    "jugement sur le spot.",
    COL_SCORE: "α × Rang qualité + (1 − α) × Rang prix. La seule colonne que le curseur "
    "déplace, et celle qui trie le tableau.",
    COL_HEURES_SURF: "Le compte brut d'heures de jour SURFABLES relevées pour ce mois "
    "sur les quatre années.",
    COL_HEURES_JOUR: "Le compte brut de TOUTES les heures de jour du mois, sur les "
    "quatre années. « Surfable % » est exactement le rapport des deux colonnes — c'est "
    "ce qui rend le pourcentage vérifiable à la main.",
    COL_INTENSITE: "Taille RELATIVE de la houle, de 0 à 1 : où tombe la hauteur moyenne "
    "des heures surfables dans la fenêtre propre au spot. 0 = au seuil bas, 1 = au "
    "plafond. Chaque spot ayant sa propre fenêtre, deux spots ne se comparent PAS en "
    "mètres : 0,45 à Supertubos (1→3 m) vaut 1,90 m, 0,45 à Zicatela (1,5→4,5 m) vaut "
    "2,85 m. Informative — elle n'entre pas dans le score. Une valeur de 0 signifie "
    "aujourd'hui « aucune heure surfable », pas « petite houle ».",
    COL_SIGNALEMENT: "« prix non couvert » : aucun prix pour cette route. « écart entre "
    "quinzaines » : les deux moitiés du mois diffèrent assez pour qu'une moyenne "
    "mensuelle induise en erreur.",
}

# Le guide de lecture complet vit dans le README, lisible sur GitHub sans rien
# installer. La page n'en porte que le strict nécessaire et pointe vers lui : dupliquer
# le texte garantirait que les deux versions divergent.
GUIDE_URL = "https://github.com/angelosalegosse/Nalu#lire-le-tableau-du-dashboard"

# En dessous de cet écart entre les deux contributions au score, aucune des deux ne
# domine : annoncer un gagnant serait une affirmation que les chiffres ne portent pas.
#
# ⚠️ Un COMMENTAIRE, jamais une chaîne sous l'affectation. `app.py` est le script que
# Streamlit exécute, et sa « magie » affiche toute expression laissée seule sur sa
# ligne : une chaîne de documentation posée là est peinte EN HAUT DE LA PAGE, au-dessus
# du titre. Vu à l'écran, invisible aux 308 tests. C'est la raison pour laquelle aucune
# constante de ce module ne porte de docstring.
ECART_EGALITE = 0.05


def moteur_du_rang(rang_q: float, rang_prix: float, alpha: float) -> str:
    """Ce qui place ce spot si haut : la houle, le prix, ou les deux à parts égales.

    C'est LA question que pose le podium et à laquelle il ne répondait pas. Ponta Preta
    sort première en janvier avec 0,7 % d'heures surfables : le lecteur voit un très
    mauvais chiffre en tête de classement et conclut que le classement est cassé. Il ne
    l'est pas — le score est une somme de DEUX rangs, et c'est le billet à 301 € qui la
    porte. Le score étant exactement `alpha * rang_q + (1 - alpha) * rang_prix`, les
    deux termes se comparent directement : il n'y a rien à estimer.
    """
    houle = alpha * rang_q
    prix = (1.0 - alpha) * rang_prix
    if abs(houle - prix) < ECART_EGALITE:
        return "classé autant sur la houle que sur le prix"
    return "classé surtout sur la houle" if houle > prix else "classé surtout sur le prix"


def milliers(n: int) -> str:
    """Espace fine insécable entre les milliers. « 1364 » se lit mal, « 1 364 » non."""
    return f"{n:,}".replace(",", " ")


def style_planisphere() -> str:
    """Le CSS qui rend la carte responsive. Extrait de `main()` pour être testable.

    Le planisphère verrouille ses proportions (`scaleanchor`) pour ne pas déformer les
    continents. Python ne connaît pas la largeur de la fenêtre, donc seul le CSS peut
    faire suivre la hauteur — d'où ce bloc plutôt qu'un paramètre de figure.

    Deux règles, et l'ordre entre elles est ce qui compte :

    1. **Le plafond porte sur la LARGEUR du conteneur.** Plotly dimensionne son SVG
       sur ce conteneur ; brider la largeur fait donc rétrécir la boîte ET le tracé
       ensemble.
    2. **La hauteur est dérivée**, jamais bridée. Un `max-height` sur le même élément
       qu'un `aspect-ratio` entre en conflit avec lui : le navigateur tranche en
       rétrécissant la largeur de la boîte, pendant que Plotly continue de dessiner à
       la taille du parent. Mesuré à 1920 px : boîte de 1255 px, SVG de 1760 px, tiers
       droit de la carte coupé — Japon, est de l'Australie, Nouvelle-Zélande et deux
       marqueurs de spots devenus invisibles.
    """
    return f"""<style>
        .st-key-planisphere {{
            max-width: {CARTE_LARGEUR_MAX}px;
        }}
        .st-key-planisphere [data-testid="stPlotlyChart"],
        .st-key-planisphere .js-plotly-plot,
        .st-key-planisphere .plot-container {{
            height: auto !important;
            aspect-ratio: {CARTE_LON_SPAN} / {CARTE_LAT_SPAN};
        }}
        </style>"""


def palette() -> dict:
    """La palette du thème RÉELLEMENT appliqué, pas de celui que le navigateur demande.

    `.streamlit/config.toml` épingle `theme.base` et impose un `backgroundColor` : la
    page est donc peinte en clair pour tout le monde, quelle que soit la préférence
    système du visiteur. Suivre `st.context.theme`, qui rapporte cette préférence,
    produisait une figure sombre posée sur une page claire — **un rectangle noir au
    milieu du dashboard**, vu sur l'instance déployée par un visiteur en mode sombre.

    L'ordre est donc : la base épinglée gagne ; à défaut seulement, on suit le
    navigateur. Retirer l'épingle de `config.toml` réactive le suivi automatique sans
    qu'il faille retoucher cette fonction.
    """
    try:
        base = st.get_option("theme.base")
    except Exception:  # hors runtime Streamlit (tests, notebooks)
        base = None
    if base in ("light", "dark"):
        return SOMBRE if base == "dark" else CLAIR

    theme = getattr(getattr(st, "context", None), "theme", None)
    return SOMBRE if getattr(theme, "type", "light") == "dark" else CLAIR


@st.cache_data(show_spinner="Chargement du cache local…")
def charger() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, date | None, int]:
    """Une seule lecture disque, mise en cache. Aucun réseau, jamais."""
    tableau = construire_tableau()
    quinzaines = pl.read_parquet(QUINZAINES_PATH)
    contour = pl.read_parquet(CONTOUR_PATH)
    jour, anciennete = fraicheur_du_snapshot()
    return tableau, quinzaines, contour, jour, anciennete


def carte(classement: pl.DataFrame, contour: pl.DataFrame, c: dict) -> go.Figure:
    """Planisphère hors ligne : le fond vient de Natural Earth, versionné dans le dépôt."""
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=contour["lon"], y=contour["lat"], mode="lines",
            line={"color": c["terre"], "width": 1},
            hoverinfo="skip", showlegend=False, name="",
        )
    )
    couverts = classement.filter(~pl.col("price_missing"))
    absents = classement.filter("price_missing")

    if absents.height:
        figure.add_trace(
            go.Scatter(
                x=absents["lon"], y=absents["lat"], mode="markers",
                # `circle-open` : chez Plotly c'est `color` qui dessine le TRAIT du
                # symbole, pas `line`. La mettre a la couleur du fond rend le marqueur
                # invisible — defaut trouve en regardant le rendu, pas en le testant.
                marker={
                    "size": 11, "color": c["encre_muette"], "symbol": "circle-open",
                    "line": {"width": 2},
                },
                text=absents["name"], showlegend=True, name="prix non couvert",
                hovertemplate="<b>%{text}</b><br>prix non couvert<extra></extra>",
            )
        )
    figure.add_trace(
        go.Scatter(
            x=couverts["lon"], y=couverts["lat"], mode="markers",
            marker={
                "size": 13, "color": couverts["score"], "colorscale":
                    [[i / (len(c["rampe"]) - 1), h] for i, h in enumerate(c["rampe"])],
                "cmin": 0, "cmax": 1, "line": {"color": c["surface"], "width": 2},
                # Barre POSEE DANS la carte, sur le Pacifique sud qui est vide de
                # spots, et non à droite du tracé. À droite, elle vit hors de la zone
                # de dessin : avec une marge nulle elle sort du cadre et son titre est
                # coupé — vu à 1440 px. Ici elle ne coûte aucune largeur de mise en
                # page, ce qui compte d'autant plus sur un écran étroit.
                "colorbar": {
                    "title": {"text": "Score", "font": {"color": c["encre_2"], "size": 11}},
                    "tickfont": {"color": c["encre_muette"], "size": 10},
                    "outlinewidth": 0, "thickness": 9, "len": 0.34,
                    "orientation": "h", "x": 0.63, "y": 0.03,
                    "xanchor": "left", "yanchor": "bottom",
                    "tickvals": [0, 0.5, 1],
                },
            },
            text=couverts["name"], customdata=couverts.select("score", "price_eur").to_numpy(),
            showlegend=True, name="prix connu",
            hovertemplate="<b>%{text}</b><br>score %{customdata[0]:.2f}"
            "<br>%{customdata[1]:.0f} €<extra></extra>",
        )
    )
    figure.update_layout(
        paper_bgcolor=c["surface"], plot_bgcolor=c["surface"],
        margin={"l": 0, "r": 0, "t": 0, "b": 0}, height=CARTE_HAUTEUR_MAX,
        font={"family": POLICE_FIGURE, "color": c["encre_2"]},
        xaxis={"visible": False, "range": list(CARTE_LON)},
        yaxis={
            "visible": False, "range": list(CARTE_LAT),
            "scaleanchor": "x", "scaleratio": 1,
        },
        hoverlabel={"bgcolor": c["surface"], "font": {"color": c["encre"]}},
        # Deux classes de marqueurs sans légende, c'est une identité portée par la
        # seule forme du symbole : le visiteur voyait onze anneaux gris sans pouvoir
        # savoir qu'ils signifient « prix non couvert » et non « mauvaise vague ».
        # Posée DANS la carte, comme la barre de couleur et pour la même raison : à
        # l'extérieur elle coûterait de la largeur de mise en page.
        #
        # `itemclick` désarmé : un clic de légende masque la série chez Plotly. Sur un
        # tableau de bord, effacer onze spots par mégarde, sans indice pour les
        # rétablir, coûte plus que le filtre ne rapporte.
        legend={
            "orientation": "h", "x": 0.01, "y": 0.03,
            "xanchor": "left", "yanchor": "bottom",
            "bgcolor": "rgba(0,0,0,0)", "borderwidth": 0,
            "font": {"color": c["encre_2"], "size": 11},
            "itemclick": False, "itemdoubleclick": False,
        },
    )
    return figure


def saisonnalite(serie: pl.DataFrame, mois_actif: int, c: dict) -> go.Figure:
    """Les douze mois du spot sélectionné. Une seule série : pas de légende."""
    couleurs = [c["serie"] if m == mois_actif else c["serie_attenuee"] for m in serie["month"]]
    figure = go.Figure(
        go.Bar(
            x=[MOIS_COURT[m - 1] for m in serie["month"]],
            y=serie["p_surf"] * 100,
            marker={"color": couleurs, "line": {"width": 0}},
            hovertemplate="%{x} — %{y:.1f} % des heures diurnes<extra></extra>",
        )
    )
    figure.update_layout(
        paper_bgcolor=c["surface"], plot_bgcolor=c["surface"],
        margin={"l": 0, "r": 0, "t": 10, "b": 0}, height=220, bargap=0.35,
        font={"family": POLICE_FIGURE, "color": c["encre_2"]},
        xaxis={"tickfont": {"color": c["encre_muette"], "size": 11}, "showgrid": False},
        yaxis={
            # Le libellé de l'axe disait « P_surf (%) », un nom de variable du code posé
            # devant un lecteur qui ne l'a jamais lu. Le chiffre est le même.
            "title": {
                "text": "% d'heures de jour surfables",
                "font": {"color": c["encre_2"], "size": 12},
            },
            "tickfont": {"color": c["encre_muette"], "size": 11},
            "gridcolor": c["grille"], "zeroline": False,
        },
        hoverlabel={"bgcolor": c["surface"], "font": {"color": c["encre"]}},
    )
    return figure


def etincelle(serie: pl.DataFrame, mois_actif: int, c: dict) -> go.Figure:
    """Les douze mois d'un spot, en miniature, sans axe ni graduation.

    C'est la version dense de `saisonnalite()` : posée dans une carte de podium, elle
    répond à « et les autres mois ? » sans un clic ni une ligne de texte. Le mois
    choisi est la seule barre à pleine teinte, donc on voit d'un coup si on tombe sur
    la saison ou à côté. Les axes sont retirés parce qu'à 54 px ils ne se lisent pas :
    l'ordre des mois est porté par la légende textuelle sous la figure.
    """
    couleurs = [c["serie"] if m == mois_actif else c["serie_attenuee"] for m in serie["month"]]
    figure = go.Figure(
        go.Bar(
            x=[MOIS_COURT[m - 1] for m in serie["month"]],
            y=serie["p_surf"] * 100,
            marker={"color": couleurs, "line": {"width": 0}},
            hovertemplate="%{x} — %{y:.1f} % des heures diurnes<extra></extra>",
        )
    )
    figure.update_layout(
        paper_bgcolor=c["surface"], plot_bgcolor=c["surface"],
        # `b` non nul : la ligne de base se dessine sur la derniere rangee de pixels et
        # se fait rogner par une marge a zero. Trois pixels suffisent a la rendre.
        margin={"l": 0, "r": 0, "t": 0, "b": 3}, height=54, bargap=0.3,
        font={"family": POLICE_FIGURE, "color": c["encre_2"]},
        showlegend=False,
        xaxis={"visible": False},
        yaxis={"visible": False, "rangemode": "tozero"},
        hoverlabel={"bgcolor": c["surface"], "font": {"color": c["encre"]}},
    )
    # Ligne de base dessinée comme une FORME, pas comme un axe : plusieurs spots sont
    # à zéro une partie de l'année, et sans trait le mois vide se lit comme une donnée
    # manquante au lieu d'un zéro. `showline` sur l'axe ne produit rien dans cette
    # configuration — vérifié dans le DOM, le groupe d'axe reste vide — alors qu'une
    # forme est dessinée sans condition.
    figure.add_shape(
        type="line", xref="paper", yref="y", x0=0, x1=1, y0=0, y1=0,
        line={"color": c["encre_muette"], "width": 1},
    )
    return figure


def podium(
    classement: pl.DataFrame, tableau: pl.DataFrame, mois: int, alpha: float, c: dict
) -> None:
    """Les trois premiers en grand, avant le tableau. Extrait de `main()` pour être testable.

    Le tableau est le livrable du MODÈLE — douze colonnes traçables, et c'est ce qui
    rend le classement auditable. Ce n'est pas le livrable du PRODUIT : les vingt lignes
    sont Teahupo'o, Cloudbreak, Pipeline, des endroits dont on rêve, et les rendre en
    flottants n'en donne aucune envie. Le podium porte le désir, le tableau porte la
    preuve, et la preuve reste entière un écran plus bas.

    Chaque carte porte une ligne de LECTURE, et c'est elle qui répond aux deux questions
    que le podium posait sans y répondre : « 0,7 %, comparé à quoi ? » — d'où le compte
    brut d'heures, qui rend le pourcentage tangible — et « pourquoi ce spot est-il
    premier avec 0,7 % ? » — d'où `moteur_du_rang()`, qui nomme celui des deux rangs qui
    porte le score.
    """
    trois = classement.head(3).iter_rows(named=True)
    for colonne, ligne in zip(st.columns(3), trois, strict=False):
        with colonne, st.container(border=True):
            st.caption(f"{ligne['rang']} · {ligne['country']}")
            st.subheader(ligne["name"])

            gauche, droite = st.columns(2)
            gauche.metric(
                "heures surfables",
                f"{ligne['p_surf'] * 100:.1f} %".replace(".", ","),
                help=AIDE_SURFABLE,
            )
            droite.metric(
                "aller-retour",
                SANS_PRIX if ligne["price_eur"] is None else f"{ligne['price_eur']:.0f} €",
                help=AIDES_COLONNES[COL_PRIX],
            )
            st.caption(
                f"{milliers(ligne['hours_surfable'])} h surfables sur "
                f"{milliers(ligne['hours_daylight'])} h de jour · "
                f"{moteur_du_rang(ligne['rank_q'], ligne['rank_price'], alpha)}"
            )

            serie = tableau.filter(pl.col("spot_id") == ligne["spot_id"]).sort("month")
            st.plotly_chart(
                etincelle(serie, mois, c),
                use_container_width=True,
                config={"displayModeBar": False},
                key=f"etincelle_{ligne['spot_id']}",
            )
            st.caption("janv → déc")


def guide_de_lecture() -> str:
    """Le guide replié au-dessus du tableau. Extrait de `main()` pour être testable.

    Chaque nom de colonne est INTERPOLÉ depuis les constantes, jamais réécrit à la main.
    Le guide a affiché « Taille relative » le temps d'un rendu pendant que l'en-tête
    disait déjà « Taille » : une légende qui nomme une colonne absente est pire que pas
    de légende, et rien n'échouait. Interpolées, les deux ne peuvent plus diverger, et
    un test vérifie que chaque libellé apparaît bien ici.
    """
    return f"""
**Le classement additionne deux rangs**, jamais deux grandeurs brutes :

```
Score = α × {COL_RANG_Q}  +  (1 − α) × {COL_RANG_PRIX}
```

Le curseur du rail *est* α. À `α = 1` seule la houle compte, à `α = 0` seul le billet.
Ce sont des **rangs centiles** calculés sur les 240 couples spot × mois — pas des
valeurs remises à l'échelle : une seule valeur extrême, un billet à 2 299 €, écraserait
une échelle min-max et rendrait le curseur inerte sur la moitié de sa course.

| Colonne | En un mot |
|---|---|
| **{COL_RANG}** | La position au mois et au réglage courants. Le tri se fait sur le {COL_SCORE}. |
| **{COL_SPOT}** · **{COL_PAYS}** | Le spot et son pays. Les vingt sont sourcés un par un. |
| **{COL_SURFABLE}** | La part des heures de **jour** du mois où le spot marche, sur 2022-2025. |
| **{COL_RANG_Q}** | Où tombe cette houle parmi les 240 couples. 1 = la meilleure du référentiel. |
| **{COL_PRIX}** | Aller-retour le moins cher relevé pour ce mois au départ de Paris. |
| **{COL_RANG_PRIX}** | 1 = le billet le moins cher. **0 = prix inconnu**, pas gratuit. |
| **{COL_SCORE}** | La somme des deux rangs : la colonne qui trie, la seule que bouge le curseur. |
| **{COL_SIGNALEMENT}** | Ce qui nuance la ligne : prix absent, ou mois en deux moitiés inégales. |
| **{COL_HEURES_SURF}** · **{COL_HEURES_JOUR}** | Comptes bruts : leur rapport EST {COL_SURFABLE}. |
| **{COL_INTENSITE}** | La houle moyenne dans la fenêtre **du spot**, 0 à 1. **Informative.** |

**Deux limites à connaître avant de lire une ligne.** Un spot sans prix reçoit le rang
prix 0, ce qui le **pénalise** au lieu de le neutraliser — il reste affiché et marqué
« prix non couvert », parce que le faire disparaître laisserait un biais de couverture
décider du contenu du produit. Et **{COL_INTENSITE} n'entre pas dans le score** : on
n'additionne pas une probabilité et une hauteur en mètres.

[→ Le guide complet, colonne par colonne, avec un exemple chiffré]({GUIDE_URL})
"""


def table_affichee(classement: pl.DataFrame) -> pl.DataFrame:
    """Le tableau tel qu'il est peint. Extrait de `main()` pour être testable.

    Le point délicat est la colonne des prix. `st.dataframe` peint « None » pour une
    valeur absente — la valeur Python brute, sur quatorze des vingt lignes. Mesuré sur
    Streamlit 1.59.1 : ni `NumberColumn` ni son `format` ne la suppriment, **seule une
    colonne de TEXTE** le permet.

    Mais du texte se trie alphabétiquement, et les prix vont de 67 à 2299 € : « 2299 »
    passerait avant « 67 », donc un clic sur l'en-tête donnerait un ordre faux. Aligner
    les nombres à droite sur la largeur du plus long rétablit l'ordre exact, parce que
    l'espace précède les chiffres dans la table des caractères. Le tiret cadratin les
    suit tous, donc les spots sans prix se rangent en fin de tri plutôt qu'en tête.

    La largeur est DÉRIVÉE des données : un snapshot qui passerait à cinq chiffres ne
    doit pas casser silencieusement l'ordre.
    """
    prix_connus = classement["price_eur"].drop_nulls()
    largeur = len(f"{prix_connus.max():.0f}") if prix_connus.len() else 1

    return classement.select(
        pl.col("rang").alias(COL_RANG),
        pl.col("name").alias(COL_SPOT),
        pl.col("country").alias(COL_PAYS),
        (pl.col("p_surf") * 100).round(1).alias(COL_SURFABLE),
        # `q` N'EST PAS affiché, et c'est délibéré : `Q = p_surf`, donc la colonne
        # peignait le même nombre que « Surfable % » à un facteur 100 près — 0,007 en
        # face de 0,7. Deux colonnes pour une seule grandeur ajoutaient de la confusion
        # là où la page cherche à en retirer, et coûtaient 34 px de largeur mesurée à un
        # tableau qui n'en avait pas. Le lien au modèle n'est pas perdu : l'infobulle de
        # « Surfable % » dit que c'est le Q de la formule, et `Rang qualité` — la valeur
        # qui entre RÉELLEMENT dans le score — reste affichée juste à côté.
        pl.col("rank_q").round(3).alias(COL_RANG_Q),
        pl.when(pl.col("price_eur").is_null())
        .then(pl.lit(SANS_PRIX))
        .otherwise(
            pl.col("price_eur").round(0).cast(pl.Int64).cast(pl.Utf8)
            .str.pad_start(largeur, " ")
            + pl.lit(" €")
        )
        .alias(COL_PRIX),
        pl.col("rank_price").round(3).alias(COL_RANG_PRIX),
        pl.col("score").round(3).alias(COL_SCORE),
        # `Signalement` remonte JUSTE APRÈS le score, et ce n'est pas cosmétique. Treize
        # colonnes débordent de 113 px à 1440 px : la dernière tombe derrière un
        # défilement horizontal. En queue de tableau, la colonne perdue était celle qui
        # porte « prix non couvert » — la mise en garde citée par le podium, la carte et
        # la légende. Ici elle qualifie le score qu'elle suit, et la colonne sacrifiée
        # devient `Taille`, la seule que le modèle déclare explicitement informative.
        pl.when(pl.col("price_missing"))
        .then(pl.lit("prix non couvert"))
        .when(pl.col("dispersion_alert"))
        .then(pl.lit("écart entre quinzaines"))
        .otherwise(pl.lit(""))
        .alias(COL_SIGNALEMENT),
        pl.col("hours_surfable").alias(COL_HEURES_SURF),
        pl.col("hours_daylight").alias(COL_HEURES_JOUR),
        pl.col("intensity").round(2).alias(COL_INTENSITE),
    )


def main() -> None:
    st.set_page_config(page_title="Nalu — où surfer, quel mois", layout="wide")
    c = palette()
    tableau, quinzaines, contour, jour_snapshot, anciennete = charger()

    st.title("Nalu")
    st.caption(
        f"Où partir surfer, et quand. {CONFIG.year_end - CONFIG.year_start + 1} ans de "
        f"climatologie de houle ({CONFIG.year_start}-{CONFIG.year_end}) croisés avec les "
        f"prix des vols au départ de {CONFIG.origin_iata}."
    )

    # Les deux contrôles vivent dans le rail, motif des explorateurs de données : le
    # premier écran appartient alors à la RÉPONSE, pas au formulaire. Effet de bord
    # mesuré et voulu : le rail réduit la largeur offerte au planisphère sur grand
    # écran, donc le vide à sa droite.
    with st.sidebar:
        mois = st.selectbox(
            "Mois de départ", range(1, 13), format_func=lambda m: MOIS[m - 1].capitalize()
        )
        alpha = st.slider(
            "Le billet le moins cher  ←→  la meilleure vague",
            0.0, 1.0, 0.5, 0.05,
            help="C'est le α du score. À 1, le classement ne tient qu'à la houle ; à 0, "
            "qu'au prix du billet. Entre les deux, il mélange les deux rangs dans cette "
            "proportion exacte.",
        )

    # Une seule implémentation du classement, partagée avec les tests : l'ordre affiché
    # est exactement celui qu'ils vérifient.
    classement = classer(tableau, mois, alpha)

    st.header(f"Où partir en {MOIS[mois - 1]}")
    # La phrase qui désamorce le contresens le plus probable de la page, posée là où il
    # se produit : le premier du podium affiche parfois 0,7 % d'heures surfables, ce qui
    # se lit comme un classement cassé tant qu'on ignore que le score additionne DEUX
    # rangs. Le dire une fois ici évite de le répéter sur chaque carte.
    st.caption(
        "Les trois premiers du classement, au réglage actuel du curseur. "
        "**Heures surfables** est la part des heures de jour du mois où houle, période "
        "et vent tombent ensemble dans les seuils du spot — un spot au pourcentage "
        "modeste peut donc être bien classé si son billet est bon marché, et la ligne "
        "sous chaque carte dit lequel des deux le porte."
    )
    podium(classement, tableau, mois, alpha, c)

    st.html(style_planisphere())
    with st.container(key="planisphere"):
        # Barre d'outils Plotly masquée : ses six boutons font 24x22 px, très en
        # dessous des 44 px d'une cible tactile, et zoomer sur un planisphère de
        # vingt points n'apporte rien. Autant de bruit en moins.
        st.plotly_chart(
            carte(classement, contour, c),
            use_container_width=True,
            config={"displayModeBar": False},
        )

    affichage = table_affichee(classement)
    # Le titre annonce le NOMBRE : sans lui, le tableau montrait dix lignes derrière
    # un défilement interne discret et rien ne disait qu'il y en a vingt. La hauteur
    # les expose toutes, pour qu'un classement se lise d'un coup d'œil et non à la
    # molette. C'est aussi le seul `h2` de la page avec la saisonnalité : avant, tout
    # le document ne portait qu'un `h1` et aucune section.
    st.header(f"Les {classement.height} spots, classés")
    # « Sans rien retirer » a été écrit quand le tableau portait encore la colonne `Q`,
    # et est devenu faux le jour où elle est partie. Une légende qui surpromet est pire
    # qu'une légende absente sur une page dont l'argument est l'auditabilité.
    st.caption(
        "Toutes les valeurs intermédiaires du calcul, jusqu'aux comptes d'heures bruts : "
        "c'est ce qui rend le classement auditable. **Chaque en-tête porte une "
        "infobulle** qui dit ce que la colonne compte — le « ? » apparaît au survol."
    )
    # Un guide replié, jamais un pavé déplié : le tableau est déjà dense, et le lecteur
    # qui comprend n'a pas à payer l'explication de celui qui ne comprend pas. La
    # version complète, colonne par colonne, vit dans le README.
    with st.expander("Comment lire ce tableau"):
        st.markdown(guide_de_lecture())
    st.dataframe(
        affichage,
        hide_index=True,
        use_container_width=True,
        height=EN_TETE_TABLEAU + classement.height * LIGNE_TABLEAU,
        # `Column` et non `NumberColumn` / `TextColumn` : il pose le libellé et l'aide
        # sans toucher au rendu. La colonne des prix est du TEXTE aligné à droite pour
        # que le tri reste numérique — lui imposer un type la casserait en silence.
        #
        # `Rang` et `Spot` sont ÉPINGLÉS. Treize colonnes ne tiennent pas sous 1100 px
        # de contenu : il reste un défilement horizontal sur écran étroit, et sans
        # épingle on se retrouve devant une rangée de flottants sans savoir de quel spot
        # ils parlent. Épinglées, l'identité de la ligne ne quitte jamais l'écran.
        column_config={
            nom: st.column_config.Column(
                label=nom, help=aide, pinned=nom in (COL_RANG, COL_SPOT)
            )
            for nom, aide in AIDES_COLONNES.items()
        },
    )

    # Bloc commentaire : la seule partie de la page qui dépend d'un service tiers, et
    # la seule qui ait le droit de manquer. `commenter()` ne lève jamais — sans clé,
    # sans réseau ou sur quota dépassé, elle renvoie une raison affichable.
    #
    # `st.caption` et non `st.info` pour l'indisponibilité : le bleu est la couleur
    # d'ACCENT de ce système, comme le rouge en est la couleur de statut. Peindre une
    # absence bénigne en bleu la ferait lire comme une information saillante.
    lecture = commenter(classement, mois, alpha)
    if lecture.disponible:
        with st.container(border=True):
            st.markdown(f"**Lecture des résultats** — {lecture.texte}")
            st.caption(
                f"Commentaire généré par {MODELE}. Il lit le tableau ci-dessus et le "
                "met en mots : **aucun chiffre affiché ne vient de lui.**"
            )
    else:
        st.caption(lecture.texte)

    # `st.header` et non un libellé de `selectbox` : « Saisonnalité d'un spot » était
    # le nom d'un contrôle, donc invisible à la structure du document. La page n'avait
    # qu'un seul titre pour six blocs de texte tous composés à la même taille.
    st.header("Saisonnalité d'un spot")
    st.caption(
        "Les douze mois du spot choisi, en part d'heures de jour surfables. La barre "
        "pleine est le mois sélectionné dans le rail : on voit d'un coup si l'on tombe "
        "sur la saison ou juste à côté. Le prix n'entre pas dans cette figure."
    )
    choix = st.selectbox("Spot", classement["name"].to_list())
    spot_id = classement.filter(pl.col("name") == choix)["spot_id"][0]
    st.plotly_chart(
        saisonnalite(
            tableau.filter(pl.col("spot_id") == spot_id).sort("month"), mois, c
        ),
        use_container_width=True,
        config={"displayModeBar": False},
    )

    quinzaine = quinzaines.filter(
        (pl.col("spot_id") == spot_id) & (pl.col("month") == mois)
    ).sort("fortnight")
    if quinzaine.height == 2:
        q1, q2 = (v * 100 for v in quinzaine["p_surf"])
        st.caption(
            f"{MOIS[mois - 1].capitalize()} : première quinzaine {q1:.1f} %, "
            f"seconde {q2:.1f} %. Un écart de plus de "
            f"{CONFIG.fortnight_gap_points:.0f} points est signalé dans le tableau."
        )

    st.divider()
    if jour_snapshot is None:
        st.warning("Aucun snapshot de prix : l'axe prix est indisponible.")
    else:
        fraicheur = (
            f"Prix collectés le {jour_snapshot.isoformat()}"
            f" — il y a {anciennete} jour{'s' if anciennete > 1 else ''}."
        )
        perime = anciennete > 30
        (st.warning if perime else st.caption)(
            fraicheur
            + (" Ces prix datent ; ils illustrent la méthode, pas une offre." if perime else "")
        )
    st.caption(
        "Données météorologiques et océaniques fournies par "
        "[Open-Meteo.com](https://open-meteo.com/) sous licence "
        "[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). "
        "Trait de côte : [Natural Earth](https://www.naturalearthdata.com/), domaine public. "
        "Prix : [Travelpayouts](https://www.travelpayouts.com/)."
    )


if __name__ == "__main__":
    main()
