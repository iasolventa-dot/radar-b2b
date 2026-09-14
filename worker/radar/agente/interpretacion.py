"""Interpretación de la petición del usuario → filtros estructurados
(doc 07 §3, prompt `PROMPT_INTERPRETACION` en `radar.agente.prompts`).

Primer paso del agente (tarea #21): traduce lenguaje natural ("constructoras
de Sevilla de 10 a 50 empleados") a un `FiltrosBusqueda` que el resto del
agente (planificador, herramientas) puede usar sin volver a tocar al LLM.

Modelo potente (`settings.modelo_planificador`, doc 07 §2: "interpretar,
planificar, arbitrar"). Mismo patrón de despacho por proveedor que
`radar.extraccion.llm` (ver ese módulo para el razonamiento completo):

- **openai** (por defecto): `chat.completions.parse()` con
  `response_format=FiltrosBusqueda` — sin bucle de reintento por JSON
  inválido, el servidor ya lo garantiza.
- **anthropic**: JSON por prompt con reintento (máx. `MAX_REINTENTOS`),
  igual que la rama anthropic de `radar.extraccion.llm`.

Nunca inventa zonas, CNAE o exclusiones que el usuario no pidió — cualquier
traducción de lo ambiguo (una comarca, "mediana" en sentido coloquial...) se
declara en `supuestos`, nunca se cuela en los filtros como si fuera literal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from anthropic import Anthropic
from anthropic.types import MessageParam, TextBlock
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, ValidationError

from radar.agente.prompts import PROMPT_INTERPRETACION
from radar.config import Settings, get_settings
from radar.extraccion.llm import _extraer_json  # mismo saneo de ```json ... ``` — no duplicar

MAX_REINTENTOS = 2

# Mismos 9 valores que el enum `estado_empresa` (docs/03b_schema_inicial.sql) —
# cualquier cambio ahí debe reflejarse aquí, si no el LLM podría "inventar"
# un estado que el esquema de BD luego rechaza.
EstadoEmpresa = Literal[
    "activa",
    "probablemente_activa",
    "dudosa",
    "inactiva",
    "en_liquidacion",
    "en_concurso",
    "disuelta",
    "extinguida",
    "desconocida",
]


class UbicacionFiltro(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # "radio"/"poligono" existieron aquí antes: el prompt los ofrecía como
    # opción y el frontend (lib/filtros.ts) hasta los mostraba en el
    # resumen de la interpretación como si fueran a aplicarse — pero
    # construir_where_empresas (herramientas.py) nunca los ha leído nunca
    # (no hay ninguna fuente de geocodificación conectada, doc 04: CartoCiudad
    # sigue "diseñada, sin construir"). Si el LLM los devolvía, la revisión
    # mostraba un filtro de ubicación que el buscador real ignoraba por
    # completo — exactamente lo que el principio 5 (nunca inventar) prohíbe,
    # aquí a nivel de la propia interpretación. Quitados de raíz en vez de
    # dejarlos "por si acaso": mejor que el LLM aproxime a provincia/municipio
    # y lo diga en `supuestos` (ver PROMPT_INTERPRETACION) que prometer una
    # precisión que el sistema no puede comprobar.
    tipo: Literal["provincias", "municipios", "ccaa"] = "provincias"
    provincias: list[str] = []
    municipios: list[str] = []
    ccaa: list[str] = []


class SectorFiltro(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sector_interno: str = ""
    codigos_cnae: list[str] = []
    palabras_clave: list[str] = []
    exclusiones: list[str] = []


class TamanoFiltro(BaseModel):
    model_config = ConfigDict(extra="ignore")

    empleados_min: int | None = None
    empleados_max: int | None = None


class RequisitosFiltro(BaseModel):
    model_config = ConfigDict(extra="ignore")

    web: bool = False
    telefono: bool = False
    email_generico: bool = False


class CalidadFiltro(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # 0.5, no 0.7: `radar.verificacion.global_.TOPE_SIN_NIF_CONFIRMADO` limita
    # a 0.6 la confianza global de CUALQUIER empresa sin NIF confirmado —
    # con las fuentes conectadas hoy (BORME nunca da NIF), eso es casi
    # todas. Un mínimo de 0.7 filtraría el 100% de los resultados reales,
    # no una parte: en los datos reales del piloto (2026-09-14), la
    # confianza global observada iba de 0.38 a 0.6, nunca por encima.
    confianza_minima: float = 0.5
    frescura_max_dias: int = 180


class FiltrosBusqueda(BaseModel):
    """Salida de la interpretación — entrada del planificador (doc 07 §4)."""

    model_config = ConfigDict(extra="ignore")

    ubicacion: UbicacionFiltro = UbicacionFiltro()
    sector: SectorFiltro = SectorFiltro()
    tamano: TamanoFiltro = TamanoFiltro()
    formas_juridicas: list[str] = []
    incluir_autonomos: bool = False
    estados: list[EstadoEmpresa] = ["activa", "probablemente_activa"]
    requisitos: RequisitosFiltro = RequisitosFiltro()
    calidad: CalidadFiltro = CalidadFiltro()
    limite_resultados: int | None = None
    presupuesto_eur: float | None = None
    supuestos: list[str] = []
    preguntas: list[str] = []


def construir_prompt(peticion: str, contexto: str | None) -> str:
    """Aparte para poder testearlo sin llamar al LLM (igual que
    `radar.extraccion.llm.construir_prompt`)."""
    return PROMPT_INTERPRETACION.format(peticion=peticion, contexto=contexto or "(sin contexto adicional)")


def parsear_respuesta(texto: str) -> FiltrosBusqueda:
    """Puede lanzar `json.JSONDecodeError` o `pydantic.ValidationError` —
    quien llama decide si reintenta (ver `_interpretar_con_anthropic`)."""
    datos = json.loads(_extraer_json(texto))
    return FiltrosBusqueda.model_validate(datos)


@dataclass
class ResultadoInterpretacion:
    filtros: FiltrosBusqueda | None
    intentos: int
    error: str | None = None


def interpretar_peticion(
    peticion: str,
    contexto: str | None = None,
    cliente: Any | None = None,
) -> ResultadoInterpretacion:
    """Punto de entrada único; despacha según `settings.proveedor_llm` (ver
    docstring del módulo). `cliente`, si se pasa, debe ser del tipo que
    espera ese proveedor (`openai.OpenAI` o `anthropic.Anthropic`) — se usa
    sobre todo para tests/inyección; en producción se construye solo."""
    settings = get_settings()
    if settings.proveedor_llm == "openai":
        return _interpretar_con_openai(peticion, contexto, cliente, settings)
    return _interpretar_con_anthropic(peticion, contexto, cliente, settings)


def _interpretar_con_openai(
    peticion: str,
    contexto: str | None,
    cliente: OpenAI | None,
    settings: Settings,
) -> ResultadoInterpretacion:
    if not settings.openai_api_key:
        return ResultadoInterpretacion(filtros=None, intentos=0, error="OPENAI_API_KEY no configurada")
    cliente = cliente or OpenAI(api_key=settings.openai_api_key)
    prompt = construir_prompt(peticion, contexto)
    try:
        completado = cliente.chat.completions.parse(
            model=settings.modelo_planificador,
            messages=[{"role": "user", "content": prompt}],
            response_format=FiltrosBusqueda,
        )
    except Exception as exc:  # noqa: BLE001 — cualquier fallo de red/API se reporta, nunca se inventan filtros
        return ResultadoInterpretacion(filtros=None, intentos=1, error=str(exc))

    mensaje = completado.choices[0].message
    if mensaje.refusal:
        return ResultadoInterpretacion(filtros=None, intentos=1, error=f"el modelo rehusó responder: {mensaje.refusal}")
    if mensaje.parsed is None:
        return ResultadoInterpretacion(filtros=None, intentos=1, error="respuesta sin JSON parseado (revisar finish_reason)")
    return ResultadoInterpretacion(filtros=mensaje.parsed, intentos=1)


def _interpretar_con_anthropic(
    peticion: str,
    contexto: str | None,
    cliente: Anthropic | None,
    settings: Settings,
) -> ResultadoInterpretacion:
    """Reintento (máx. `MAX_REINTENTOS`) pasando el error de validación de
    vuelta, igual que `radar.extraccion.llm._extraer_con_llm_anthropic`."""
    if not settings.anthropic_api_key:
        return ResultadoInterpretacion(filtros=None, intentos=0, error="ANTHROPIC_API_KEY no configurada")
    cliente = cliente or Anthropic(api_key=settings.anthropic_api_key)

    mensajes: list[MessageParam] = [{"role": "user", "content": construir_prompt(peticion, contexto)}]
    ultimo_error: str | None = None
    for intento in range(1, MAX_REINTENTOS + 2):
        respuesta = cliente.messages.create(model=settings.modelo_planificador, max_tokens=1536, messages=mensajes)
        texto_respuesta = "".join(bloque.text for bloque in respuesta.content if isinstance(bloque, TextBlock))
        try:
            return ResultadoInterpretacion(filtros=parsear_respuesta(texto_respuesta), intentos=intento)
        except (json.JSONDecodeError, ValidationError) as exc:
            ultimo_error = str(exc)
            mensajes.append({"role": "assistant", "content": texto_respuesta})
            mensajes.append(
                {"role": "user", "content": f"Tu respuesta no es JSON válido según el esquema pedido: {exc}\nCorrígela y responde SOLO con el JSON."}
            )
    return ResultadoInterpretacion(filtros=None, intentos=MAX_REINTENTOS + 1, error=ultimo_error)
