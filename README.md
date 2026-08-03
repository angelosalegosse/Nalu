# Nalu

### → **[Ouvrir la démo : nalu-surf.streamlit.app](https://nalu-surf.streamlit.app)**

Rien à cloner, rien à installer. **Si la page met une trentaine de secondes à
apparaître, ce n'est pas cassé :** l'hébergement gratuit endort les applications
inactives et les réveille à la première visite. Les visites suivantes sont immédiates.

---

Moteur de recommandation de trips surf. Il croise **quatre ans de climatologie de
houle** (2022-2025) avec les **prix des vols au départ de Paris**, et classe les spots
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

## Déploiement

L'application est hébergée sur **Streamlit Community Cloud**, gratuit et connecté au
dépôt : chaque `push` sur `main` redéploie. Trois points qui ne sont pas devinables :

- **Les dépendances viennent de `uv.lock`.** Community Cloud cherche un fichier de
  dépendances dans un ordre fixe et s'arrête au premier trouvé ; `uv.lock` est en tête.
  C'est le bon cas : il installe les versions exactes du verrou **et** le paquet
  `nalu` lui-même, ce qu'un `requirements.txt` ne ferait pas. Ne pas en ajouter un —
  il ne serait pas lu, et deux fichiers de dépendances est précisément ce que la
  documentation déconseille.
- **Python 3.12 doit être choisi à la création de l'application**, dans « Advanced
  settings ». `pyproject.toml` impose `requires-python = "==3.12.*"` : sur une autre
  version, `uv sync` échoue au lieu de résoudre une pile différente en silence.
  La version ne se change pas après coup, il faut supprimer et redéployer.
- **`GEMINI_API_KEY` se pose en secret d'application**, jamais dans le dépôt
  (Settings → Secrets, au format TOML). Elle est **facultative** : rien ne la lit
  aujourd'hui, elle n'alimentera que le bloc de commentaire de l'issue #9.

Les chemins de données sont ancrés sur la racine du dépôt (`nalu/paths.py`) et non sur
le répertoire courant. C'est ce qui permet à l'application de démarrer quel que soit
l'endroit d'où l'hébergeur la lance.

## État d'avancement

