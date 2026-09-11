"""Normalización y validación de teléfonos españoles a formato E.164 (doc 05 §1).

Nota (doc 02 §3, `worker/tests/golden` §0): para números no españoles en
producción hay que sustituir esta validación básica por `phonenumbers`
(ya está en las dependencias del worker). De momento cubre el caso de uso
del MVP (España).
"""

from __future__ import annotations

import math
import re


def normalizar_telefono(tel: object) -> dict:
    """→ ``{e164, valido, tipo: fijo|movil|especial|extranjero|None, aviso}``."""
    r: dict = {"e164": None, "valido": False, "tipo": None, "aviso": None}
    if tel is None or (isinstance(tel, float) and math.isnan(tel)):
        return r
    s = str(tel).strip()
    if isinstance(tel, float) and tel.is_integer():
        s = str(int(tel))
    s = re.sub(r"(ext|extensión|extension|ext\.)\s*\d+$", "", s, flags=re.IGNORECASE)
    digitos = re.sub(r"\D", "", s)
    if s.startswith("+") and not digitos.startswith("34"):
        r.update(
            e164="+" + digitos,
            tipo="extranjero",
            valido=8 <= len(digitos) <= 15,
            aviso="número no español: validar con libphonenumber",
        )
        return r
    if digitos.startswith("0034"):
        digitos = digitos[4:]
    elif digitos.startswith("34") and len(digitos) == 11:
        digitos = digitos[2:]
    if len(digitos) != 9:
        r["aviso"] = f"longitud {len(digitos)} (se esperaban 9 dígitos)"
        return r
    p = digitos[0]
    if p in "67":
        tipo = "movil"
    elif digitos[:2] in ("80", "90"):
        tipo = "especial"
    elif p in "89":
        tipo = "fijo"
    else:
        r["aviso"] = "prefijo no válido en España"
        return r
    r.update(e164="+34" + digitos, valido=True, tipo=tipo)
    if tipo == "especial":
        r["aviso"] = "número de tarificación especial: no usar como señal de identidad"
    return r
