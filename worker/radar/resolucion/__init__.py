"""Resolución de entidades (doc 05 §2): bloqueo (`blocking`) + puntuación de
duplicados (`scoring`). La decisión de fusionar, mandar a revisión o crear
una empresa nueva la toma el orquestador del pipeline a partir de
`scoring.comparar(...)["decision"]`.
"""

from radar.resolucion.scoring import UMBRAL_FUSION_AUTO, UMBRAL_REVISION, comparar

__all__ = ["UMBRAL_FUSION_AUTO", "UMBRAL_REVISION", "comparar"]
