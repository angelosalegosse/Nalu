"""Les trois notebooks doivent s'exécuter de bout en bout, hors ligne.

Un notebook de vitrine qui ne tourne plus est pire qu'absent : il affiche des
sorties figées qui ne correspondent plus au code, et le lecteur n'a aucun moyen de
le savoir. Ce test est ce qui empêche cette dérive silencieuse.

Il exécute une COPIE dans un répertoire temporaire : les notebooks du dépôt gardent
leurs sorties, qui sont ce qu'un prospect lit sur GitHub sans rien installer.
"""

import shutil
import subprocess
import sys

import pytest

from nalu.paths import RACINE

NOTEBOOKS_DIR = RACINE / "notebooks"
ATTENDUS = (
    "01-exploration-houle.ipynb",
    "02-validation-scoring.ipynb",
    "03-analyse-vols.ipynb",
)


def test_les_trois_notebooks_sont_presents() -> None:
    manquants = [n for n in ATTENDUS if not (NOTEBOOKS_DIR / n).exists()]
    assert not manquants, f"notebooks absents : {manquants}"


def test_les_notebooks_du_depot_portent_leurs_sorties() -> None:
    """Sans sorties, la page GitHub n'a rien à montrer à un prospect."""
    import json

    for nom in ATTENDUS:
        contenu = json.loads((NOTEBOOKS_DIR / nom).read_text(encoding="utf-8"))
        cellules_code = [c for c in contenu["cells"] if c["cell_type"] == "code"]
        avec_sortie = [c for c in cellules_code if c.get("outputs")]
        assert avec_sortie, f"{nom} : aucune cellule de code n'a de sortie"


def test_aucun_notebook_ne_contient_de_trace_d_erreur() -> None:
    """Un notebook commité avec un `Traceback` visible est une vitrine cassée."""
    import json

    for nom in ATTENDUS:
        contenu = json.loads((NOTEBOOKS_DIR / nom).read_text(encoding="utf-8"))
        for i, cellule in enumerate(contenu["cells"]):
            for sortie in cellule.get("outputs", []):
                assert sortie.get("output_type") != "error", (
                    f"{nom}, cellule {i} : {sortie.get('ename')}"
                )


@pytest.mark.slow
@pytest.mark.parametrize("nom", ATTENDUS)
def test_le_notebook_s_execute_de_bout_en_bout(nom: str, tmp_path) -> None:
    """`nbconvert --execute` sur une copie. Échoue si une seule cellule lève."""
    if shutil.which("jupyter") is None and not (RACINE / ".venv").exists():
        pytest.skip("jupyter indisponible dans cet environnement")

    copie = tmp_path / nom
    shutil.copy(NOTEBOOKS_DIR / nom, copie)

    resultat = subprocess.run(
        [
            sys.executable, "-m", "jupyter", "nbconvert",
            "--to", "notebook", "--execute", "--inplace",
            "--ExecutePreprocessor.timeout=600",
            str(copie),
        ],
        capture_output=True,
        cwd=RACINE,
    )
    assert resultat.returncode == 0, (
        f"{nom} n'a pas pu s'executer :\n"
        + resultat.stderr.decode("utf-8", "replace")[-3000:]
    )
