# Nalu

Moteur de recommandation de trips surf : croise **4 ans (2022‑2025)** de climatologie de houle avec les prix des vols au départ de Paris, et classe les spots selon un curseur qualité/prix réglable par l'utilisateur.

**Nature du projet :** vitrine technique d'un cabinet de conseil Data & IA. Le lecteur cible du dépôt n'est pas un surfeur, c'est un prospect qui évalue une compétence. Ce n'est pas destiné à la production, mais tout doit être propre, auditable et publiquement accessible.

**Échéance : 16 août 2026.**

---

## Lire ceci en premier

Le plan complet vit dans les issues GitHub, pas dans ce fichier.

```bash
gh issue view 1          # EPIC : plan complet, modèle, sources, critères d'acceptation
gh issue list            # les 8 issues filles, #2 à #10
```

`TODOS.md` à la racine contient le travail délibérément différé, avec son contexte.

## État au 3 août 2026

| Issue | État |
|---|---|
| #2 socle, `config.py`, `geo.py` | ✅ livrée |
| #3 référentiel 20 spots, fenêtres calculées | ✅ livrée |
| #4 ingestion Open-Meteo, cache commité | ✅ livrée |
| #6 sonde de couverture, prix, snapshot | ✅ livrée |
| #7 surfabilité, climatologie, dispersion | ✅ livrée |
| #8 score en rangs, curseur, dashboard | ✅ livrée |
| #10 déploiement public | ✅ code livré — **reste UN réglage côté Streamlit** |
| #9 Gemini, notebooks, validation externe | ✅ livrée |

`main` est verte, 279 tests. Le pipeline tourne de bout en bout : 20 spots sourcés →
701 280 heures → 240 probabilités mensuelles → 240 prix → classement réordonnable,
commenté par Gemini quand une clé est posée.

**Le plan est complet.** Il ne reste aucune issue ouverte.

⚠️ **Point en suspens sur #10 :** l'application déployée sur
`https://nalu-surf.streamlit.app` demandait une **connexion** au 3 août 2026 —
mesuré, `/_stcore/health` renvoie `303` vers `share.streamlit.io/-/auth/app`. Un
prospect ne peut pas l'ouvrir, ce qui vide l'issue de son objet. Correction :
Streamlit Cloud → l'app → Settings → Sharing → accès public. **Vérifier l'URL en
navigateur avant de considérer #10 close.**

## Deux arbitrages ouverts — à trancher avec le porteur, pas seul

1. **Un spot sans prix reçoit le rang 0, ce qui le punit au lieu de le marquer.**
   En janvier, La Gravière marche 28,3 % des heures diurnes — quarante fois Ponta
   Preta — mais sort 3ᵉ à `alpha = 0,5` faute de prix. Avec 170 couples sur 240 non
   couverts, l'axe prix mesure surtout « a un prix », pas « est bon marché » : le biais
   de popularité mesuré en #6 rentre par la fenêtre, dans le classement lui-même.
   Options posées : ne rien changer (c'est la spec) · neutraliser le spot non couvert
   au lieu de le pénaliser · ajouter un filtre « spots couverts uniquement ».
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

## Régénérer les artefacts

Tous sont commités ; ces commandes ne servent qu'à les reconstruire.

```bash
uv run python -m nalu.exposure              # fenêtres de houle (réseau : Natural Earth)
uv run python -m nalu.ingest.openmeteo      # cache horaire (réseau, ~2300 unités de quota)
uv run python -m nalu.ingest.flights --collect   # snapshot de prix (réseau, jeton)
uv run python -m nalu.ingest.flights --check-token
uv run python -m nalu.scoring.climatology   # 240 + 480 lignes, hors ligne, ~1 s
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

## Stack

`uv` + Python 3.12 · `polars` + parquet · `openmeteo-requests` · `shapely` · `pydantic` · `streamlit` + `plotly` · `pytest` + `hypothesis` + `pytest-socket` · `ruff`

## Testing

```bash
uv run pytest              # 279 tests, ~21 s (dont ~17 s de notebooks)
uv run pytest -m "not slow"  # boucle courte : saute l'execution des notebooks
uv run ruff check          # lint — il inspecte AUSSI les .ipynb
uv run streamlit run src/nalu/app.py    # http://localhost:8501
```

Sept tests portent le plus de valeur et ne doivent jamais être supprimés :
1. **Invariance aux extrêmes** (`hypothesis`, `tests/test_combine.py`) : ajouter un prix aberrant ne change pas l'ordre des autres. C'est la preuve du passage aux rangs centiles. Une contre-épreuve documente ce que min-max aurait fait.
2. **Démarrage sans réseau** (`pytest-socket`) : protège la promesse centrale de la démo. La CI clone à froid et exécute ces tests contre le cache commité, donc la promesse est vérifiée à chaque push sur une machine neuve.
3. **Intégrité du cache** (`verify_cache_integrity`) : un cache partiel produit un classement faux et plausible. Le pipeline échoue en nommant le spot **et** l'année.
4. **Accord des deux `in_arc`** (`tests/test_surf.py`) : sans lui, deux implémentations d'une règle unique divergeraient en silence.
5. **Scan de secrets sur l'historique** (`tests/test_secrets.py`) : le dépôt est public, et ça ne se défait pas. La CI clone en `fetch-depth: 0`, sinon le scan n'aurait qu'un commit à lire et passerait vert sans rien vérifier. Le fichier **s'exclut lui-même** du scan : ses échantillons de contre-épreuve sont des formes de secrets. Même précaution que l'étape `python[3]` de `ci.yml`.
6. **La métrique de validation sait échouer** (`tests/test_validation.py`) : une contre-épreuve vérifie qu'elle n'est pas inerte, et qu'un spot sans pic compte comme un **échec** et non comme une exclusion. C'est ce qui empêche de faire réussir la validation en écartant ce qui la gêne.
7. **Dégradation de la couche IA** (`tests/test_commentary.py`) : clé absente, clé refusée, réseau coupé, réponse vide. Aucune ne doit lever, et l'avertissement ne doit jamais contenir la clé.

**Regarder le rendu, pas seulement les tests.** Trois défauts d'interface sur trois
sont passés au travers de la suite et n'ont été trouvés qu'en ouvrant la page :
marqueurs invisibles, couleur de statut détournée en accent, artefact non versionné.

## Dataviz

Les couleurs du dashboard viennent du skill `dataviz` et sont passées au validateur
(bande de clarté, chroma, séparation daltonisme, contraste) — jamais choisies à l'œil.
Elles vivent dans `CLAIR` / `SOMBRE` en tête de `src/nalu/app.py` et dans
`.streamlit/config.toml`. **Invoquer `/dataviz` avant d'écrire le moindre graphique.**

Le rouge est une couleur de **statut** dans ce système : ne pas l'utiliser comme accent
d'interface, sous peine qu'un curseur soit lu comme une alerte.

Le planisphère est versionné (`data/world_outline.parquet`, 17 Ko) parce que
`scatter_geo` de Plotly télécharge sa topologie depuis un CDN : sans lui, carte vide
hors ligne.

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
