"""Acceso a la tabla `busquedas` (doc 03b §5) para la API. Toca `conn` de
verdad — se prueba de forma manual/integración contra Supabase, igual que
`radar.orquestador.bd` (ver docstring de ese módulo); la traducción a/desde
jsonb que no depende de la conexión vive en `radar.api.estado`, que sí
tiene tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from radar.agente.interpretacion import FiltrosBusqueda
from radar.agente.planificador import ResultadoPlanificador, RondaPlanificador
from radar.api.estado import serializar_estadisticas


@dataclass
class BusquedaDB:
    id: str
    peticion: str
    filtros: dict[str, Any]
    presupuesto_eur: float
    estado: str
    rondas: int
    estadisticas: dict[str, Any]
    coste_eur: float
    creado_en: datetime
    finalizado_en: datetime | None


_COLUMNAS = "id, peticion, filtros, presupuesto_eur, estado, rondas, estadisticas, coste_eur, creado_en, finalizado_en"


def _fila_a_busqueda(fila: tuple[Any, ...]) -> BusquedaDB:
    return BusquedaDB(
        id=str(fila[0]), peticion=fila[1], filtros=fila[2], presupuesto_eur=float(fila[3]), estado=fila[4],
        rondas=fila[5], estadisticas=fila[6], coste_eur=float(fila[7]), creado_en=fila[8], finalizado_en=fila[9],
    )


def crear_busqueda(conn: psycopg.Connection, *, peticion: str, filtros: FiltrosBusqueda, presupuesto_eur: float, usuario_id: str | None) -> str:
    """Inserta con `estado='interpretada'` (ver `radar.api.estado`) —
    todavía no ha gastado ni un euro, solo guarda los filtros para que el
    usuario los confirme. Devuelve el `id` (uuid) como `str`."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into busquedas (usuario_id, peticion, filtros, presupuesto_eur, estado, estadisticas) "
            "values (%s, %s, %s::jsonb, %s, 'interpretada', %s::jsonb) returning id",
            (usuario_id, peticion, filtros.model_dump_json(), presupuesto_eur, serializar_estadisticas([], max_rondas=0)),
        )
        fila = cur.fetchone()
    if fila is None:
        raise RuntimeError("insert en busquedas no devolvió id (no debería pasar nunca)")
    conn.commit()
    return str(fila[0])


def obtener_busqueda(conn: psycopg.Connection, busqueda_id: str) -> BusquedaDB | None:
    with conn.cursor() as cur:
        cur.execute(f"select {_COLUMNAS} from busquedas where id = %s", (busqueda_id,))
        fila = cur.fetchone()
    return _fila_a_busqueda(fila) if fila is not None else None


def listar_busquedas(conn: psycopg.Connection, *, limite: int = 20) -> list[BusquedaDB]:
    with conn.cursor() as cur:
        cur.execute(f"select {_COLUMNAS} from busquedas order by creado_en desc limit %s", (limite,))
        filas = cur.fetchall()
    return [_fila_a_busqueda(f) for f in filas]


def marcar_en_curso(conn: psycopg.Connection, busqueda_id: str, *, filtros: FiltrosBusqueda, max_rondas: int) -> None:
    """Se llama al confirmar (`POST /busquedas/{id}/confirmar`), antes de
    lanzar el planificador en segundo plano. Si `filtros` viene editado
    respecto a la interpretación original, se sobrescribe aquí."""
    with conn.cursor() as cur:
        cur.execute(
            "update busquedas set estado = 'en_curso', filtros = %s::jsonb, estadisticas = %s::jsonb where id = %s",
            (filtros.model_dump_json(), serializar_estadisticas([], max_rondas=max_rondas), busqueda_id),
        )
    conn.commit()


def guardar_progreso_ronda(conn: psycopg.Connection, busqueda_id: str, *, rondas_hasta_ahora: list[RondaPlanificador], max_rondas: int, coste_gastado_eur: float) -> None:
    """`on_ronda` de `radar.agente.planificador.planificar` llama a esto
    (a través de un cierre en `radar.api.main`) tras cada ronda — abre su
    propia conexión (ver esa función), así que aquí solo hace el UPDATE."""
    with conn.cursor() as cur:
        cur.execute(
            "update busquedas set rondas = %s, coste_eur = %s, estadisticas = %s::jsonb where id = %s",
            (len(rondas_hasta_ahora), coste_gastado_eur, serializar_estadisticas(rondas_hasta_ahora, max_rondas=max_rondas), busqueda_id),
        )
    conn.commit()


def finalizar_busqueda_db(
    conn: psycopg.Connection,
    busqueda_id: str,
    *,
    estado: str,
    rondas: list[RondaPlanificador],
    max_rondas: int,
    coste_gastado_eur: float,
    resultado: ResultadoPlanificador,
) -> None:
    """`estado` ya viene decidido por `radar.api.estado.estado_final_de`."""
    with conn.cursor() as cur:
        cur.execute(
            "update busquedas set estado = %s, rondas = %s, coste_eur = %s, estadisticas = %s::jsonb, finalizado_en = now() where id = %s",
            (estado, len(rondas), coste_gastado_eur, serializar_estadisticas(rondas, max_rondas=max_rondas, resultado=resultado), busqueda_id),
        )
    conn.commit()
