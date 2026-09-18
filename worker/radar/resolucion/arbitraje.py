"""Arbitraje LLM de la zona de revisión (doc 05 §2.5, tarea #21 -- hasta
ahora "no conectado", ver docstring de `radar.orquestador.procesar`).

`radar.resolucion.scoring.comparar` (código determinista) decide QUÉ pares
de empresas llegan a `candidatos_duplicado`; este módulo arbitra esos
candidatos con el LLM, usando todo el contexto disponible (nombre, NIF,
sedes, administradores, objeto social, de qué fuente viene cada una) para
decidir si son la misma empresa, dos empresas distintas (homónimas,
franquicia, grupo), o si no hay evidencia suficiente para decidir con
seguridad -- en ese último caso, y siempre que la confianza declarada quede
por debajo de `CONFIANZA_MINIMA_AUTOMATICA`, el candidato se queda pendiente
para revisión humana (panel /duplicados). El LLM juzga, pero nunca fusiona
solo porque el nombre coincida si no está seguro (principio 3 y 5 del
proyecto) -- eso es responsabilidad de `scripts/arbitrar_duplicados.py`, que
es quien decide si actuar según la confianza devuelta aquí.

Mismo patrón de proveedor configurable que `radar.extraccion.llm` (léelo
primero si vas a tocar esto): OpenAI con salida estructurada nativa,
Anthropic con JSON por prompt + reintento.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from anthropic import Anthropic
from anthropic.types import MessageParam, TextBlock
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, ValidationError

from radar.config import Settings, get_settings

MAX_REINTENTOS = 2

# Por debajo de esta confianza, "misma"/"distinta" no se aplican solos --
# scripts/arbitrar_duplicados.py deja el candidato pendiente para revisión
# humana. Provisional, igual que UMBRAL_FUSION_AUTO/UMBRAL_REVISION en
# scoring.py: se calibra con el golden set (ver PROJECT_STATUS.md, bloqueo
# activo del proyecto).
CONFIANZA_MINIMA_AUTOMATICA = 0.85

PROMPT = """Eres un experto en resolución de entidades de empresas españolas (NIF/CIF, Registro Mercantil). Un sistema determinista marcó estas dos fichas como POSIBLE duplicado -- decide si son la MISMA empresa jurídica o dos empresas DISTINTAS.

Puntuación del sistema determinista: {puntuacion}
Señales que encontró: {senales}

Empresa A:
{empresa_a_json}

Empresa B:
{empresa_b_json}

Reglas (no las repitas en tu respuesta, solo aplícalas):
- El NIF es la clave maestra. Si ambas tienen NIF y son distintos, son SIEMPRE dos empresas distintas.
- Un nombre idéntico o muy parecido NO basta por sí solo: pueden ser dos empresas homónimas en localidades distintas, una franquicia, o empresas de un mismo grupo con razón social parecida pero personalidad jurídica propia.
- Si ninguna de las dos aporta NIF, domicilio ni administradores en común que permitan decidir con seguridad, responde "incierto" y una confianza baja -- no adivines ni fuerces una decisión.

