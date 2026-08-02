"""Scan de secrets avant — et après — la bascule du dépôt en public.

Rendre un dépôt public est une **porte à sens unique** : une fois l'historique
cloné par un tiers, le retirer de GitHub ne le retire de nulle part ailleurs. Ce
fichier est donc la vérification qui précède la bascule, et la garde qui la suit.

Il regarde trois choses que l'œil ne tient pas dans la durée :

  1. `.env` n'est ni suivi par git, ni absent de `.gitignore` ;
  2. `.env.example`, lui **versionné**, ne porte que des clés vides ;
  3. l'historique complet ne contient aucune valeur de forme secrète.

Le point 3 lit `git log --all -p`. Un clone superficiel n'a pas d'historique à
scanner : le test le dit et se retire, plutôt que de passer en donnant l'illusion
d'avoir vérifié. La CI cloue `fetch-depth: 0` pour qu'il s'exécute vraiment.
"""

import re
import subprocess

import pytest

from nalu.paths import RACINE

# Formes de secrets réellement émis par les fournisseurs concernés — pas une
# heuristique d'entropie, qui sur ce dépôt ne remonterait que des empreintes de
# roues PyPI. Chaque motif vise un émetteur nommé.
MOTIFS = {
    "clé privée PEM": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "clé d'accès AWS": r"\bAKIA[0-9A-Z]{16}\b",
    "clé Google API (dont Gemini)": r"\bAIza[0-9A-Za-z_-]{35}\b",
    "jeton GitHub": r"\bgh[pousr]_[0-9A-Za-z]{36,}\b",
    "jeton Slack": r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b",
    "clé de style OpenAI/Anthropic": r"\bsk-[0-9A-Za-z_-]{20,}\b",
    "affectation littérale d'un secret": (
        r"(?i)(token|secret|api[_-]?key|password|passwd)\s*[=:]\s*"
        r"[\"'][0-9A-Za-z/+_-]{16,}[\"']"
    ),
}

# Le jeton Travelpayouts est un hexadécimal de 32 caractères, sans préfixe : aucun
# motif ne peut le distinguer d'une empreinte. On le cherche donc par sa valeur,
# lue dans le `.env` du poste quand il existe. Sur une machine sans `.env` — la CI —
# il n'y a rien à chercher, et le test reste utile pour tout le reste.
ENV_LOCAL = RACINE / ".env"


def _git(*args: str) -> str:
    resultat = subprocess.run(
        ["git", *args], cwd=RACINE, capture_output=True, check=True
    )
    return resultat.stdout.decode("utf-8", "replace")


def _historique_complet() -> str:
    """L'historique complet, PRIVE de ce fichier-ci.

    Sans l'exclusion, le scan se détecte lui-même : les échantillons synthétiques
    plus bas sont, une fois ce fichier commité, des formes de secrets présentes
    dans l'historique. C'est arrivé — vert en local avant le commit, rouge en CI
    juste après. Même précaution que l'étape `python[3]` de `ci.yml`, qui s'écrit
    avec une classe de caractères pour ne pas se signaler elle-même.

    Exclure ce seul fichier ne crée pas d'angle mort utile : c'est le fichier dont
    la raison d'être est de contenir des chaînes de forme secrète, et il est relu
    à chaque modification.
    """
    if (RACINE / ".git" / "shallow").exists():
        pytest.skip("clone superficiel : aucun historique à scanner (CI : fetch-depth: 0)")
    return _git("log", "--all", "-p", "--", ".", ":(exclude)tests/test_secrets.py")


def test_env_n_est_pas_suivi_par_git() -> None:
    assert ".env" not in _git("ls-files").splitlines()


def test_env_est_bien_ignore() -> None:
    assert ".env" in (RACINE / ".gitignore").read_text(encoding="utf-8-sig")


def test_env_n_a_jamais_ete_commite() -> None:
    """Le fichier ne doit pas non plus avoir existé dans un commit passé."""
    assert _git("log", "--all", "--full-history", "--oneline", "--", ".env").strip() == ""


def test_env_example_ne_porte_que_des_cles_vides() -> None:
    """`.env.example` est versionné : une valeur y serait publiée telle quelle."""
    renseignees = []
    for ligne in (RACINE / ".env.example").read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, valeur = ligne.partition("=")
        if valeur.strip().strip("\"'"):
            renseignees.append(cle.strip())
    assert not renseignees, f"valeurs présentes dans .env.example : {renseignees}"


@pytest.mark.parametrize("nom,motif", sorted(MOTIFS.items()))
def test_l_historique_ne_contient_aucun_secret(nom: str, motif: str) -> None:
    trouve = re.search(motif, _historique_complet())
    # On nomme le motif et l'emplacement, jamais la valeur : un message d'échec est
    # lui-même journalisé par la CI, donc public.
    assert trouve is None, f"{nom} : forme de secret trouvée dans l'historique git"


# Contre-épreuve : un scan qui ne peut jamais échouer donne une fausse assurance,
# et c'est pire que pas de scan du tout. Ces échantillons sont synthétiques.
ECHANTILLONS = {
    "clé privée PEM": "-----BEGIN RSA PRIVATE KEY-----",
    "clé d'accès AWS": "AKIAIOSFODNN7EXAMPLE",
    "clé Google API (dont Gemini)": "AIza" + "b" * 35,
    "jeton GitHub": "ghp_" + "c" * 36,
    "jeton Slack": "xoxb-1234567890-abcdef",
    "clé de style OpenAI/Anthropic": "sk-" + "d" * 24,
    "affectation littérale d'un secret": 'api_key = "0123456789abcdefghij"',
}


@pytest.mark.parametrize("nom,motif", sorted(MOTIFS.items()))
def test_chaque_motif_detecte_vraiment_sa_forme(nom: str, motif: str) -> None:
    assert re.search(motif, ECHANTILLONS[nom]), f"le motif {nom} est inerte"


def test_les_motifs_ne_sonnent_pas_sur_le_depot_sain() -> None:
    """Aucun motif ne doit se déclencher sur une empreinte de roue PyPI."""
    benin = 'wheel = { url = "https://x/y", hash = "sha256:' + "a" * 64 + '" }'
    for motif in MOTIFS.values():
        assert not re.search(motif, benin)


def test_le_jeton_du_poste_est_absent_de_l_historique() -> None:
    if not ENV_LOCAL.exists():
        pytest.skip("aucun .env sur cette machine : rien à confronter")
    valeurs = []
    for ligne in ENV_LOCAL.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, valeur = ligne.partition("=")
        valeur = valeur.strip().strip("\"'")
        if valeur:
            valeurs.append((cle.strip(), valeur))
    if not valeurs:
        pytest.skip(".env présent mais sans valeur renseignée")
    historique = _historique_complet()
    fuites = [cle for cle, valeur in valeurs if valeur in historique]
    assert not fuites, f"valeur de {fuites} présente dans l'historique git"
