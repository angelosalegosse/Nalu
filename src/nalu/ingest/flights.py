"""Prix des vols : sonde de couverture, connecteur live, snapshot versionné.

    DIAGRAMME — sources de prix (à vérifier dans tout commit modifiant ce fichier)

                          demande de prix (20 destinations)
                                       |
                                       v
                        +--------------------------------+
                        |     FlightPriceSource          |  protocole
                        +--------------------------------+
                          /                            \\
                         v                              v
        +-------------------------+        +---------------------------+
        | TravelpayoutsSource     |        | SnapshotSource            |
        | api.travelpayouts.com   |        | data/snapshots/           |
        | /v1/prices/monthly      |        |   flights_AAAA-MM-JJ.parquet
        | jeton OPTIONNEL         |        | COMMITE, source PAR DEFAUT|
        +-------------------------+        +---------------------------+
                    |                                   ^
                    |  401 / 500 / jeton absent         |
                    +-----------------------------------+
                              bascule + avertissement explicite

    Le connecteur live ne sert QU'A regenerer le snapshot. Le dashboard lit toujours
    le snapshot : c'est ce qui garantit une demo reproductible et hors ligne.

    Une destination sans prix produit une ligne a `price_eur = null`. JAMAIS une ligne
    absente : le dashboard doit pouvoir la marquer « non couverte » plutot que de
    l'oublier, et un spot oublie disparaitrait silencieusement du classement.

Travelpayouts sert des minima issus du **cache de recherches** de ses utilisateurs, pas
une interrogation GDS. La couverture est donc proportionnelle à la popularité
touristique de la destination. `probe()` mesure ce biais et le publie.
"""

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

import polars as pl
import yaml

from nalu.config import CONFIG
from nalu.paths import DATA, RACINE

TRAVELPAYOUTS_URL = "https://api.travelpayouts.com/v1/prices/monthly"
VARIABLE_JETON = "TRAVELPAYOUTS_TOKEN"
ENV_PATH = RACINE / ".env"
POPULARITE_PATH = DATA / "airport_popularity.yaml"
SNAPSHOT_DIR = DATA / "snapshots"

# Horizon du produit : on choisit un mois de départ à moyen terme, pas une date.
MOIS_HORIZON = 12

# Destination de contrôle du jeton : Bali est la route la plus fréquentée du
# référentiel. Un succès ici prouve que le jeton est bon ; un échec ne prouve rien.
DESTINATION_DE_CONTROLE = "DPS"

SCHEMA = {
    "airport_iata": pl.String,
    "month": pl.Date,
    "price_eur": pl.Float64,
    "collected_at": pl.Datetime("us", "UTC"),
}


# ─── Jeton ─────────────────────────────────────────────────────────────────────


def charger_env(chemin: Path | None = None) -> None:
    """Charge `.env` dans l'environnement, sans écraser ce qui existe déjà.

    Pas de dépendance pour trois lignes : le format utile est `CLE=valeur`.

    `chemin` est résolu à l'appel, pas à la définition : une valeur par défaut liée
    au moment du `def` fige `ENV_PATH` et rend le test « sans jeton » inécrivable.
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


# ─── Mois d'horizon ────────────────────────────────────────────────────────────


def mois_horizon(depart: date | None = None, nombre: int = MOIS_HORIZON) -> list[date]:
    """Les `nombre` prochains mois, premier jour de chacun. Déterministe si `depart` est fourni."""
    depart = depart or date.today()
    mois = []
    annee, m = depart.year, depart.month
    for _ in range(nombre):
        mois.append(date(annee, m, 1))
        m += 1
        if m > 12:
            annee, m = annee + 1, 1
    return mois


def trame_vide(destinations: list[str], mois: list[date], collecte: datetime) -> pl.DataFrame:
    """Produit cartésien destinations x mois, tous les prix à null.

    C'est le squelette qui garantit qu'aucune destination ne disparaît silencieusement.
    """
    return pl.DataFrame(
        {
            "airport_iata": [d for d in destinations for _ in mois],
            "month": [m for _ in destinations for m in mois],
            "price_eur": [None] * (len(destinations) * len(mois)),
            "collected_at": [collecte] * (len(destinations) * len(mois)),
        },
        schema=SCHEMA,
    )


# ─── Sources ───────────────────────────────────────────────────────────────────


class FlightPriceSource(Protocol):
    """Un fournisseur de prix mensuels. Changer de fournisseur doit coûter un fichier."""

    nom: str

    def monthly_prices(self, destinations: list[str], mois: list[date]) -> pl.DataFrame:
        """Renvoie une ligne par (destination, mois), `price_eur` nul si non couvert."""
        ...


class BasculeError(RuntimeError):
    """La source live est inutilisable. L'appelant doit basculer sur le snapshot."""


