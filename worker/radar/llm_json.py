"""Llamada genérica a un LLM que devuelve JSON validado con un esquema pydantic,
con el proveedor configurado (`settings.proveedor_llm`) y su coste real.

Mismo patrón que `radar.resolucion.arbitraje` (OpenAI: salida estructurada
nativa; Anthropic: JSON por prompt + reintento), extraído aquí para los
módulos nuevos que necesitan juzgar con IA (relevancia de resultados,
resolución de dudas) sin repetir el código de proveedor en cada uno.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Generic, TypeVar

from anthropic import Anthropic
from anthropic.types import MessageParam, TextBlock
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from radar.config import get_settings
from radar.coste_llm import calcular_coste_eur

M = TypeVar("M", bound=BaseModel)
MAX_REINTENTOS = 2


@dataclass
class RespuestaJSON(Generic[M]):
    datos: M | None
    coste_eur: float = 0.0
    error: str | None = None


def _sin_bloque_codigo(texto: str) -> str:
    t = texto.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.removesuffix("```")
        if t.lstrip().startswith("json"):
            t = t.lstrip()[4:]
    return t.strip()


def pedir_json(prompt: str, esquema: type[M], *, modelo: str | None = None, max_tokens: int = 2048) -> RespuestaJSON[M]:
    """Nunca lanza: un fallo de red/API o una respuesta inválida vuelve como
    `error`, y quien llama decide (normalmente: no aplicar nada)."""
    settings = get_settings()
    modelo = modelo or settings.modelo_extraccion
    if settings.proveedor_llm == "openai":
        if not settings.openai_api_key:
            return RespuestaJSON(None, error="OPENAI_API_KEY no configurada")
        try:
            completado = OpenAI(api_key=settings.openai_api_key).chat.completions.parse(
                model=modelo, messages=[{"role": "user", "content": prompt}], response_format=esquema,
            )
        except Exception as exc:  # noqa: BLE001
            return RespuestaJSON(None, error=str(exc))
        uso = completado.usage
        coste = calcular_coste_eur(modelo, uso.prompt_tokens, uso.completion_tokens) if uso else 0.0
        mensaje = completado.choices[0].message
        if mensaje.parsed is None:
            return RespuestaJSON(None, coste, mensaje.refusal or "respuesta sin JSON parseado")
        return RespuestaJSON(mensaje.parsed, coste)

    if not settings.anthropic_api_key:
        return RespuestaJSON(None, error="ANTHROPIC_API_KEY no configurada")
    cliente = Anthropic(api_key=settings.anthropic_api_key)
    mensajes: list[MessageParam] = [{"role": "user", "content": prompt}]
    coste = 0.0
    error: str | None = None
    for _ in range(MAX_REINTENTOS + 1):
        try:
            respuesta = cliente.messages.create(model=modelo, max_tokens=max_tokens, messages=mensajes)
        except Exception as exc:  # noqa: BLE001
            return RespuestaJSON(None, coste, str(exc))
        coste += calcular_coste_eur(modelo, respuesta.usage.input_tokens, respuesta.usage.output_tokens)
        texto = "".join(b.text for b in respuesta.content if isinstance(b, TextBlock))
        try:
            return RespuestaJSON(esquema.model_validate(json.loads(_sin_bloque_codigo(texto))), coste)
        except (json.JSONDecodeError, ValidationError) as exc:
            error = str(exc)
            mensajes += [
                {"role": "assistant", "content": texto},
                {"role": "user", "content": f"Tu respuesta no es JSON válido según el esquema: {exc}\nResponde SOLO con el JSON corregido."},
            ]
    return RespuestaJSON(None, coste, error)
