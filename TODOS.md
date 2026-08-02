# TODOS

Travail considéré, chiffré, et volontairement différé. Chaque entrée porte assez de contexte pour être reprise dans trois mois sans reconstituer le raisonnement.

Créé le 2026-08-02 par `/plan-eng-review`. Voir l'epic [#1](https://github.com/angelosalegosse/Nalu/issues/1).

---

## 1. Étendre le référentiel de 20 à 50 spots

**Quoi :** porter `data/spots.yaml` de 20 à 50 spots, chacun avec ses seuils, sa `source` et sa `confidence`.

**Pourquoi :** la définition de produit d'origine était « les 50 meilleurs spots de surf du monde ». La réduction à 20 est un arbitrage qualité contre quantité rendu le 2026-08-02, pas un abandon.

**Pour :** produit conforme à l'intention initiale ; le coût unitaire est maintenant connu, donc l'extension est une décision et non une enquête ; la méthode aura été prouvée sur 20 avant d'être étendue.

**Contre :** environ 5 valeurs à sourcer manuellement par spot, soit 150 valeurs supplémentaires ; environ 260 unités de quota Open-Meteo par spot.

**Contexte :** à 50 spots, l'ingestion pesait environ 13 000 unités de quota pondéré, au-dessus du plafond journalier de 10 000 d'Open-Meteo. Le passage à 20 ramène le total à environ 5 200. Pour étendre, il faudra soit étaler l'ingestion sur deux jours, soit avoir basculé sur NOAA WaveWatch III entre-temps.

**Dépend de :** issue #3 livrée, et la question de licence tranchée (voir #4).

---

## 2. Intégrer la marée au modèle de surfabilité

**Quoi :** ajouter une condition de marée à `surfable()`, avec une fenêtre de marée par spot.

**Pourquoi :** sur une grande partie des reef breaks du référentiel, la marée décide autant que la houle. Un spot peut être parfait à mi-marée montante et inutilisable deux heures plus tard. C'est la limite la plus sérieuse du modèle actuel, et un prospect surfeur la pointera.

**Pour :** traite la faiblesse la plus visible du modèle auprès d'un public qui connaît le sujet ; rend le modèle nettement plus crédible techniquement.

**Contre :** ajoute une variable au quota d'ingestion ; impose de rouvrir les 20 spots pour poser une fenêtre de marée, soit 20 valeurs de plus à sourcer ; ajoute une dimension au modèle et à ses tests.

**Contexte :** écarté le 2026-08-02 faute de source gratuite couvrant le monde entier sur 10 ans d'archives. **Piste non explorée :** Open-Meteo expose `sea_level_height_msl` dans son API marine, ce qui pourrait suffire à approximer le cycle de marée sans recourir aux tables officielles. À tester en premier, environ une demi-journée.

**Dépend de :** rien de bloquant.

---

## 3. Mode court terme (0 à 10 jours)

**Quoi :** un second mode répondant à « je pars ce week-end, où ? », alimenté par les prévisions de houle plutôt que par la climatologie.

**Pourquoi :** c'est l'autre moitié du besoin réel d'un surfeur. Open-Meteo sert les prévisions par le même client, gratuitement.

**Pour :** **le moteur de surfabilité est réutilisable presque tel quel.** Seule la source de houle change, et les prix passeraient sur du last-minute. C'est le point non évident qui rend cette extension bien moins chère qu'elle n'en a l'air, de l'ordre de 80 % du travail déjà fait.

**Contre :** deux pipelines d'ingestion, deux modèles de score, deux écrans à maintenir. Les prévisions fiables s'arrêtent vers 7 à 10 jours, donc l'horizon utile est étroit.

**Contexte :** écarté dès la phase de cadrage du 2026-08-02, après arbitrage explicite. Le moyen terme a été jugé plus original et plus démonstratif, parce qu'aucun service grand public ne répond à « quel mois partir » alors que tous répondent à « quelles vagues demain ».

**Dépend de :** issue #7 livrée (le moteur de surfabilité est commun aux deux modes).

---

## 4. Réintégrer l'axe prix si le repli mono-axe se déclenche

**Quoi :** si la sonde de couverture de J+2 renvoie moins de 10 spots couverts, le produit devient mono-axe et l'axe prix disparaît. Ce point décrit comment le réintégrer ensuite.

**Pourquoi :** le croisement houle × prix est l'idée centrale du produit. Y renoncer serait un repli tactique, pas un abandon.

**Pour :** si le repli se déclenche à J+2, les alternatives sont déjà identifiées au lieu d'être cherchées sous pression, à douze jours de l'échéance.

**Contre :** consigne un travail qui n'existera peut-être jamais, si la couverture s'avère bonne.

**Contexte :** Amadeus Self-Service a été décommissionné le 2026-07-17, ce qui a supprimé la voie royale du projet. Travelpayouts, seule option réellement gratuite restante, sert des données en cache dont la couverture est proportionnelle à la popularité touristique de la destination.

**Pistes non explorées :**
- **Duffel** : modèle à l'usage, environ 3 $ par commande confirmée et 0,005 $ par recherche au-delà d'un ratio. Payant, mais sans coût fixe, donc compatible avec un usage de démonstration à volume nul.
- **Travelpayouts en mode affilié avec marqueur** : le paramètre `show_to_affiliates` change le périmètre des prix retournés et pourrait élargir la couverture.
- **Proxy de distance et de saisonnalité** : calibrer un modèle de prix sur les routes effectivement couvertes, et l'extrapoler aux autres en l'annonçant explicitement comme une estimation.

**Dépend de :** le résultat de la sonde de couverture, issue #6, à J+2.
