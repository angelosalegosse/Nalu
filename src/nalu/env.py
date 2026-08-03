"""Lecture des variables d'environnement optionnelles, et leur affichage sans fuite.

Deux consommateurs : le jeton Travelpayouts de `ingest/flights.py` et la clé Gemini
de `llm/commentary.py`. Une seule implémentation, ici — deux copies divergeraient sur
le detail qui compte : `setdefault`, qui laisse gagner ce que le shell a deja pose.

**Aucune valeur lue ici ne doit etre journalisee.** `empreinte()` existe pour qu'on
puisse parler d'un secret sans l'ecrire : elle est irreversible et suffit a verifier
qu'on a bien pose la bonne cle.
"""

import os
from pathlib import Path

from nalu.paths import RACINE

ENV_PATH = RACINE / ".env"
"""Ancre sur la racine du depot, pas sur le repertoire courant : c'est ce qui permet
au chargement de fonctionner quel que soit l'endroit d'ou l'application est lancee."""


def charger_env(chemin: Path | None = None) -> None:
    """Charge `.env` dans l'environnement, sans ecraser ce qui existe deja.

    Pas de dependance pour trois lignes : le format utile est `CLE=valeur`.

    `chemin` est resolu a l'appel, pas a la definition : une valeur par defaut liee
    au moment du `def` figerait `ENV_PATH` et rendrait les tests inecrivables.
    """
    chemin = chemin if chemin is not None else ENV_PATH
    if not chemin.exists():
        return
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, valeur = ligne.partition("=")
        cle, valeur = cle.strip(), valeur.strip().strip("\"'")
        if cle and valeur:
            os.environ.setdefault(cle, valeur)


def lire(nom: str) -> str | None:
    """La valeur de `nom`, ou `None` si elle est absente ou vide.

    Ne jamais journaliser ce que renvoie cette fonction.
    """
    charger_env()
    return os.environ.get(nom, "").strip() or None


def empreinte(valeur: str) -> str:
    """Trace non reversible, pour parler d'un secret sans le divulguer."""
    if len(valeur) <= 8:
        return f"{'*' * len(valeur)} ({len(valeur)} caractères)"
    return f"{valeur[:3]}…{valeur[-2:]} ({len(valeur)} caractères)"
