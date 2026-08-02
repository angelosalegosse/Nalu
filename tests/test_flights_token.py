"""Vérification du jeton Travelpayouts : jamais divulgué, jamais bloquant."""

from pathlib import Path

import pytest

from nalu.ingest import flights
from nalu.ingest.flights import VARIABLE_JETON, charger_env, check_token, empreinte, jeton

JETON_FACTICE = "abcdef0123456789abcdef0123456789"


def test_l_empreinte_ne_divulgue_pas_le_jeton() -> None:
    trace = empreinte(JETON_FACTICE)
    assert JETON_FACTICE not in trace
    assert trace.startswith("abc")
    assert "32 caractères" in trace


def test_l_empreinte_d_un_jeton_court_est_entierement_masquee() -> None:
    assert "secret" not in empreinte("secret")


def test_charger_env_lit_les_paires_et_ignore_les_commentaires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fichier = tmp_path / ".env"
    fichier.write_text(
        "# un commentaire\n\nUNE_CLE=une_valeur\nAUTRE = \"guillemets\"\nligne_sans_egal\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("UNE_CLE", raising=False)
    monkeypatch.delenv("AUTRE", raising=False)

    charger_env(fichier)

    import os

    assert os.environ["UNE_CLE"] == "une_valeur"
    assert os.environ["AUTRE"] == "guillemets"


def test_charger_env_n_ecrase_pas_l_environnement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une variable déjà posée par le shell ou la CI doit gagner sur le fichier."""
    fichier = tmp_path / ".env"
    fichier.write_text("UNE_CLE=depuis_le_fichier\n", encoding="utf-8")
    monkeypatch.setenv("UNE_CLE", "depuis_le_shell")

    charger_env(fichier)

    import os

    assert os.environ["UNE_CLE"] == "depuis_le_shell"


def test_un_env_absent_ne_fait_pas_echouer(tmp_path: Path) -> None:
    charger_env(tmp_path / "inexistant.env")  # ne lève pas


@pytest.mark.disable_socket
def test_sans_jeton_le_controle_echoue_proprement_et_sans_reseau(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Le jeton est optionnel : son absence explique, elle ne casse rien."""
    monkeypatch.delenv(VARIABLE_JETON, raising=False)
    # On pointe `ENV_PATH` sur un fichier absent plutôt que de changer de répertoire
    # courant : depuis que les chemins sont ancrés sur la racine du dépôt, un `chdir`
    # ne cache plus le `.env` du poste. Ce test passait alors pour une mauvaise
    # raison — il lisait le vrai jeton du développeur au lieu de n'en trouver aucun.
    monkeypatch.setattr(flights, "ENV_PATH", tmp_path / "inexistant.env")

    assert jeton() is None
    ok, message = check_token()
    assert not ok
    assert VARIABLE_JETON in message
    assert "snapshot" in message
