"""Plantilla (número de empleados) de una empresa (2026-10-23).

Hasta ahora ningún conector la aportaba, así que el filtro «de 10 a 200
empleados» no tenía ningún efecto. Fuentes que sí la dan, sin coste nuevo:

- LinkedIn (Apify, ya conectado): el tramo declarado por la propia empresa en
  su página («11-50 employees»). `employeeCount` NO es la plantilla (son los
  miembros de LinkedIn que dicen trabajar allí) y no se usa.
- La web de la empresa, cuando lo dice explícitamente («un equipo de más de 40
  profesionales», «plantilla de 120 trabajadores»).

Aquí solo se interpreta el texto (código, sin LLM) y se decide si un rango
encaja con el filtro de la búsqueda.
"""

from __future__ import annotations

import re
from typing import Literal

Rango = tuple[int | None, int | None]

_NUM = r"(\d{1,3}(?:[.,]\d{3})+|\d{1,6})"


def _entero(texto: str) -> int:
    return int(re.sub(r"[.,]", "", texto))


def rango_empleados(texto: str | None) -> Rango | None:
    """'11-50 employees' -> (11, 50); '10,001+ employees' -> (10001, None);
    'más de 40' -> (40, None); 'entre 20 y 30' -> (20, 30); '120' -> (120, 120);
    'Myself only' / '1 employee' -> (1, 1). None si no se entiende."""
    if not texto:
        return None
    t = texto.strip().lower()
    if re.search(r"myself only|self-employed|solo yo", t):
        return (1, 1)
    m = re.search(rf"{_NUM}\s*(?:-|–|a|y|to)\s*{_NUM}", t)
    if m:
        a, b = _entero(m.group(1)), _entero(m.group(2))
        return (min(a, b), max(a, b))
    m = re.search(rf"{_NUM}\s*\+", t) or re.search(rf"(?:m[aá]s de|over|more than|\+)\s*{_NUM}", t)
    if m:
        return (_entero(m.group(1)), None)
    m = re.search(rf"(?:menos de|less than|under)\s*{_NUM}", t)
    if m:
        return (1, max(1, _entero(m.group(1)) - 1))
    m = re.search(_NUM, t)
    if m:
        n = _entero(m.group(1))
        return (n, n) if n > 0 else None
    return None


# Menciones explícitas en una web. Solo con una palabra de PERSONAS detrás
# (trabajadores, empleados, profesionales, personas...), para no confundir
# «más de 500 clientes» u «obras» con la plantilla.
_PERSONAS = r"(?:trabajador(?:es|as)|emplead[oa]s|profesionales|personas|t[eé]cnicos|operarios|colaboradores)"
_RX_PLANTILLA = [
    re.compile(
        rf"(?:plantilla|equipo(?:\s+humano)?|contamos\s+con|formado\s+por|compuest[oa]\s+por|integrad[oa]\s+por)"
        rf"[^.\n]{{0,40}}?((?:m[aá]s\s+de\s+|entre\s+{_NUM}\s+y\s+)?{_NUM}\s+{_PERSONAS})",
        re.IGNORECASE,
    ),
    re.compile(rf"\b((?:m[aá]s\s+de\s+){_NUM}\s+(?:trabajador(?:es|as)|emplead[oa]s|profesionales))\b", re.IGNORECASE),
    re.compile(rf"\b({_NUM}\s+(?:trabajador(?:es|as)|emplead[oa]s)\s+en\s+plantilla)\b", re.IGNORECASE),
]


def plantilla_en_texto(texto: str) -> str | None:
    """La primera mención explícita de la plantilla en el texto de una web,
    tal cual («más de 40 profesionales»), o None."""
    for rx in _RX_PLANTILLA:
        m = rx.search(texto or "")
        if m:
            frase = re.sub(r"\s+", " ", m.group(1)).strip()
            rango = rango_empleados(frase)
            # Cifras absurdas para una plantilla (años, códigos postales...).
            if rango and (rango[0] or 0) < 100000 and (rango[0] or 0) > 0:
                return frase
    return None


Encaje = Literal["dentro", "fuera", "desconocido"]


def encaje_en_filtro(rango: Rango | None, minimo: int | None, maximo: int | None) -> Encaje:
    """¿La plantilla conocida encaja con el filtro? Solo «fuera» si NO hay
    solape posible: un tramo de LinkedIn «2-10» con un filtro «10-200» se
    acepta (puede tener 10)."""
    if rango is None or (rango[0] is None and rango[1] is None):
        return "desconocido"
    bajo, alto = rango
    if minimo is not None and alto is not None and alto < minimo:
        return "fuera"
    if maximo is not None and bajo is not None and bajo > maximo:
        return "fuera"
    return "dentro"


def texto_rango(minimo: int | None, maximo: int | None) -> str:
    if minimo is None and maximo is None:
        return ""
    if minimo == maximo:
        return str(minimo)
    if maximo is None:
        return f"más de {minimo}"
    if minimo is None:
        return f"hasta {maximo}"
    return f"{minimo}-{maximo}"
