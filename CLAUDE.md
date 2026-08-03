# Nalu

Moteur de recommandation de trips surf : croise **4 ans (2022‑2025)** de climatologie de houle avec les prix des vols au départ de Paris, et classe les spots selon un curseur qualité/prix réglable par l'utilisateur.

**Nature du projet :** vitrine technique d'un cabinet de conseil Data & IA. Le lecteur cible du dépôt n'est pas un surfeur, c'est un prospect qui évalue une compétence. Ce n'est pas destiné à la production, mais tout doit être propre, auditable et publiquement accessible.

**Échéance : 16 août 2026.**

---

## Lire ceci en premier

Le plan complet vit dans les issues GitHub, pas dans ce fichier.

```bash
gh issue view 1              # EPIC : plan complet, modèle, sources, critères d'acceptation
gh issue list --state all    # les 8 issues filles, #2 à #10 — TOUTES fermées
```

⚠️ `gh issue list` sans `--state all` ne renvoie **rien** : les dix issues sont fermées
depuis le 3 août 2026. Le dépôt n'est pas vide de plan, le plan est fini.

L'EPIC #1 porte en tête un tableau des **cinq amendements rendus par la mesure** —
profondeur d'archive, abandon de NOAA, repli après la sonde de couverture, douzième
paramètre, poids réel du quota — et le texte du plan d'origine est conservé intact en
dessous. Chaque issue fille est fermée avec le commit qui l'a livrée.

`TODOS.md` à la racine contient le travail délibérément différé, avec son contexte.

## État au 4 août 2026

| Issue | État |
|---|---|
| #2 socle, `config.py`, `geo.py` | ✅ livrée |
| #3 référentiel 20 spots, fenêtres calculées | ✅ livrée |
| #4 ingestion Open-Meteo, cache commité | ✅ livrée |
| #6 sonde de couverture, prix, snapshot | ✅ livrée |
| #7 surfabilité, climatologie, dispersion | ✅ livrée |
| #8 score en rangs, curseur, dashboard | ✅ livrée |
| #10 déploiement public | ✅ livrée — **en ligne et publique** |
| #9 Gemini, notebooks, validation externe | ✅ livrée |

**→ https://nalu-surf.streamlit.app** — vérifiée ouverte à un visiteur anonyme.
Streamlit Cloud redéploie à chaque push sur `main`.

`main` est verte, 298 tests. Le pipeline tourne de bout en bout : 20 spots sourcés →
701 280 heures → 240 probabilités mensuelles → 240 prix → classement réordonnable,
commenté par Gemini quand une clé est posée.

**Le plan est complet.** Il ne reste aucune issue ouverte.

### Ce qui a été fait le 4 août, hors plan

Deux passes de design, dans cet ordre — la seconde n'aurait rien valu sans la première.

1. **Passe de défauts** (`df77fe3`). Sept défauts trouvés en ouvrant la page, aucun
   attrapé par les 287 tests : deux classes de marqueurs sans légende · `None` affiché
   en clair sur quatorze lignes · un seul `h1` pour six blocs de texte identiques ·
   dix lignes sur vingt derrière un défilement invisible · mois tronqués en
   « avri / octo / nove » · deux typographies · un accent manquant.
2. **Direction visuelle** (`c357c06`), sur un brief explicite du porteur : *ce qu'un
   prospect doit retenir est une **envie**, pas une démonstration.* Trois références
   ouvertes et mesurées — Our World in Data pour la structure, Nomad List pour le
   désir, The Pudding pour l'artisanat. D'où : Fraunces + Inter, contrôles dans le rail
   latéral, et un **podium** de trois cartes avant le tableau.

**Le principe qui en sort, et qui doit survivre :** le tableau est le livrable du
**modèle**, pas celui du **produit**. Les vingt lignes sont Teahupo'o, Cloudbreak,
Pipeline — des endroits dont on rêve — et les rendre en treize colonnes de flottants
n'en donne aucune envie. Le podium porte le désir, le tableau porte la preuve, et la
preuve reste **entière** un écran plus bas : le critère 21 de l'EPIC exige des chiffres
traçables, il est tenu. Ne pas amputer le tableau pour faire joli.

