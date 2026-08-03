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

# Plafond de hauteur sur grand écran : au-delà, la carte pousse le tableau — qui est
# le vrai sujet de la page — sous la ligne de flottaison.
CARTE_HAUTEUR_MAX = 460


def palette() -> dict:
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
                text=absents["name"], showlegend=False,
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
            showlegend=False,
            hovertemplate="<b>%{text}</b><br>score %{customdata[0]:.2f}"
            "<br>%{customdata[1]:.0f} €<extra></extra>",
        )
    )
    figure.update_layout(
        paper_bgcolor=c["surface"], plot_bgcolor=c["surface"],
        margin={"l": 0, "r": 0, "t": 0, "b": 0}, height=CARTE_HAUTEUR_MAX,
        xaxis={"visible": False, "range": list(CARTE_LON)},
        yaxis={
            "visible": False, "range": list(CARTE_LAT),
            "scaleanchor": "x", "scaleratio": 1,
        },
        hoverlabel={"bgcolor": c["surface"], "font": {"color": c["encre"]}},
    )
    return figure


def saisonnalite(serie: pl.DataFrame, mois_actif: int, c: dict) -> go.Figure:
    """Les douze mois du spot sélectionné. Une seule série : pas de légende."""
    couleurs = [c["serie"] if m == mois_actif else c["serie_attenuee"] for m in serie["month"]]
    figure = go.Figure(
        go.Bar(
            x=[MOIS[m - 1][:4] for m in serie["month"]],
            y=serie["p_surf"] * 100,
            marker={"color": couleurs, "line": {"width": 0}},
            hovertemplate="%{x} — %{y:.1f} % des heures diurnes<extra></extra>",
        )
    )
    figure.update_layout(
        paper_bgcolor=c["surface"], plot_bgcolor=c["surface"],
        margin={"l": 0, "r": 0, "t": 10, "b": 0}, height=220, bargap=0.35,
        xaxis={"tickfont": {"color": c["encre_muette"], "size": 11}, "showgrid": False},
        yaxis={
            "title": {"text": "P_surf (%)", "font": {"color": c["encre_2"], "size": 12}},
            "tickfont": {"color": c["encre_muette"], "size": 11},
            "gridcolor": c["grille"], "zeroline": False,
        },
        hoverlabel={"bgcolor": c["surface"], "font": {"color": c["encre"]}},
    )
    return figure


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

    # Le planisphère verrouille ses proportions (`scaleanchor`) pour ne pas déformer
    # les continents. Une hauteur fixe entre alors en conflit avec cette contrainte :
    # sur un écran étroit, la carte est bornée par la LARGEUR et ne remplit plus la
    # hauteur réservée. Mesuré à 390 px : carte de 143 px dans une boîte de 340,
    # soit ~200 px de vide entre la carte et le tableau. La hauteur doit donc suivre
    # la largeur, ce que seul le CSS sait faire — Python ne connaît pas la fenêtre.
    st.html(
        f"""<style>
        .st-key-planisphere [data-testid="stPlotlyChart"],
        .st-key-planisphere .js-plotly-plot,
        .st-key-planisphere .plot-container {{
            height: auto !important;
            aspect-ratio: {CARTE_LON_SPAN} / {CARTE_LAT_SPAN};
            max-height: {CARTE_HAUTEUR_MAX}px;
        }}
        </style>"""
    )
    with st.container(key="planisphere"):
        st.plotly_chart(carte(classement, contour, c), use_container_width=True)

    affichage = classement.select(
        "rang",
        pl.col("name").alias("Spot"),
        pl.col("country").alias("Pays"),
        (pl.col("p_surf") * 100).round(1).alias("P_surf %"),
        pl.col("q").round(3).alias("Q"),
        pl.col("rank_q").round(3).alias("rang Q"),
        pl.col("price_eur").alias("Prix €"),
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
    st.dataframe(affichage, hide_index=True, use_container_width=True)
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

    choix = st.selectbox("Saisonnalité d'un spot", classement["name"].to_list())
    spot_id = classement.filter(pl.col("name") == choix)["spot_id"][0]
    st.plotly_chart(
        saisonnalite(
            tableau.filter(pl.col("spot_id") == spot_id).sort("month"), mois, c
        ),
        use_container_width=True,
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
