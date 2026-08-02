"""Le socle tient : bon interpreteur, paquet importable."""

import sys

import nalu


def test_interpreteur_est_bien_en_3_12() -> None:
    """La pile scientifique n'est pas stabilisee sur 3.14 : l'epingle doit tenir."""
    assert sys.version_info[:2] == (3, 12)


def test_le_paquet_nalu_est_importable() -> None:
    assert nalu.__version__


def test_les_sous_paquets_sont_importables() -> None:
    import nalu.ingest
    import nalu.llm
    import nalu.scoring

    assert nalu.ingest.__doc__
    assert nalu.scoring.__doc__
    assert nalu.llm.__doc__
