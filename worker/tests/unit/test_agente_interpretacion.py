"""Tests de las partes de `radar.agente.interpretacion` que no llaman a la
API (construcción del prompt y parseo/validación de la respuesta) — igual
que `tests/unit/test_extraccion_llm.py` para el otro módulo con el mismo
patrón de despacho por proveedor."""

import json

import pytest
from pydantic import ValidationError

from radar.agente.interpretacion import (
    FiltrosBusqueda,
    construir_prompt,
    parsear_respuesta,
)


def test_construir_prompt_incluye_peticion_y_contexto():
    p = construir_prompt("constructoras de Sevilla de 10 a 50 empleados", "cliente: EasyProject")
    assert "constructoras de Sevilla de 10 a 50 empleados" in p
    assert "cliente: EasyProject" in p
    assert "Responde SOLO con JSON" in p


def test_construir_prompt_sin_contexto_no_revienta():
    p = construir_prompt("constructoras de Huelva", None)
    assert "constructoras de Huelva" in p
    assert "(sin contexto adicional)" in p


def test_parsear_respuesta_minima_aplica_valores_por_defecto():
    texto = json.dumps(
        {
            "ubicacion": {"tipo": "provincias", "provincias": ["Sevilla"]},
            "sector": {"sector_interno": "construccion", "codigos_cnae": ["41", "43"]},
            "tamano": {"empleados_min": 10, "empleados_max": 50},
            "formas_juridicas": [],
            "incluir_autonomos": False,
            "estados": ["activa", "probablemente_activa"],
            "requisitos": {"web": False, "telefono": False, "email_generico": False},
            "calidad": {"confianza_minima": 0.7, "frescura_max_dias": 180},
            "limite_resultados": None,
            "presupuesto_eur": None,
            "supuestos": ["'Sevilla' interpretado como la provincia, no solo la capital"],
            "preguntas": [],
        }
    )
    filtros = parsear_respuesta(texto)
    assert isinstance(filtros, FiltrosBusqueda)
    assert filtros.ubicacion.provincias == ["Sevilla"]
    assert filtros.tamano.empleados_min == 10
    assert filtros.tamano.empleados_max == 50
    assert filtros.calidad.confianza_minima == 0.7
    assert "'Sevilla' interpretado como la provincia, no solo la capital" in filtros.supuestos


def test_parsear_respuesta_envuelta_en_fences_markdown():
    envuelto = '```json\n{"ubicacion": {"provincias": ["Huelva"]}}\n```'
    filtros = parsear_respuesta(envuelto)
    assert filtros.ubicacion.provincias == ["Huelva"]


def test_parsear_respuesta_json_invalido_lanza():
    with pytest.raises(json.JSONDecodeError):
        parsear_respuesta("esto no es JSON")


def test_parsear_respuesta_estado_desconocido_lanza_validation_error():
    texto = json.dumps({"estados": ["esto_no_existe"]})
    with pytest.raises(ValidationError):
        parsear_respuesta(texto)


def test_filtros_busqueda_valores_por_defecto():
    filtros = FiltrosBusqueda()
    assert filtros.estados == ["activa", "probablemente_activa"]
    assert filtros.incluir_autonomos is False
    assert filtros.calidad.confianza_minima == 0.7
    assert filtros.calidad.frescura_max_dias == 180
