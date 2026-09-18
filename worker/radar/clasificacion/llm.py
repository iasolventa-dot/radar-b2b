"""Clasificación objeto_social -> CNAE con LLM (prompt #5 de la skill
agente-busqueda-empresas), para cuando `radar.clasificacion.reglas` no
encontró un código explícito en el texto. El modelo elige entre los
candidatos de `radar.clasificacion.candidatos.buscar_candidatos` (bloqueo
por similitud trigram) -- nunca se le deja inventar un código fuera de esa
lista: `elegir` valida la respuesta contra los candidatos antes de
devolverla, el catálogo CNAE tiene categorías vecinas demasiado parecidas
para fiarse de que el modelo no confunda una descripción con otra.

Mismo patrón de proveedor configurable que `radar.extraccion.llm` /
`radar.resolucion.arbitraje` (léelos primero si vas a tocar esto).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from anthropic import Anthropic
from anthropic.types import MessageParam, TextBlock
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, ValidationError

from radar.clasificacion.candidatos import CandidatoCnae
from radar.config import Settings, get_settings

MAX_REINTENTOS = 2

PROMPT = """Clasifica la actividad PRINCIPAL de esta empresa según la CNAE ({version_cnae}), usando solo la evidencia dada.
Evidencia: objeto social (BORME): {objeto_social}

Candidatos CNAE a considerar (código / descripción / similitud de texto con el objeto social):
{lista_candidatos}

Reglas:
- Elige el "cnae_principal" SOLO de entre los códigos de la lista de candidatos -- si ninguno encaja de verdad con la actividad descrita, deja "cnae_principal" en null y dilo en "evidencia".
- "cnaes_secundarios" también solo de esa lista (puede quedar vacío).
- No inventes un código que no esté en la lista, aunque te parezca que encajaría mejor.
- Si el objeto social describe varias actividades a la vez sin indicar cuál es la principal, o el texto es demasiado genérico para decidir, usa confianza baja.