Le pipeline tourne de bout en bout : 20 spots sourcés → 701 280 heures de houle →
240 probabilités mensuelles → 240 prix → un classement que le curseur réordonne.
Socle ([#2](https://github.com/angelosalegosse/Nalu/issues/2)), référentiel
([#3](https://github.com/angelosalegosse/Nalu/issues/3)), ingestion
([#4](https://github.com/angelosalegosse/Nalu/issues/4)), prix
([#6](https://github.com/angelosalegosse/Nalu/issues/6)), surfabilité
([#7](https://github.com/angelosalegosse/Nalu/issues/7)), score et dashboard
([#8](https://github.com/angelosalegosse/Nalu/issues/8)), déploiement
([#10](https://github.com/angelosalegosse/Nalu/issues/10)) et couche IA + notebooks
+ validation externe ([#9](https://github.com/angelosalegosse/Nalu/issues/9)) sont
livrés. Le plan est complet.

```
data/spots.yaml (20 spots, chacun avec `source` et `confidence`)  [#3] fait
        |
        +--> geo.py : lancer de rayons sur Natural Earth          [#2] fait
        |            -> fenetre d'exposition CALCULEE             [#3] fait
        |
        +--> ingest/openmeteo.py --> 160 parquet COMMITES  --> scoring/surf.py
        |    (houle + vent + soleil)  (701 280 heures,          (surfabilite horaire)
        |     [#4] fait                11,8 Mo, hors ligne)
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

Les douze paramètres réglables vivent tous dans
[`src/nalu/config.py`](src/nalu/config.py), chacun suivi de la phrase qui le justifie.
Aucune constante en dur ailleurs.

## Lire le tableau du dashboard

Le tableau des vingt spots est la **preuve** du classement : il expose toutes les
valeurs intermédiaires, pour qu'on puisse refaire le calcul à la main. C'est aussi ce
qui le rend dense. Cette section le décode colonne par colonne — dans l'application,
chaque en-tête porte la même explication en infobulle.

### Les colonnes, une par une

| Colonne | Ce qu'elle vaut | Ce qu'il faut savoir |
|---|---|---|
| **Rang** | 1 à 20 | Position dans le classement du mois choisi, au réglage actuel du curseur. Le tableau est trié par **Score**, pas par houle. |
| **Surfable %** | 0 à 100 | La part des heures **de jour** du mois où la houle, sa période *et* le vent sont simultanément dans les seuils du spot. Moyenne sur 2022-2025. C'est `p_surf` dans le code, et le `Q` de la formule : la même valeur, en pourcentage plutôt qu'en probabilité. |
| **Rang qualité** | 0 à 1 | Rang centile de `Q` parmi les **240 couples spot × mois**. 1 = la meilleure houle du référentiel, 0 = la moins bonne. C'est cette valeur, et non le pourcentage brut, qui entre dans le score. |
| **Prix A/R** | € ou `—` | Aller-retour le moins cher relevé pour ce mois au départ de Paris. `—` signifie **aucune donnée pour cette route**, jamais un prix nul. |
| **Rang prix** | 0 à 1 | Rang centile du prix sur les mêmes 240 couples. 1 = le billet le moins cher. **Un spot sans prix reçoit 0** — voir la limite ci-dessous. |
| **Score** | 0 à 1 | `α × Rang qualité + (1 − α) × Rang prix`. La seule colonne que le curseur déplace, et celle qui trie le tableau. |
| **Signalement** | texte | `prix non couvert` : aucun prix pour cette route. `écart entre quinzaines` : les deux moitiés du mois diffèrent assez pour qu'une moyenne mensuelle induise en erreur. |
| **Heures OK** | un compte | Le nombre brut d'heures de jour **surfables** comptées pour ce mois sur les quatre années. |
| **Heures jour** | un compte | Le nombre **total** d'heures de jour sur la même période. **Surfable %** est exactement le rapport des deux colonnes — c'est ce qui rend le pourcentage vérifiable à la main. |
| **Taille** | 0 à 1 | Taille **relative**, détaillée juste en dessous. **Informative : elle n'entre pas dans le score.** |

Les en-têtes sont courts parce que douze colonnes tiennent mal sur un écran étroit ;
l'explication complète est dans l'infobulle de chaque en-tête, au survol. L'ordre des
colonnes suit l'importance décroissante : sur un écran étroit, celles qui passent
derrière le défilement horizontal sont les dernières, qui sont aussi les plus
accessoires.

`Q` n'a pas sa propre colonne. `Q = P_surf` par définition du modèle, donc l'afficher
peignait deux fois le même nombre — `0,007` en face de `0,7` — ce qui ajoutait de la
confusion là où le tableau cherche à en retirer. Le lien à la formule n'est pas perdu :
**Surfable %** *est* `Q`, en pourcentage, et **Rang qualité** — la valeur qui entre
réellement dans le score — est juste à côté.

### La colonne « Taille » : un ratio, dont le maximum est 1

C'est une **position relative dans la fenêtre de hauteur propre au spot**, pas une
taille de vague :

```
Taille = (houle moyenne des heures surfables − hs_offshore_min) / (hs_offshore_max − hs_offshore_min)
```

- **Le maximum est 1**, atteint si la houle moyenne égale le plafond du spot. **0** vaut
  pour le seuil bas. Le résultat est borné dans `[0, 1]` par construction : une heure
  n'est comptée surfable que si sa hauteur tombe déjà dans la fenêtre, donc une moyenne
  de valeurs comprises entre les deux bornes ne peut pas en sortir.
- **1 n'est jamais atteint en pratique, et ne peut presque pas l'être.** C'est une
  *moyenne* sur toutes les heures surfables du mois : il faudrait que chacune tombe pile
  au plafond. Sur les 240 couples, le maximum observé est **0,57** — Supertubos en
  novembre, soit 2,14 m de houle moyenne dans une fenêtre de 1 à 3 m. La médiane est
  **0,14**. Une valeur au-dessus de 0,4 est donc déjà un gros mois.
- **Deux spots ne se comparent pas en mètres.** Chaque fenêtre est propre au spot, et
  elles vont de 1,7 à 3,0 m d'étendue. `0,45` vaut **1,90 m** à Supertubos (fenêtre
  1→3 m) et **2,85 m** à Zicatela (fenêtre 1,5→4,5 m). La colonne répond à « ce mois
  est-il gros *pour ce spot* », jamais à « quel spot a les plus grosses vagues ».
- **Un 0 se lit « aucune heure surfable », pas « petite houle ».** Les 46 lignes à 0 du
  cache actuel sont exactement les 46 sans une seule heure surfable : sans hauteur à
  moyenner, le calcul retombe sur 0. C'est une ambiguïté réelle de la colonne — la
  distinguer d'un vrai zéro demanderait une valeur absente, et la colonne **Heures OK**
  la lève déjà en affichant 0.

**Pourquoi elle reste hors du score.** C'est une normalisation min-max, exactement ce
que le score s'interdit. Ici c'est sans danger : les bornes sont des **seuils déclarés
et sourcés** par spot, pas des extrêmes observés qu'une seule valeur aberrante
déplacerait. Mais l'ajouter au score reviendrait à additionner une probabilité et une
grandeur d'une autre nature, ce que le modèle refuse depuis le début.

### Pourquoi le premier n'est pas celui qui a les meilleures vagues

C'est le contresens le plus probable de la page, et il vaut d'être fait une fois pour
comprendre le modèle. **Janvier, curseur au milieu (`α = 0,5`), les trois premiers :**

| Rang | Spot | Surfable % | Rang qualité | Prix A/R | Rang prix | Score |
|---:|---|---:|---:|---:|---:|---:|
| 1 | Ponta Preta | 0,7 | 0,326 | 301 € | 0,768 | **0,547** |
| 2 | Uluwatu | 2,2 | 0,494 | 683 € | 0,580 | **0,537** |
| 3 | La Gravière | 28,3 | 0,992 | — | 0,000 | **0,496** |

Ponta Preta est première avec **0,7 % d'heures surfables** : sur les 1 364 heures de
jour de janvier relevées sur quatre ans, 10 seulement réunissaient houle, période et
vent. C'est très peu, et le modèle le dit. Le calcul se refait de tête :

```
Ponta Preta   0,5 × 0,326 + 0,5 × 0,768 = 0,163 + 0,384 = 0,547
                            ^^^^^^^^^^^   c'est le billet a 301 € qui porte le score
La Graviere   0,5 × 0,992 + 0,5 × 0,000 = 0,496 + 0     = 0,496
                                          ^^^^^   la meilleure houle du mois, et 3e
```

**Le curseur n'est pas un réglage cosmétique, c'est le modèle.** Poussé sur « la
meilleure vague » (`α = 1`), le rang prix disparaît de l'équation et le classement
devient celui de la houle seule : La Gravière première avec 0,992, Anchor Point, puis
Mundaka. Tiré sur « le billet le moins cher » (`α = 0`), Ponta Preta reste première pour
la raison inverse — son billet.

C'est aussi pour cela que chaque carte du podium porte une ligne du type
*« 10 h surfables sur 1 364 h de jour · classé surtout sur le prix »* : elle nomme celui
des deux termes qui l'emporte, au réglage courant.

### Deux limites qu'il faut lire avant de conclure

- **Un spot sans prix reçoit le rang prix 0, ce qui le pénalise au lieu de le
  neutraliser.** Sur 240 couples, 170 n'ont aucun prix : à `α = 0,5`, l'axe prix mesure
  donc en partie « cette route est-elle populaire » et pas seulement « ce billet est-il
  bon marché ». Cas le plus net, toujours en janvier : Arugam Bay et Sultans sortent 11ᵉ
  et 12ᵉ avec `Surfable % = 0` — jamais surfables — devant Teahupo'o et Chicama, qui le
  sont un peu, **uniquement parce qu'ils ont un prix**. La [couverture des prix et le
  biais qu'elle cache](#couverture-des-prix-et-le-biais-quelle-cache--mesuré-le-2-août-2026)
  est mesurée plus bas, et l'arbitrage est ouvert et assumé, pas ignoré.
- **Taille relative n'entre pas dans le score.** On n'additionne pas une probabilité
  bornée et une hauteur de houle qui ne l'est pas. Un spot peut donc avoir une meilleure
  taille relative et un moins bon rang : ce n'est pas une incohérence, c'est la règle.

### Les deux figures

Le **planisphère** ne montre qu'une chose : le Score, par la teinte du disque. Un
**anneau** au lieu d'un disque signifie « prix non couvert » — un trou de données, pas
une mauvaise vague. La légende est posée dans la carte pour ne pas coûter de largeur.

La **saisonnalité** montre les douze mois d'un seul spot, en part d'heures de jour
surfables. La barre pleine est le mois choisi. Le prix n'y entre pas : c'est la figure
qui répond à « quand », quand le tableau répond à « où ».

## Les fenêtres de houle sont calculées, pas déclarées

Un spot ne reçoit pas la houle de toutes les directions : une pointe, une baie ou une
île voisine en masquent une partie. Plutôt que de déclarer cette fenêtre à la main,
[`geo.py`](src/nalu/geo.py) lance 180 rayons depuis chaque spot sur les polygones de
côtes Natural Earth et retient le plus long arc où le rayon atteint 500 km d'océan
ouvert.

```bash
uv run python -m nalu.exposure     # régénère data/exposure_windows.yaml
```

**Le résultat a été confronté à la direction de houle idéale publiée pour chaque
spot. 15 fenêtres sur 20 concordent sans intervention.** Les 5 écarts ne sont pas du
bruit, ils ont deux causes identifiées :

| Cause | Spots | Ce qui se passe |
|---|---|---|
| Point break à enroulement | Anchor Point, Jeffreys Bay, Chicama | La houle arrive d'un cap que la pointe elle-même masque, puis réfracte autour. Le lancer de rayons mesure l'exposition **locale** ; ERA5 à 50 km donne la direction **du large**. |
| Ombre d'une île sous 500 km | Tres Palmas, Tamarin Bay | Hispaniola, La Réunion. Le seuil de 500 km mesure le fetch nécessaire à la formation d'une houle longue — l'employer comme critère de blocage ferme un secteur que la houle traverse. |

Ces 5 spots portent un `swell_dir_override` accompagné d'un `override_reason`
obligatoire : la validation Pydantic **échoue** si la raison manque. La valeur
calculée reste écrite dans `data/exposure_windows.yaml`, pour que l'écart entre ce
que dit la géométrie et ce que dit le terrain reste lisible.

## Pourquoi quatre ans et pas dix

Le projet visait dix ans d'archives. La mesure a tranché autrement, et le raisonnement
mérite d'être lu — c'est le genre d'arbitrage qui décide de la valeur d'un modèle.

Open-Meteo distingue deux choses qu'on confond facilement :

| | `wave_*` — mer totale | `swell_wave_*` — houle seule |
|---|---|---|
| Contenu | houle **+ mer du vent** | houle uniquement |
| `era5_ocean` (0,5°) | 1940 → aujourd'hui | **vide, à toutes les années** |
| `best_match` (5–25 km) | déc. 2021 → | déc. 2021 → |

Vérifié année par année, sur plusieurs spots. La documentation annonce
`swell_wave_height` comme disponible : c'est faux pour ERA5-Ocean.

L'arbitrage était donc **dix ans avec la mer du vent incluse**, ou **quatre ans avec la
houle pure**. Utiliser la mer totale ferait compter du clapot comme surfable — c'est
exactement ce que le modèle cherche à éviter, puisque toute sa valeur tient à ne pas
confondre une vague de 1,5 m à 14 s avec un clapot de 1,5 m à 5 s.

**Quatre ans de houle pure valent mieux que dix ans de mer confondue.** La limite est
réelle et assumée : la variabilité interannuelle est sous-échantillonnée, et un épisode
El Niño pèse plus lourd sur quatre ans que sur dix.

NOAA WaveWatch III a été évalué comme alternative et écarté : son hindcast couvre
1979-2009, le multi-grid s'arrête en 2019, et il ne rejoint jamais le présent.

## Couverture des prix, et le biais qu'elle cache — mesuré le 2 août 2026

Travelpayouts ne fait pas d'interrogation GDS : il sert des minima issus du **cache de
recherches de ses utilisateurs**. La couverture d'une route est donc proportionnelle à
sa popularité touristique, pas à son intérêt pour un surfeur. Ce biais était prévu
avant la mesure ; le plan de repli a été écrit avant d'en connaître le résultat.

Sonde `uv run python -m nalu.ingest.flights --probe`, origine `PAR`, horizon 12 mois :

| Spot | IATA | Mois avec un prix | Popularité |
|---|---|---:|---:|
| Uluwatu | DPS | 11 | 3 |
| Sultans | MLE | 10 | 3 |
| Teahupo'o | PPT | 9 | 2 |
| Supertubos | LIS | 7 | 3 |
| Tamarin Bay | MRU | 7 | 3 |
| Arugam Bay | CMB | 4 | 2 |
| Bells Beach | MEL | 4 | 2 |
| Ponta Preta | SID | 4 | 2 |
| Anchor Point | AGA | 3 | 3 |
| Mundaka | BIO | 3 | 3 |
| La Gravière | BIQ | 2 | 3 |
| Banzai Pipeline | HNL | 2 | 2 |
| Playa Grande | LIR | 2 | 2 |
| Cloudbreak | NAN | 1 | 1 |
| Tres Palmas | SJU | 1 | 2 |
| **Klitmøller** | AAL | **0** | 1 |
| **Thurso East** | INV | **0** | 1 |
| **Jeffreys Bay** | PLZ | **0** | 1 |
| **Zicatela** | PXM | **0** | 1 |
| **Chicama** | TRU | **0** | 1 |

**Corrélation de rangs entre couverture et popularité : +0,78.**

Le biais n'est donc pas une hypothèse, c'est un fait mesuré. **Les cinq destinations
sans aucun prix sont exactement les cinq de popularité minimale.** Le passage en rang
centile aurait rendu ce biais invisible, pas absent : sans cette mesure, le classement
final aurait silencieusement corrélé avec la fréquentation touristique.

### Décision produit appliquée

15 destinations couvertes sur 20 → **référentiel restreint aux spots couverts**, selon
le tableau de repli fixé *avant* la mesure (≥ 16 : deux axes · 10–15 : restreint ·
< 10 : mono-axe). Ce repli n'a pas été renégocié après coup — une décision prise après
le résultat serait une justification, pas une décision.

Concrètement, et conformément au modèle : **les cinq spots non couverts restent
affichés**, reçoivent un rang de prix nul et sont visiblement marqués « prix non
couvert ». La restriction porte sur l'axe prix, pas sur le référentiel : les faire
disparaître reviendrait à laisser le biais décider du contenu du produit.

### Ce que ce chiffre ne dit pas

« Couvert » signifie ici **au moins un mois sur douze**. C'est une barre basse, et le
résultat y est sensible :

| Seuil de couverture | Destinations retenues | Décision qui en découlerait |
|---|---:|---|
| ≥ 1 mois *(retenu)* | 15 | référentiel restreint |
| ≥ 2 mois | 13 | référentiel restreint |
| ≥ 3 mois | 10 | référentiel restreint |
| ≥ 6 mois | 5 | mono-axe |

Cloudbreak et Tres Palmas, avec un seul mois servi, n'ont pas de véritable axe prix
comparable sur l'année. C'est une limite réelle du produit, écrite ici plutôt que
découverte par un lecteur attentif.

## Les trois notebooks, et ce qu'ils prouvent

```bash
uv run jupyter lab notebooks/          # les ouvrir
uv run jupyter nbconvert --to notebook --execute --inplace notebooks/*.ipynb
```

Ils sont commités **avec leurs sorties** : un lecteur les lit sur GitHub sans rien
installer. Un test rejoue les trois à chaque CI, pour qu'ils ne puissent pas afficher
des résultats que le code ne produit plus.

| Notebook | Ce qu'il établit |
|---|---|
| [`01-exploration-houle`](notebooks/01-exploration-houle.ipynb) | Le cache est complet (0 % de valeurs manquantes). La mer totale surestime la houle de 0,22 m en médiane, et de plus de 50 cm sur 14 % des heures — **la décision de perdre six ans d'archive est mesurée, pas postulée.** |
| [`02-validation-scoring`](notebooks/02-validation-scoring.ipynb) | La confrontation à deux sources externes. **Le modèle échoue à son propre critère.** |
| [`03-analyse-vols`](notebooks/03-analyse-vols.ipynb) | La couverture des prix corrèle à **+0,78** avec la popularité touristique. Qualité contre prix : **+0,12**, donc l'arbitrage du curseur est réel. |

### La validation externe échoue, et c'est écrit

Le modèle retrouve la haute saison publiée sur **10 spots sur 20 — 50 %, contre 70 %
exigés.** Le seuil avait été fixé avant la mesure, dans `src/nalu/validation.py`, et
il n'a pas été déplacé après coup.

Ce que dit le détail, qui est plus utile que le taux :

- l'**écart médian est nul** — quand le modèle tombe juste, il tombe pile ;
- **6 échecs sur 10 ratent d'un seul mois**, ce qui est de l'ordre du désaccord entre
  guides ;
- **2 spots n'ont aucun pic** (Sultans, Tres Palmas, `p_surf = 0` partout) : leurs
  seuils sont mal calibrés, c'est mesuré et non corrigé ici ;
- **2 spots se trompent vraiment** — La Gravière et Mundaka, placés en plein hiver
  quand les guides publient l'automne. Même cause pour les deux : leur saison dépend
  de la **forme du fond**, sable ou embouchure, que le modèle ne voit pas. C'est la
  limite `hs_offshore_*` déjà annoncée, et la validation la retrouve seule.

La métrique et le référentiel de comparaison
([`data/validation_seasons.yaml`](data/validation_seasons.yaml), deux sources par
spot, chacune avec son URL) sont versionnés **avant** la première exécution du
notebook. `git log --follow` sur ces deux fichiers est ce qui distingue une validation
d'un ajustement déguisé.

## La couche IA : elle commente, elle ne décide pas

`GEMINI_API_KEY` est **facultative**. Sans elle, le dashboard fonctionne
intégralement et le bloc commentaire affiche une phrase explicite.

- **Aucun chiffre affiché ne vient du modèle de langage.** Il lit un classement déjà
  calculé et le met en mots.
- **Le tableau qui lui est transmis est de la donnée, pas des instructions.** Il est
  encadré par des délimiteurs, avec consigne explicite d'ignorer toute directive qui
  s'y trouverait — la seule surface d'injection du produit, fermée avant d'en avoir
  besoin.
- **Le commentaire est mis en cache par `(mois, alpha au dixième)`**, sinon le curseur
  épuiserait le quota gratuit en quelques secondes de va-et-vient.
- **Toute panne dégrade** : clé absente, clé refusée, réseau coupé, quota dépassé,
  réponse vide. Jamais une exception dans un dashboard de démonstration.

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

## Licence des données — la question tranchée avant la publication

Publier cette vitrine oblige à répondre à une question qu'une démo locale laissait
dormir : **le tier gratuit d'Open-Meteo est réservé à l'usage non commercial**, et une
vitrine de cabinet de conseil n'est pas un usage non commercial. L'argument « la démo
tourne hors ligne » ne suffit plus dès lors qu'elle est publiée pour se faire connaître.

La réponse tient à une distinction que les deux pages d'Open-Meteo énoncent
séparément, et qu'il faut lire ensemble :

| Ce dont on parle | Ce que dit Open-Meteo | Ce que fait Nalu |
|---|---|---|
| **Le service d'API** gratuit | usage **non commercial** uniquement | l'application déployée ne l'appelle **jamais** |
| **Les données** servies par l'API | **CC BY 4.0**, qui autorise l'usage commercial avec attribution | redistribuées telles quelles, attribuées |
| La source sous-jacente (ERA5 / Copernicus) | licence Copernicus, usage commercial autorisé | — |

Ce qui est restreint, c'est **l'accès au service**, pas la réutilisation des données.
L'application publiée ne fait aucun appel réseau : elle lit un cache parquet versionné.
Ce cache est de la donnée sous CC BY 4.0, redistribuée avec son attribution, en pied de
dashboard et ici même. Cette redistribution est explicitement permise par la licence.

**La zone grise, écrite plutôt que passée sous silence.** L'ingestion qui a rempli ce
cache — une seule, le 2 août 2026, 2 296 unités de quota — a bien consommé le service
gratuit, pour un projet qui sert de vitrine à une activité commerciale. On peut soutenir
que cette collecte unique aurait dû relever d'une licence commerciale. Trois éléments,
pour que le lecteur juge lui-même : elle n'a eu lieu qu'une fois, elle porte sur un
volume dérisoire, et l'application ne comporte ni publicité, ni abonnement, ni lien
marchand. Passer à l'offre payante d'Open-Meteo lèverait l'ambiguïté, au prix de la
première contrainte du projet — coût total nul.

**NOAA WaveWatch III ne sauve pas cette question**, contrairement à ce que prévoyait le
plan initial : son hindcast s'arrête en 2009, son multi-grid en 2019, et il ne rejoint
jamais le présent. La bascule aurait échangé un problème de licence contre un modèle
qui ne décrit plus le climat actuel.

## Licence du code

Le code de ce dépôt est publié sous licence [MIT](LICENSE). Les **données** de `data/`
ne sont pas couvertes par cette licence : elles restent sous celle de leur source
(Open-Meteo CC BY 4.0, Natural Earth domaine public, prix Travelpayouts).
