"""Confianza global de la empresa (doc 05 §6).

Media ponderada de cuatro confianzas efectivas ya calculadas por el
orquestador (con `radar.verificacion.confianza.consolidar_campo` para
identidad/ubicación/contacto y `radar.verificacion.estado.determinar_estado`
para estado), con el tope del doc: sin NIF confirmado, la empresa no puede
superar 0,6 de confianza global.
"""

from __future__ import annotations

# Doc 05 §6
PESO_IDENTIDAD = 0.40
PESO_ESTADO = 0.25
PESO_UBICACION = 0.15
PESO_CONTACTO = 0.20

TOPE_SIN_NIF_CONFIRMADO = 0.6


def calcular_confianza_global(
    confianza_identidad: float | None,
    confianza_estado: float | None,
    confianza_ubicacion: float | None,
    confianza_contacto: float | None,
    nif_confirmado: bool,
) -> float:
    """`confianza_identidad` combina NIF + razón social (p. ej. la media o el
    mínimo de sus `confianza_efectiva` de `consolidar_campo`; lo decide el
    orquestador). Cualquier confianza ausente (``None``) cuenta como 0 —
    un dato que falta no puede subir la confianza global.
    """
    identidad = confianza_identidad or 0.0
    estado = confianza_estado or 0.0
    ubicacion = confianza_ubicacion or 0.0
    contacto = confianza_contacto or 0.0

    valor = (
        PESO_IDENTIDAD * identidad
        + PESO_ESTADO * estado
        + PESO_UBICACION * ubicacion
        + PESO_CONTACTO * contacto
    )
    if not nif_confirmado:
        valor = min(valor, TOPE_SIN_NIF_CONFIRMADO)
    return round(max(0.0, min(1.0, valor)), 4)
