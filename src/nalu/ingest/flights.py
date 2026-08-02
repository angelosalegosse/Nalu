"""Prix des vols Travelpayouts — pour l'instant, la seule vérification du jeton.

Le reste de l'issue #6 (sonde de couverture, connecteur live, snapshot versionné)
arrive ensuite. Ce module commence par ce qui débloque tout : savoir si le jeton
fonctionne, **sans jamais l'afficher ni le journaliser**.

    uv run python -m nalu.ingest.flights --check-token

Le jeton est OPTIONNEL. Absent, le projet démarre, les tests passent et le dashboard
s'affiche depuis le snapshot versionné. Il ne sert qu'à régénérer ce snapshot.
"""

import argparse
import os
import sys
from pathlib import Path

from nalu.config import CONFIG

TRAVELPAYOUTS_URL = "https://api.travelpayouts.com/v1/prices/monthly"
VARIABLE_JETON = "TRAVELPAYOUTS_TOKEN"
ENV_PATH = Path(".env")

# Destination de contrôle : Bali est la route la plus fréquentée du référentiel, donc
# celle qui a le plus de chances d'être servie par un cache alimenté par la demande.
# Un échec ici ne prouve pas que le jeton est mauvais, mais un succès prouve qu'il est bon.
DESTINATION_DE_CONTROLE = "DPS"


def charger_env(chemin: Path = ENV_PATH) -> None:
    """Charge `.env` dans l'environnement, sans écraser ce qui existe déjà.

    Pas de dépendance pour trois lignes : le format utile est `CLE=valeur`.
    """
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


def jeton() -> str | None:
    """Le jeton, ou `None`. Ne jamais journaliser la valeur renvoyée."""
    charger_env()
    valeur = os.environ.get(VARIABLE_JETON, "").strip()
    return valeur or None


def empreinte(valeur: str) -> str:
    """Trace non réversible, pour parler du jeton sans le divulguer."""
    if len(valeur) <= 8:
        return f"{'*' * len(valeur)} ({len(valeur)} caractères)"
    return f"{valeur[:3]}…{valeur[-2:]} ({len(valeur)} caractères)"


def check_token(destination: str = DESTINATION_DE_CONTROLE) -> tuple[bool, str]:
    """Un seul appel réel. Renvoie (succès, message lisible) — jamais le jeton."""
    valeur = jeton()
    if valeur is None:
        return False, (
            f"{VARIABLE_JETON} absent. Le renseigner dans {ENV_PATH} "
            f"(voir .env.example). Rien d'autre n'est bloqué : le projet "
            f"fonctionne sans, depuis le snapshot versionné."
        )

    import httpx

    from nalu.net import default_ssl_context

    try:
        reponse = httpx.get(
            TRAVELPAYOUTS_URL,
            params={
                "origin": CONFIG.origin_iata,
                "destination": destination,
                "currency": CONFIG.currency.lower(),
            },
            headers={"X-Access-Token": valeur},
            verify=default_ssl_context(),
            timeout=30,
        )
    except Exception as e:
        return False, f"appel impossible ({type(e).__name__}) : {e}"

    trace = empreinte(valeur)
    if reponse.status_code == 401:
        return False, f"jeton REFUSÉ (HTTP 401). Empreinte du jeton lu : {trace}"
    if reponse.status_code != 200:
        return False, f"réponse inattendue HTTP {reponse.status_code}. Jeton lu : {trace}"

    charge = reponse.json()
    if not charge.get("success", False):
        return False, f"l'API répond succès=false : {charge.get('error', charge)}"

    mois = charge.get("data") or {}
    return True, (
        f"jeton VALIDE ({trace}). {CONFIG.origin_iata} vers {destination} : "
        f"{len(mois)} mois avec un prix sur les 12 prochains."
    )


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--check-token", action="store_true", help="vérifie le jeton")
    parseur.add_argument("--destination", default=DESTINATION_DE_CONTROLE)
    args = parseur.parse_args(argv)

    if not args.check_token:
        parseur.print_help()
        return 0

    ok, message = check_token(args.destination)
    print(("OK   " if ok else "ÉCHEC ") + message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