Responde SOLO con JSON:
{{"decision": "misma" | "distinta" | "incierto", "confianza": 0.0, "motivo": ""}}"""


class RespuestaArbitraje(BaseModel):
    model_config = ConfigDict(extra="ignore")

    decision: Literal["misma", "distinta", "incierto"]
    confianza: float = 0.0
    motivo: str = ""


@dataclass
class ResultadoArbitraje:
    respuesta: RespuestaArbitraje | None
    error: str | None = None


def construir_prompt(puntuacion: float | None, senales: list[str], empresa_a: dict, empresa_b: dict) -> str:
    """Aparte para poder testearlo sin llamar al LLM (mismo patrón que
    `radar.extraccion.llm.construir_prompt`)."""
    return PROMPT.format(
        puntuacion=puntuacion if puntuacion is not None else "desconocida",
        senales=", ".join(senales) if senales else "(ninguna)",
        empresa_a_json=json.dumps(empresa_a, ensure_ascii=False, default=str),
        empresa_b_json=json.dumps(empresa_b, ensure_ascii=False, default=str),
    )


def _extraer_json(texto: str) -> str:
    """El modelo a veces envuelve el JSON en ```json ... ``` pese a que se
    le pide "SOLO JSON" — quitarlo antes de parsear (idéntico a
    `radar.extraccion.llm._extraer_json`)."""
    t = texto.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.removesuffix("```")
        if t.lstrip().startswith("json"):
            t = t.lstrip()[4:]
    return t.strip()


def arbitrar(
    puntuacion: float | None,
    senales: list[str],
    empresa_a: dict,
    empresa_b: dict,
    cliente: Any | None = None,
) -> ResultadoArbitraje:
    """Punto de entrada único; despacha según `settings.proveedor_llm`.
    `cliente`, si se pasa, debe ser del tipo que espera ese proveedor
    (`openai.OpenAI` o `anthropic.Anthropic`) — se usa sobre todo para
    tests/inyección; en producción se construye solo."""
    settings = get_settings()
    if settings.proveedor_llm == "openai":
        return _arbitrar_openai(puntuacion, senales, empresa_a, empresa_b, cliente, settings)
    return _arbitrar_anthropic(puntuacion, senales, empresa_a, empresa_b, cliente, settings)


def _arbitrar_openai(
    puntuacion: float | None, senales: list[str], empresa_a: dict, empresa_b: dict,
    cliente: OpenAI | None, settings: Settings,
) -> ResultadoArbitraje:
    if not settings.openai_api_key:
        return ResultadoArbitraje(respuesta=None, error="OPENAI_API_KEY no configurada")
    cliente = cliente or OpenAI(api_key=settings.openai_api_key)
    prompt = construir_prompt(puntuacion, senales, empresa_a, empresa_b)
    try:
        completado = cliente.chat.completions.parse(
            model=settings.modelo_planificador,
            messages=[{"role": "user", "content": prompt}],
            response_format=RespuestaArbitraje,
        )
    except Exception as exc:  # noqa: BLE001 — cualquier fallo de red/API se reporta, nunca se inventa una respuesta
        return ResultadoArbitraje(respuesta=None, error=str(exc))

    mensaje = completado.choices[0].message
    if mensaje.refusal:
        return ResultadoArbitraje(respuesta=None, error=f"el modelo rehusó responder: {mensaje.refusal}")
    if mensaje.parsed is None:
        return ResultadoArbitraje(respuesta=None, error="respuesta sin JSON parseado (revisar finish_reason)")
    return ResultadoArbitraje(respuesta=mensaje.parsed)


def _arbitrar_anthropic(
    puntuacion: float | None, senales: list[str], empresa_a: dict, empresa_b: dict,
    cliente: Anthropic | None, settings: Settings,
) -> ResultadoArbitraje:
    if not settings.anthropic_api_key:
        return ResultadoArbitraje(respuesta=None, error="ANTHROPIC_API_KEY no configurada")
    cliente = cliente or Anthropic(api_key=settings.anthropic_api_key)

    mensajes: list[MessageParam] = [{"role": "user", "content": construir_prompt(puntuacion, senales, empresa_a, empresa_b)}]
    ultimo_error: str | None = None
    for _ in range(MAX_REINTENTOS + 1):
        respuesta = cliente.messages.create(model=settings.modelo_planificador, max_tokens=512, messages=mensajes)
        texto_respuesta = "".join(bloque.text for bloque in respuesta.content if isinstance(bloque, TextBlock))
        try:
            datos = json.loads(_extraer_json(texto_respuesta))
            return ResultadoArbitraje(respuesta=RespuestaArbitraje.model_validate(datos))
        except (json.JSONDecodeError, ValidationError) as exc:
            ultimo_error = str(exc)
            mensajes.append({"role": "assistant", "content": texto_respuesta})
            mensajes.append(
                {"role": "user", "content": f"Tu respuesta no es JSON válido según el esquema pedido: {exc}\nCorrígela y responde SOLO con el JSON."}
            )
    return ResultadoArbitraje(respuesta=None, error=ultimo_error)
