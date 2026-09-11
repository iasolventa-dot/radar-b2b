"""Normalización y validación deterministas de datos de empresas españolas
(doc 05 §1): NIF, teléfono, email/dominio, nombre/forma jurídica, dirección.

Punto de entrada: `radar.normalizacion.registro.normalizar_registro`.
"""

from radar.normalizacion.registro import normalizar_registro

__all__ = ["normalizar_registro"]
