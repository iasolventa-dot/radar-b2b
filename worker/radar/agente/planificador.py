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
  restante antes de la siguiente ronda. Desde 2026-09-21 también suma el
  coste de tokens del propio LLM planificador (`radar.coste_llm`, a partir
  de `respuesta.usage`, gratis en cada llamada) -- antes NO se descontaba
  del presupuesto ni se reflejaba en `coste_gastado_eur`/`busquedas.coste_eur`
  en absoluto (doc "Coste de tokens del LLM no se resta del presupuesto"),
  así que el coste mostrado en el panel siempre se quedaba corto frente al
  gasto real de OpenAI/Anthropic.

`planificar()` acepta un `on_ronda` opcional, invocado justo después de
cada ronda (antes de decidir si el bucle sigue) — pensado para que quien
llame (p. ej. `radar.api`, tarea #22) pueda persistir el progreso en la
tabla `busquedas` sin esperar a que termine todo el bucle, que puede tardar
varios minutos. Si `on_ronda` lanza, el bucle se detiene con
`motivo_fin='error'` — un fallo guardando progreso es tan grave como un
fallo de la API del LLM, nunca se ignora en silencio.

También acepta un `debe_cancelar` opcional, comprobado justo después de
`on_ronda` en cada ronda — si devuelve `True`, el bucle termina con
`motivo_fin='cancelada_por_usuario'` (`radar.api.estado.estado_final_de`
lo traduce a `busquedas.estado = 'cancelada'`, migración
202609141400). Es cooperativo, no preventivo: solo se comprueba ENTRE
rondas, así que no puede interrumpir una llamada al LLM o a una
herramienta (`descubrir_borme`, `buscar_web`) que ya esté en curso — el
efecto real es "para en la primera ronda que pueda después de pedirlo",
no instantáneo. Mismo criterio que `on_ronda` si falla comprobándolo: se
trata como error, nunca se ignora en silencio.
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
    ContextoHerramientas,
    a_tool_param_anthropic,
    a_tool_param_openai,
    ejecutar_herramienta,
    herramientas_activas,
)
from radar.agente.interpretacion import FiltrosBusqueda
from radar.agente.prompts import PROMPT_PLANIFICADOR_SISTEMA
from radar.config import Settings, get_settings
from radar.coste_llm import calcular_coste_eur

# Herramienta ficticia (nunca la llama el LLM, la genera el propio bucle)
# para registrar el coste de tokens de cada llamada al planificador como
# una "ronda" más -- ver comentario en `_planificar_openai`/`_planificar_anthropic`.
PLANIFICADOR_LLM = "planificador_llm"

HERRAMIENTAS_QUE_CONSUMEN_PRESUPUESTO = {
    "buscar_web", "descubrir_borme", "descubrir_places", "enriquecer_con_apify",
    "descubrir_google_search", "descubrir_apify_maps", "enriquecer_con_linkedin", "enriquecer_con_facebook",
    "completar_contacto", PLANIFICADOR_LLM,
}

OnRonda = Callable[["RondaPlanificador"], Awaitable[None]]
DebeCancelar = Callable[[], Awaitable[bool]]


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


def _sistema(filtros: FiltrosBusqueda, presupuesto_eur: float, max_rondas: int, contexto_previo: str = "") -> str:
    base = PROMPT_PLANIFICADOR_SISTEMA.format(
        filtros_json=filtros.model_dump_json(), presupuesto_eur=round(presupuesto_eur, 4), max_rondas=max_rondas
    )
    return f"{base}\n\n{contexto_previo}" if contexto_previo else base


