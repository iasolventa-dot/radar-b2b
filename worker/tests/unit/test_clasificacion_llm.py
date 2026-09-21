"""Tests de las partes de `radar.clasificacion.llm` que no llaman a la API
(construcción del prompt, parseo/validación de la respuesta y el filtro
contra la lista de candidatos) — la llamada de red en sí (`clasificar`) se
prueba de forma manual/integración, mismo criterio que `test_extraccion_llm.py`
y `test_resolucion_arbitraje.py`."""

import json

from radar.clasificacion.candidatos import CandidatoCnae
from radar.clasificacion.llm import (
    RespuestaClasificacionCnae,
    _extraer_json,
    _validar_contra_candidatos,
    clasificar,
    construir_prompt,
)

CANDIDATOS = [
    CandidatoCnae(codigo="4399", descripcion="Otras actividades de construcción especializada n.c.o.p.", similitud=0.9),
    CandidatoCnae(codigo="4120", descripcion="Construcción de edificios", similitud=0.4),
]


def test_construir_prompt_incluye_objeto_social_y_candidatos():
    p = construir_prompt("Reforma y rehabilitación de edificios", CANDIDATOS, "CNAE-2025")
    assert "Reforma y rehabilitación de edificios" in p
    assert "4399 / Otras actividades de construcción especializada n.c.o.p. / similitud 0.90" in p
    assert "CNAE-2025" in p
    assert "Responde SOLO con JSON" in p


def test_construir_prompt_sin_candidatos():
    p = construir_prompt("algo", [], "CNAE-2025")
    assert "(sin candidatos)" in p


def test_extraer_json_quita_fences_markdown():
    envuelto = '```json\n{"cnae_principal": "4399"}\n```'
    assert json.loads(_extraer_json(envuelto)) == {"cnae_principal": "4399"}


def test_respuesta_valida():
    r = RespuestaClasificacionCnae.model_validate(
        {"cnae_principal": "4399", "cnaes_secundarios": [], "sector_interno": "Construcción", "confianza": 0.9, "evidencia": "coincide"}
    )
    assert r.cnae_principal == "4399"


def test_respuesta_confianza_por_defecto():
    r = RespuestaClasificacionCnae.model_validate({})
    assert r.cnae_principal is None
    assert r.confianza == 0.0


def test_validar_contra_candidatos_acepta_codigo_en_la_lista():
    r = RespuestaClasificacionCnae(cnae_principal="4399", cnaes_secundarios=["4120"], confianza=0.9)
    validado = _validar_contra_candidatos(r, CANDIDATOS)
    assert validado.cnae_principal == "4399"
    assert validado.cnaes_secundarios == ["4120"]


def test_validar_contra_candidatos_descarta_codigo_inventado():
    """El modelo no debe poder colar un código fuera de los candidatos --
    aunque el JSON sea válido, si no está en la lista se descarta."""
    r = RespuestaClasificacionCnae(cnae_principal="9999", confianza=0.95, evidencia="me lo invento")
    validado = _validar_contra_candidatos(r, CANDIDATOS)
    assert validado.cnae_principal is None
    assert validado.confianza == 0.0
    assert "descartado" in validado.evidencia


def test_validar_contra_candidatos_filtra_secundarios_invalidos():
    r = RespuestaClasificacionCnae(cnae_principal="4399", cnaes_secundarios=["4120", "0000"], confianza=0.8)
    validado = _validar_contra_candidatos(r, CANDIDATOS)
    assert validado.cnaes_secundarios == ["4120"]


def test_clasificar_sin_candidatos_no_llama_al_llm():
    resultado = clasificar("algo", [], "CNAE-2025")
    assert resultado.respuesta is not None
    assert resultado.respuesta.cnae_principal is None
    assert resultado.respuesta.evidencia == "sin candidatos que considerar"
