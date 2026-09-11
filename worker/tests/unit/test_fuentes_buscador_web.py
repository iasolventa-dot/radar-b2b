"""Tests de las partes de `radar.fuentes.buscador_web` que no llaman a la
API real (construcción del parámetro de herramienta, parseo de la
respuesta y construcción del `RegistroBruto`, para los dos proveedores) —
la llamada de red en sí (`buscar`) se prueba de forma manual/integración,
igual que `radar.extraccion.llm.extraer_con_llm`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from radar.fuentes.buscador_web import (
    ConectorBuscadorWeb,
    ResultadoBusqueda,
    ResultadoWeb,
    _consultas_de,
    _procesar_respuesta_anthropic,
    _procesar_respuesta_openai,
    _resultado_a_registro_bruto,
    _tool_param_anthropic,
    _tool_param_openai,
)

# --- Fakes con la misma forma que los tipos de los SDK (ver docstrings de
# `_procesar_respuesta_anthropic` / `_procesar_respuesta_openai`) — no
# dependen de `anthropic` ni `openai` para poder testear sin red. ---------


@dataclass
class _FakeResultadoAnthropic:
    url: str
    title: str
    page_age: str | None = None


@dataclass
class _FakeBloqueTexto:
    type: str = "text"
    text: str = "hecho"


@dataclass
class _FakeErrorHerramientaAnthropic:
    error_code: str
    type: str = "web_search_tool_result_error"


@dataclass
class _FakeBloqueResultadoAnthropic:
    content: Any
    type: str = "web_search_tool_result"


@dataclass
class _FakeServerToolUsage:
    web_search_requests: int
    web_fetch_requests: int = 0


@dataclass
class _FakeUsageAnthropic:
    server_tool_use: _FakeServerToolUsage | None = None


@dataclass
class _FakeMensajeAnthropic:
    content: list[Any] = field(default_factory=list)
    usage: _FakeUsageAnthropic | None = None


@dataclass
class _FakeFuenteOpenai:
    url: str
    type: str = "url"


@dataclass
class _FakeAccionBusquedaOpenai:
    sources: list[_FakeFuenteOpenai] | None
    type: str = "search"


@dataclass
class _FakeAccionAbrirPaginaOpenai:
    url: str | None
    type: str = "open_page"


@dataclass
class _FakeLlamadaBusquedaOpenai:
    action: Any
    status: str = "completed"
    type: str = "web_search_call"


@dataclass
class _FakeRespuestaOpenai:
    output: list[Any] = field(default_factory=list)


# --- _tool_param_anthropic -------------------------------------------------


def test_tool_param_anthropic_valores_por_defecto():
    tool = _tool_param_anthropic(dominios_permitidos=None, dominios_bloqueados=None)
    assert tool["type"] == "web_search_20250305"
    assert tool["name"] == "web_search"
    assert tool["max_uses"] == 1
    assert tool["allowed_callers"] == ["direct"]
    assert "allowed_domains" not in tool
    assert "blocked_domains" not in tool


def test_tool_param_anthropic_dominios_permitidos():
    tool = _tool_param_anthropic(dominios_permitidos=["boe.es"], dominios_bloqueados=None)
    assert tool["allowed_domains"] == ["boe.es"]


def test_tool_param_anthropic_dominios_permitidos_y_bloqueados_son_excluyentes():
    with pytest.raises(ValueError):
        _tool_param_anthropic(dominios_permitidos=["boe.es"], dominios_bloqueados=["facebook.com"])


# --- _procesar_respuesta_anthropic -----------------------------------------


def test_procesar_respuesta_anthropic_extrae_urls_y_numero_de_busquedas():
    resultados = [
        _FakeResultadoAnthropic(url="https://www.perezobras.es", title="Pérez Obras SL — Inicio", page_age="2026-01-10"),
        _FakeResultadoAnthropic(url="https://www.perezobras.es/aviso-legal", title="Aviso legal", page_age=None),
    ]
    respuesta = _FakeMensajeAnthropic(
        content=[_FakeBloqueTexto(), _FakeBloqueResultadoAnthropic(content=resultados)],
        usage=_FakeUsageAnthropic(server_tool_use=_FakeServerToolUsage(web_search_requests=1)),
    )
    r = _procesar_respuesta_anthropic(respuesta, "consulta de prueba", max_resultados=5)
    assert r.consulta == "consulta de prueba"
    assert r.numero_busquedas == 1
    assert r.error is None
    assert [x.url for x in r.resultados] == [res.url for res in resultados]
    assert r.resultados[0].titulo == "Pérez Obras SL — Inicio"
    assert r.resultados[0].page_age == "2026-01-10"


def test_procesar_respuesta_anthropic_recorta_a_max_resultados():
    resultados = [_FakeResultadoAnthropic(url=f"https://x{i}.es", title=f"x{i}") for i in range(10)]
    respuesta = _FakeMensajeAnthropic(
        content=[_FakeBloqueResultadoAnthropic(content=resultados)],
        usage=_FakeUsageAnthropic(server_tool_use=_FakeServerToolUsage(web_search_requests=1)),
    )
    r = _procesar_respuesta_anthropic(respuesta, "q", max_resultados=3)
    assert len(r.resultados) == 3


def test_procesar_respuesta_anthropic_captura_error_de_la_herramienta():
    respuesta = _FakeMensajeAnthropic(
        content=[_FakeBloqueResultadoAnthropic(content=_FakeErrorHerramientaAnthropic(error_code="too_many_requests"))],
        usage=_FakeUsageAnthropic(server_tool_use=_FakeServerToolUsage(web_search_requests=0)),
    )
    r = _procesar_respuesta_anthropic(respuesta, "q", max_resultados=5)
    assert r.error == "too_many_requests"
    assert r.resultados == []
    assert r.numero_busquedas == 0


def test_procesar_respuesta_anthropic_sin_bloque_de_busqueda_no_falla():
    respuesta = _FakeMensajeAnthropic(content=[_FakeBloqueTexto()], usage=_FakeUsageAnthropic(server_tool_use=None))
    r = _procesar_respuesta_anthropic(respuesta, "q", max_resultados=5)
    assert r.resultados == []
    assert r.numero_busquedas == 0
    assert r.error is None


def test_procesar_respuesta_anthropic_sin_usage_no_falla():
    respuesta = _FakeMensajeAnthropic(content=[], usage=None)
    r = _procesar_respuesta_anthropic(respuesta, "q", max_resultados=5)
    assert r.numero_busquedas == 0


# --- _tool_param_openai ------------------------------------------------


def test_tool_param_openai_valores_por_defecto():
    tool = _tool_param_openai(dominios_permitidos=None, dominios_bloqueados=None)
    assert tool["type"] == "web_search"
    assert tool["search_context_size"] == "low"
    assert "filters" not in tool


def test_tool_param_openai_dominios_permitidos():
    tool = _tool_param_openai(dominios_permitidos=["boe.es"], dominios_bloqueados=None)
    assert tool["filters"] == {"allowed_domains": ["boe.es"]}


def test_tool_param_openai_no_soporta_dominios_bloqueados():
    with pytest.raises(ValueError):
        _tool_param_openai(dominios_permitidos=None, dominios_bloqueados=["facebook.com"])


# --- _procesar_respuesta_openai -----------------------------------------


def test_procesar_respuesta_openai_extrae_urls_de_las_acciones_de_busqueda():
    respuesta = _FakeRespuestaOpenai(
        output=[
            _FakeLlamadaBusquedaOpenai(
                action=_FakeAccionBusquedaOpenai(
                    sources=[_FakeFuenteOpenai(url="https://www.perezobras.es"), _FakeFuenteOpenai(url="https://www.perezobras.es/aviso-legal")]
                )
            )
        ]
    )
    r = _procesar_respuesta_openai(respuesta, "consulta de prueba", max_resultados=5)
    assert r.consulta == "consulta de prueba"
    assert r.numero_busquedas == 1
    assert [x.url for x in r.resultados] == ["https://www.perezobras.es", "https://www.perezobras.es/aviso-legal"]
    assert all(x.titulo is None for x in r.resultados)  # openai no da título (ver docstring del módulo)


def test_procesar_respuesta_openai_ignora_acciones_open_page_y_find_in_page():
    respuesta = _FakeRespuestaOpenai(
        output=[
            _FakeLlamadaBusquedaOpenai(action=_FakeAccionBusquedaOpenai(sources=[_FakeFuenteOpenai(url="https://x.es")])),
            _FakeLlamadaBusquedaOpenai(action=_FakeAccionAbrirPaginaOpenai(url="https://x.es/pagina-interna")),
        ]
    )
    r = _procesar_respuesta_openai(respuesta, "q", max_resultados=5)
    assert [x.url for x in r.resultados] == ["https://x.es"]
    assert r.numero_busquedas == 2  # las dos llamadas cuentan para el coste, aunque solo una tenga URLs


def test_procesar_respuesta_openai_deduplica_por_url_y_recorta():
    fuentes = [_FakeFuenteOpenai(url="https://x.es"), _FakeFuenteOpenai(url="https://x.es"), _FakeFuenteOpenai(url="https://y.es")]
    respuesta = _FakeRespuestaOpenai(
        output=[_FakeLlamadaBusquedaOpenai(action=_FakeAccionBusquedaOpenai(sources=fuentes))]
    )
    r = _procesar_respuesta_openai(respuesta, "q", max_resultados=1)
    assert [x.url for x in r.resultados] == ["https://x.es"]


def test_procesar_respuesta_openai_solo_cuenta_llamadas_completadas():
    respuesta = _FakeRespuestaOpenai(
        output=[_FakeLlamadaBusquedaOpenai(action=_FakeAccionBusquedaOpenai(sources=[]), status="failed")]
    )
    r = _procesar_respuesta_openai(respuesta, "q", max_resultados=5)
    assert r.numero_busquedas == 0
    assert r.resultados == []


def test_procesar_respuesta_openai_sin_llamadas_no_falla():
    r = _procesar_respuesta_openai(_FakeRespuestaOpenai(output=[]), "q", max_resultados=5)
    assert r.resultados == []
    assert r.numero_busquedas == 0


# --- _resultado_a_registro_bruto -----------------------------------------


def test_resultado_a_registro_bruto_no_afirma_ningun_campo_de_empresa():
    """Doc 04 §5: los snippets no son evidencia — `campos` debe ir vacío
    sea cual sea el resultado, para que nunca se cuele un dato de empresa
    "confirmado" por un buscador."""
    resultado = ResultadoBusqueda(
        consulta="site:perezobras.es aviso legal",
        resultados=[ResultadoWeb(url="https://www.perezobras.es/aviso-legal", titulo="Aviso legal", page_age=None)],
        numero_busquedas=1,
    )
    registro = _resultado_a_registro_bruto(resultado)
    assert registro.fuente == "buscador_web"
    assert registro.campos == type(registro.campos)()  # CamposExtraidos() vacío
    assert registro.payload["consulta"] == "site:perezobras.es aviso legal"
    assert registro.payload["resultados"][0]["url"] == "https://www.perezobras.es/aviso-legal"


def test_resultado_a_registro_bruto_admite_titulo_none_openai():
    resultado = ResultadoBusqueda(
        consulta="q", resultados=[ResultadoWeb(url="https://x.es", titulo=None, page_age=None)], numero_busquedas=1
    )
    registro = _resultado_a_registro_bruto(resultado)
    assert registro.payload["resultados"][0]["titulo"] is None


# --- _consultas_de / ConectorBuscadorWeb.estimar_coste --------------------


def test_consultas_de_admite_lista_o_consulta_unica():
    assert _consultas_de({"consultas": ["a", "b"]}) == ["a", "b"]
    assert _consultas_de({"consulta": "a"}) == ["a"]
    assert _consultas_de({}) == []


def test_estimar_coste_es_proporcional_al_numero_de_consultas():
    conector = ConectorBuscadorWeb()
    assert conector.estimar_coste({"consultas": ["a", "b", "c"]}) == pytest.approx(0.03)
    assert conector.estimar_coste({"consulta": "a"}) == pytest.approx(0.01)
    assert conector.estimar_coste({}) == 0.0