async def _bucle_llm(
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    filtros: FiltrosBusqueda,
    *,
    presupuesto_eur: float,
    max_rondas: int = 10,
    cliente: Any | None = None,
    on_ronda: OnRonda | None = None,
    debe_cancelar: DebeCancelar | None = None,
    busqueda_id: str | None = None,
    usar_places: bool = False,
    apify_actores: frozenset[str] | set[str] = frozenset(),
    paso_inicial: int = 0,
    contexto_previo: str = "",
) -> ResultadoPlanificador:
    """Bucle del LLM; despacha según `settings.proveedor_llm` (ver
    docstring del módulo). `cliente`, si se pasa, debe ser del cliente
    nativo del proveedor del planificador (`openai.OpenAI` o
    `anthropic.Anthropic`) — para tests/inyección; en producción se
    construye solo. `on_ronda`: ver docstring del módulo. `debe_cancelar`,
    si se pasa, se comprueba justo después de cada `on_ronda` — si
    devuelve `True`, el bucle termina con
    `motivo_fin="cancelada_por_usuario"` (que `radar.api.estado.estado_final_de`
    traduce a `busquedas.estado = 'cancelada'`). No puede interrumpir una
    llamada al LLM o a una herramienta que ya esté en curso — solo actúa
    entre rondas, igual que el propio `on_ronda`. `busqueda_id`: se
    pasa tal cual a `ContextoHerramientas` — permite a `descubrir_borme`/
    `buscar_web` enlazar cada empresa encontrada con esta búsqueda en
    `busqueda_resultados` (doc 03b); sin él (tests, uso suelto) las
    herramientas simplemente no enlazan nada."""
    settings = get_settings()
    if settings.proveedor_llm == "openai":
        return await _planificar_openai(
            conn, cliente_http, filtros, presupuesto_eur, max_rondas, cliente, settings, on_ronda, debe_cancelar, busqueda_id,
            usar_places, apify_actores, paso_inicial, contexto_previo,
        )
    return await _planificar_anthropic(
        conn, cliente_http, filtros, presupuesto_eur, max_rondas, cliente, settings, on_ronda, debe_cancelar, busqueda_id,
        usar_places, apify_actores, paso_inicial, contexto_previo,
    )


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
    debe_cancelar: DebeCancelar | None = None,
    busqueda_id: str | None = None,
    usar_places: bool = False,
    apify_actores: frozenset[str] | set[str] = frozenset(),
    paso_inicial: int = 0,
    contexto_previo: str = "",
) -> ResultadoPlanificador:
    if cliente is None:
        if not settings.openai_api_key:
            return ResultadoPlanificador(error="OPENAI_API_KEY no configurada")
        cliente = OpenAI(api_key=settings.openai_api_key)

    contexto = ContextoHerramientas(
        conn=conn, cliente_http=cliente_http, filtros=filtros, presupuesto_restante_eur=presupuesto_eur, busqueda_id=busqueda_id,
        usar_places=usar_places, apify_actores=frozenset(apify_actores),
    )
    # cast: a_tool_param_openai devuelve dict[str, Any] a propósito (herramientas.py no depende
    # de ningún SDK); el union de TypedDicts que espera `tools` es demasiado específico para que
    # mypy lo acepte sin ayuda — el SDK valida la forma real en tiempo de ejecución igualmente.
    tools = cast(Any, [a_tool_param_openai(h) for h in herramientas_activas(conn, usar_places=usar_places, apify_actores=apify_actores)])
    resultado_final = ResultadoPlanificador()
    # Contador de PASOS (una llamada a una herramienta), no de vueltas al LLM
    # ("rondas" en el sentido de max_rondas/numero_ronda abajo). Un mismo turno
    # del LLM puede pedir varias herramientas a la vez (tool_choice="auto" no
    # lo impide) -- usar numero_ronda como numero de RondaPlanificador hacía
    # que dos llamadas del mismo turno compartieran número, y React (la key
    # del <li> en progreso-busqueda.tsx) las trataba como el mismo elemento.
    contador_pasos = paso_inicial

    entrada: Any = _sistema(filtros, presupuesto_eur, max_rondas, contexto_previo)
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

        # Coste real del propio LLM (2026-09-21): `respuesta.usage` viene
        # gratis en cada respuesta y antes no se leía nunca -- el coste
        # mostrado en el panel solo incluía buscar_web/descubrir_borme, no
        # el planificador que decide qué llamar. Se registra como una
        # "ronda" más (herramienta ficticia `PLANIFICADOR_LLM`) para
        # reaprovechar toda la persistencia/agregación que ya existe por
        # ronda, en vez de tocar bd_busquedas.py.
        if respuesta.usage is not None:
            coste_llm = calcular_coste_eur(
                settings.modelo_planificador, respuesta.usage.input_tokens, respuesta.usage.output_tokens
            )
            contexto.presupuesto_restante_eur -= coste_llm
            resultado_final.coste_gastado_eur += coste_llm
            ronda_llm = RondaPlanificador(
                contador_pasos := contador_pasos + 1,
                PLANIFICADOR_LLM,
                {},
                {
                    "modelo": settings.modelo_planificador,
                    "tokens_entrada": respuesta.usage.input_tokens,
                    "tokens_salida": respuesta.usage.output_tokens,
                    "coste_eur": round(coste_llm, 6),
                },
            )
            resultado_final.rondas.append(ronda_llm)
            if on_ronda is not None:
                try:
                    await on_ronda(ronda_llm)
                except Exception as exc:  # noqa: BLE001 — mismo criterio que el resto de rondas
                    resultado_final.error = f"fallo guardando progreso: {exc}"
                    break

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
            ronda = RondaPlanificador(contador_pasos := contador_pasos + 1, llamada.name, argumentos, resultado_h)
            resultado_final.rondas.append(ronda)
            if on_ronda is not None:
                try:
                    await on_ronda(ronda)
                except Exception as exc:  # noqa: BLE001 — no persistir progreso es tan grave como un fallo de la API
                    resultado_final.error = f"fallo guardando progreso: {exc}"
                    terminar = True
            if debe_cancelar is not None and not terminar:
                try:
                    cancelar = await debe_cancelar()
                except Exception as exc:  # noqa: BLE001 — igual que on_ronda: no se ignora en silencio
                    resultado_final.error = f"fallo comprobando cancelación: {exc}"
                    terminar = True
                else:
                    if cancelar:
                        resultado_final.motivo_fin = "cancelada_por_usuario"
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
    debe_cancelar: DebeCancelar | None = None,
    busqueda_id: str | None = None,
    usar_places: bool = False,
    apify_actores: frozenset[str] | set[str] = frozenset(),
    paso_inicial: int = 0,
    contexto_previo: str = "",
) -> ResultadoPlanificador:
    if cliente is None:
        if not settings.anthropic_api_key:
            return ResultadoPlanificador(error="ANTHROPIC_API_KEY no configurada")
        cliente = Anthropic(api_key=settings.anthropic_api_key)

    contexto = ContextoHerramientas(
        conn=conn, cliente_http=cliente_http, filtros=filtros, presupuesto_restante_eur=presupuesto_eur, busqueda_id=busqueda_id,
        usar_places=usar_places, apify_actores=frozenset(apify_actores),
    )
    tools = cast(Any, [a_tool_param_anthropic(h) for h in herramientas_activas(conn, usar_places=usar_places, apify_actores=apify_actores)])  # ver comentario de `_planificar_openai`
    resultado_final = ResultadoPlanificador()
    contador_pasos = paso_inicial  # ver comentario de `_planificar_openai` -- mismo motivo, mismo arreglo

    sistema = _sistema(filtros, presupuesto_eur, max_rondas, contexto_previo)
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

        # Coste real del propio LLM -- ver comentario equivalente en
        # `_planificar_openai`, mismo criterio, mismo `usage` gratis en la
        # respuesta (`input_tokens`/`output_tokens` también en Anthropic).
        if respuesta.usage is not None:
            coste_llm = calcular_coste_eur(
                settings.modelo_planificador, respuesta.usage.input_tokens, respuesta.usage.output_tokens
            )
            contexto.presupuesto_restante_eur -= coste_llm
            resultado_final.coste_gastado_eur += coste_llm
            ronda_llm = RondaPlanificador(
                contador_pasos := contador_pasos + 1,
                PLANIFICADOR_LLM,
                {},
                {
                    "modelo": settings.modelo_planificador,
                    "tokens_entrada": respuesta.usage.input_tokens,
                    "tokens_salida": respuesta.usage.output_tokens,
                    "coste_eur": round(coste_llm, 6),
                },
            )
            resultado_final.rondas.append(ronda_llm)
            if on_ronda is not None:
                try:
                    await on_ronda(ronda_llm)
                except Exception as exc:  # noqa: BLE001 — mismo criterio que el resto de rondas
                    resultado_final.error = f"fallo guardando progreso: {exc}"
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
            ronda = RondaPlanificador(contador_pasos := contador_pasos + 1, llamada.name, dict(llamada.input), resultado_h)
            resultado_final.rondas.append(ronda)
            if on_ronda is not None:
                try:
                    await on_ronda(ronda)
                except Exception as exc:  # noqa: BLE001 — no persistir progreso es tan grave como un fallo de la API
                    resultado_final.error = f"fallo guardando progreso: {exc}"
                    terminar = True
            if debe_cancelar is not None and not terminar:
                try:
                    cancelar = await debe_cancelar()
                except Exception as exc:  # noqa: BLE001 — igual que on_ronda: no se ignora en silencio
                    resultado_final.error = f"fallo comprobando cancelación: {exc}"
                    terminar = True
                else:
                    if cancelar:
                        resultado_final.motivo_fin = "cancelada_por_usuario"
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


