"""Extracción de respaldo con LLM (doc 04 §3 paso 3, doc 07 §2, prompt #3
de la skill `agente-busqueda-empresas`). Solo se llama cuando
`DatosLegalesExtraidos.necesita_llm` es `True` — las reglas deterministas
(`radar.extraccion.reglas`) van primero siempre.

Modelo rápido y barato (`settings.modelo_extraccion`, doc 07 §2: "Alto
volumen"). La salida se valida con pydantic; si no es JSON válido o no
cumple el esquema, se reintenta pasando el error de vuelta al modelo, máx.
2 veces (prompts.md, cabecera) — a la 3ª se rinde y deja `None`, nunca
inventa un resultado.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from typing import Literal

from anthropic import Anthropic
from anthropic.types import MessageParam
from pydantic import BaseModel, ConfigDict, ValidationError

from radar.config import get_settings
from radar.extraccion.reglas import DatosLegalesExtraidos

MAX_REINTENTOS = 2

PROMPT = """Extrae los datos de identificación de la empresa TITULAR de esta web. Texto de las páginas (aviso legal, contacto, quiénes somos):
<texto>{texto_paginas}</texto>
Dominio: {dominio}
Pistas de la extracción por reglas: {resultado_reglas_json}

Reglas:
- Copia los datos tal como aparecen; NO los completes ni corrijas. Si un dato no aparece, null.
- Si aparecen datos de varias empresas (agencia que hizo la web, empresa del grupo, clientes), identifica cuál es la titular y explica por qué.
- Un NIF solo es de la titular si el texto lo asocia claramente a ella.

Responde SOLO con JSON:
{{"titular": {{"razon_social": null, "nombre_comercial": null, "nif": null, "domicilio": null, "codigo_postal": null, "municipio": null,
             "registro_mercantil": null, "telefonos": [], "emails": []}},
 "otras_empresas_mencionadas": [{{"nombre": "", "nif": null, "relacion": "agencia_web|grupo|cliente|otra"}}],
 "confianza": 0.0, "notas": ""}}"""


class TitularExtraidoLLM(BaseModel):
    model_config = ConfigDict(extra="ignore")

    razon_social: str | None = None
    nombre_comercial: str | None = None
    nif: str | None = None
    domicilio: str | None = None
    codigo_postal: str | None = None
    municipio: str | None = None
    registro_mercantil: str | None = None
    telefonos: list[str] = []
    emails: list[str] = []


class OtraEmpresaMencionadaLLM(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nombre: str
    nif: str | None = None
    relacion: Literal["agencia_web", "grupo", "cliente", "otra"] = "otra"


class RespuestaExtraccionLLM(BaseModel):
    model_config = ConfigDict(extra="ignore")

    titular: TitularExtraidoLLM
    otras_empresas_mencionadas: list[OtraEmpresaMencionadaLLM] = []
    confianza: float = 0.0
    notas: str = ""


def construir_prompt(texto_paginas: str, dominio: str | None, resultado_reglas: DatosLegalesExtraidos) -> str:
    """Aparte para poder testearlo sin llamar al LLM. `texto_paginas` se
    recorta a 12.000 caracteres — de sobra para un aviso legal/contacto
    real, y evita mandar páginas enteras mal descargadas al modelo (doc 07
    §1: "ni descargar páginas enteras a su contexto" es la regla del
    agente; el mismo criterio de coste aplica aquí)."""
    pistas = json.dumps(dataclasses.asdict(resultado_reglas), ensure_ascii=False, default=str)
    return PROMPT.format(texto_paginas=texto_paginas[:12_000], dominio=dominio or "desconocido", resultado_reglas_json=pistas)


def _extraer_json(texto: str) -> str:
    """El modelo a veces envuelve el JSON en ```json ... ``` pese a que se
    le pide "SOLO JSON" — quitarlo antes de parsear."""
    t = texto.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.removesuffix("```")
        if t.lstrip().startswith("json"):
            t = t.lstrip()[4:]
    return t.strip()


def parsear_respuesta(texto: str) -> RespuestaExtraccionLLM:
    """Puede lanzar `json.JSONDecodeError` o `pydantic.ValidationError` —
    quien llama decide si reintenta (ver `extraer_con_llm`)."""
    datos = json.loads(_extraer_json(texto))
    return RespuestaExtraccionLLM.model_validate(datos)


@dataclass
class ResultadoLLM:
    respuesta: RespuestaExtraccionLLM | None
    intentos: int
    error: str | None = None


def extraer_con_llm(
    texto_paginas: str,
    dominio: str | None,
    resultado_reglas: DatosLegalesExtraidos,
    cliente: Anthropic | None = None,
) -> ResultadoLLM:
    """Llama al modelo de extracción con reintento (máx. `MAX_REINTENTOS`)
    pasando el error de validación de vuelta, como pide `prompts.md`
    (cabecera). Si tras agotar los reintentos sigue sin ser JSON válido,
    devuelve `respuesta=None` — nunca un resultado a medio validar.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        return ResultadoLLM(respuesta=None, intentos=0, error="ANTHROPIC_API_KEY no configurada")
    cliente = cliente or Anthropic(api_key=settings.anthropic_api_key)

    mensajes: list[MessageParam] = [{"role": "user", "content": construir_prompt(texto_paginas, dominio, resultado_reglas)}]
    ultimo_error: str | None = None
    for intento in range(1, MAX_REINTENTOS + 2):
        respuesta = cliente.messages.create(model=settings.modelo_extraccion, max_tokens=1024, messages=mensajes)
        texto_respuesta = "".join(bloque.text for bloque in respuesta.content if bloque.type == "text")
        try:
            return ResultadoLLM(respuesta=parsear_respuesta(texto_respuesta), intentos=intento)
        except (json.JSONDecodeError, ValidationError) as exc:
            ultimo_error = str(exc)
            mensajes.append({"role": "assistant", "content": texto_respuesta})
            mensajes.append(
                {"role": "user", "content": f"Tu respuesta no es JSON válido según el esquema pedido: {exc}\nCorrígela y responde SOLO con el JSON."}
            )
    return ResultadoLLM(respuesta=None, intentos=MAX_REINTENTOS + 1, error=ultimo_error)
