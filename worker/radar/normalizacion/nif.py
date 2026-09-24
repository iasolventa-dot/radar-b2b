"""Validación y normalización de NIF/CIF/DNI/NIE (doc 05 §1).

El NIF es la clave maestra de una persona jurídica (principio no negociable
del proyecto): dos NIF válidos distintos son siempre empresas distintas,
aunque compartan nombre, web o teléfono.
"""

from __future__ import annotations

import math
import re

_LETRAS_DNI = "TRWAGMYFPDXBNJZSQVHLCKE"
_LETRAS_CONTROL_CIF = "JABCDEFGHI"
_LETRAS_CIF = "ABCDEFGHJNPQRSUVW"

# Letra inicial del NIF → formas jurídicas compatibles (doc 05 §1: "la letra
# inicial indica tipo de entidad"). Códigos tal como los produce
# `radar.normalizacion.nombre.extraer_forma_juridica`.
FORMA_POR_LETRA: dict[str, set[str]] = {
    "A": {"SA", "SAU", "SAL"},
    "B": {"SL", "SLU", "SLL", "SLNE"},
    "C": {"SC"},  # sociedades colectivas
    "D": set(),  # comanditarias
    "E": {"CB"},
    "F": {"SCOOP", "SCA"},
    "G": set(),  # asociaciones, fundaciones
    "H": set(),  # comunidades de propietarios
    "J": {"SC", "SCP"},
    "U": set(),  # UTE
    "V": set(),
}


def _letra_dni(numero: int) -> str:
    return _LETRAS_DNI[numero % 23]


def _control_cif(siete_digitos: str) -> tuple[str, str]:
    """Devuelve (digito_control, letra_control) para los 7 dígitos centrales de un CIF."""
    d = [int(c) for c in siete_digitos]
    pares = d[1] + d[3] + d[5]
    impares = sum(sum(divmod(2 * x, 10)) for x in (d[0], d[2], d[4], d[6]))
    control = (10 - (pares + impares) % 10) % 10
    return str(control), _LETRAS_CONTROL_CIF[control]


def normalizar_nif(nif: object) -> str:
    """Mayúsculas, sin espacios/guiones/puntos, sin prefijo VAT 'ES' (doc 05 §1)."""
    if nif is None or (isinstance(nif, float) and math.isnan(nif)):
        return ""
    n = re.sub(r"[^A-Za-z0-9]", "", str(nif)).upper()
    if n.startswith("ES") and len(n) == 11:  # formato VAT intracomunitario
        n = n[2:]
    return n


def validar_nif(nif: object) -> dict:
    """Valida NIF de sociedad (CIF), DNI, NIE y NIF especiales K/L/M.

    Devuelve ``{nif, valido, tipo, persona_fisica, aviso}``.
    """
    n = normalizar_nif(nif)
    r: dict = {"nif": n, "valido": False, "tipo": None, "persona_fisica": None, "aviso": None}
    if not n:
        r["aviso"] = "vacío"
        return r
    if re.fullmatch(r"\d{8}[A-Z]", n):
        r.update(tipo="dni", persona_fisica=True, valido=n[-1] == _letra_dni(int(n[:8])))
    elif re.fullmatch(r"[XYZ]\d{7}[A-Z]", n):
        num = int(str("XYZ".index(n[0])) + n[1:8])
        r.update(tipo="nie", persona_fisica=True, valido=n[-1] == _letra_dni(num))
    elif re.fullmatch(r"[KLM]\d{7}[A-Z]", n):
        r.update(tipo="nif_especial", persona_fisica=True, valido=n[-1] == _letra_dni(int(n[1:8])))
    elif re.fullmatch(r"[" + _LETRAS_CIF + r"]\d{7}[0-9A-J]", n):
        digito, letra = _control_cif(n[1:8])
        r.update(tipo="sociedad", persona_fisica=False, valido=n[-1] in (digito, letra))
        if r["valido"]:
            if n[0] in "ABEH" and n[-1] == letra and letra != digito:
                r["aviso"] = "control con letra en tipo que suele usar dígito"
            elif n[0] in "NPQRSW" and n[-1] == digito:
                r["aviso"] = "control con dígito en tipo que suele usar letra"
    else:
        r["aviso"] = "formato no reconocido"
        return r
    if not r["valido"]:
        r["aviso"] = "dígito/letra de control incorrecto"
    return r


FORMAS_SOCIETARIAS = set().union(*FORMA_POR_LETRA.values()) - {"CB"}


def dni_en_sociedad(forma: str | None, nif: str | None) -> bool:
    """Una sociedad (SL, SA, cooperativa...) nunca tiene DNI/NIE: si aparece
    uno, es el de una persona (administrador, titular de la web), no el suyo.
    Visto en vivo 2026-09-24: "ELING S.L.U." con NIF 08369853S. Una comunidad
    de bienes (CB) sí puede figurar con el NIF de un comunero."""
    return bool(forma in FORMAS_SOCIETARIAS and nif and validar_nif(nif)["persona_fisica"])


def forma_compatible_con_nif(forma: str | None, nif: str) -> bool | None:
    """None si no se puede juzgar; False si la letra del NIF contradice la forma jurídica."""
    if not forma or not nif or not nif[0].isalpha() or nif[0] in "XYZKLM":
        return None
    compatibles = FORMA_POR_LETRA.get(nif[0])
    if compatibles is None or not compatibles:
        return None
    return forma in compatibles
