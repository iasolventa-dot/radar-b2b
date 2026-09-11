"""Tests de las partes de `radar.extraccion.llm` que no llaman a la API
(construcción del prompt y parseo/validación de la respuesta) — la llamada
de red en sí (`extraer_con_llm`) se prueba de forma manual/integración,
igual que el resto de módulos que hablan con un servicio externo."""

import json

import pytest
from pydantic import ValidationError

from radar.extraccion.llm import (
    RespuestaExtraccionLLM,
    _extraer_json,
    construir_prompt,
    parsear_respuesta,
)
from radar.extraccion.reglas import DatosLegalesExtraidos


def test_construir_prompt_incluye_texto_dominio_y_pistas():
    reglas = DatosLegalesExtraidos(razones_sociales=["Construcciones Pérez SL"])
    p = construir_prompt("texto del aviso legal", "perezobras.es", reglas)
    assert "texto del aviso legal" in p
    assert "perezobras.es" in p
    assert "Construcciones Pérez SL" in p
    assert "Responde SOLO con JSON" in p


def test_construir_prompt_recorta_texto_largo():
    reglas = DatosLegalesExtraidos()
    p = construir_prompt("x" * 20_000, None, reglas)
    assert "x" * 12_000 in p
    assert "x" * 12_001 not in p


def test_extraer_json_quita_fences_markdown():
    envuelto = '```json\n{"a": 1}\n```'
    assert json.loads(_extraer_json(envuelto)) == {"a": 1}


def test_extraer_json_deja_json_plano_intacto():
    assert _extraer_json('{"a": 1}') == '{"a": 1}'


def test_parsear_respuesta_valida():
    texto = json.dumps(
        {
            "titular": {"razon_social": "Construcciones Pérez SL", "nif": "B41123456", "telefonos": [], "emails": []},
            "otras_empresas_mencionadas": [{"nombre": "Agencia Digital", "relacion": "agencia_web"}],
            "confianza": 0.8,
            "notas": "NIF claramente asociado al titular en el aviso legal",
        }
    )
    r = parsear_respuesta(texto)
    assert isinstance(r, RespuestaExtraccionLLM)
    assert r.titular.razon_social == "Construcciones Pérez SL"
    assert r.otras_empresas_mencionadas[0].relacion == "agencia_web"


def test_parsear_respuesta_json_invalido_lanza():
    with pytest.raises(json.JSONDecodeError):
        parsear_respuesta("esto no es json")


def test_parsear_respuesta_esquema_invalido_lanza():
    # falta "titular", que es obligatorio
    with pytest.raises(ValidationError):
        parsear_respuesta(json.dumps({"confianza": 0.5}))


def test_parsear_respuesta_relacion_desconocida_usa_valor_no_reconocido():
    with pytest.raises(ValidationError):
        parsear_respuesta(
            json.dumps(
                {
                    "titular": {"telefonos": [], "emails": []},
                    "otras_empresas_mencionadas": [{"nombre": "X", "relacion": "socio_fundador"}],
                }
            )
        )
