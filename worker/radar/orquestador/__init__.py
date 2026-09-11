"""Orquestador del pipeline (doc 02 §2, pasos 6-8): junta
`radar.normalizacion`, `radar.resolucion` y `radar.verificacion` con la
base de datos para convertir los `RegistroBruto` de un conector en
`empresas` verificadas. Ver `procesar.procesar_registro`.
"""

from radar.orquestador.procesar import ResultadoResolucion, procesar_registro

__all__ = ["ResultadoResolucion", "procesar_registro"]
