"""Tests de las partes de `radar.agente.planificador` que no llaman a
ninguna API: cálculo de coste por herramienta, construcción del prompt de
sistema, serialización de bloques de respuesta de Anthropic y el
envoltorio `_ejecutar_segura` sobre `ejecutar_herramienta`. El bucle
completo (`planificar`) se prueba de forma manual/integración, igual que
el resto de módulos que hablan con un proveedor de LLM."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from anthropic.types import TextBlock, ToolUseBlock

from radar.agente.interpretacion import FiltrosBusqueda
from radar.agente.planificador import (
    ResultadoPlanificador,
    _bloque_asistente_a_param,
    _coste_de,
    _ejecutar_segura,
    _sistema,
)

# ---------- _coste_de ----------


def test_coste_de_buscar_web_usa_coste_eur_del_resultado():
    assert _coste_de("buscar_web", {"coste_eur": 0.05}) == 0.05


def test_coste_de_descubrir_borme_usa_coste_eur_del_resultado():
    assert _coste_de("descubrir_borme", {"coste_eur": 0.0}) == 0.0


def test_coste_de_herramienta_sin_coste_ignora_el_campo():
    # consultar_bd no gasta presupuesto aunque, por lo que sea, el resultado tuviera esa clave
    assert _coste_de("consultar_bd", {"coste_eur": 99.0}) == 0.0


def test_coste_de_sin_clave_coste_eur_es_cero():
    assert _coste_de("buscar_web", {}) == 0.0


# ---------- _sistema ----------


def test_sistema_incluye_filtros_presupuesto_y_max_rondas():
    filtros = FiltrosBusqueda()
    prompt = _sistema(filtros, 15.5, 8)
    assert "15.5" in prompt
    assert "8" in prompt
    assert '"estados"' in prompt  # filtros.model_dump_json() volcado dentro del prompt


# ---------- _bloque_asistente_a_param ----------


def test_bloque_asistente_texto():
    bloque = TextBlock(type="text", text="hecho")
    assert _bloque_asistente_a_param(bloque) == {"type": "text", "text": "hecho"}


def test_bloque_asistente_tool_use():
    bloque = ToolUseBlock(type="tool_use", id="tu_1", name="buscar_web", input={"consultas": ["x"]})
    assert _bloque_asistente_a_param(bloque) == {"type": "tool_use", "id": "tu_1", "name": "buscar_web", "input": {"consultas": ["x"]}}


# ---------- _ejecutar_segura ----------


@dataclass
class _ContextoFalso:
    conn: object = None
    cliente_http: object = None
    cliente_llm: object = None
    filtros: FiltrosBusqueda = field(default_factory=FiltrosBusqueda)
    telefonos_compartidos: object = None
    presupuesto_restante_eur: float = 5.0


def test_ejecutar_segura_devuelve_resultado_normal():
    r = asyncio.run(_ejecutar_segura("preguntar_usuario", {"pregunta": "¿Zona?"}, _ContextoFalso()))  # type: ignore[arg-type]
    assert r["pregunta"] == "¿Zona?"


def test_ejecutar_segura_convierte_value_error_en_dict_error():
    r = asyncio.run(_ejecutar_segura("no_existe", {}, _ContextoFalso()))  # type: ignore[arg-type]
    assert "error" in r
    assert "desconocida" in r["error"]


def test_ejecutar_segura_argumento_obligatorio_ausente_no_lanza():
    r = asyncio.run(_ejecutar_segura("finalizar_busqueda", {}, _ContextoFalso()))  # type: ignore[arg-type]
    assert "error" in r


# ---------- ResultadoPlanificador (valores por defecto) ----------


def test_resultado_planificador_por_defecto():
    r = ResultadoPlanificador()
    assert r.rondas == []
    assert r.motivo_fin == "max_rondas"
    assert r.pregunta is None
    assert r.coste_gastado_eur == 0.0
    assert r.error is None
