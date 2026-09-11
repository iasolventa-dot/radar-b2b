"""Conector de búsqueda web (doc 04 §5, doc 08 D-06).

Proveedor configurable con `settings.proveedor_llm` / `settings.search_api_provider`
(doc 02 §3; por defecto **openai** desde 2026-09-11 — el proyecto no tiene
contratada cuenta de Anthropic, ver `08_registro_decisiones.md`). Ambos
proveedores usan la herramienta de búsqueda web integrada en su propia API
de mensajes/respuestas (nunca un proveedor externo como Tavily/Serper/Exa,
que sigue siendo la comparación pendiente de D-06):

- **openai**: herramienta `web_search` de la Responses API. Verificada el
  2026-09-11 contra el SDK instalado (`openai==3.13.0`,
  `openai/types/responses/web_search_tool_param.py` y
  `response_function_web_search.py`) — NO contra la documentación pública,
  que en un fetch dio una forma de respuesta distinta (con título y con
  campo `results` a nivel superior) que no coincide con lo que el propio
  SDK tipa. Diferencias reales frente a la de Anthropic, que si te importa
  el título o bloquear dominios debes tener en cuenta:
    - Cada URL encontrada NO trae título (`ActionSearchSource` solo tiene
      `url`) — `ResultadoWeb.titulo` queda `None` con este proveedor.
    - Solo admite `allowed_domains`, no `blocked_domains` (la API de
      OpenAI no tiene ese filtro) — pasar `dominios_bloqueados` con este
      proveedor lanza `ValueError`.
    - No hay un contador de "búsquedas facturadas" en `usage` como el
      `server_tool_use.web_search_requests` de Anthropic: contamos
      nosotros los items `web_search_call` con `status="completed"` en
      `response.output` como proxy del coste real.
    - Tope de búsquedas por llamada con `max_tool_calls=1` (equivalente al
      `max_uses=1` de Anthropic). Además, a diferencia de Anthropic, hacen
      falta dos parámetros extra que Anthropic no necesita (comprobado en
      vivo 2026-09-11 con `gpt-5.6-sol`, cada uno con su propio fallo
      silencioso si falta):
        - `tool_choice="required"`: sin esto, el modelo puede responder
          "hecho" sin llegar a invocar la herramienta (0 resultados, 0
          búsquedas facturadas).
        - `include=["web_search_call.action.sources"]`: sin esto, la
          búsqueda se ejecuta y se factura, pero `action.sources` llega
          vacío igualmente (1 búsqueda facturada, 0 URLs) — OpenAI no
          incluye las fuentes por defecto en la respuesta.
- **anthropic**: herramienta `web_search_20250305`. Verificada el
  2026-09-11 contra `anthropic==1.4.0` — ver comentarios en `_buscar_anthropic`.

Precio verificado el 2026-09-11 en ambos proveedores: **10 USD por 1.000
búsquedas** (+ tokens normales de la respuesta, mínimos aquí porque el
prompt prohíbe comentar resultados). Ninguno de los dos publica precio en
EUR — aproximamos 1 USD ≈ 1 EUR para el presupuesto (D-04); a
verificar/ajustar con el tipo de cambio real si el volumen lo justifica.

Principio clave (doc 04 §5), igual para los dos proveedores: **los
snippets no son evidencia**. Este conector SOLO sirve para descubrir URLs
candidatas (web corporativa, ficha de directorio, página que menciona un
NIF concreto...). Nunca extrae ni afirma un dato de empresa a partir de un
snippet — por eso el `RegistroBruto` que produce lleva `campos` vacío: los
datos reales los saca `radar.extraccion.enriquecer_desde_web` (doc 02 paso
5) DESCARGANDO Y LEYENDO la URL encontrada aquí, nunca fiándose del
extracto del buscador.

Coherente con la fila `buscador_web` de `fuentes` (doc 03b, migración
202609100001_esquema_inicial.sql): `permite_almacenar = false`,
`campos_almacenables = '{}'` — `radar.orquestador.bd.insertar_registro_bruto`
ya vacía el `payload` para esta fuente antes de guardar; aquí, además, no
rellenamos `campos` para no depender de que nadie recuerde aplicar esa
regla más adelante.

**El código decide qué se busca, no el modelo.** `descubrir()` recibe
consultas ya construidas literalmente (los patrones de doc 04 §5:
`"reformas" "Dos Hermanas"`, `site:dominio.es aviso legal`, `"B12345678"`);
este conector nunca deja que el modelo elija qué buscar — eso es tarea del
agente planificador (doc 07, tarea #21), no de este conector.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from anthropic import Anthropic
from anthropic.types import MessageParam, WebSearchTool20250305Param
from openai import OpenAI
from openai.types.responses import WebSearchToolParam

from radar.config import Settings, get_settings

from .base import CamposExtraidos, Conector, RegistroBruto

COSTE_POR_BUSQUEDA_EUR = 0.01

TOOL_VERSION_ANTHROPIC: Literal["web_search_20250305"] = "web_search_20250305"
TOOL_VERSION_OPENAI: Literal["web_search"] = "web_search"

_PROMPT = (
    "Ejecuta EXACTAMENTE una búsqueda con la herramienta de búsqueda web, con "
    "esta consulta literal, sin modificarla ni traducirla:\n\n{consulta}\n\n"
    "No hagas ninguna otra búsqueda. No comentes, no resumas ni interpretes "
    "los resultados: responde solo con la palabra 'hecho' cuando termines."
)


@dataclass
class ResultadoWeb:
    url: str
    titulo: str | None  # openai no lo da (ver docstring del módulo); anthropic sí
    page_age: str | None  # solo anthropic


@dataclass
class ResultadoBusqueda:
    consulta: str
    resultados: list[ResultadoWeb] = field(default_factory=list)
    numero_busquedas: int = 0  # coste real (nº de búsquedas facturadas), no estimado
    error: str | None = None  # motivo si la herramienta falló (no es un fallo nuestro)


# --- Proveedor: OpenAI (Responses API) ------------------------------------


def _tool_param_openai(
    *, dominios_permitidos: list[str] | None, dominios_bloqueados: list[str] | None
) -> WebSearchToolParam:
    if dominios_bloqueados:
        raise ValueError(
            "dominios_bloqueados no está soportado por la herramienta web_search de OpenAI "
            "(solo 'filters.allowed_domains') — usa dominios_permitidos o cambia a proveedor_llm=anthropic"
        )
    tool: WebSearchToolParam = {"type": TOOL_VERSION_OPENAI, "search_context_size": "low"}
    if dominios_permitidos:
        tool["filters"] = {"allowed_domains": dominios_permitidos}
    return tool


def _procesar_respuesta_openai(respuesta: Any, consulta: str, max_resultados: int) -> ResultadoBusqueda:
    """`respuesta` es un `openai.types.responses.Response` (o, en tests,
    cualquier objeto con `.output` de la misma forma). Cada item
    `web_search_call` describe UNA acción (`action.type`): solo
    `"search"` trae `action.sources` (lista de `{type:"url", url}`, sin
    título — `open_page`/`find_in_page` son pasos intermedios del modelo,
    no resultados nuevos que nos interesen). Deduplicamos por URL
    conservando el orden."""
    vistas: set[str] = set()
    resultados: list[ResultadoWeb] = []
    numero_busquedas = 0
    for item in respuesta.output:
        if getattr(item, "type", None) != "web_search_call":
            continue
        if getattr(item, "status", None) == "completed":
            numero_busquedas += 1
        # Acceso directo (no getattr encadenado): ya sabemos que `item` es un
        # web_search_call, así que `.action` existe siempre en el SDK real;
        # `respuesta` es `Any`, así que esto no falsea el tipado de mypy con
        # el `Any | None` que devuelve el getattr de 3 argumentos con default=None.
        accion = item.action
        if accion.type != "search":
            continue
        for fuente in accion.sources or []:
            if fuente.url not in vistas:
                vistas.add(fuente.url)
                resultados.append(ResultadoWeb(url=fuente.url, titulo=None, page_age=None))

    return ResultadoBusqueda(consulta=consulta, resultados=resultados[:max_resultados], numero_busquedas=numero_busquedas)


def _buscar_openai(
    cliente: OpenAI | None,
    consulta: str,
    *,
    max_resultados: int,
    dominios_permitidos: list[str] | None,
    dominios_bloqueados: list[str] | None,
    modelo: str | None,
    settings: Settings,
) -> ResultadoBusqueda:
    if cliente is None:
        if not settings.openai_api_key:
            return ResultadoBusqueda(consulta=consulta, error="OPENAI_API_KEY no configurada")
        cliente = OpenAI(api_key=settings.openai_api_key)

    tool = _tool_param_openai(dominios_permitidos=dominios_permitidos, dominios_bloqueados=dominios_bloqueados)
    try:
        respuesta = cliente.responses.create(
            model=modelo or settings.modelo_planificador,
            input=_PROMPT.format(consulta=consulta),
            tools=[tool],
            tool_choice="required",  # si no, algunos modelos responden "hecho" sin llegar a buscar
            max_tool_calls=1,
            # Sin esto, `web_search_call.action.sources` viene vacío aunque la
            # búsqueda se haya facturado — comprobado en vivo 2026-09-11
            # ("1 búsqueda facturada" pero 0 URLs hasta añadir este include).
            include=["web_search_call.action.sources"],
        )
    except Exception as exc:  # noqa: BLE001 — nunca inventamos resultados si la API falla
        return ResultadoBusqueda(consulta=consulta, error=str(exc))
    return _procesar_respuesta_openai(respuesta, consulta, max_resultados)


# --- Proveedor: Anthropic (Messages API) -----------------------------------


def _tool_param_anthropic(
    *, dominios_permitidos: list[str] | None, dominios_bloqueados: list[str] | None
) -> WebSearchTool20250305Param:
    if dominios_permitidos and dominios_bloqueados:
        raise ValueError("dominios_permitidos y dominios_bloqueados son excluyentes (API de Anthropic)")
    tool: WebSearchTool20250305Param = {
        "type": TOOL_VERSION_ANTHROPIC,
        "name": "web_search",
        "max_uses": 1,
        "allowed_callers": ["direct"],
    }
    if dominios_permitidos:
        tool["allowed_domains"] = dominios_permitidos
    if dominios_bloqueados:
        tool["blocked_domains"] = dominios_bloqueados
    return tool


def _procesar_respuesta_anthropic(respuesta: Any, consulta: str, max_resultados: int) -> ResultadoBusqueda:
    """`respuesta` es un `anthropic.types.Message` (o, en tests, cualquier
    objeto con la misma forma: `.content`,
    `.usage.server_tool_use.web_search_requests`).

    Un bloque `web_search_tool_result` trae, en `.content`, o bien una
    lista de `web_search_result` (éxito) o un único
    `web_search_tool_result_error` con `.error_code` (fallo de la
    herramienta, p. ej. `too_many_requests`) — nunca ambas cosas (doc del
    SDK). Nunca leemos `encrypted_content` ni ningún snippet: solo url,
    título y antigüedad de la página.
    """
    resultados: list[ResultadoWeb] = []
    error: str | None = None
    for bloque in respuesta.content:
        if getattr(bloque, "type", None) != "web_search_tool_result":
            continue
        contenido = bloque.content
        if isinstance(contenido, list):
            for r in contenido:
                resultados.append(ResultadoWeb(url=r.url, titulo=r.title, page_age=r.page_age))
        else:
            error = contenido.error_code

    numero_busquedas = 0
    uso = getattr(respuesta, "usage", None)
    server_tool_use = getattr(uso, "server_tool_use", None) if uso is not None else None
    if server_tool_use is not None:
        numero_busquedas = server_tool_use.web_search_requests

    return ResultadoBusqueda(
        consulta=consulta, resultados=resultados[:max_resultados], numero_busquedas=numero_busquedas, error=error
    )


def _buscar_anthropic(
    cliente: Anthropic | None,
    consulta: str,
    *,
    max_resultados: int,
    dominios_permitidos: list[str] | None,
    dominios_bloqueados: list[str] | None,
    modelo: str | None,
    settings: Settings,
) -> ResultadoBusqueda:
    if cliente is None:
        if not settings.anthropic_api_key:
            return ResultadoBusqueda(consulta=consulta, error="ANTHROPIC_API_KEY no configurada")
        cliente = Anthropic(api_key=settings.anthropic_api_key)

    tool = _tool_param_anthropic(dominios_permitidos=dominios_permitidos, dominios_bloqueados=dominios_bloqueados)
    mensajes: list[MessageParam] = [{"role": "user", "content": _PROMPT.format(consulta=consulta)}]
    try:
        respuesta = cliente.messages.create(
            model=modelo or settings.modelo_extraccion, max_tokens=256, messages=mensajes, tools=[tool]
        )
    except Exception as exc:  # noqa: BLE001 — nunca inventamos resultados si la API falla
        return ResultadoBusqueda(consulta=consulta, error=str(exc))
    return _procesar_respuesta_anthropic(respuesta, consulta, max_resultados)


# --- Punto de entrada común --------------------------------------------


def buscar(
    cliente: Any | None,
    consulta: str,
    *,
    max_resultados: int = 5,
    dominios_permitidos: list[str] | None = None,
    dominios_bloqueados: list[str] | None = None,
    modelo: str | None = None,
) -> ResultadoBusqueda:
    """Ejecuta UNA consulta literal contra el buscador web y devuelve las
    URLs encontradas (recortadas a `max_resultados`) — sin snippets ni
    contenido cifrado: quien llama debe descargar y leer la URL
    (`radar.extraccion.enriquecer_desde_web`), nunca fiarse del extracto
    del buscador (doc 04 §5).

    Despacha según `settings.proveedor_llm` (ver docstring del módulo).
    `cliente`, si se pasa, debe ser del cliente nativo del proveedor
    correspondiente (`openai.OpenAI` o `anthropic.Anthropic`).
    """
    settings = get_settings()
    if settings.proveedor_llm == "openai":
        return _buscar_openai(
            cliente, consulta, max_resultados=max_resultados, dominios_permitidos=dominios_permitidos,
            dominios_bloqueados=dominios_bloqueados, modelo=modelo, settings=settings,
        )
    return _buscar_anthropic(
        cliente, consulta, max_resultados=max_resultados, dominios_permitidos=dominios_permitidos,
        dominios_bloqueados=dominios_bloqueados, modelo=modelo, settings=settings,
    )


def _resultado_a_registro_bruto(resultado: ResultadoBusqueda) -> RegistroBruto:
    """`campos` se deja vacío a propósito (ver docstring del módulo): este
    `RegistroBruto` es solo un registro de qué URLs salieron para esta
    consulta, nunca una afirmación sobre ninguna empresa. El `payload` sí
    lleva las URLs (para que quien orquesta la búsqueda las use), aunque
    `insertar_registro_bruto` lo vaciará igualmente antes de guardar en BD
    porque `fuentes.buscador_web.permite_almacenar = false`.
    """
    return RegistroBruto(
        fuente="buscador_web",
        id_externo=None,
        url=None,
        payload={
            "consulta": resultado.consulta,
            "resultados": [{"url": r.url, "titulo": r.titulo, "page_age": r.page_age} for r in resultado.resultados],
            "error": resultado.error,
        },
        campos=CamposExtraidos(),
    )


class ConectorBuscadorWeb(Conector):
    codigo = "buscador_web"
    coste_unitario_eur = COSTE_POR_BUSQUEDA_EUR

    def __init__(self, cliente: Any | None = None):
        self.cliente = cliente

    def estimar_coste(self, parametros: dict) -> float:
        return len(_consultas_de(parametros)) * COSTE_POR_BUSQUEDA_EUR

    async def descubrir(self, parametros: dict, max_coste_eur: float) -> AsyncIterator[RegistroBruto]:
        """Parámetros esperados:

        - ``consultas``: lista de consultas literales (str) a ejecutar tal
          cual — o ``consulta`` para una sola. Las construye quien llama
          (doc 04 §5 da los patrones); este conector no decide qué buscar.
        - ``max_resultados``: URLs a quedarse por consulta (por defecto 5).
        - ``dominios_permitidos`` / ``dominios_bloqueados``: opcional
          (``dominios_bloqueados`` solo funciona con proveedor_llm=anthropic).

        Para el presupuesto usamos el coste REAL devuelto por la API
        (`numero_busquedas` de cada resultado), no una estimación — puede
        ser 0 si la herramienta falló y no llegó a buscar.
        """
        max_resultados = parametros.get("max_resultados", 5)
        dominios_permitidos = parametros.get("dominios_permitidos")
        dominios_bloqueados = parametros.get("dominios_bloqueados")

        coste_acumulado = 0.0
        for consulta in _consultas_de(parametros):
            if coste_acumulado + COSTE_POR_BUSQUEDA_EUR > max_coste_eur:
                break
            resultado = buscar(
                self.cliente,
                consulta,
                max_resultados=max_resultados,
                dominios_permitidos=dominios_permitidos,
                dominios_bloqueados=dominios_bloqueados,
            )
            coste_acumulado += resultado.numero_busquedas * COSTE_POR_BUSQUEDA_EUR
            yield _resultado_a_registro_bruto(resultado)


def _consultas_de(parametros: dict) -> list[str]:
    if parametros.get("consultas"):
        return list(parametros["consultas"])
    if parametros.get("consulta"):
        return [parametros["consulta"]]
    return []
