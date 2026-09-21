"""Tests de `radar.fuentes.osm` -- fixtures reales (respuesta de Overpass del
2026-09-21 para Sevilla capital), sin red."""

import json
from pathlib import Path

import pytest

from radar.fuentes.osm import (
    OverpassError,
    construir_consulta,
    elemento_a_registro,
    parsear_respuesta,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "osm"


def _elementos() -> list[dict]:
    return json.loads((FIXTURES / "sevilla_construccion.json").read_text(encoding="utf-8"))["elements"]


def test_elemento_sin_nombre_no_es_candidato():
    sin_nombre = [e for e in _elementos() if not e["tags"].get("name")]
    assert sin_nombre, "el fixture debe incluir un elemento sin nombre"
    assert elemento_a_registro(sin_nombre[0]) is None


def test_registro_usa_nombre_comercial_y_nunca_inventa_razon_social():
    registros = [r for r in map(elemento_a_registro, _elementos()) if r]
    assert len(registros) == 12
    for r in registros:
        assert r.fuente == "osm"
        assert r.campos.nombre_comercial
        assert r.campos.razon_social is None
        assert r.campos.nif is None
        assert r.url and r.url.startswith("https://www.openstreetmap.org/")
        assert r.id_externo and "/" in r.id_externo


def test_direccion_telefono_y_web_se_mapean():
    el = {
        "type": "node", "id": 7, "lat": 37.39, "lon": -5.99,
        "tags": {
            "name": "WUD - Taller", "craft": "carpenter", "addr:street": "Calle Aceituno",
            "addr:housenumber": "6", "addr:postcode": "41003", "addr:city": "Sevilla",
            "phone": "+34 657169404; +34 955000000", "website": "https://www.isabellepradas.com/",
            "email": "info@isabellepradas.com",
        },
    }
    r = elemento_a_registro(el)
    assert r is not None
    assert r.campos.domicilio == "Calle Aceituno 6"
    assert r.campos.codigo_postal == "41003"
    assert r.campos.telefonos == ["+34 657169404", "+34 955000000"]
    assert r.campos.web == "https://www.isabellepradas.com/"
    assert (r.campos.lat, r.campos.lon) == (37.39, -5.99)


def test_coordenadas_de_way_vienen_de_center():
    r = elemento_a_registro({"type": "way", "id": 9, "center": {"lat": 1.5, "lon": 2.5}, "tags": {"name": "X Obras"}})
    assert r is not None and (r.campos.lat, r.campos.lon) == (1.5, 2.5)


def test_respuesta_html_de_rate_limit_es_error_no_cero_resultados():
    texto = (FIXTURES / "rate_limited.html").read_text(encoding="utf-8")
    with pytest.raises(OverpassError, match="rate_limited"):
        parsear_respuesta(texto)


def test_respuesta_valida_vacia_es_lista_vacia():
    assert parsear_respuesta('{"version":0.6,"elements":[]}') == []


def test_consulta_rechaza_codigo_ine_no_numerico():
    with pytest.raises(ValueError):
        construir_consulta(['41004"];out;//'])


def test_consulta_ignora_palabras_clave_peligrosas():
    q = construir_consulta(["41004"], palabras_clave=['a"];out;', "fontanería"])
    assert 'a"];out;' not in q
    assert "fontanería" in q


def test_consulta_construccion_incluye_oficios_y_area_por_ine():
    q = construir_consulta(["41004", "41091"])
    assert '"ine:municipio"="41004"' in q and '"ine:municipio"="41091"' in q
    assert "construction_company" in q and "plumber" in q
    assert "out center tags" in q
