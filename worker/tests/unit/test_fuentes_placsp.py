"""Tests de `radar.fuentes.placsp.parsear_entrada` contra entradas REALES
de PLACSP (sindicación 643), recuperadas y verificadas a mano el
2026-09-15 -- ver docstring del módulo para el porqué de estas fixtures
concretas (y de por qué esta entrega no incluye el conector de
descubrimiento completo).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from radar.fuentes.placsp import NS, es_cpv_relevante, parsear_entrada

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "placsp"


def _cargar_entry(nombre: str) -> ET.Element:
    arbol = ET.parse(FIXTURES / nombre)
    entry = arbol.find("atom:entry", NS)
    assert entry is not None, f"{nombre} no tiene ninguna <entry>"
    return entry


def test_es_cpv_relevante():
    assert es_cpv_relevante("45233000") is True  # división 45, construcción
    assert es_cpv_relevante("39150000") is False  # mobiliario
    assert es_cpv_relevante(None) is False
    assert es_cpv_relevante("") is False


def test_entrada_adjudicada_con_nif_da_un_contrato():
    """Adjudicatario con NIF real (persona jurídica normal, no una UTE --
    ver test_ute_sin_nif_no_da_ningun_contrato para ese caso)."""
    contratos = parsear_entrada(_cargar_entry("entrada_adjudicada_con_nif.xml"))
    assert len(contratos) == 1
    c = contratos[0]
    assert c.adjudicatario_nif
    assert c.adjudicatario_nombre
    assert c.importe_adjudicado is not None and c.importe_adjudicado > 0
    assert c.fecha_adjudicacion is not None


def test_ute_sin_nif_no_da_ningun_contrato():
    """Hallazgo real al construir estas fixtures (2026-09-15): el único
    ganador de CPV de construcción (45xxxxxx) que se pudo recuperar es una
    UTE (Unión Temporal de Empresas) -- muy habitual en obra pública
    grande -- identificada por PLACSP con `schemeName="OTROS"` y un id
    interno, NO con un NIF. `_nif_de_party` no lo confunde con un NIF real
    (nunca inventar, principio 5): sin NIF, ese lote se omite, aunque el
    resto de los datos (importe, fecha, CPV) estén completos."""
    contratos = parsear_entrada(_cargar_entry("entrada_ute_sin_nif.xml"))
    assert contratos == []


def test_entrada_publicada_sin_adjudicar_no_da_ningun_contrato():
    """Estado 'PUB' (solo publicada, sin ganador todavía) -- sin
    WinningParty, no hay nada que extraer. Lista vacía, no None ni error:
    quien llame puede iterar sin comprobar antes."""
    contratos = parsear_entrada(_cargar_entry("entrada_publicada_sin_adjudicar.xml"))
    assert contratos == []


def test_entrada_multiples_lotes_da_un_contrato_por_lote_con_ganador():
    """Licitación real de mobiliario (Canarias) con 3 lotes -- 2 con
    ganador y 1 desierto (ResultCode=3, ReceivedTenderQuantity=0, sin
    WinningParty: nadie presentó oferta a ese lote). El parser debe dar
    2 contratos, no 3 ni 0 -- si devolviera solo "el primer ganador" en
    vez de recorrer todos los TenderResult, perdería el segundo lote
    adjudicado; si no comprobara WinningParty por lote, inventaría un
    contrato para el lote desierto."""
    contratos = parsear_entrada(_cargar_entry("entrada_multiples_lotes.xml"))
    assert len(contratos) == 2
    nifs = {c.adjudicatario_nif for c in contratos}
    assert len(nifs) == 2, "los 2 lotes adjudicados tienen adjudicatarios distintos en la licitación real"
    # ninguno de los 2 es de construccion (CPV real: mobiliario)
    assert all(not es_cpv_relevante(c.cpv) for c in contratos)


def test_todos_los_contratos_tienen_nif_y_nombre():
    """Nunca inventar (principio 5): si algún lote real llegara sin NIF o
    sin nombre, parsear_entrada debe omitirlo, no rellenar con None ni
    cadena vacía disfrazada de dato real."""
    for fixture in ("entrada_adjudicada_con_nif.xml", "entrada_multiples_lotes.xml"):
        for c in parsear_entrada(_cargar_entry(fixture)):
            assert c.adjudicatario_nif and c.adjudicatario_nif.strip()
            assert c.adjudicatario_nombre and c.adjudicatario_nombre.strip()


@pytest.mark.parametrize("fixture", ["entrada_adjudicada_con_nif.xml", "entrada_multiples_lotes.xml"])
def test_nuts_presente_cuando_la_fuente_lo_da(fixture):
    """NUTS (código de región de ejecución, p. ej. 'ES705' = Gran Canaria)
    -- no todas las entradas reales lo traen, pero cuando lo traen debe
    llegar tal cual, sin normalizar ni recortar."""
    contratos = parsear_entrada(_cargar_entry(fixture))
    assert any(c.nuts for c in contratos)
