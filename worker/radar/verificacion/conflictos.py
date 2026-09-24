"""Contradicciones entre fuentes para un mismo campo de una empresa (2026-09-24).

`radar.verificacion.confianza.consolidar_campo` ya elige el valor más probable
de cada campo. Este módulo decide, cuando hay otro valor distinto que alguna
fuente afirma de verdad, a qué cola va la contradicción:

- 'resuelto_con_evidencia' («Cola de revisión»): hay evidencia fuerte para
  quedarse con el ganador. Se aplica sola; una persona solo confirma o deshace.
  Evidencia fuerte = varias fuentes independientes contra una sola; el valor
  alternativo es una observación claramente más antigua que otra igual o más
  fiable ha sustituido; lo respalda un registro oficial y al otro no; o hay una
  diferencia de confianza amplia.
- 'sin_contrastar' («Datos sin contrastar»): fuentes de fiabilidad parecida dan
  valores distintos y nada permite decidir. Se deja el más probable y decide
  una persona.

Solo campos de valor ÚNICO: una empresa tiene un NIF, una razón social, una
web principal. Teléfonos y emails son multivalor (una empresa tiene varios):
dos teléfonos distintos no se contradicen, se guardan los dos.
No toca la base de datos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from radar.verificacion.confianza import ResultadoConsolidacion, ValorConsolidado

CAMPOS_VALOR_UNICO = ("nif", "razon_social", "web")

# Un valor alternativo cuenta como contradicción solo si alguna fuente lo
# afirma con una confianza mínima (no un residuo muy decaído).
UMBRAL_ALTERNATIVA = 0.35
DIAS_DATO_ANTIGUO = 30
MARGEN_CONFIANZA_CLARO = 0.30

TipoConflicto = Literal["sin_contrastar", "resuelto_con_evidencia"]

ETIQUETA_CAMPO = {"nif": "NIF", "razon_social": "razón social", "web": "web"}


@dataclass
class ConflictoDetectado:
    campo: str
    tipo: TipoConflicto
    valor_elegido: str
    motivo: str
    alternativas: list[dict] = field(default_factory=list)


def _detalle(v: ValorConsolidado, observaciones: list[dict]) -> dict:
    propias = [o for o in observaciones if o.get("valor_norm") == v.valor]
    fuentes = sorted({o.get("fuente_nombre") or "?" for o in propias})
    originales = [o.get("valor_original") for o in propias if o.get("valor_original")]
    evidencias = [o.get("url_evidencia") for o in propias if o.get("url_evidencia")]
    return {
        "valor": originales[0] if originales else v.valor,
        "valor_norm": v.valor,
        "confianza": round(v.confianza_efectiva, 3),
        "n_fuentes_independientes": v.n_fuentes_independientes,
        "dias_desde_ultima": v.dias_desde_ultima,
        "registro_oficial": v.tiene_registro_oficial,
        "fuentes": fuentes,
        "evidencias": evidencias[:3],
    }


def _motivo_evidencia_fuerte(ganador: ValorConsolidado, alt: ValorConsolidado) -> str | None:
    if ganador.n_fuentes_independientes >= 2 and alt.n_fuentes_independientes == 1:
        return f"{ganador.n_fuentes_independientes} fuentes independientes coinciden; solo una da otro valor."
    if alt.dias_desde_ultima - ganador.dias_desde_ultima >= DIAS_DATO_ANTIGUO and ganador.confianza >= alt.confianza:
        return (
            f"El otro valor es un dato antiguo (hace {alt.dias_desde_ultima} días) y una fuente igual o más fiable "
            f"lo ha actualizado (hace {ganador.dias_desde_ultima} días)."
        )
    if ganador.tiene_registro_oficial and not alt.tiene_registro_oficial:
        return "Lo respalda un registro oficial; el otro valor no."
    if ganador.confianza_efectiva - alt.confianza_efectiva >= MARGEN_CONFIANZA_CLARO:
        return (
            f"Diferencia de confianza clara ({ganador.confianza_efectiva:.2f} frente a {alt.confianza_efectiva:.2f})."
        )
    return None


def clasificar_conflicto(resultado: ResultadoConsolidacion | None, observaciones: list[dict]) -> ConflictoDetectado | None:
    """`None` si no hay contradicción (un solo valor, o las alternativas son
    residuales). Si la hay, el ganador sigue siendo el de la consolidación."""
    if resultado is None or resultado.campo not in CAMPOS_VALOR_UNICO or len(resultado.valores) < 2:
        return None
    ganador = resultado.valores[0]
    # Una persona ya decidió este valor (fuente 'manual', desde el panel): no
    # se vuelve a abrir la contradicción aunque siga existiendo el otro dato.
    if any(o.get("grupo_independencia") == "manual" and o.get("valor_norm") == ganador.valor for o in observaciones):
        return None
    alternativas = [v for v in resultado.valores[1:] if v.valor != ganador.valor and v.confianza_efectiva >= UMBRAL_ALTERNATIVA]
    if not alternativas:
        return None

    motivos = [_motivo_evidencia_fuerte(ganador, alt) for alt in alternativas]
    etiqueta = ETIQUETA_CAMPO.get(resultado.campo, resultado.campo)
    if all(motivos):
        tipo: TipoConflicto = "resuelto_con_evidencia"
        motivo = str(motivos[0]) if len(set(motivos)) == 1 else " / ".join(dict.fromkeys(str(m) for m in motivos))
    else:
        tipo = "sin_contrastar"
        motivo = (
            f"Fuentes de fiabilidad parecida dan valores distintos de {etiqueta} y no hay evidencia suficiente "
            "para decidir; se muestra el más probable."
        )
    return ConflictoDetectado(
        campo=resultado.campo,
        tipo=tipo,
        valor_elegido=_detalle(ganador, observaciones)["valor"],
        motivo=motivo,
        alternativas=[_detalle(v, observaciones) for v in [ganador, *alternativas]],
    )
