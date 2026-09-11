"""Bucle de tool use del planificador (doc 07 §4, `PROMPT_PLANIFICADOR_SISTEMA`
en `radar.agente.prompts`): en cada ronda, el LLM decide qué herramienta de
`radar.agente.herramientas` llamar (o si terminar), nunca escribe en la BD
ni inventa datos de una empresa — eso ya lo garantizan las herramientas.

Proveedor configurable con `settings.proveedor_llm` (mismo patrón que
`radar.extraccion.llm` / `radar.fuentes.buscador_web` / `radar.agente.interpretacion`):

- **openai** (por defecto): Responses API. Cada ronda es una llamada
  `responses.create(..., tools=[...], tool_choice="auto",
  previous_response_id=...)` — no hace falta reenviar el historial
  completo cada vez, solo el `id` de la respuesta anterior. Se leen los
  items `type="function_call"` de `response.output`, se ejecutan y se
  manda la siguiente ronda como `input=[{"type":"function_call_output",...}]`.
- **anthropic**: Messages API, sin equivalente a `previous_response_id` en
  este SDK — el historial completo (`messages`) se reenvía cada ronda,
  igual que en `radar.extraccion.llm._extraer_con_llm_anthropic`. Se leen
  los `ToolUseBlock` de `.content` y se responde con un turno de usuario
  de bloques `tool_result`.

Reglas del bucle (doc 07 §4, "Termina si..."):

- Para en cuanto el LLM llama a `finalizar_busqueda` (fin normal) o a
  `preguntar_usuario` (este primer planificador no es interactivo: no hay
  forma de reanudar con la respuesta del usuario en la misma llamada, así
  que la pregunta también corta el bucle — quien llame a `planificar()`
  decide qué hacer con `ResultadoPlanificador.pregunta`).
- Para también, de forma sintética (sin que el LLM lo pida), si se agota
  el presupuesto o si se alcanza `max_rondas` — nunca deja el bucle sin
  un motivo de cierre.
- Si una ronda no llama a NINGUNA herramienta (el LLM no debería, el
  prompt se lo pide explícitamente, pero los modelos a veces fallan esto)
  se trata como fin implícito con motivo 'rendimientos_decrecientes', para
  no colgar el bucle esperando una llamada que no llega.
- El coste real gastado (`ResultadoPlanificador.coste_gastado_eur`) suma
  el `coste_eur` que devuelve cada herramienta con coste (`buscar_web`,
  `descubrir_borme`) — nunca una estimación — y se resta del presupuesto
  restante antes de la siguiente ronda.

`planificar()` acepta un `on_ronda` opcional, invocado justo después de
cada ronda (antes de decidir si el bucle sigue) — pensado para que quien
llame (p. ej. `radar.api`, tarea #22) pueda persistir el progreso en la
tabla `busquedas` sin esperar a que termine todo el bucle, que puede tardar
varios minutos. Si `on_ronda` lanza, el bucle se detiene con
`motivo_fin='error'` — un fallo guardando progreso es tan grave como un
fallo de la API del LLM, nunca se ignora en silencio.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

import httpx
import psycopg
from anthropic import Anthropic
from anthropic.types import MessageParam, TextBlock, ToolResultBlockParam, ToolUseBlock
from openai import OpenAI
from openai.types.responses import ResponseFunctionToolCall

from radar.agente.herramientas import (
    HERRAMIENTAS,
    ContextoHerramientas,
    a_tool_param_anthropic,
    a_tool_param_openai,
    ejecutar_herramienta,
)
from radar.agente.interpretacion import FiltrosBusqueda
from radar.agente.prompts import PROMPT_PLANIFICADOR_SISTEMA
from radar.config import Settings, get_settings

HERRAMIENTAS_QUE_CONSUMEN_PRESUPUESTO = {"buscar_web", "descubrir_borme"}

OnRonda = Callable[["RondaPlanificador"], Awaitable[None]]


@dataclass
class RondaPlanificador:
    numero: int
    herramienta: str
    argumentos: dict[str, Any]
    resultado: dict[str, Any]


@dataclass
class ResultadoPlanificador:
    rondas: list[RondaPlanificador] = field(default_factory=list)
    motivo_fin: str = "max_rondas"
    resumen: str = ""
    pregunta: dict[str, Any] | None = None
    coste_gastado_eur: float = 0.0
    error: str | None = None


def _coste_de(herramienta: str, resultado: dict[str, Any]) -> float:
    if herramienta not in HERRAMIENTAS_QUE_CONSUMEN_PRESUPUESTO:
        return 0.0
    return float(resultado.get("coste_eur", 0.0) or 0.0)


async def _ejecutar_segura(nombre: str, argumentos: dict[str, Any], contexto: ContextoHerramientas) -> dict[str, Any]:
    """Nunca lanza: un `ValueError` de `ejecutar_herramienta` (herramienta
    desconocida o argumento obligatorio ausente) se convierte en
    `{'error': ...}` para que el LLM lo vea en el `tool_result` y pueda
    corregir la llamada en la siguiente ronda, en vez de tirar el bucle."""
    try:
        return await ejecutar_herramienta(nombre, argumentos, contexto)
    except ValueError as exc:
        return {"error": str(exc)}


def _sistema(filtros: FiltrosBusqueda, presupuesto_eur: float, max_rondas: int) -> str:
    return PROMPT_PLANIFICADOR_SISTEMA.format(
        filtros_json=filtros.model_dump_json(), presupuesto_eur=presupuesto_eur, max_rondas=max_rondas
    )


async def planificar(
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    filtros: FiltrosBusqueda,
    *,
    presupuesto_eur: float,
    max_rondas: int = 10,
    cliente: Any | None = None,
    on_ronda: OnRonda | None = None,
) -> ResultadoPlanificador:
    """Punto de entrada único; despacha según `settings.proveedor_llm` (ver
    docstring del módulo). `cliente`, si se pasa, debe ser del cliente
    nativo del proveedor del planificador (`openai.OpenAI` o
    `anthropic.Anthropic`) — para tests/inyección; en producción se
    construye solo. `on_ronda`: ver docstring del módulo."""
    settings = get_settings()
    if settings.proveedor_llm == "openai":
        return await _planificar_openai(conn, cliente_http, filtros, presupuesto_eur, max_rondas, cliente, settings, on_ronda)
    return await _planificar_anthropic(conn, cliente_http, filtros, presupuesto_eur, max_rondas, cliente, settings, on_ronda)


# --- Proveedor: OpenAI (Responses API) --------------------------------


async def _planificar_openai(
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    filtros: FiltrosBusqueda,
    presupuesto_eur: float,
    max_rondas: int,
    cliente: OpenAI | None,
    settings: Settings,
    on_ronda: OnRonda | None,
) -> ResultadoPlanificador:
    if cliente is None:
        if not settings.openai_api_key:
            return ResultadoPlanificador(error="OPENAI_API_KEY no configurada")
        cliente = OpenAI(api_key=settings.openai_api_key)

    contexto = ContextoHerramientas(conn=conn, cliente_http=cliente_http, filtros=filtros, presupuesto_restante_eur=presupuesto_eur)
    # cast: a_tool_param_openai devuelve dict[str, Any] a propósito (herramientas.py no depende
    # de ningún SDK); el union de TypedDicts que espera `tools` es demasiado específico para que
    # mypy lo acepte sin ayuda — el SDK valida la forma real en tiempo de ejecución igualmente.
    tools = cast(Any, [a_tool_param_openai(h) for h in HERRAMIENTAS])
    resultado_final = ResultadoPlanificador()

    entrada: Any = _sistema(filtros, presupuesto_eur, max_rondas)
    previous_response_id: str | None = None

    for numero_ronda in range(1, max_rondas + 1):
        if contexto.presupuesto_restante_eur <= 0:
            resultado_final.motivo_fin = "presupuesto_agotado"
            break
        try:
            respuesta = cliente.responses.create(
                model=settings.modelo_planificador,
                input=entrada,
                tools=tools,
                tool_choice="auto",
                previous_response_id=previous_response_id,
            )
        except Exception as exc:  # noqa: BLE001 — nunca inventamos progreso si la API falla
            resultado_final.error = str(exc)
            break
        previous_response_id = respuesta.id

        # isinstance (no `getattr(item, "type", None) == "function_call"`) para que mypy narrowee
        # de verdad el Union de items de `respuesta.output` — mismo motivo que en
        # `radar.fuentes.buscador_web._procesar_respuesta_openai`.
        llamadas = [item for item in respuesta.output if isinstance(item, ResponseFunctionToolCall)]
        if not llamadas:
            resultado_final.motivo_fin = "rendimientos_decrecientes"
            resultado_final.resumen = respuesta.output_text or "El planificador terminó sin llamar a finalizar_busqueda."
            break

        salidas: list[dict[str, Any]] = []
        terminar = False
        for llamada in llamadas:
            try:
                argumentos = json.loads(llamada.arguments) if llamada.arguments else {}
            except json.JSONDecodeError as exc:
                argumentos = {}
                resultado_h: dict[str, Any] = {"error": f"argumentos no son JSON válido: {exc}"}
            else:
                resultado_h = await _ejecutar_segura(llamada.name, argumentos, contexto)

            coste = _coste_de(llamada.name, resultado_h)
            contexto.presupuesto_restante_eur -= coste
            resultado_final.coste_gastado_eur += coste
            ronda = RondaPlanificador(numero_ronda, llamada.name, argumentos, resultado_h)
            resultado_final.rondas.append(ronda)
            if on_ronda is not None:
                try:
                    await on_ronda(ronda)
                except Exception as exc:  # noqa: BLE001 — no persistir progreso es tan grave como un fallo de la API
                    resultado_final.error = f"fallo guardando progreso: {exc}"
                    terminar = True
            salidas.append(
                {"type": "function_call_output", "call_id": llamada.call_id, "output": json.dumps(resultado_h, ensure_ascii=False, default=str)}
            )
            if llamada.name == "finalizar_busqueda":
                resultado_final.motivo_fin = resultado_h.get("motivo", "cobertura_alcanzada")
                resultado_final.resumen = resultado_h.get("resumen", "")
                terminar = True
            elif llamada.name == "preguntar_usuario":
                resultado_final.pregunta = resultado_h
                terminar = True

        if terminar:
            break
        entrada = salidas

    resultado_final.coste_gastado_eur = round(resultado_final.coste_gastado_eur, 4)
    return resultado_final


# --- Proveedor: Anthropic (Messages API) -------------------------------


def _bloque_asistente_a_param(bloque: Any) -> dict[str, Any]:
    """Solo texto y `tool_use` — es lo único que puede traer una respuesta
    de este bucle (sin pensamiento extendido ni otras herramientas nativas
    activadas). Cualquier otro bloque se ignora al reenviarlo (no aporta
    nada a la siguiente ronda)."""
    if isinstance(bloque, ToolUseBlock):
        return {"type": "tool_use", "id": bloque.id, "name": bloque.name, "input": bloque.input}
    if isinstance(bloque, TextBlock):
        return {"type": "text", "text": bloque.text}
    return {"type": "text", "text": ""}


async def _planificar_anthropic(
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    filtros: FiltrosBusqueda,
    presupuesto_eur: float,
    max_rondas: int,
    cliente: Anthropic | None,
    settings: Settings,
    on_ronda: OnRonda | None,
) -> ResultadoPlanificador:
    if cliente is None:
        if not settings.anthropic_api_key:
            return ResultadoPlanificador(error="ANTHROPIC_API_KEY no configurada")
        cliente = Anthropic(api_key=settings.anthropic_api_key)

    contexto = ContextoHerramientas(conn=conn, cliente_http=cliente_http, filtros=filtros, presupuesto_restante_eur=presupuesto_eur)
    tools = cast(Any, [a_tool_param_anthropic(h) for h in HERRAMIENTAS])  # ver comentario de `_planificar_openai`
    resultado_final = ResultadoPlanificador()

    sistema = _sistema(filtros, presupuesto_eur, max_rondas)
    mensajes: list[MessageParam] = [{"role": "user", "content": "Empieza la búsqueda."}]

    for numero_ronda in range(1, max_rondas + 1):
        if contexto.presupuesto_restante_eur <= 0:
            resultado_final.motivo_fin = "presupuesto_agotado"
            break
        try:
            respuesta = cliente.messages.create(
                model=settings.modelo_planificador, max_tokens=2048, system=sistema, messages=mensajes, tools=tools
            )
        except Exception as exc:  # noqa: BLE001 — nunca inventamos progreso si la API falla
            resultado_final.error = str(exc)
            break

        contenido_asistente = cast(Any, [_bloque_asistente_a_param(b) for b in respuesta.content])
        mensajes.append({"role": "assistant", "content": contenido_asistente})
        llamadas = [b for b in respuesta.content if isinstance(b, ToolUseBlock)]
        if not llamadas:
            texto = "".join(b.text for b in respuesta.content if isinstance(b, TextBlock))
            resultado_final.motivo_fin = "rendimientos_decrecientes"
            resultado_final.resumen = texto or "El planificador terminó sin llamar a finalizar_busqueda."
            break

        resultados_tool: list[ToolResultBlockParam] = []
        terminar = False
        for llamada in llamadas:
            resultado_h = await _ejecutar_segura(llamada.name, llamada.input, contexto)
            coste = _coste_de(llamada.name, resultado_h)
            contexto.presupuesto_restante_eur -= coste
            resultado_final.coste_gastado_eur += coste
            ronda = RondaPlanificador(numero_ronda, llamada.name, dict(llamada.input), resultado_h)
            resultado_final.rondas.append(ronda)
            if on_ronda is not None:
                try:
                    await on_ronda(ronda)
                except Exception as exc:  # noqa: BLE001 — no persistir progreso es tan grave como un fallo de la API
                    resultado_final.error = f"fallo guardando progreso: {exc}"
                    terminar = True
            resultados_tool.append(
                {"type": "tool_result", "tool_use_id": llamada.id, "content": json.dumps(resultado_h, ensure_ascii=False, default=str)}
            )
            if llamada.name == "finalizar_busqueda":
                resultado_final.motivo_fin = resultado_h.get("motivo", "cobertura_alcanzada")
                resultado_final.resumen = resultado_h.get("resumen", "")
                terminar = True
            elif llamada.name == "preguntar_usuario":
                resultado_final.pregunta = resultado_h
                terminar = True

        mensajes.append({"role": "user", "content": resultados_tool})
        if terminar:
            break

    resultado_final.coste_gastado_eur = round(resultado_final.coste_gastado_eur, 4)
    return resultado_final
