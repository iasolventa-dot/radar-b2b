"""Extracción determinista de códigos CNAE explícitos en `objeto_social`
(BORME). Muchos actos de constitución ya traen el propio código en el
texto -- "Actividad principal: 43.99 / Otras actividades de construcción
especializada n.c.o.p." o variantes "CNAE: 5611", "CNAE 9531", "-CNAE
6421-" -- así que antes de gastar una llamada a LLM
(`radar.clasificacion.llm`) merece la pena mirar si el dato ya está ahí,
tal cual, sin inferir nada (principio 5 del proyecto: no inventar).

Pura: no toca la base de datos ni el LLM. Los códigos que devuelve son de
4 dígitos sin punto ("4399"), sin validar contra el catálogo `cnae` ni
resolver de qué versión son -- eso es `radar.clasificacion.candidatos`,
porque necesita la conexión.

Deliberadamente conservadora: si el texto no distingue con claridad cuál
código es la actividad principal (varios códigos sueltos sin marcar cuál
es cuál), devuelve todo vacío en vez de adivinar -- ese caso lo resuelve
el LLM con los candidatos de `buscar_candidatos_cnae`, no esta función.
Probada contra objeto_social reales capturados con BORME/Sevilla,
2026-09-18 (ver `tests/unit/test_clasificacion_reglas.py`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_RE_CODIGO_CON_BARRA = re.compile(r"(\d{2})\.(\d{2})\s*/")
_RE_CODIGO_CNAE_PALABRA = re.compile(r"CNAE\s*:?\s*-?\s*(\d{4})\b", re.IGNORECASE)
_RE_MARCA_PRINCIPAL = re.compile(r"actividad(?:es)?\s+principal(?:es)?\s*:?", re.IGNORECASE)
_RE_MARCA_OTRAS = re.compile(r"otras?\s+actividad(?:es)?\s*:?", re.IGNORECASE)


@dataclass
class CodigosExtraidos:
    principal: str | None = None
    secundarios: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.principal is not None


def _codigos_en(fragmento: str) -> list[str]:
    """Todos los códigos (4 dígitos, sin punto) del fragmento, en el orden
    en que aparecen -- primero el formato "NN.NN /" (el más frecuente,
    siempre va pegado a una descripción) y luego "CNAE NNNN" (suelto, sin
    descripción detrás)."""
    encontrados: list[tuple[int, str]] = []
    for m in _RE_CODIGO_CON_BARRA.finditer(fragmento):
        encontrados.append((m.start(), m.group(1) + m.group(2)))
    for m in _RE_CODIGO_CNAE_PALABRA.finditer(fragmento):
        encontrados.append((m.start(), m.group(1)))
    encontrados.sort(key=lambda par: par[0])
    vistos: list[str] = []
    for _, codigo in encontrados:
        if codigo not in vistos:
            vistos.append(codigo)
    return vistos


def extraer_codigos_explicitos(objeto_social: str | None) -> CodigosExtraidos:
    """Si el texto ya trae el código CNAE tal cual, lo devuelve sin
    inferir nada. `CodigosExtraidos()` vacío si no hay ninguno o el texto
    no distingue principal/secundarias con seguridad."""
    if not objeto_social:
        return CodigosExtraidos()

    marca_principal = _RE_MARCA_PRINCIPAL.search(objeto_social)
    if marca_principal:
        marca_otras = _RE_MARCA_OTRAS.search(objeto_social, pos=marca_principal.end())
        fin_principal = marca_otras.start() if marca_otras else len(objeto_social)
        zona_principal = objeto_social[marca_principal.end() : fin_principal]
        codigos_principal = _codigos_en(zona_principal)
        principal = codigos_principal[0] if codigos_principal else None

        secundarios: list[str] = []
        if marca_otras:
            zona_otras = objeto_social[marca_otras.end() :]
            secundarios = [c for c in _codigos_en(zona_otras) if c != principal]

        return CodigosExtraidos(principal=principal, secundarios=secundarios)

    # Sin "actividad principal" explícito: con un único código en todo el
    # texto, se asume que es la actividad principal (empresa de objeto
    # único). Con dos o más sueltos no hay forma fiable de saber cuál es
    # la principal sin inferir -- se deja vacío a propósito.
    codigos = _codigos_en(objeto_social)
    if len(codigos) == 1:
        return CodigosExtraidos(principal=codigos[0])
    return CodigosExtraidos()
