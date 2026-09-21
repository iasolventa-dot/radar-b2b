"""Claves y ajustes que se editan desde el panel (sección "Ajustes") en vez
de en el `.env`. Viven en `configuracion_secretos` (migración
202609211000), tabla con RLS activado y sin políticas: solo este worker, que
conecta directo a Postgres, puede leerla o escribirla -- nunca el navegador.

Prioridad de la clave de Google Places: la guardada desde el panel gana sobre
`GOOGLE_PLACES_API_KEY` del `.env` (que sigue funcionando como respaldo).
"""

from __future__ import annotations

import psycopg

from radar.config import get_settings

CLAVE_PLACES = "google_places_api_key"
CLAVE_PLACES_PRESUPUESTO_MENSUAL = "google_places_presupuesto_mensual_eur"
PRESUPUESTO_MENSUAL_PLACES_POR_DEFECTO_EUR = 5.0
CLAVE_APIFY = "apify_api_token"
CLAVE_APIFY_PRESUPUESTO_MENSUAL = "apify_presupuesto_mensual_usd"
PRESUPUESTO_MENSUAL_APIFY_POR_DEFECTO_USD = 5.0


def obtener_secreto(clave: str, conn: psycopg.Connection) -> str | None:
    with conn.cursor() as cur:
        cur.execute("select valor from configuracion_secretos where clave = %s", (clave,))
        fila = cur.fetchone()
    return fila[0] if fila else None


def guardar_secreto(clave: str, valor: str, conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "insert into configuracion_secretos (clave, valor) values (%s, %s) "
            "on conflict (clave) do update set valor = excluded.valor, actualizado_en = now()",
            (clave, valor),
        )


def borrar_secreto(clave: str, conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("delete from configuracion_secretos where clave = %s", (clave,))


def obtener_clave_places(conn: psycopg.Connection) -> str | None:
    clave = (obtener_secreto(CLAVE_PLACES, conn) or get_settings().google_places_api_key or "").strip()
    return clave or None


def enmascarar(clave: str) -> str:
    """Solo para mostrar en el panel: nunca se devuelve la clave entera."""
    if len(clave) <= 8:
        return "•" * len(clave)
    return f"{clave[:4]}…{clave[-4:]}"


def presupuesto_mensual_places_eur(conn: psycopg.Connection) -> float:
    valor = obtener_secreto(CLAVE_PLACES_PRESUPUESTO_MENSUAL, conn)
    try:
        return float(valor) if valor is not None else PRESUPUESTO_MENSUAL_PLACES_POR_DEFECTO_EUR
    except ValueError:
        return PRESUPUESTO_MENSUAL_PLACES_POR_DEFECTO_EUR


def gasto_mes_places_eur(conn: psycopg.Connection) -> float:
    with conn.cursor() as cur:
        cur.execute(
            "select coalesce(sum(coste_eur), 0) from uso_google_places "
            "where creado_en >= date_trunc('month', now())"
        )
        fila = cur.fetchone()
    return float(fila[0]) if fila else 0.0


def obtener_token_apify(conn: psycopg.Connection) -> str | None:
    return (obtener_secreto(CLAVE_APIFY, conn) or "").strip() or None


def presupuesto_mensual_apify_usd(conn: psycopg.Connection) -> float:
    valor = obtener_secreto(CLAVE_APIFY_PRESUPUESTO_MENSUAL, conn)
    try:
        return float(valor) if valor is not None else PRESUPUESTO_MENSUAL_APIFY_POR_DEFECTO_USD
    except ValueError:
        return PRESUPUESTO_MENSUAL_APIFY_POR_DEFECTO_USD


def gasto_mes_apify_usd(conn: psycopg.Connection) -> float:
    with conn.cursor() as cur:
        cur.execute("select coalesce(sum(coste_usd), 0) from uso_apify where creado_en >= date_trunc('month', now())")
        fila = cur.fetchone()
    return float(fila[0]) if fila else 0.0