# --- Orquestación en fases (2026-09-23) ---------------------------------


def _resumen_fase_previa(rondas: list[RondaPlanificador]) -> str:
    if not rondas:
        return ""
    lineas = [
        f"- {r.herramienta}: nuevas={r.resultado.get('nueva_empresa', 0)}, vinculadas={r.resultado.get('vinculado', 0)}, "
        f"coste={r.resultado.get('coste_eur', 0)} EUR" + (f", error={r.resultado['error']}" if r.resultado.get("error") else "")
        for r in rondas
    ]
    return (
        "YA EJECUTADO AUTOMÁTICAMENTE antes de ti (fuentes de pago que el usuario marcó; no las repitas con los mismos "
        "argumentos):\n" + "\n".join(lineas)
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
    debe_cancelar: DebeCancelar | None = None,
    busqueda_id: str | None = None,
    usar_places: bool = False,
    apify_actores: frozenset[str] | set[str] = frozenset(),
) -> ResultadoPlanificador:
    """Punto de entrada único. Tres fases (ver `radar.agente.fases`):
    1) fuentes de pago marcadas por el usuario, siempre; 2) el bucle del LLM
    (`_bucle_llm`) con el presupuesto restante; 3) `completar_contacto` sobre
    todo lo encontrado. `on_ronda`/`debe_cancelar`: ver docstring del módulo
    -- se aplican igual a las rondas de las fases 1 y 3."""
    from radar.agente.completar_contacto import completar_contacto
    from radar.agente.fases import ejecutar_con_tope, planes_fuentes_marcadas

    actores = frozenset(apify_actores)
    contexto = ContextoHerramientas(
        conn=conn, cliente_http=cliente_http, filtros=filtros, presupuesto_restante_eur=presupuesto_eur,
        busqueda_id=busqueda_id, usar_places=usar_places, apify_actores=actores,
    )
    total = ResultadoPlanificador()

    async def registrar(nombre: str, argumentos: dict[str, Any], resultado: dict[str, Any]) -> bool:
        """Añade la ronda, descuenta su coste y avisa. `True` = hay que parar."""
        coste = _coste_de(nombre, resultado)
        contexto.presupuesto_restante_eur -= coste
        total.coste_gastado_eur += coste
        ronda = RondaPlanificador(len(total.rondas) + 1, nombre, argumentos, resultado)
        total.rondas.append(ronda)
        if on_ronda is not None:
            try:
                await on_ronda(ronda)
            except Exception as exc:  # noqa: BLE001
                total.error = f"fallo guardando progreso: {exc}"
                return True
        if debe_cancelar is not None:
            try:
                if await debe_cancelar():
                    total.motivo_fin = "cancelada_por_usuario"
                    return True
            except Exception as exc:  # noqa: BLE001
                total.error = f"fallo comprobando cancelación: {exc}"
                return True
        return False

    def cerrar() -> ResultadoPlanificador:
        total.coste_gastado_eur = round(total.coste_gastado_eur, 4)
        return total

    # --- Fase 1: fuentes de pago marcadas --------------------------------
    for nombre, argumentos in planes_fuentes_marcadas(filtros, usar_places=usar_places, apify_actores=actores):
        args, resultado = await ejecutar_con_tope(nombre, argumentos, contexto, presupuesto_eur)
        if await registrar(nombre, args, resultado):
            return cerrar()
        if nombre == "descubrir_google_search":
            encadenadas = []
            if "facebook" in actores and resultado.get("candidatos_facebook"):
                encadenadas.append(("enriquecer_con_facebook", {"urls": resultado["candidatos_facebook"]}))
            if "linkedin" in actores and resultado.get("candidatos_linkedin"):
                encadenadas.append(("enriquecer_con_linkedin", {"urls": resultado["candidatos_linkedin"]}))
            for n2, a2 in encadenadas:
                args2, res2 = await ejecutar_con_tope(n2, a2, contexto, presupuesto_eur)
                if await registrar(n2, args2, res2):
                    return cerrar()

    # --- Fase 2: bucle del LLM -------------------------------------------
    llm = await _bucle_llm(
        conn, cliente_http, filtros, presupuesto_eur=max(0.0, contexto.presupuesto_restante_eur), max_rondas=max_rondas,
        cliente=cliente, on_ronda=on_ronda, debe_cancelar=debe_cancelar, busqueda_id=busqueda_id,
        usar_places=usar_places, apify_actores=actores, paso_inicial=len(total.rondas),
        contexto_previo=_resumen_fase_previa(total.rondas),
    )
    total.rondas.extend(llm.rondas)
    total.coste_gastado_eur += llm.coste_gastado_eur
    contexto.presupuesto_restante_eur -= llm.coste_gastado_eur
    total.motivo_fin, total.resumen, total.pregunta, total.error = llm.motivo_fin, llm.resumen, llm.pregunta, llm.error
    if llm.error or llm.motivo_fin == "cancelada_por_usuario" or busqueda_id is None:
        return cerrar()

    # --- Fase 3: completar contacto --------------------------------------
    motivo_llm = total.motivo_fin
    resultado_contacto = await completar_contacto(
        conn, cliente_http, filtros, busqueda_id=busqueda_id,
        max_coste_eur=max(0.0, contexto.presupuesto_restante_eur), apify_actores=actores,
        telefonos_compartidos=contexto.telefonos_compartidos,
    )
    if not await registrar("completar_contacto", {}, resultado_contacto):
        total.motivo_fin = motivo_llm
    return cerrar()