@dataclass
class TravelpayoutsSource:
    """Connecteur live. Ne sert qu'à régénérer le snapshot, jamais le dashboard."""

    token: str | None = None
    nom: str = "travelpayouts-live"
    timeout: float = 30.0

    def __post_init__(self) -> None:
        if self.token is None:
            self.token = jeton()

    def _appeler(self, destination: str) -> dict:
        import httpx

        from nalu.net import default_ssl_context

        reponse = httpx.get(
            TRAVELPAYOUTS_URL,
            params={
                "origin": CONFIG.origin_iata,
                "destination": destination,
                "currency": CONFIG.currency.lower(),
            },
            headers={"X-Access-Token": self.token or ""},
            verify=default_ssl_context(),
            timeout=self.timeout,
        )
        if reponse.status_code == 401:
            raise BasculeError(
                f"HTTP 401 : jeton refusé par Travelpayouts sur {destination}. "
                "Vérifier TRAVELPAYOUTS_TOKEN dans .env."
            )
        if reponse.status_code >= 500:
            raise BasculeError(
                f"HTTP {reponse.status_code} : Travelpayouts indisponible sur {destination}."
            )
        reponse.raise_for_status()
        return reponse.json()

    def monthly_prices(self, destinations: list[str], mois: list[date]) -> pl.DataFrame:
        if not self.token:
            raise BasculeError(
                f"{VARIABLE_JETON} absent : aucune collecte live possible. "
                "Le snapshot versionné prend le relais."
            )

        collecte = datetime.now(UTC)
        connus = set(mois)
        lignes: dict[tuple[str, date], float] = {}

        for destination in destinations:
            charge = self._appeler(destination)
            for cle, valeur in (charge.get("data") or {}).items():
                # Les clés sont des « AAAA-MM ». Un mois hors horizon est ignoré.
                try:
                    annee, m = cle.split("-")[:2]
                    premier = date(int(annee), int(m), 1)
                except (ValueError, IndexError):
                    continue
                prix = valeur.get("price")
                if premier in connus and prix is not None:
                    lignes[(destination, premier)] = float(prix)

        trame = trame_vide(destinations, mois, collecte)
        if not lignes:
            return trame
        trouves = pl.DataFrame(
            {
                "airport_iata": [d for d, _ in lignes],
                "month": [m for _, m in lignes],
                "prix_trouve": list(lignes.values()),
            },
            schema={"airport_iata": pl.String, "month": pl.Date, "prix_trouve": pl.Float64},
        )
        return (
            trame.join(trouves, on=["airport_iata", "month"], how="left")
            .with_columns(pl.coalesce("prix_trouve", "price_eur").alias("price_eur"))
            .drop("prix_trouve")
            .select(*SCHEMA)
        )


@dataclass
class SnapshotSource:
    """Lecture du snapshot versionné. Source PAR DÉFAUT, et seule source hors ligne."""

    chemin: Path | None = None
    nom: str = "snapshot"

    def __post_init__(self) -> None:
        if self.chemin is None:
            self.chemin = dernier_snapshot()

    def monthly_prices(self, destinations: list[str], mois: list[date]) -> pl.DataFrame:
        if self.chemin is None or not self.chemin.exists():
            raise FileNotFoundError(
                f"aucun snapshot de prix dans {SNAPSHOT_DIR}. "
                "Le générer avec `uv run python -m nalu.ingest.flights --collect`."
            )
        trame = pl.read_parquet(self.chemin)
        collecte = trame["collected_at"].max() if trame.height else datetime.now(UTC)
        squelette = trame_vide(destinations, mois, collecte)
        return (
            squelette.join(
                trame.select("airport_iata", "month", pl.col("price_eur").alias("prix_snapshot")),
                on=["airport_iata", "month"],
                how="left",
            )
            .with_columns(pl.coalesce("prix_snapshot", "price_eur").alias("price_eur"))
            .drop("prix_snapshot")
            .select(*SCHEMA)
        )


