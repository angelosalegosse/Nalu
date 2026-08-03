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
            "title": {"text": "P_surf (%)", "font": {"color": c["encre_2"], "size": 12}},
            "tickfont": {"color": c["encre_muette"], "size": 11},
            "gridcolor": c["grille"], "zeroline": False,
        },
        hoverlabel={"bgcolor": c["surface"], "font": {"color": c["encre"]}},
    )
    return figure


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
        "rang",
        pl.col("name").alias("Spot"),
        pl.col("country").alias("Pays"),
        (pl.col("p_surf") * 100).round(1).alias("P_surf %"),
        pl.col("q").round(3).alias("Q"),
        pl.col("rank_q").round(3).alias("rang Q"),
        pl.when(pl.col("price_eur").is_null())
        .then(pl.lit(SANS_PRIX))
        .otherwise(
            pl.col("price_eur").round(0).cast(pl.Int64).cast(pl.Utf8)
            .str.pad_start(largeur, " ")
            + pl.lit(" €")
        )
        .alias("Prix €"),
        pl.col("rank_price").round(3).alias("rang prix"),
        pl.col("score").round(3).alias("Score"),
        pl.col("hours_surfable").alias("h surfables"),
        pl.col("hours_daylight").alias("h diurnes"),
        pl.col("intensity").round(2).alias("Intensité"),
        pl.when(pl.col("price_missing"))
        .then(pl.lit("prix non couvert"))
        .when(pl.col("dispersion_alert"))
        .then(pl.lit("écart entre quinzaines"))
        .otherwise(pl.lit(""))
        .alias("Signalement"),
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

    gauche, droite = st.columns([1, 2])
    with gauche:
        mois = st.selectbox(
            "Mois de départ", range(1, 13), format_func=lambda m: MOIS[m - 1].capitalize()
        )
    with droite:
        alpha = st.slider(
            "Le billet le moins cher  ←→  la meilleure vague",
            0.0, 1.0, 0.5, 0.05,
            help="alpha = 1 privilégie la qualité de houle, alpha = 0 le prix du billet.",
        )

    # Une seule implémentation du classement, partagée avec les tests : l'ordre affiché
    # est exactement celui qu'ils vérifient.
    classement = classer(tableau, mois, alpha)

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
    st.dataframe(
        affichage,
        hide_index=True,
        use_container_width=True,
        height=EN_TETE_TABLEAU + classement.height * LIGNE_TABLEAU,
    )
    st.caption(
        "**Intensité** est informative : elle n'entre pas dans le score. "
        "**Le rang prix vaut 0** pour un spot non couvert — il reste affiché."
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
