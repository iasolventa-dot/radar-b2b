"""Traducción pura (sin BD, sin red) entre las estructuras del planificador
(`radar.agente.planificador`) y lo que se guarda en `busquedas.estadisticas`
(jsonb, doc 03b §5) — aparte de `radar.api.bd_busquedas` para poder
testearla sin Postgres, mismo criterio que `radar.orquestador.logica` o
`radar.agente.herramientas.construir_where_empresas`.

Estados de `busquedas.estado` usados por esta API — el esquema (doc 03b)
solo documenta el campo como `text` con default `'pendiente'` y da como
ejemplo 'pendiente'/'en_curso'/'completada'/'cancelada'/'error'; aquí se
añaden dos intermedios que la tabla no preveía explícitamente pero que
hacen falta para el flujo de dos pasos "interpretar → confirmar" (doc 02
§2, paso 1) y para cuando el agente para a mitad de búsqueda con una
pregunta (`preguntar_usuario`):

- ``interpretada``: filtros generados, esperando que el usuario los
  confirme (o los edite) antes de gastar presupuesto.
- ``en_curso``: el planificador está ejecutando rondas.
- ``esperando_respuesta``: el planificador paró porque llamó a
  `preguntar_usuario` — no es un error ni un fin normal.
- ``completada`` / ``error``: fin normal (llamó a `finalizar_busqueda`) o
  fallo (API caída, sin presupuesto para ni una ronda, etc.).
"""

from __future__ import annotations

from typing import Any, Literal

from radar.agente.planificador import ResultadoPlanificador, RondaPlanificador

EstadoBusqueda = Literal["interpretada", "en_curso", "completada", "esperando_respuesta", "error"]


def serializar_ronda(ronda: RondaPlanificador) -> dict[str, Any]:
    return {
        "numero": ronda.numero,
        "herramienta": ronda.herramienta,
        "argumentos": ronda.argumentos,
        "resultado": ronda.resultado,
    }


def serializar_estadisticas(rondas: list[RondaPlanificador], *, max_rondas: int, resultado: ResultadoPlanificador | None = None) -> dict[str, Any]:
    """`resultado` se pasa solo cuando el bucle ya ha terminado (fin normal,
    pregunta o error) — mientras está en curso, `rondas` es la lista
    acumulada hasta el momento y no hay motivo/resumen/pregunta/error
    todavía."""
    estadisticas: dict[str, Any] = {"max_rondas": max_rondas, "rondas": [serializar_ronda(r) for r in rondas]}
    if resultado is not None:
        estadisticas["motivo_fin"] = resultado.motivo_fin
        estadisticas["resumen"] = resultado.resumen
        estadisticas["pregunta"] = resultado.pregunta
        estadisticas["error"] = resultado.error
    return estadisticas


def estado_final_de(resultado: ResultadoPlanificador) -> EstadoBusqueda:
    """Solo se llama cuando `planificar()` ya ha devuelto — decide en qué
    estado queda la búsqueda según cómo terminó el bucle (ver docstring del
    módulo)."""
    if resultado.error:
        return "error"
    if resultado.pregunta is not None:
        return "esperando_respuesta"
    return "completada"
