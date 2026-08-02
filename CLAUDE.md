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

**Commencer par l'issue #2 (socle).** Elle débloque tout le reste, y compris l'issue #6 qui porte le seul risque capable de changer la nature du produit.

`TODOS.md` à la racine contient le travail délibérément différé, avec son contexte.

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
| `uv` est **absent** | — | À installer en premier (issue #2) |

## Décisions verrouillées — ne pas rouvrir sans raison explicite

Ces points ont été tranchés par `/spec` puis par `/plan-eng-review` et une contre-expertise indépendante, le 2 août 2026. Le raisonnement complet est dans l'issue #1.

- **Score en rangs centiles :** `Score = alpha * rang(Q) + (1-alpha) * rang(-prix)`, sur les 240 couples spot x mois. **Jamais de normalisation min-max** : une seule valeur extrême écrase l'échelle et rend le curseur inerte.
- **`Q(s,m) = P_surf(s,m)`**, une probabilité pure, sans pondération. L'intensité est affichée mais **n'entre pas dans le score** : on n'additionne pas une probabilité et une grandeur non bornée.
- **Variable de houle : `swell_wave_height`, jamais `wave_height`.** La seconde agrège la mer du vent, donc du clapot compté comme surfable.
- **Profondeur d'archive : 2022‑2025, 4 ans — pas 10.** *Amendé le 2026-08-02, mesuré et non déduit.* Open-Meteo sert la partition de houle (`swell_wave_*`) uniquement depuis décembre 2021, via `best_match`. Le modèle `era5_ocean`, qui remonte à 1940, ne sert **que** la mer totale (`wave_*`) : vérifié année par année sur Bali et Hossegor, `swell_wave_*` y est vide même en 2024. L'arbitrage « 10 ans avec la mer totale » contre « 4 ans avec la houle pure » a été tranché en faveur de la seconde : la décision ci-dessus prime sur la profondeur. Janvier 2022 est complet sur les 20 spots.
- **NOAA WaveWatch III est écarté comme alternative.** Le hindcast 30 ans couvre 1979‑2009, le multi-grid s'arrête en 2019, le tout en GRIB2. Il ne rejoint jamais le présent et ne résout donc ni la profondeur ni la licence. La demi-journée d'évaluation inscrite au plan est sans objet.
- **Seuils de hauteur nommés `hs_offshore_min` / `hs_offshore_max`.** Ce sont des hauteurs significatives **au large** (ERA5 à 50 km de maille), pas des tailles de vague au pic.
- **`vent_ok` dépend du secteur :** `SI offshore ALORS vitesse < max_offshore SINON vitesse < max_onshore`. **Jamais un OU**, qui déclarerait surfable un offshore de 45 nœuds.
- **Fenêtres directionnelles calculées**, pas déclarées : lancer de rayons sur les côtes Natural Earth. Override manuel possible mais `override_reason` obligatoire.
- **20 spots, pas 50.** Chacun avec `source` et `confidence` obligatoires. Les seuils sont l'actif central du produit et doivent être auditables.
- **Client Open-Meteo officiel** (`openmeteo-requests` + `requests-cache` + `retry-requests`). **Ne pas écrire de client HTTP ni de backoff maison.**
- **Le quota Open-Meteo est pondéré** : `(variables / 10) x (jours / 14) x localisations`. Environ 5 200 unités pour un remplissage à froid. Plafonds 600/min, 5 000/h, 10 000/jour. Grouper les spots réduit la latence, **pas** le quota.
- **Amadeus Self-Service est mort** (portail fermé le 17 juillet 2026). Toute documentation en ligne le recommandant est périmée. Ne pas y perdre de temps.

## Interdits techniques

- **Aucune boucle ligne à ligne** dans `scoring/`. Expressions polars vectorisées uniquement, vérifié par un test de performance.
- **Aucune constante en dur** hors de `nalu/config.py`. Les onze paramètres du modèle y vivent, chacun suivi de la phrase qui le justifie.
- **`in_arc()` n'existe qu'une fois**, dans `nalu/geo.py`. Le passage de fenêtre par 0 degré est le bug le plus probable du projet.
- **Aucun secret commité.** `.env` dans `.gitignore`, `.env.example` documente les variables, toutes optionnelles.

## Stack

`uv` + Python 3.12 · `polars` + parquet · `openmeteo-requests` · `shapely` · `pydantic` · `streamlit` + `plotly` · `pytest` + `hypothesis` + `pytest-socket` · `ruff`

## Testing

```bash
uv run pytest          # tests
uv run ruff check      # lint
uv run streamlit run src/nalu/app.py
```

Trois tests portent le plus de valeur et ne doivent jamais être supprimés :
1. **Invariance aux extrêmes** (`hypothesis`) : ajouter un prix aberrant ne change pas l'ordre des autres. C'est la preuve du passage aux rangs centiles.
2. **Démarrage sans réseau** (`pytest-socket`) : protège la promesse centrale de la démo.
3. **Intégrité du cache** : un cache partiel produit un classement faux et plausible. Le pipeline doit échouer en nommant le spot et l'année manquants.

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
