"""Verificación (doc 05 §3-§6): confianza de campo, estado y confianza
global de la empresa. Consume observaciones ya normalizadas
(`radar.normalizacion`) y candidatos ya resueltos (`radar.resolucion`); no
toca la base de datos — eso lo hace el orquestador del pipeline.
"""

from radar.verificacion.confianza import (
    UMBRAL_MULTIVALOR,
    ResultadoConsolidacion,
    ValorConsolidado,
    consolidar_campo,
    semivida_dias,
)
from radar.verificacion.estado import SenalesEstado, determinar_estado
from radar.verificacion.global_ import calcular_confianza_global

__all__ = [
    "UMBRAL_MULTIVALOR",
    "ResultadoConsolidacion",
    "SenalesEstado",
    "ValorConsolidado",
    "calcular_confianza_global",
    "consolidar_campo",
    "determinar_estado",
    "semivida_dias",
]
