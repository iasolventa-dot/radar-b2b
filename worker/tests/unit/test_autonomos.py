"""Quién es autónomo a efectos del filtro de la búsqueda (sin BD)."""

from radar.agente.autonomos import es_autonomo


def _es(**k):
    base = {"es_persona_fisica": False, "nif": None, "forma_juridica": None, "nombres": [], "tiene_cargos_borme": False,
            "autonomo_ia": None}
    return es_autonomo(**{**base, **k})


def test_nif_de_persona_fisica_es_autonomo_aunque_la_ia_diga_lo_contrario() -> None:
    assert _es(nif="49130682Z", autonomo_ia=False)


def test_cif_de_sociedad_nunca_es_autonomo() -> None:
    assert not _es(nif="B91030973", autonomo_ia=True, nombres=["Lorena Pérez Castro"])


def test_forma_juridica_o_borme_es_sociedad() -> None:
    assert not _es(nombres=["FONTANERIA SAN JOSE SL"], autonomo_ia=True)
    assert not _es(tiene_cargos_borme=True, autonomo_ia=True)


def test_sin_evidencia_decide_la_ia() -> None:
    assert _es(nombres=["Gonzalo de Luque"], autonomo_ia=True)
    assert not _es(nombres=["Fontanero JT"], autonomo_ia=False)
    assert not _es(nombres=["Fontanero JT"], autonomo_ia=None)  # sin juicio: no se excluye
