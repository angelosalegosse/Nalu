"""Racine du dépôt, et le répertoire de données qui en dépend.

Pourquoi ce module existe : jusqu'ici les neuf chemins de `data/` étaient relatifs
au **répertoire courant**. En local on lance toujours depuis la racine du dépôt, donc
personne ne le voyait. Lancé d'ailleurs, le pipeline meurt sur
`FileNotFoundError: data/scores/climatology.parquet` — mesuré, pas supposé.

C'est exactement le genre de dépendance implicite qui casse un déploiement : rien ne
garantit qu'un hébergeur lance l'application depuis la racine du dépôt, et le message
d'erreur ne dit pas que le problème est le répertoire courant. Ancrer les chemins sur
l'emplacement du code supprime la classe de panne entière.

`parents[2]` : `src/nalu/paths.py` -> `src/nalu` -> `src` -> racine.
"""

from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
DATA = RACINE / "data"
