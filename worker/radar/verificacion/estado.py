"""Estado de la empresa: ¿sigue existiendo? (doc 05 §4).

`determinar_estado` recibe las señales ya detectadas (por el orquestador,
a partir de observaciones vigentes de cada fuente) y aplica la máquina de
reglas del doc 05 §4 **en orden**: la primera regla que aplica fija el
estado. Los valores de `estado_empresa` son los del enum de doc 03b.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EstadoEmpresa = Literal[
    "activa",
    "probablemente_activa",
    "dudosa",
    "inactiva",
    "en_liquidacion",
    "en_concurso",
    "disuelta",
    "extinguida",
    "desconocida",
]


@dataclass
class SenalesEstado:
    """Una señal por grupo de independencia (doc 05 §4.6: "cada una de un
    grupo independiente"): BORME/BOE, Google Places, web propia,
    contratación pública y redes sociales son grupos distintos, así que
    cada campo booleano de abajo ya representa como máximo una señal.

    Los campos de la sección "duras" (1-5) cortocircuitan la evaluación en
    cuanto son ``True``, en el orden en que aparecen. Los de "señales"
    (6) solo se usan si ninguna de las duras aplicó.
    """

    # --- Reglas duras 1-5 (doc 05 §4), evaluadas en este orden ---
    borme_extincion: bool = False
    # "con_liquidacion" | "sin_liquidacion" | None
    borme_disolucion: Literal["con_liquidacion", "sin_liquidacion"] | None = None
    borme_concurso: bool = False
    boe_revocacion_nif: bool = False
    google_cerrado_permanentemente: bool = False

    # --- Señales positivas (doc 05 §4.6), una por grupo independiente ---
    web_viva_reciente: bool = False  # <=12 meses, doc 05 §4: "Web viva"
    adjudicacion_publica_reciente: bool = False  # <=24 meses
    acto_societario_no_extintivo_reciente: bool = False  # BORME, <=24 meses
    google_operativo: bool = False
    actividad_redes_reciente: bool = False

    # Señales negativas: el doc 05 §1 solo menciona "dominio que no resuelve
    # o está caducado" como ejemplo; aquí se generaliza a un contador para
    # que el orquestador pueda sumar cualquier señal negativa detectada
    # (web caída, teléfono desconectado, etc.) sin acoplar este módulo a
    # una lista cerrada.
    senales_negativas: int = 0


def _contar_positivas(s: SenalesEstado) -> int:
    return sum(
        [
            s.web_viva_reciente,
            s.adjudicacion_publica_reciente,
            s.acto_societario_no_extintivo_reciente,
            s.google_operativo,
            s.actividad_redes_reciente,
        ]
    )


def determinar_estado(senales: SenalesEstado) -> tuple[EstadoEmpresa, float]:
    """Devuelve ``(estado, estado_confianza)`` según doc 05 §4.

    Las confianzas de las reglas duras 1-2 y 4 son las del doc (0,95 y
    0,90). El resto (concurso, cerrado_permanentemente, y el bloque de
    señales 6) no tienen número en el doc — son valores iniciales
    razonables, a calibrar con el golden set como el resto de umbrales de
    este proyecto (doc 05, cabecera).
    """
    if senales.borme_extincion:
        return "extinguida", 0.95
    if senales.borme_disolucion == "con_liquidacion":
        return "en_liquidacion", 0.95
    if senales.borme_disolucion == "sin_liquidacion":
        return "disuelta", 0.95
    if senales.borme_concurso:
        return "en_concurso", 0.90
    if senales.boe_revocacion_nif:
        return "inactiva", 0.90
    if senales.google_cerrado_permanentemente:
        positivas = _contar_positivas(senales)
        if positivas == 0:
            return "inactiva", 0.85
        return "dudosa", 0.60

    positivas = _contar_positivas(senales)
    negativas = senales.senales_negativas

    if positivas > 0 and negativas > 0:
        # Doc 05 §4.6: "señales positivas y negativas a la vez → dudosa".
        return "dudosa", 0.55
    if positivas >= 2:
        return "activa", 0.85
    if positivas == 1:
        return "probablemente_activa", 0.65
    if negativas > 0:
        # No está en el doc como caso explícito; se trata como "inactiva"
        # (enum doc 03b: "sin actividad detectable"), no como "dudosa"
        # (que el propio enum reserva para señales contradictorias).
        return "inactiva", 0.55
    return "desconocida", 0.30