⚠️ **Piège de diagnostic, à ne pas refaire.** `https://nalu-surf.streamlit.app/`
répond `303` vers `share.streamlit.io/-/auth/app`. Ce n'est **pas** un mur de
connexion : c'est l'amorçage de session anonyme que **toute** application Streamlit
Cloud renvoie. Vérifié contre un témoin vivant (`30days.streamlit.app`), qui se
comporte à l'identique. Le signal fiable est le websocket : `/_stcore/stream` répond
`101` quand l'application tourne. J'ai conclu à tort à un dépôt privé sur la seule
foi du `303`, et fait chercher un réglage inexistant.

## Trois arbitrages ouverts — à trancher avec le porteur, pas seul

1. **Un spot sans prix reçoit le rang 0, ce qui le punit au lieu de le marquer.**
   En janvier, La Gravière marche 28,3 % des heures diurnes — quarante fois Ponta
   Preta — mais sort 3ᵉ à `alpha = 0,5` faute de prix. Avec 170 couples sur 240 non
   couverts, l'axe prix mesure surtout « a un prix », pas « est bon marché » : le biais
   de popularité mesuré en #6 rentre par la fenêtre, dans le classement lui-même.

   *Preuve plus tranchante, mesurée le 2026-08-04 :* **Arugam Bay et Sultans sortent
   11ᵉ et 12ᵉ avec `p_surf` = 0,0 %** — jamais surfables en janvier — **au-dessus** de
   Thurso East (2,1 %), Teahupo'o (1,4 %), Chicama (0,9 %) et Jeffreys Bay (0,7 %).
   Uniquement parce qu'ils ont un prix. C'est la formulation la plus courte du
   problème : le classement place des spots à probabilité nulle devant des spots
   surfables.

   Options posées : ne rien changer (c'est la spec) · neutraliser le spot non couvert
   au lieu de le pénaliser · ajouter un filtre « spots couverts uniquement ».
   `RANG_SANS_PRIX` est isolé dans `scoring/combine.py`, et le code sépare déjà
   proprement « rang absent » de « rang 0 » : le changement serait chirurgical.
2. **Sultans et Tres Palmas restent à `p_surf = 0` sur les douze mois.**
   *La condition posée est maintenant remplie :* #9 a livré la validation externe, la
   métrique d'accord est écrite dans `src/nalu/validation.py` et le référentiel de
   comparaison dans `data/validation_seasons.yaml`, **tous deux versionnés avant la
   première mesure**. Le résultat est publié : accord de **50 % contre 70 % exigés**,
   ces deux spots comptés comme échecs et non exclus.
   Le notebook 01 désigne le suspect n°1 : **seuls 4 spots sur 20 ont une période
   moyenne médiane au-dessus de leur seuil converti**, donc `p_surf` est très sensible
   au seuil de période. Recalibrer est désormais légitime — la mesure précède
   l'ajustement — mais **reste à décider avec le porteur**, spot par spot et avec sa
   source. Ne pas y toucher sans rejouer le notebook 02 après coup.
3. **Le vide autour du planisphère, et la contrainte qui l'impose.**
   Streamlit **fige la hauteur du bloc depuis Python** : le conteneur mesure toujours
   `figure.layout.height`, et **aucun CSS ne le déplace** — vérifié en ciblant
   `stElementContainer` (`height: auto !important` ignoré), en retirant la hauteur
   (`autosize` → 450, toujours fixe) et en supprimant le `use_container_width`
   déprécié (sans effet). La carte étant verrouillée en proportions, le vide ne
   disparaît qu'à **une seule largeur de contenu**, celle où la carte atteint
   exactement son plafond.

   ⚠️ **Les mesures ont changé le 2026-08-04** : le passage des contrôles dans le rail
   latéral retire 300 px à la largeur du contenu, donc déplace cette largeur pivot et
   déplace le vide avec elle. Mesuré avant et après, aux mêmes quatre viewports :

   | viewport | carte (après) | vide sous — avant → après | vide à droite — avant → après |
   |---|---|---|---|
   | 390 | 358×131 | 329 → **329** | 0 → 0 |
   | 1280 | 820×301 | 49 → **159** | 0 → 0 |
   | 1920 | 1255×460 | 0 → 0 | 505 → **205** |
   | 2560 | 1255×460 | 0 → 0 | 1145 → **845** |

   **Le rail n'est donc pas une victoire nette :** il retire 300 px de vide à droite
   sur grand écran, et en ajoute 110 sous la carte à 1280. Mobile est inchangé.
   L'arbitrage reste entier, avec des nombres différents.

   « Pleine largeur **et** hauteur qui suit » n'est pas atteignable. Essayé et
   **annulé** : la carte grandissait à 533 px pendant que le bloc restait à 460, donc
   le bas de la carte — barre de couleur comprise — passait **sous le tableau**
   (57 px à 1920, 251 px à 2560).

   Deux pistes chiffrées restent ouvertes, **mais leurs nombres datent d'avant le
   rail** et sont donc à remesurer : cadrage resserré à `CARTE_LAT = (-45, 64)` en
   gardant le plafond, qui ramenait le vide mobile de 329 à 272 px sans rien coûter ;
   ou relever le plafond, qui alignait la carte sur le tableau à une largeur donnée
   mais aggravait le vide mobile. Une troisième piste est apparue avec le podium :
   **le vide sous la carte n'est plus adjacent au tableau** mais à un bloc de cartes,
   donc il se voit moins — le mesurer à l'œil avant de coder quoi que ce soit.

## Autre point en suspens — toujours ouvert au 4 août

`.devcontainer/devcontainer.json`, ajouté par Streamlit Cloud au déploiement, épingle
**Python 3.11** et installe un `requirements.txt` inexistant via `pip`. Le projet
exige 3.12 et `uv.lock`. Pire, son `updateContentCommand` n'installe que `streamlit` :
ni `polars`, ni `plotly`, ni le paquet `nalu`. Sans conséquence sur la CI ni sur le
déploiement, mais un prospect qui clique « Open in Codespaces » sur la vitrine tombe
sur un environnement **qui ne démarre pas**.

Deux issues possibles, à trancher : l'aligner sur 3.12 + `uv sync`, ou **supprimer
`.devcontainer/`** puisque Streamlit Cloud ne s'en sert pas pour déployer. Un Codespace
qui marche est un argument de plus ; un dossier supprimé n'est rien. Non fait.

## Par où reprendre

Aucune issue ouverte, aucun code en attente. Ce qui reste est une liste de **décisions**,
par ordre de rapport valeur/effort :

1. **Arbitrage n°1** — le rang 0 d'un spot sans prix. Le moins cher à décider, le plus
   visible dans le produit, et le changement serait chirurgical.
2. **Le devcontainer** — dix minutes, aucune décision de modèle.
3. **Arbitrage n°2** — le recalibrage du seuil de période. Le plus lourd : sourçage
   spot par spot, puis rejouer le notebook 02.
4. **Arbitrage n°3** — le vide du planisphère. Le pire rapport effort/bénéfice, et le
   podium l'a déjà rendu moins saillant.

## Régénérer les artefacts

Tous sont commités ; ces commandes ne servent qu'à les reconstruire.

```bash
uv run python -m nalu.exposure              # fenêtres de houle (réseau : Natural Earth)
uv run python -m nalu.ingest.openmeteo      # cache horaire (réseau, ~2300 unités de quota)
uv run python -m nalu.ingest.flights --collect   # snapshot de prix (réseau, jeton)
uv run python -m nalu.ingest.flights --check-token
uv run python -m nalu.scoring.climatology   # 240 + 480 lignes, hors ligne, ~1 s
uv run jupyter nbconvert --to notebook --execute --inplace notebooks/*.ipynb
```

Les notebooks sont commités **avec leurs sorties** : c'est ce qu'un prospect lit sur
GitHub sans rien installer. Les réexécuter réécrit ces sorties, donc ne le faire que
si le code a changé.

**Les polices** (`src/nalu/static/fonts/`) sont le seul artefact régénérable qui n'ait
pas de commande. Elles viennent des sous-ensembles `latin` et `latin-ext` servis par
Google Fonts : récupérer le CSS de `fonts.googleapis.com` avec un User-Agent de
navigateur — sinon il renvoie du `ttf` au lieu du `woff2` —, en extraire les `url()` et
les `unicode-range`, télécharger, et reporter les plages **telles quelles** dans
`config.toml`. Les licences OFL vivent à côté des fichiers et doivent y rester.

⚠️ Piège Windows croisé en le faisant : `print()` en Python écrit des fins de ligne
`\r\n`, donc une URL passée à `curl` via un fichier intermédiaire traîne un retour
chariot et la connexion échoue avec un `http 000` illisible. `tr -d '\r'`.

## Carte du code

```
src/nalu/
  config.py       les DOUZE parametres du modele, chacun avec sa justification
  paths.py        RACINE et DATA — tous les chemins sont ancres sur le depot,
                  JAMAIS sur le repertoire courant
  env.py          lecture de .env + masquage d'un secret (empreinte())
  palette.py      CLAIR / SOMBRE, partages par le dashboard et les notebooks
  geo.py          in_arc() et sa jumelle vectorisee, une seule fois
  spots.py        schema Pydantic, load_raw_spots() / load_spots()
  coastline.py    Natural Earth, planisphere versionne
  exposure.py     lancer de rayons -> fenetres de houle calculees
  net.py          magasin de certificats systeme (proxy TLS)
  validation.py   metrique d'accord + seuils, ECRITS AVANT la mesure
  app.py          dashboard Streamlit — podium(), etincelle(), table_affichee()
                  sont extraits de main() pour etre testables
  static/fonts/   Fraunces + Inter en woff2, AUTO-HEBERGES, avec leurs licences
                  OFL. Servis sous app/static/ via server.enableStaticServing
  ingest/         openmeteo.py (cache horaire), flights.py (prix)
  scoring/        surf.py, climatology.py, combine.py
  llm/            commentary.py — Gemini, optionnel, degrade toujours

data/
  spots.yaml                 le referentiel, seul contenu non regenerable
  exposure_windows.yaml      fenetres calculees
  validation_seasons.yaml    reference externe de #9, ECRITE AVANT la mesure
  airport_popularity.yaml    rangs de popularite, poses AVANT la sonde
  snapshots/                 cache Open-Meteo (80 fichiers) + snapshot de prix
  scores/                    climatology.parquet, fortnights.parquet
  world_outline.parquet      fond de carte hors ligne

notebooks/     01 houle · 02 validation externe · 03 vols — commites AVEC sorties
```

## Contraintes non négociables

1. **Coût total : 0 EUR.** Aucune API payante, aucun essai avec carte bancaire, à aucune étape.
2. **La démo doit tourner sans réseau**, depuis un cache parquet versionné dans le dépôt. C'est la promesse qui protège une démonstration devant un client.
3. **La vitrine doit être accessible par un lien.** Une vitrine que personne ne peut ouvrir ne remplit pas sa fonction (issue #10).

## Pièges de cette machine

| Piège | Conséquence | Règle |
|---|---|---|
| `python` local est en **3.14.2** | Pile scientifique instable, erreurs de compilation C | Épingler **Python 3.12** via `uv` |
| `python3` renvoie le raccourci Microsoft Store | Échec silencieux ou message absurde | **Ne jamais écrire `python3`** dans un script, un README ou une CI |
| `jq` est **absent** | Tout script qui en dépend échoue | Sérialiser le JSON avec Python |
| **Proxy TLS d'entreprise** | `uv sync` échoue sur `invalid peer certificate: UnknownIssuer`, et Python sur `CERTIFICATE_VERIFY_FAILED` | `uv sync --system-certs`, ou `export UV_SYSTEM_CERTS=1` pour toute la session — **`UV_NATIVE_TLS` est déprécié**, `uv` le signale. Attention : toute commande qui fait re-résoudre `uv` (modifier `pyproject.toml`, `uv add`) rejoue le téléchargement et échoue sans ça. Côté Python, `nalu.net.use_system_trust_store()` (via `truststore`) est déjà appelé par tout ce qui sort sur le réseau |
| `uv` était absent | — | Installé, version 0.12.1, dans `~/.local/bin` (pas toujours dans le `PATH` d'un shell neuf) |
| Le **navigateur headless** de `/browse` redémarre entre deux commandes et retombe sur `about:blank` | Toute mesure DOM prise dans un appel séparé est fausse, et silencieusement | Enchaîner `viewport`, `goto`, `wait`, `js` et `screenshot` **dans un seul appel Bash**. Une page blanche est presque toujours l'outil, pas le site |
| Streamlit **fige la hauteur du bloc** d'un graphique depuis `figure.layout.height` | Le CSS peut agrandir le tracé mais pas le bloc : le graphique passe **sous** l'élément suivant | Ne jamais compter sur le CSS pour rendre une hauteur responsive. Voir l'arbitrage n°3 |

## Décisions verrouillées — ne pas rouvrir sans raison explicite

Ces points ont été tranchés par `/spec` puis par `/plan-eng-review` et une contre-expertise indépendante, le 2 août 2026. Le raisonnement complet est dans l'issue #1.

- **Score en rangs centiles :** `Score = alpha * rang(Q) + (1-alpha) * rang(-prix)`, sur les 240 couples spot x mois. **Jamais de normalisation min-max** : une seule valeur extrême écrase l'échelle et rend le curseur inerte.
- **`Q(s,m) = P_surf(s,m)`**, une probabilité pure, sans pondération. L'intensité est affichée mais **n'entre pas dans le score** : on n'additionne pas une probabilité et une grandeur non bornée.
- **Variable de houle : `swell_wave_height`, jamais `wave_height`.** La seconde agrège la mer du vent, donc du clapot compté comme surfable.
- **Profondeur d'archive : 2022‑2025, 4 ans — pas 10.** *Amendé le 2026-08-02, mesuré et non déduit.* Open-Meteo sert la partition de houle (`swell_wave_*`) uniquement depuis décembre 2021, via `best_match`. Le modèle `era5_ocean`, qui remonte à 1940, ne sert **que** la mer totale (`wave_*`) : vérifié année par année sur Bali et Hossegor, `swell_wave_*` y est vide même en 2024. L'arbitrage « 10 ans avec la mer totale » contre « 4 ans avec la houle pure » a été tranché en faveur de la seconde : la décision ci-dessus prime sur la profondeur. Janvier 2022 est complet sur les 20 spots.
- **NOAA WaveWatch III est écarté comme alternative.** Le hindcast 30 ans couvre 1979‑2009, le multi-grid s'arrête en 2019, le tout en GRIB2. Il ne rejoint jamais le présent et ne résout donc ni la profondeur ni la licence. La demi-journée d'évaluation inscrite au plan est sans objet.
- **Seuils de hauteur nommés `hs_offshore_min` / `hs_offshore_max`.** Ce sont des hauteurs significatives **au large** (ERA5 à 50 km de maille), pas des tailles de vague au pic.
- **Seuil de période nommé `swell_peak_period_min`, et converti avant comparaison.** *Ajouté le 2026-08-02, après mesure.* Les guides de surf annoncent une période **de pic** ; Open-Meteo ne sert qu'une période **moyenne** (`swell_wave_peak_period` est vide, vérifié). Confondre les deux rendait Uluwatu artificiellement mort à 14 % de passage et les Maldives à 0 %. Le modèle convertit via `CONFIG.peak_to_mean_period_ratio`. **Le fichier de configuration porte donc douze paramètres, plus onze** — même règle, chacun suivi de sa justification.
- **`vent_ok` dépend du secteur :** `SI offshore ALORS vitesse < max_offshore SINON vitesse < max_onshore`. **Jamais un OU**, qui déclarerait surfable un offshore de 45 nœuds.
- **Fenêtres directionnelles calculées**, pas déclarées : lancer de rayons sur les côtes Natural Earth. Override manuel possible mais `override_reason` obligatoire.
- **20 spots, pas 50.** Chacun avec `source` et `confidence` obligatoires. Les seuils sont l'actif central du produit et doivent être auditables.
- **Client Open-Meteo officiel** (`openmeteo-requests` + `requests-cache` + `retry-requests`). **Ne pas écrire de client HTTP ni de backoff maison.**
- **Le quota Open-Meteo est pondéré** : `(variables / 10) x (jours / 14) x localisations`. Plafonds 600/min, 5 000/h, 10 000/jour. Grouper les spots réduit la latence, **pas** le quota. *Mesuré sur le remplissage réel du 2026-08-02 : **2 296 unités, 8 requêtes, 196 s** — les 5 200 du plan visaient 10 ans. Les pauses ont été déclenchées par le plafond **par minute**, pas l'horaire.*
- **Le référentiel est restreint aux spots couverts, pas réduit.** *Décidé après la sonde du 2026-08-02 : **15 destinations couvertes sur 20**, corrélation de rangs couverture ↔ popularité **+0,78**.* Les 5 non couvertes (Klitmøller, Thurso East, Jeffreys Bay, Zicatela, Chicama) sont exactement les 5 de popularité minimale. La restriction porte sur **l'axe prix**, jamais sur le référentiel : les 20 spots restent affichés et marqués. Les supprimer laisserait le biais décider du contenu du produit.
- **Amadeus Self-Service est mort** (portail fermé le 17 juillet 2026). Toute documentation en ligne le recommandant est périmée. Ne pas y perdre de temps.

## Interdits techniques

- **Aucune boucle ligne à ligne** dans `scoring/`. Expressions polars vectorisées uniquement, vérifié par un test de performance.
- **Aucune constante en dur** hors de `nalu/config.py`. Les **douze** paramètres du modèle y vivent, chacun suivi de la phrase qui le justifie. Un test compte les champs : en ajouter un sans justification échoue.
- **`in_arc()` n'existe qu'une fois**, dans `nalu/geo.py`. Le passage de fenêtre par 0 degré est le bug le plus probable du projet. Sa jumelle vectorisée `in_arc_expr()` vit **dans le même fichier**, et un test par propriétés sur 600 tirages prouve qu'elles ne divergent pas.
- **Aucun secret commité.** `.env` dans `.gitignore`, `.env.example` documente les variables, toutes optionnelles. ⚠️ **Le jeton va dans `.env`, jamais dans `.env.example`** — ce dernier est versionné. Vérifier avec `uv run python -m nalu.ingest.flights --check-token`, qui n'affiche jamais la valeur.
- **Tout ce qui est commité dans `data/` doit avoir son exception dans `.gitignore`.** La règle `*.parquet` capte tout par défaut. Un artefact oublié passe les tests en local et casse la CI — arrivé une fois avec `data/world_outline.parquet`.
- **Aucune ressource distante dans la page.** Ni topologie de carte, ni police, ni feuille de style, ni image. La contrainte a déjà mordu **deux fois** : `scatter_geo` allait chercher son fond de carte sur un CDN (carte vide hors ligne), et une police servie par Google Fonts serait retombée sur une fonte système. Les deux échouent **en silence** — la page s'affiche, en moins bien — donc aucun test naïf ne les voit. Tout actif de rendu se commite : `data/world_outline.parquet`, `src/nalu/static/fonts/`. Cette règle protège la contrainte n°2, qui est la promesse la plus fragile du projet.

## Stack

`uv` + Python 3.12 · `polars` + parquet · `openmeteo-requests` · `shapely` · `pydantic` · `streamlit` + `plotly` · `pytest` + `hypothesis` + `pytest-socket` · `ruff`

## Testing

```bash
uv run pytest              # 298 tests, ~25 s (dont ~17 s de notebooks)
uv run pytest -m "not slow"  # boucle courte : saute l'execution des notebooks
uv run ruff check          # lint — il inspecte AUSSI les .ipynb
uv run streamlit run src/nalu/app.py    # http://localhost:8501
```

Huit tests portent le plus de valeur et ne doivent jamais être supprimés :
1. **Invariance aux extrêmes** (`hypothesis`, `tests/test_combine.py`) : ajouter un prix aberrant ne change pas l'ordre des autres. C'est la preuve du passage aux rangs centiles. Une contre-épreuve documente ce que min-max aurait fait.
2. **Démarrage sans réseau** (`pytest-socket`) : protège la promesse centrale de la démo. La CI clone à froid et exécute ces tests contre le cache commité, donc la promesse est vérifiée à chaque push sur une machine neuve.
3. **Intégrité du cache** (`verify_cache_integrity`) : un cache partiel produit un classement faux et plausible. Le pipeline échoue en nommant le spot **et** l'année.
4. **Accord des deux `in_arc`** (`tests/test_surf.py`) : sans lui, deux implémentations d'une règle unique divergeraient en silence.
5. **Scan de secrets sur l'historique** (`tests/test_secrets.py`) : le dépôt est public, et ça ne se défait pas. La CI clone en `fetch-depth: 0`, sinon le scan n'aurait qu'un commit à lire et passerait vert sans rien vérifier. Le fichier **s'exclut lui-même** du scan : ses échantillons de contre-épreuve sont des formes de secrets. Même précaution que l'étape `python[3]` de `ci.yml`.
6. **La métrique de validation sait échouer** (`tests/test_validation.py`) : une contre-épreuve vérifie qu'elle n'est pas inerte, et qu'un spot sans pic compte comme un **échec** et non comme une exclusion. C'est ce qui empêche de faire réussir la validation en écartant ce qui la gêne.
7. **Dégradation de la couche IA** (`tests/test_commentary.py`) : clé absente, clé refusée, réseau coupé, réponse vide. Aucune ne doit lever, et l'avertissement ne doit jamais contenir la clé.
8. **Les polices sont auto-hébergées et présentes** (`tests/test_app.py`) : chaque `url` déclarée dans `fontFaces` existe dans le dépôt, aucune ne commence par `http`, et `enableStaticServing` reste actif. Une police manquante ou distante **ne lève jamais** : la page retombe en silence sur une fonte système, donc le défaut serait invisible en local et visible seulement lors d'une démo sans réseau.

**Regarder le rendu, pas seulement les tests.** **Onze défauts d'interface sur onze**
sont passés au travers de la suite et n'ont été trouvés qu'en ouvrant la page :
marqueurs invisibles · couleur de statut détournée en accent · artefact non versionné ·
carte écrasée sur mobile · **carte coupée à droite sur grand écran** · **figure sombre
sur page claire** · deux classes de marqueurs sans légende · `None` affiché en clair ·
page sans aucune section · mois tronqués en « avri / octo / nove » · deux typographies.
Plusieurs ont échappé à des tests que je venais d'écrire, parce que je testais **une
seule largeur** et **un seul thème**.

Corollaire : tester au moins **390, 1280, 1920 et 2560 px**, et vérifier le thème
clair *et* la préférence sombre. Un rendu correct à 1440 px ne prouve rien.

⚠️ **Le DOM ne suffit pas non plus.** `st.dataframe` peint ses cellules dans un
**canvas** : `document.body.innerText` ne les contient pas. J'ai cru avoir supprimé les
`None` du tableau sur la foi d'un `innerText` à zéro alors qu'ils étaient toujours à
l'écran. Pour un tableau, il faut **regarder l'image**.

⚠️ **Le navigateur headless de `/browse` ne rend aucune application Streamlit Cloud.**
Il reste sur le squelette de chargement, indéfiniment. Vérifié contre le témoin vivant
`30days.streamlit.app`, qui se comporte à l'identique : c'est l'outil, pas le site. Ne
pas en conclure que le déploiement est cassé — auditer l'instance **locale**, qui sert
le même code, et ouvrir l'URL publique dans un vrai navigateur.

## Dataviz

Les couleurs du dashboard viennent du skill `dataviz` et sont passées au validateur
(bande de clarté, chroma, séparation daltonisme, contraste) — jamais choisies à l'œil.
Elles vivent dans **`src/nalu/palette.py`** — une seule définition pour le dashboard
et pour les notebooks, qui n'ont pas à charger Streamlit pour connaître un bleu — et
dans `.streamlit/config.toml`. **Invoquer `/dataviz` avant d'écrire le moindre
graphique.**

Vérifié le 2026-08-03 : la teinte catégorielle unique passe les cinq contrôles sur
surface claire **et** sombre, et les deux rampes séquentielles sont strictement
monotones en clarté. `serie_attenuee` n'est **pas** un second emplacement catégoriel :
c'est un pas d'atténuation, et le soumettre au validateur comme catégoriel le fait
échouer à juste titre.

Le rouge est une couleur de **statut** dans ce système : ne pas l'utiliser comme accent
d'interface, sous peine qu'un curseur soit lu comme une alerte. Le bleu est la couleur
d'**accent** : ne pas peindre en `st.info` une absence bénigne, elle se lirait comme
une information saillante.

**La figure doit suivre le thème RÉELLEMENT appliqué, pas celui du navigateur.**
`.streamlit/config.toml` épingle `theme.base = "light"`, donc la page est claire pour
tout le monde. `palette()` lit `st.get_option("theme.base")` en premier et ne retombe
sur `st.context.theme` que si aucune base n'est épinglée. Sans cette règle, un visiteur
en mode sombre reçoit un **rectangle noir** au milieu d'une page claire — arrivé, et
invisible depuis un navigateur en thème clair.

**Le CSS du planisphère ne borne rien.** Ni `max-height` — posé sur le même élément
qu'un `aspect-ratio`, il fait rétrécir la **largeur** de la boîte pendant que Plotly
dessine à la taille du parent, et coupe le tiers droit de la carte. Ni `max-width` sans
raison — la carte s'arrêterait avant le tableau. `style_planisphere()` est extrait de
`main()` pour que ces deux interdits soient testables, et ils le sont.

Le planisphère est versionné (`data/world_outline.parquet`, 17 Ko) parce que
`scatter_geo` de Plotly télécharge sa topologie depuis un CDN : sans lui, carte vide
hors ligne.

**Deux classes de marqueurs imposent une légende.** Règle du skill `dataviz` : dès
deux séries, la légende est obligatoire, et l'identité ne repose jamais sur la couleur
seule. Le planisphère distingue « prix connu » (disque coloré par le score) de « prix
non couvert » (anneau) — sans légende, un anneau gris se lisait comme une mauvaise
vague et non comme un trou de données. Elle est posée **dans** la carte, comme la barre
de couleur et pour la même raison : à l'extérieur elle coûterait de la largeur. Son
`itemclick` est désarmé, sinon un clic efface onze spots sans indice pour les rétablir.

**La police des figures doit être celle de la page.** Par défaut Plotly compose en
*Open Sans* et Streamlit en *Source Sans* : deux typographies sur un même écran,
mesurées dans le DOM. `POLICE_FIGURE` dans `app.py` les réunit — la palette était déjà
partagée, la police ne l'était pas.

**Streamlit 1.59 permet une vraie identité typographique, sans une ligne de CSS.**
J'avais écrit l'inverse, c'était faux. Le thème expose `font`, `headingFont`,
`headingFontSizes`, `headingFontWeights`, `baseRadius`, et surtout **`fontFaces`**,
qui déclare des polices auto-hébergées. **Fraunces** pour les titres, **Inter** pour le
texte, décidés avec le porteur le 2026-08-04 sur un brief explicite : « c'est beau,
j'ai envie de jouer ».

Les fichiers sont **commités**, jamais appelés sur un CDN — une police distante
retomberait sur une fonte système exactement le jour d'une démo sans réseau. Trois
tests le verrouillent : chaque `url` déclarée existe dans le dépôt, aucune ne commence
par `http`, et `server.enableStaticServing` reste actif. Sans ce dernier, `app/static/`
ne répond pas et la page retombe **en silence**.

Les plages Unicode viennent de Google Fonts et sont reprises telles quelles : le
navigateur ne télécharge le sous-ensemble étendu que si un glyphe l'exige — vérifié,
il ne l'est pas aujourd'hui.

**La ligne de base d'une sparkline se dessine comme une FORME, pas comme un axe.**
`showline` sur l'axe ne produit rien dans cette configuration — vérifié dans le DOM,
le groupe d'axe reste vide — et une marge basse à zéro rogne de toute façon le trait.
Sans elle, un mois à `p_surf = 0` se lit comme une donnée manquante et non comme un
zéro, ce qui arrive sur la moitié des spots.

**Ne jamais abréger un mois par troncature.** À quatre lettres on obtient « avri »,
« octo », « nove », « déce », qui se lisent comme des fautes ; à trois, « juin » et
« juillet » se confondent en « jui » et **l'axe perd une barre en silence**. J'ai
introduit exactement cette régression en corrigeant la première. `MOIS_COURT` porte des
abréviations posées à la main, et deux tests vérifient qu'elles restent douze et
distinctes.

**`st.dataframe` peint « None » pour une valeur absente**, et ni `NumberColumn` ni son
`format` ne le suppriment — mesuré sur Streamlit 1.59.1, les trois cas essayés. Seule
une colonne de **texte** le permet. Mais du texte se trie alphabétiquement, et les prix
vont de 67 à 2299 € : sans alignement à droite, « 2299 € » passerait avant « 67 € ».
`table_affichee()` est extraite de `main()` pour que ce piège soit testable, et il l'est.

## Skill routing

Quand la demande correspond à un skill disponible, l'invoquer via l'outil Skill. En cas de doute, invoquer le skill.

- Bugs, erreurs, comportement inexpliqué → `/investigate`
- Tester le site, vérifier que ça marche → `/qa`
- Relire un diff avant de livrer → `/review`
- Architecture, revue de plan → `/plan-eng-review`
- Pipeline de revue complet → `/autoplan`
- Nettoyage, simplification, réutilisation → `/simplify`
- Lancer l'application pour voir un changement → `/run`
- Nouvelle issue de backlog à rédiger → `/spec`