@dataclass
class SourceAvecRepli:
    """Essaie la source live, bascule sur le repli en journalisant un avertissement.

    C'est ici, et nulle part ailleurs, que se décide « le live a échoué, on continue ».
    """

    live: FlightPriceSource
    repli: FlightPriceSource
    nom: str = "live-avec-repli"
    avertissements: list[str] | None = None

    def monthly_prices(self, destinations: list[str], mois: list[date]) -> pl.DataFrame:
        if self.avertissements is None:
            self.avertissements = []
        try:
            return self.live.monthly_prices(destinations, mois)
        except Exception as erreur:
            # Volontairement large : 401, 500, jeton absent, réseau coupé, réponse
            # illisible. Aucune de ces situations ne doit empêcher la démo de tourner.
            message = (
                f"source « {self.live.nom} » indisponible ({erreur}) "
                f"— repli sur « {self.repli.nom} »"
            )
            self.avertissements.append(message)
            print(f"  AVERTISSEMENT {message}")
            return self.repli.monthly_prices(destinations, mois)


def dernier_snapshot(racine: Path = SNAPSHOT_DIR) -> Path | None:
    """Le snapshot de prix le plus récent, par ordre de nom (donc de date)."""
    if not racine.exists():
        return None
    trouves = sorted(racine.glob("flights_*.parquet"))
    return trouves[-1] if trouves else None


# ─── Sonde de couverture ───────────────────────────────────────────────────────


def charger_popularite(chemin: Path = POPULARITE_PATH) -> dict[str, int]:
    brut = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    return {code: int(v["tier"]) for code, v in brut.items()}


def _rangs(valeurs: list[float]) -> list[float]:
    """Rangs moyens, ex aequo compris. Base d'une corrélation de Spearman."""
    ordonnes = sorted(range(len(valeurs)), key=lambda i: valeurs[i])
    rangs = [0.0] * len(valeurs)
    i = 0
    while i < len(ordonnes):
        j = i
        while j + 1 < len(ordonnes) and valeurs[ordonnes[j + 1]] == valeurs[ordonnes[i]]:
            j += 1
        moyen = (i + j) / 2 + 1
        for k in range(i, j + 1):
            rangs[ordonnes[k]] = moyen
        i = j + 1
    return rangs


