"""La palette du produit, et rien d'autre. Une seule définition pour deux lecteurs.

Le dashboard (`app.py`) et les notebooks doivent peindre la même chose de la même
façon : deux copies divergeraient au premier ajustement, et la vitrine donnerait
l'impression de deux produits. Elle vit donc ici, sans dépendance à Streamlit —
un notebook n'a pas à charger un serveur web pour connaître un bleu.

**Ces couleurs ne sont pas choisies à l'œil.** Elles sortent du système de dataviz du
projet et passent son validateur. Vérifié le 2026-08-03 :

  - la teinte catégorielle unique (`serie`) passe les cinq contrôles — bande de
    clarté, plancher de chroma, séparation daltonisme, plancher vision normale et
    contraste — sur la surface claire ET sur la surface sombre ;
  - les deux rampes séquentielles sont strictement monotones en clarté.

`serie_attenuee` n'est **pas** un second emplacement catégoriel : c'est un pas
d'atténuation, volontairement clair, réservé à ce qu'on met en retrait. L'employer
comme seconde série ferait échouer la bande de clarté et le plancher de chroma — et
c'est précisément ce que le validateur signale si on le lui soumet comme tel.

Le rouge est absent, et c'est délibéré : dans ce système c'est une couleur de
STATUT. Un accent d'interface peint en rouge se lit comme une alerte.
"""

CLAIR = {
    "surface": "#fcfcfb",
    "encre": "#0b0b0b",
    "encre_2": "#52514e",
    "encre_muette": "#898781",
    "grille": "#e1e0d9",
    "serie": "#2a78d6",
    "serie_attenuee": "#b7d3f6",
    "rampe": ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#104281"],
    "terre": "#e1e0d9",
}

SOMBRE = {
    "surface": "#1a1a19",
    "encre": "#ffffff",
    "encre_2": "#c3c2b7",
    "encre_muette": "#898781",
    "grille": "#2c2c2a",
    "serie": "#3987e5",
    "serie_attenuee": "#1c5cab",
    "rampe": ["#104281", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4"],
    "terre": "#2c2c2a",
}


def style_matplotlib(c: dict | None = None) -> dict:
    """Réglages `rcParams` pour que les notebooks aient l'allure du dashboard.

    Grille et axes récessifs, pas de cadre : dans un graphique, le trait de données
    doit être ce qu'on voit en premier.
    """
    c = c or CLAIR
    return {
        "figure.facecolor": c["surface"],
        "axes.facecolor": c["surface"],
        "savefig.facecolor": c["surface"],
        "axes.edgecolor": c["grille"],
        "axes.labelcolor": c["encre_2"],
        "axes.titlecolor": c["encre"],
        "axes.grid": True,
        "axes.axisbelow": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "grid.color": c["grille"],
        "grid.linewidth": 0.8,
        "text.color": c["encre"],
        "xtick.color": c["encre_muette"],
        "ytick.color": c["encre_muette"],
        "xtick.labelcolor": c["encre_2"],
        "ytick.labelcolor": c["encre_2"],
        "figure.dpi": 110,
        "font.size": 10,
        "lines.linewidth": 2.0,
        "lines.markersize": 8,
    }
