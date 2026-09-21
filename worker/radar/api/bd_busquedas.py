"""Acceso a la tabla `busquedas` (doc 03b §5) para la API. Toca `conn` de
verdad — se prueba de forma manual/integración contra Supabase, igual que
`radar.orquestador.bd` (ver docstring de ese módulo); la traducción a/desde
jsonb que no depende de la conexión vive en `radar.api.estado`, que sí
tiene tests."""

from __future__ import annotations

import json
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
    usuario los confirme. Devuelve el `id` (uuid) como `str`.

    `estadisticas` pasa por `json.dumps(...)` antes del placeholder
    `%s::jsonb` — psycopg no adapta un `dict` de Python directamente
    (`serializar_estadisticas` devuelve un `dict`, no una cadena JSON), es
    la misma convención que ya declara el docstring de
    `radar.orquestador.bd`. Sin esto, todo `POST /busquedas` fallaba con
    `psycopg.ProgrammingError: cannot adapt type 'dict'` — no había forma
    de crear ni una sola búsqueda desde el panel.
    """
    with conn.cursor() as cur:
        cur.execute(
            "insert into busquedas (usuario_id, peticion, filtros, presupuesto_eur, estado, estadisticas) "
            "values (%s, %s, %s::jsonb, %s, 'interpretada', %s::jsonb) returning id",
            (
                usuario_id, peticion, filtros.model_dump_json(), presupuesto_eur,
                json.dumps(serializar_estadisticas([], max_rondas=0)),
            ),
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


def leer_opciones(conn: psycopg.Connection, busqueda_id: str) -> dict:
    """Casillas de fuentes de pago de esta búsqueda (columna `opciones`)."""
    with conn.cursor() as cur:
        cur.execute("select opciones from busquedas where id = %s", (busqueda_id,))
        fila = cur.fetchone()
    return dict(fila[0]) if fila and fila[0] else {}


def marcar_en_curso(
    conn: psycopg.Connection, busqueda_id: str, *, filtros: FiltrosBusqueda, max_rondas: int,
    usar_google_places: bool = False, usar_apify: bool = False,
) -> None:
    """Se llama al confirmar (`POST /busquedas/{id}/confirmar`), antes de
    lanzar el planificador en segundo plano. Si `filtros` viene editado
    respecto a la interpretación original, se sobrescribe aquí."""
    with conn.cursor() as cur:
        cur.execute(
            "update busquedas set estado = 'en_curso', filtros = %s::jsonb, estadisticas = %s::jsonb, "
            "opciones = %s::jsonb where id = %s",
            (
                filtros.model_dump_json(), json.dumps(serializar_estadisticas([], max_rondas=max_rondas)),
                json.dumps({"usar_google_places": usar_google_places, "usar_apify": usar_apify}), busqueda_id,
            ),
        )
    conn.commit()


def guardar_progreso_ronda(conn: psycopg.Connection, busqueda_id: str, *, rondas_hasta_ahora: list[RondaPlanificador], max_rondas: int, coste_gastado_eur: float) -> None:
    """`on_ronda` de `radar.agente.planificador.planificar` llama a esto
    (a través de un cierre en `radar.api.main`) tras cada ronda — abre su
    propia conexión (ver esa función), así que aquí solo hace el UPDATE."""
    with conn.cursor() as cur:
        cur.execute(
            "update busquedas set rondas = %s, coste_eur = %s, estadisticas = %s::jsonb where id = %s",
            (
                len(rondas_hasta_ahora), coste_gastado_eur,
                json.dumps(serializar_estadisticas(rondas_hasta_ahora, max_rondas=max_rondas)),
                busqueda_id,
            ),
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
            (
                estado, len(rondas), coste_gastado_eur,
                json.dumps(serializar_estadisticas(rondas, max_rondas=max_rondas, resultado=resultado)),
                busqueda_id,
            ),
        )
    conn.commit()


def solicitar_cancelacion(conn: psycopg.Connection, busqueda_id: str, *, resolver_inmediatamente: bool) -> str:
    """Marca `cancelar_solicitado = true` (migración 202609141400).

    Si no hay ningún bucle activo escuchando ese flag
    (`resolver_inmediatamente=True`, el caso de `estado='esperando_respuesta'`:
    el planificador ya paró solo al llamar a `preguntar_usuario`), se
    cierra el estado a `'cancelada'` aquí mismo — no hay nada corriendo que
    pueda hacerlo por su cuenta.

    Si sí hay un bucle activo (`estado='en_curso'`), solo se pone el flag;
    es el propio bucle (`radar.agente.planificador`, parámetro
    `debe_cancelar`) quien lo comprobará entre rondas y escribirá
    `estado='cancelada'` al terminar (vía `finalizar_busqueda_db`) — no se
    escribe el estado aquí para no arriesgarse a pisar una finalización
    normal que llegue casi al mismo tiempo (condición de carrera: el
    planificador podría terminar por `finalizar_busqueda` justo antes de
    comprobar el flag).

    Devuelve el estado resultante para la respuesta de la API.
    """
    with conn.cursor() as cur:
        if resolver_inmediatamente:
            cur.execute(
                "update busquedas set cancelar_solicitado = true, estado = 'cancelada', finalizado_en = now() "
                "where id = %s",
                (busqueda_id,),
            )
        else:
            cur.execute("update busquedas set cancelar_solicitado = true where id = %s", (busqueda_id,))
    conn.commit()
    return "cancelada" if resolver_inmediatamente else "en_curso"


def debe_cancelarse(conn: psycopg.Connection, busqueda_id: str) -> bool:
    """Lo llama el cierre `debe_cancelar` de `radar.api.main` en cada ronda
    — una consulta ligera (una sola columna), no `obtener_busqueda`
    completa, porque se ejecuta con mucha más frecuencia."""
    with conn.cursor() as cur:
        cur.execute("select cancelar_solicitado from busquedas where id = %s", (busqueda_id,))
        fila = cur.fetchone()
    return bool(fila[0]) if fila else False


def cerrar_busquedas_huerfanas(conn: psycopg.Connection) -> int:
    """Se llama una vez, al arrancar el worker (`lifespan` en
    `radar.api.main`) — no en cada request.

    El diseño es de un solo proceso, sin cola de verdad (docstring de
    `radar.api.main`): el bucle del planificador vive en la memoria de UN
    proceso Python, nunca se persiste ni se puede retomar en otro. Si ese
    proceso muere a mitad de una búsqueda (Ctrl+C, corte de luz, `git
    pull` con `--reload` reiniciando, lo que sea), la fila se queda en
    `estado='en_curso'` para siempre — no hay ningún otro proceso que
    vaya a recogerla nunca, ni el propio botón "Cancelar" puede hacer
    nada por ella: pide `cancelar_solicitado=true` y espera a un bucle
    que ya no existe.

    Por construcción de este diseño (un solo proceso), CUALQUIER fila que
    esté `en_curso` en el momento en que un proceso arranca tiene que ser
    de una ejecución anterior que ya no está corriendo — el proceso actual
    acaba de empezar, no puede haber creado él mismo ese trabajo. Así que
    se cierran todas, sin ambigüedad: `cancelada` si ya se les había
    pedido cancelar antes de que el proceso muriera, `error` en el resto.

    Devuelve cuántas cerró (para el mensaje de arranque en los logs)."""
    with conn.cursor() as cur:
        cur.execute(
            "update busquedas set "
            "  estado = case when cancelar_solicitado then 'cancelada' else 'error' end, "
            "  estadisticas = estadisticas || jsonb_build_object("
            "    'error', 'el proceso del worker se reinició o se cerró a mitad de esta búsqueda'"
            "  ), "
            "  finalizado_en = now() "
            "where estado = 'en_curso'"
        )
        n = cur.rowcount
    conn.commit()
    return n