def spearman(x: list[float], y: list[float]) -> float:
    """Corrélation de rangs. 0 si l'une des séries est constante."""
    if len(x) < 2:
        return 0.0
    rx, ry = _rangs(x), _rangs(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    return 0.0 if dx == 0 or dy == 0 else num / (dx * dy)


@dataclass(frozen=True)
class Couverture:
    """Résultat de la sonde. Porte la décision produit, pas seulement des chiffres."""

    par_destination: dict[str, int]
    correlation_popularite: float
    mesure_le: date

    @property
    def couverts(self) -> int:
        """Destinations ayant au moins un mois avec un prix."""
        return sum(1 for n in self.par_destination.values() if n > 0)

    @property
    def decision(self) -> str:
        if self.couverts >= CONFIG.coverage_two_axis_min:
            return "deux-axes"
        if self.couverts >= CONFIG.coverage_restricted_min:
            return "referentiel-restreint"
        return "mono-axe"

    @property
    def decision_lisible(self) -> str:
        return {
            "deux-axes": "produit à deux axes, tel que spécifié",
            "referentiel-restreint": (
                "référentiel restreint aux spots couverts, exclusion écrite dans le README"
            ),
            "mono-axe": (
                "PRODUIT MONO-AXE : calendrier de saisonnalité, l'axe prix est abandonné"
            ),
        }[self.decision]


def probe(trame: pl.DataFrame, popularite: dict[str, int] | None = None) -> Couverture:
    """Mesure la couverture ET sa corrélation avec la popularité de la destination.

    Le passage en rang centile rendrait ce biais invisible, pas absent. Le mesurer est
    ce qui transforme une faiblesse cachée en démonstration de méthode.
    """
    popularite = popularite if popularite is not None else charger_popularite()

    comptes = (
        trame.group_by("airport_iata")
        .agg(pl.col("price_eur").is_not_null().sum().alias("mois_couverts"))
        .sort("airport_iata")
    )
    par_destination = dict(
        zip(comptes["airport_iata"].to_list(), comptes["mois_couverts"].to_list(), strict=True)
    )

    communs = [d for d in par_destination if d in popularite]
    correlation = spearman(
        [float(popularite[d]) for d in communs],
        [float(par_destination[d]) for d in communs],
    )
    return Couverture(par_destination, correlation, date.today())


# ─── Collecte du snapshot ──────────────────────────────────────────────────────


def chemin_snapshot(jour: date | None = None, racine: Path = SNAPSHOT_DIR) -> Path:
    return racine / f"flights_{(jour or date.today()).isoformat()}.parquet"


def collect(
    destinations: list[str],
    source: FlightPriceSource | None = None,
    mois: list[date] | None = None,
    chemin: Path | None = None,
) -> tuple[pl.DataFrame, Path]:
    """Collecte les prix et écrit le snapshot daté. Le snapshot est un ACTIF."""
    source = source or TravelpayoutsSource()
    mois = mois or mois_horizon()
    chemin = chemin or chemin_snapshot()

    trame = source.monthly_prices(destinations, mois)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    provisoire = chemin.with_suffix(".partiel")
    trame.write_parquet(provisoire, compression="zstd")
    provisoire.replace(chemin)
    return trame, chemin


# ─── Vérification du jeton ─────────────────────────────────────────────────────


def check_token(destination: str = DESTINATION_DE_CONTROLE) -> tuple[bool, str]:
    """Un seul appel réel. Renvoie (succès, message lisible) — jamais le jeton."""
    valeur = jeton()
    if valeur is None:
        return False, (
            f"{VARIABLE_JETON} absent. Le renseigner dans {ENV_PATH} "
            f"(voir .env.example). Rien d'autre n'est bloqué : le projet "
            f"fonctionne sans, depuis le snapshot versionné."
        )
    source = TravelpayoutsSource(token=valeur)
    try:
        trame = source.monthly_prices([destination], mois_horizon())
    except BasculeError as erreur:
        return False, f"{erreur} Empreinte du jeton lu : {empreinte(valeur)}"
    except Exception as erreur:
        return False, f"appel impossible ({type(erreur).__name__}) : {erreur}"

    couverts = trame["price_eur"].is_not_null().sum()
    return True, (
        f"jeton VALIDE ({empreinte(valeur)}). {CONFIG.origin_iata} vers {destination} : "
        f"{couverts} mois avec un prix sur les {MOIS_HORIZON} prochains."
    )


# ─── CLI ───────────────────────────────────────────────────────────────────────


def _destinations() -> list[str]:
    from nalu.spots import load_raw_spots

    return sorted({s.airport_iata for s in load_raw_spots()})


def _rapport(couverture: Couverture, popularite: dict[str, int]) -> str:
    lignes = [
        f"Sonde de couverture Travelpayouts — {couverture.mesure_le.isoformat()}",
        f"Origine {CONFIG.origin_iata}, horizon {MOIS_HORIZON} mois, devise {CONFIG.currency}",
        "",
        f"{'IATA':<6} {'mois couverts':>14}  {'popularité':>10}",
    ]
    for code, mois in sorted(
        couverture.par_destination.items(), key=lambda kv: (-kv[1], kv[0])
    ):
        lignes.append(f"{code:<6} {mois:>14}  {popularite.get(code, '?'):>10}")
    lignes += [
        "",
        f"Destinations couvertes : {couverture.couverts} / {len(couverture.par_destination)}",
        f"Corrélation de rangs couverture ~ popularité : {couverture.correlation_popularite:+.2f}",
        f"DÉCISION PRODUIT : {couverture.decision_lisible}",
    ]
    return "\n".join(lignes)


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description="Prix des vols Travelpayouts")
    parseur.add_argument("--check-token", action="store_true", help="vérifie le jeton")
    parseur.add_argument("--probe", action="store_true", help="sonde de couverture")
    parseur.add_argument("--collect", action="store_true", help="écrit le snapshot daté")
    parseur.add_argument("--destination", default=DESTINATION_DE_CONTROLE)
    args = parseur.parse_args(argv)

    if args.check_token:
        ok, message = check_token(args.destination)
        print(("OK   " if ok else "ÉCHEC ") + message)
        return 0 if ok else 1

    if args.collect or args.probe:
        destinations = _destinations()
        if args.collect:
            trame, chemin = collect(destinations)
            print(f"snapshot écrit : {chemin} ({trame.height} lignes)")
        else:
            source = SourceAvecRepli(TravelpayoutsSource(), SnapshotSource())
            trame = source.monthly_prices(destinations, mois_horizon())
        print()
        print(_rapport(probe(trame), charger_popularite()))
        return 0

    parseur.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
