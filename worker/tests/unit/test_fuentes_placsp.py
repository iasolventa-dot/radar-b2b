"""Tests de `radar.fuentes.placsp.parsear_entrada` contra entradas REALES
de PLACSP (sindicación 643), recuperadas y verificadas a mano el
2026-09-15 -- ver docstring del módulo para el porqué de estas fixtures
concretas (y de por qué esta entrega no incluye el conector de
descubrimiento completo).
"""

from __future__ import annotations

import asyncio
import io
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from radar.fuentes.placsp import (
    NS,
    ConectorPLACSP,
    _entradas_de_zip,
    es_cpv_relevante,
    parsear_entrada,
    provincia_de_nuts,
)

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


# ---------- provincia_de_nuts ----------


def test_provincia_de_nuts_sevilla():
    assert provincia_de_nuts("ES618") == "Sevilla"


def test_provincia_de_nuts_canarias_colapsa_a_la_provincia_ine():
    """NUTS3 divide Canarias en 7 islas; el INE (y el resto de este
    proyecto, ubicacion.provincias) solo conoce 2 provincias -- deben
    colapsar a la provincia correcta, no quedarse en el nombre de la isla."""
    assert provincia_de_nuts("ES705") == "Las Palmas"  # Gran Canaria
    assert provincia_de_nuts("ES709") == "Santa Cruz de Tenerife"  # Tenerife


def test_provincia_de_nuts_desconocido_o_ausente_no_inventa():
    assert provincia_de_nuts(None) is None
    assert provincia_de_nuts("") is None
    assert provincia_de_nuts("ES999") is None  # no existe ese código


# ---------- _entradas_de_zip / ConectorPLACSP.descubrir ----------
#
# Un zip sintético (no uno real de PLACSP -- ver docstring del módulo
# sobre por qué no se pudo verificar un zip real completo desde este
# entorno) con DOS ficheros .atom dentro, tal como puede pasar de verdad
# cuando un mes supera las 500 entradas por fichero (manual de
# OpenPLACSP). Reutiliza las entradas reales ya guardadas como fixtures.

FEED_INICIO = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<feed xmlns="http://www.w3.org/2005/Atom" '
    'xmlns:cbc-place-ext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2" '
    'xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2" '
    'xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2" '
    'xmlns:cac-place-ext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2" '
    'xmlns:at="http://purl.org/atompub/tombstones/1.0">\n'
)


def _entry_cruda(nombre_fixture: str) -> str:
    """La <entry> tal cual, sin el <feed> que la envuelve en el fichero
    de fixture (para poder recombinar varias en un solo .atom sintético)."""
    texto = (FIXTURES / nombre_fixture).read_text(encoding="utf-8")
    inicio = texto.index("<entry>")
    fin = texto.index("</entry>") + len("</entry>")
    return texto[inicio:fin]


def _zip_sintetico() -> bytes:
    atom_1 = FEED_INICIO + _entry_cruda("entrada_adjudicada_con_nif.xml") + "\n</feed>"
    atom_2 = (
        FEED_INICIO
        + _entry_cruda("entrada_ute_sin_nif.xml")
        + "\n"
        + _entry_cruda("entrada_multiples_lotes.xml")
        + "\n</feed>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("licitaciones_parte1.atom", atom_1)
        zf.writestr("licitaciones_parte2.atom", atom_2)
    return buffer.getvalue()


def test_entradas_de_zip_lee_los_dos_atom_del_zip():
    """1 entrada en el primer .atom + 2 en el segundo = 3 <entry> en
    total -- si _entradas_de_zip solo leyera el primer fichero del zip,
    se perderían las 2 del segundo."""
    entries = list(_entradas_de_zip(_zip_sintetico()))
    assert len(entries) == 3


def test_conector_descubrir_filtra_por_cpv_y_provincia():
    """De las 3 <entry> del zip sintético (1 con NIF real y CPV no-
    construcción en Canarias, 1 UTE de construcción en Madrid sin NIF, 1
    de mobiliario con 2 lotes en Canarias): con el filtro por defecto
    (CPV 45, sin filtro de provincia) no debería salir ninguna --
    'entrada_ute_sin_nif' es la única de construcción, y su ganador no
    tiene NIF real (schemeName='OTROS'), así que se descarta en el
    parseo antes de llegar al filtro de CPV."""

    async def _correr(parametros):
        conector = ConectorPLACSP(cliente=None)  # type: ignore[arg-type]

        async def _zip_falso(anyo, mes):
            return _zip_sintetico()

        conector._descargar_zip = _zip_falso  # type: ignore[method-assign]
        return [r async for r in conector.descubrir(parametros, max_coste_eur=0.0)]

    resultados = asyncio.run(_correr({}))
    assert resultados == []

    # sin filtro de CPV (prefijos_cpv=("",) casa con cualquier cosa, ""
    # es prefijo de toda cadena): deben salir los 3 registros con NIF
    # real -- 1 de FRIO-7 (CPV no-construcción) + 2 del lote de mobiliario
    # (los que sí tenían ganador); el de la UTE nunca aparece, ni con este
    # filtro tan permisivo, porque se descarta en el parseo por falta de
    # NIF, antes de llegar a ningún filtro de CPV.
    resultados_todos = asyncio.run(_correr({"prefijos_cpv": ("",)}))
    assert len(resultados_todos) == 3
    assert {r.campos.nif for r in resultados_todos} == {"B35323732", "B35474931", "26885830A"}
