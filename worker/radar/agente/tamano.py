"""Filtro de plantilla («de 10 a 200 empleados») sobre los resultados de una
búsqueda (2026-10-23).

Antes el filtro de tamaño solo se guardaba: ninguna fuente daba la plantilla.
Ahora la dan LinkedIn (tramo de su página de empresa) y la web propia cuando lo
dice (`radar.normalizacion.plantilla`), y se consolida en
`empresas.empleados_min/max`. Esta fase, al final de la búsqueda:

- descarta («descartado», con el motivo y la fuente) las empresas cuya
  plantilla CONOCIDA está fuera del rango pedido;
- deja las de plantilla desconocida, porque no hay dato para descartarlas
  (principio 5: nunca inventar). El panel muestra la columna «Plantilla» para
  distinguirlas.

Como el filtro de autónomos, nunca toca un resultado que una persona ya revisó
y lo descartado se puede recuperar en la Cola de revisión.
"""

from __future__ import annotations

from typing import Any

import psycopg

from radar.agente.interpretacion import FiltrosBusqueda
from radar.normalizacion.plantilla import encaje_en_filtro, texto_rango

_SQL = """
select br.empresa_id::text, e.empleados_min, e.empleados_max, e.tamano_fuente
from busqueda_resultados br join empresas e on e.id = br.empresa_id
where br.busqueda_id = %s and e.fusionada_en is null and not br.relevancia_revisada
  and coalesce(br.clasificacion, '') not in ('descartado', 'rechazado')
"""


def tiene_filtro_de_plantilla(filtros: FiltrosBusqueda) -> bool:
    return filtros.tamano.empleados_min is not None or filtros.tamano.empleados_max is not None


def motivo_fuera(minimo: int | None, maximo: int | None, fuente: str | None, filtros: FiltrosBusqueda) -> str:
    pedido = texto_rango(filtros.tamano.empleados_min, filtros.tamano.empleados_max)
    origen = f" ({fuente})" if fuente else ""
    return f"Plantilla fuera del rango pedido ({pedido} empleados): {texto_rango(minimo, maximo)} empleados{origen}"


def filtrar_por_plantilla(conn: psycopg.Connection, filtros: FiltrosBusqueda, busqueda_id: str) -> dict[str, Any]:
    if not tiene_filtro_de_plantilla(filtros):
        return {"motivo_parada": "la búsqueda no pide un número de empleados", "coste_eur": 0.0}
    cuenta = {"revisadas": 0, "dentro": 0, "fuera": 0, "sin_dato": 0}
    for empresa_id, minimo, maximo, fuente in conn.execute(_SQL, (busqueda_id,)).fetchall():
        cuenta["revisadas"] += 1
        rango = (minimo, maximo) if minimo is not None or maximo is not None else None
        encaje = encaje_en_filtro(rango, filtros.tamano.empleados_min, filtros.tamano.empleados_max)
        if encaje == "desconocido":
            cuenta["sin_dato"] += 1
        elif encaje == "dentro":
            cuenta["dentro"] += 1
        else:
            cuenta["fuera"] += 1
            conn.execute(
                "update busqueda_resultados set clasificacion = 'descartado', motivo_relevancia = %s "
                "where busqueda_id = %s and empresa_id = %s and not relevancia_revisada",
                (motivo_fuera(minimo, maximo, fuente, filtros), busqueda_id, empresa_id),
            )
    conn.commit()
    return {**cuenta, "coste_eur": 0.0}
