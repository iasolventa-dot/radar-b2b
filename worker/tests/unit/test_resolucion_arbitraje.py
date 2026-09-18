"""Tests de las partes de `radar.resolucion.arbitraje` que no llaman a la
API (construcción del prompt y parseo/validación de la respuesta) — la
llamada de red en sí (`arbitrar`) se prueba de forma manual/integración,
mismo criterio que `test_extraccion_llm.py`."""

import json

import pytest
from pydantic import ValidationError

from radar.resolucion.arbitraje import RespuestaArbitraje, _extraer_json, construir_prompt


def test_construir_prompt_incluye_puntuacion_senales_y_empresas():
    p = construir_prompt(
        0.55,
        ["nombre casi idéntico sin ninguna señal de ubicación en ninguno de los dos registros"],
        {"razon_social": "VIMOINSA VIVIENDAS PREFABRICADAS SL", "nif": None},
        {"razon_social": "VIMOINSA VIVIENDAS PREFABRICADAS SOCIEDAD LIMITADA", "nif": None},
    )
    assert "0.55" in p
    assert "nombre casi idéntico" in p
    assert "VIMOINSA VIVIENDAS PREFABRICADAS SL" in p
    assert "VIMOINSA VIVIENDAS PREFABRICADAS SOCIEDAD LIMITADA" in p
    assert "Responde SOLO con JSON" in p


def test_construir_prompt_sin_senales_ni_puntuacion():
    p = construir_prompt(None, [], {"razon_social": "A"}, {"razon_social": "B"})
    assert "desconocida" in p
    assert "(ninguna)" in p


def test_extraer_json_quita_fences_markdown():
    envuelto = '```json\n{"decision": "misma"}\n```'
    assert json.loads(_extraer_json(envuelto)) == {"decision": "misma"}


def test_respuesta_arbitraje_valida():
    r = RespuestaArbitraje.model_validate(
        {"decision": "misma", "confianza": 0.92, "motivo": "mismo nombre exacto, sin señales de que sean homónimas"}
    )
    assert r.decision == "misma"
    assert r.confianza == 0.92


def test_respuesta_arbitraje_decision_desconocida_lanza():
    with pytest.raises(ValidationError):
        RespuestaArbitraje.model_validate({"decision": "quizas", "confianza": 0.5})


def test_respuesta_arbitraje_decision_obligatoria():
    with pytest.raises(ValidationError):
        RespuestaArbitraje.model_validate({"confianza": 0.5})