Responde SOLO con JSON:
{{"cnae_principal": null, "cnaes_secundarios": [], "sector_interno": "", "confianza": 0.0, "evidencia": ""}}"""


class RespuestaClasificacionCnae(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cnae_principal: str | None = None
    cnaes_secundarios: list[str] = []
    sector_interno: str = ""
    confianza: float = 0.0
    evidencia: str = ""


@dataclass
class ResultadoClasificacion:
    respuesta: RespuestaClasificacionCnae | None
    error: str | None = None


def construir_prompt(objeto_social: str, candidatos: list[CandidatoCnae], version_cnae: str) -> str:
    """Aparte para poder testearlo sin llamar al LLM (mismo patrón que
    `radar.extraccion.llm.construir_prompt`)."""
    lista = "\n".join(f"- {c.codigo} / {c.descripcion} / similitud {c.similitud:.2f}" for c in candidatos) or "(sin candidatos)"
    return PROMPT.format(version_cnae=version_cnae, objeto_social=objeto_social[:2000], lista_candidatos=lista)


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


def _validar_contra_candidatos(
    respuesta: RespuestaClasificacionCnae, candidatos: list[CandidatoCnae]
) -> RespuestaClasificacionCnae:
    """El modelo solo debía elegir de la lista de candidatos -- por si no
    lo respeta, se descarta aquí cualquier código que no esté en ella en
    vez de fiarse (principio 4: el LLM juzga, el código verifica)."""
    validos = {c.codigo for c in candidatos}
    principal = respuesta.cnae_principal if respuesta.cnae_principal in validos else None
    secundarios = [c for c in respuesta.cnaes_secundarios if c in validos]
    if principal != respuesta.cnae_principal:
        return respuesta.model_copy(
            update={
                "cnae_principal": None,
                "cnaes_secundarios": secundarios,
                "confianza": 0.0,
                "evidencia": f"{respuesta.evidencia} [descartado: el modelo eligió un código fuera de los candidatos]".strip(),
            }
        )
    return respuesta.model_copy(update={"cnaes_secundarios": secundarios})


def clasificar(
    objeto_social: str,
    candidatos: list[CandidatoCnae],
    version_cnae: str = "CNAE-2025",
    cliente: Any | None = None,
) -> ResultadoClasificacion:
    """Punto de entrada único; despacha según `settings.proveedor_llm`.
    `cliente`, si se pasa, debe ser del tipo que espera ese proveedor
    (`openai.OpenAI` o `anthropic.Anthropic`) — se usa sobre todo para
    tests/inyección; en producción se construye solo."""
    settings = get_settings()
    if not candidatos:
        return ResultadoClasificacion(
            respuesta=RespuestaClasificacionCnae(confianza=0.0, evidencia="sin candidatos que considerar"),
        )
    if settings.proveedor_llm == "openai":
        return _clasificar_openai(objeto_social, candidatos, version_cnae, cliente, settings)
    return _clasificar_anthropic(objeto_social, candidatos, version_cnae, cliente, settings)


def _clasificar_openai(
    objeto_social: str, candidatos: list[CandidatoCnae], version_cnae: str, cliente: OpenAI | None, settings: Settings
) -> ResultadoClasificacion:
    if not settings.openai_api_key:
        return ResultadoClasificacion(respuesta=None, error="OPENAI_API_KEY no configurada")
    cliente = cliente or OpenAI(api_key=settings.openai_api_key)
    prompt = construir_prompt(objeto_social, candidatos, version_cnae)
    try:
        completado = cliente.chat.completions.parse(
            model=settings.modelo_extraccion,
            messages=[{"role": "user", "content": prompt}],
            response_format=RespuestaClasificacionCnae,
        )
    except Exception as exc:  # noqa: BLE001 — cualquier fallo de red/API se reporta, nunca se inventa una respuesta
        return ResultadoClasificacion(respuesta=None, error=str(exc))

    mensaje = completado.choices[0].message
    if mensaje.refusal:
        return ResultadoClasificacion(respuesta=None, error=f"el modelo rehusó responder: {mensaje.refusal}")
    if mensaje.parsed is None:
        return ResultadoClasificacion(respuesta=None, error="respuesta sin JSON parseado (revisar finish_reason)")
    return ResultadoClasificacion(respuesta=_validar_contra_candidatos(mensaje.parsed, candidatos))


def _clasificar_anthropic(
    objeto_social: str, candidatos: list[CandidatoCnae], version_cnae: str, cliente: Anthropic | None, settings: Settings
) -> ResultadoClasificacion:
    if not settings.anthropic_api_key:
        return ResultadoClasificacion(respuesta=None, error="ANTHROPIC_API_KEY no configurada")
    cliente = cliente or Anthropic(api_key=settings.anthropic_api_key)

    mensajes: list[MessageParam] = [{"role": "user", "content": construir_prompt(objeto_social, candidatos, version_cnae)}]
    ultimo_error: str | None = None
    for _ in range(MAX_REINTENTOS + 1):
        respuesta = cliente.messages.create(model=settings.modelo_extraccion, max_tokens=512, messages=mensajes)
        texto_respuesta = "".join(bloque.text for bloque in respuesta.content if isinstance(bloque, TextBlock))
        try:
            datos = json.loads(_extraer_json(texto_respuesta))
            parseada = RespuestaClasificacionCnae.model_validate(datos)
            return ResultadoClasificacion(respuesta=_validar_contra_candidatos(parseada, candidatos))
        except (json.JSONDecodeError, ValidationError) as exc:
            ultimo_error = str(exc)
            mensajes.append({"role": "assistant", "content": texto_respuesta})
            mensajes.append(
                {"role": "user", "content": f"Tu respuesta no es JSON válido según el esquema pedido: {exc}\nCorrígela y responde SOLO con el JSON."}
            )
    return ResultadoClasificacion(respuesta=None, error=ultimo_error)
