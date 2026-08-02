# Nalu

Moteur de recommandation de trips surf. Il croise **dix ans de climatologie de houle**
(ERA5, 2015-2024) avec les **prix des vols au départ de Paris**, et classe les spots
selon un curseur que l'utilisateur déplace entre « la meilleure vague » et
« le billet le moins cher ».

Un surfeur ne planifie pas ses vacances à la météo du week-end : il pose une semaine
de congés trois mois à l'avance. Aucune prévision de houle n'existe à cet horizon.
La seule réponse honnête est probabiliste — *quelle est la probabilité que ce spot
marche en octobre, et combien coûte le billet ce mois-là*.

> **Vitrine technique.** Ce dépôt n'est pas destiné à la production. Il est écrit pour
> être lu : chaque hypothèse du modèle est isolée, typée et justifiée en une phrase.

---

## Démarrage

Un seul prérequis : [`uv`](https://docs.astral.sh/uv/). Il télécharge lui-même
Python 3.12 — inutile d'en avoir un d'installé.

```bash
uv sync                # environnement + dépendances, verrouillés par uv.lock
uv run pytest          # tests
uv run ruff check      # lint
```

> **Python 3.12 est épinglé** (`requires-python = "==3.12.*"` et `.python-version`).
> La pile scientifique n'est pas stabilisée sur 3.14, et un environnement non épinglé
> transforme un `uv sync` de trente secondes en vingt minutes de compilation C.

> **Derrière un proxy d'entreprise ?** Si `uv sync` échoue sur
> `invalid peer certificate: UnknownIssuer`, le trafic TLS est réécrit par un proxy
> dont l'autorité n'est pas dans le magasin livré avec `uv`. Utiliser le magasin de
> certificats du système : `uv sync --system-certs` (ou `UV_NATIVE_TLS=1`).

Les deux variables d'environnement de `.env.example` sont **optionnelles**. Sans
elles, tout démarre : le cache parquet versionné dans le dépôt rend la démonstration
reproductible **sans réseau et sans clé d'API**.

## État d'avancement

Le socle est en place ([#2](https://github.com/angelosalegosse/Nalu/issues/2)) : outillage,
`config.py` et `geo.py`. Le reste du pipeline arrive par les issues #3 à #10.

```
data/spots.yaml (20 spots, chacun avec `source` et `confidence`)
        |
        +--> geo.py : lancer de rayons sur Natural Earth          [#2] fait
        |            -> fenetre d'exposition CALCULEE
        |
        +--> ingest/openmeteo.py --> data/raw/*.parquet --> scoring/surf.py
        |    (houle + vent + soleil)   (cache versionne)     (surfabilite horaire)
        |                                                            |
        |                                                            v
        |                                                  scoring/climatology.py
        |                                                   (P_surf par spot x mois)
        |                                                            |
        +--> ingest/flights.py                                       |
             (sonde + live + snapshot)                               |
                        |                                            |
                        +-------------> scoring/combine.py <---------+
                                Score = a*rang(Q) + (1-a)*rang(-prix)
                                                   |
                                                   v
                                          app.py (Streamlit)
```

Le plan complet vit dans les issues GitHub :

```bash
gh issue view 1     # EPIC : modèle, sources, critères d'acceptation
gh issue list       # les issues filles, #2 à #10
```

`TODOS.md` recense le travail délibérément différé, avec le contexte pour le reprendre.

## Le modèle, en trois lignes

```
P_surf(s,m) = heures surfables en mois m / heures diurnes totales en mois m
Q(s,m)      = P_surf(s,m)                          # une probabilite pure
Score(s,m)  = a * rang(Q) + (1-a) * rang(-prix)    # rangs centiles sur 240 couples
```

Deux choix structurants, et leur raison :

- **Rangs centiles, jamais de min-max.** Une seule valeur extrême écrase une échelle
  min-max et rend le curseur inerte. Le rang est insensible aux extrêmes par
  construction, et rend les deux critères commensurables.
- **`Q` est une probabilité pure.** L'intensité de la houle est calculée et affichée,
  mais **n'entre pas dans le score** : on n'additionne pas une probabilité et une
  grandeur non bornée.

Les onze paramètres réglables vivent tous dans
[`src/nalu/config.py`](src/nalu/config.py), chacun suivi de la phrase qui le justifie.
Aucune constante en dur ailleurs.

## Limites assumées

- **ERA5-Ocean est à 0,5°, soit environ 50 km.** Ce sont des hauteurs significatives
  de houle **au large**, pas des tailles de vague au pic — d'où les seuils nommés
  `hs_offshore_min` / `hs_offshore_max`, pour rendre l'abus sémantique impossible.
- **Pas de marée.** Elle décide autant que la houle sur beaucoup de reef breaks, mais
  aucune source gratuite ne la couvre mondialement sur dix ans d'archives.
- **Pas de bathymétrie ni de réfraction.** Hors de portée d'une maille de 50 km.
- **20 spots, pas 50.** Les seuils sont l'actif central du produit : 20 spots sourcés
  valent mieux que 50 devinés.

## Sources et attribution

| Source | Usage | Licence |
|---|---|---|
| [Open-Meteo](https://open-meteo.com/) (ERA5 / ERA5-Ocean) | Houle, vent, lever et coucher du soleil | CC BY 4.0, usage non commercial |
| [Travelpayouts](https://www.travelpayouts.com/) | Prix mini par mois au départ de Paris | Programme affilié gratuit |
| [Natural Earth](https://www.naturalearthdata.com/) | Polygones de côtes | Domaine public |

Données météorologiques et océaniques fournies par Open-Meteo.com,
d'après les réanalyses ERA5 du Copernicus Climate Change Service (ECMWF).

## Licence

À définir avant publication de la vitrine (issue #10).
