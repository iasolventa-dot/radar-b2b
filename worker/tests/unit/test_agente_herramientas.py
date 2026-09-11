"""Tests de las partes de `radar.agente.herramientas` que no tocan la BD ni
la red: construcción del SQL de filtros, coincidencia de sector, esquemas
de herramientas y el despacho de `ejecutar_herramienta` (con dobles falsos
para las funciones con efectos secundarios). `consultar_bd`,
`descubrir_borme` y `buscar_web` en sí se prueban de forma manual/
integración, igual que el resto del orquestador (ver docstring del
módulo)."""

from __future__ import annotations

import asyncio

import pytest

from radar.agente.herramientas import (
    HERRAMIENTAS,
    _coincide_sector,
    a_tool_param_anthropic,
    a_tool_param_openai,
    construir_where_empresas,
    ejecutar_herramienta,
    finalizar_busqueda,
    preguntar_usuario,
)
from radar.agente.interpretacion import FiltrosBusqueda, SectorFiltro, TamanoFiltro, UbicacionFiltro

# ---------- construir_where_empresas ----------


def test_where_por_defecto_excluye_fusionadas_y_autonomos():
    sql, params = construir_where_empresas(FiltrosBusqueda())
    assert "e.fusionada_en is null" in sql
    assert "e.es_persona_fisica = false" in sql
    assert "estado" in sql
    assert params  # al menos el array de estados por defecto


def test_where_incluir_autonomos_no_filtra_persona_fisica():
    sql, _ = construir_where_empresas(FiltrosBusqueda(incluir_autonomos=True))
    assert "es_persona_fisica" not in sql


def test_where_cnae_y_tamano():
    filtros = FiltrosBusqueda(
        sector=SectorFiltro(codigos_cnae=["41", "43"]),
        tamano=TamanoFiltro(empleados_min=10, empleados_max=50),
    )
    sql, params = construir_where_empresas(filtros)
    assert "cnae_principal = any" in sql
    assert "empleados_max >= %s" in sql
    assert "empleados_min <= %s" in sql
    assert ["41", "43"] in params
    assert 10 in params
    assert 50 in params


def test_where_provincia_prevalece_sobre_municipio():
    filtros = FiltrosBusqueda(ubicacion=UbicacionFiltro(provincias=["Sevilla"], municipios=["Écija"]))
    sql, params = construir_where_empresas(filtros)
    assert "s.provincia = any" in sql
    assert "s.municipio_nombre" not in sql
    assert ["Sevilla"] in params


def test_where_sin_provincia_usa_municipio():
    filtros = FiltrosBusqueda(ubicacion=UbicacionFiltro(municipios=["Écija", "Osuna"]))
    sql, params = construir_where_empresas(filtros)
    assert "s.municipio_nombre = any" in sql
    assert ["Écija", "Osuna"] in params


# ---------- _coincide_sector ----------


def test_coincide_sector_sin_palabras_clave_acepta_todo():
    assert _coincide_sector("cualquier cosa", "Cualquier SL", []) is True


def test_coincide_sector_busca_en_objeto_y_nombre_sin_tildes():
    assert _coincide_sector("Construcción y reforma de edificios", None, ["construccion"]) is True
    assert _coincide_sector(None, "Reformas Pérez SL", ["reformas"]) is True


def test_coincide_sector_no_coincide():
    assert _coincide_sector("Venta al por menor de ropa", "Modas García SL", ["construccion", "obras"]) is False


# ---------- esquemas de herramientas ----------


def test_herramientas_tiene_las_cinco_implementadas():
    nombres = {h.nombre for h in HERRAMIENTAS}
    assert nombres == {"consultar_bd", "descubrir_borme", "buscar_web", "preguntar_usuario", "finalizar_busqueda"}


def test_a_tool_param_openai_forma_correcta():
    h = next(h for h in HERRAMIENTAS if h.nombre == "buscar_web")
    tool = a_tool_param_openai(h)
    assert tool["type"] == "function"
    assert tool["name"] == "buscar_web"
    assert tool["parameters"] is h.parametros


def test_a_tool_param_anthropic_forma_correcta():
    h = next(h for h in HERRAMIENTAS if h.nombre == "buscar_web")
    tool = a_tool_param_anthropic(h)
    assert tool["name"] == "buscar_web"
    assert tool["input_schema"] is h.parametros


# ---------- preguntar_usuario / finalizar_busqueda ----------


def test_preguntar_usuario_sin_opciones():
    assert preguntar_usuario("¿Incluyo autónomos?") == {"pregunta": "¿Incluyo autónomos?", "opciones": []}


def test_finalizar_busqueda():
    r = finalizar_busqueda("presupuesto_agotado", "Se gastaron los 20€ del tope")
    assert r == {"motivo": "presupuesto_agotado", "resumen": "Se gastaron los 20€ del tope"}


# ---------- ejecutar_herramienta (dispatcher) ----------
# Funciones sync que envuelven `asyncio.run(...)` en vez de `pytest.mark.asyncio`:
# el proyecto no tiene pytest-asyncio como dependencia (el resto del código
# async se prueba de forma manual/integración, ver docstring del módulo) y
# estas rutas del dispatcher no necesitan un event loop real.


class _ContextoFalso:
    """Doble mínimo de `ContextoHerramientas` — no necesita `conn` real
    porque solo se prueban las rutas que no la tocan (preguntar_usuario,
    finalizar_busqueda, validación de argumentos)."""

    def __init__(self):
        self.conn = None
        self.cliente_http = None
        self.cliente_llm = None
        self.filtros = FiltrosBusqueda()
        self.telefonos_compartidos = None
        self.presupuesto_restante_eur = 5.0


def test_ejecutar_herramienta_preguntar_usuario():
    r = asyncio.run(ejecutar_herramienta("preguntar_usuario", {"pregunta": "¿Zona?"}, _ContextoFalso()))  # type: ignore[arg-type]
    assert r["pregunta"] == "¿Zona?"


def test_ejecutar_herramienta_finalizar_busqueda_sin_resumen():
    r = asyncio.run(ejecutar_herramienta("finalizar_busqueda", {"motivo": "max_rondas"}, _ContextoFalso()))  # type: ignore[arg-type]
    assert r == {"motivo": "max_rondas", "resumen": ""}


def test_ejecutar_herramienta_desconocida_lanza():
    with pytest.raises(ValueError, match="desconocida"):
        asyncio.run(ejecutar_herramienta("no_existe", {}, _ContextoFalso()))  # type: ignore[arg-type]


def test_ejecutar_herramienta_buscar_web_sin_consultas_lanza():
    with pytest.raises(ValueError, match="consultas"):
        asyncio.run(ejecutar_herramienta("buscar_web", {"max_coste_eur": 1.0}, _ContextoFalso()))  # type: ignore[arg-type]


def test_ejecutar_herramienta_descubrir_borme_sin_provincia_lanza():
    with pytest.raises(ValueError, match="provincia_titulo"):
        asyncio.run(ejecutar_herramienta("descubrir_borme", {}, _ContextoFalso()))  # type: ignore[arg-type]
