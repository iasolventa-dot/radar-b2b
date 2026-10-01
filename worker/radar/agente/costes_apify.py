"""Conciliación del gasto de Apify al final de cada búsqueda (2026-10-01).

Apify termina de sumar lo cobrado (`usageTotalUsd`) unos segundos después de
acabar cada ejecución. Radar lo lee al terminar y, aunque ya relee hasta que
se estabiliza, en una comprobación contra la consola de Apify registraba un
~12 % menos del gasto real. Al final de la búsqueda se relee cada ejecución de
Apify lanzada durante ella, se corrige `uso_apify` (de él sale el tope
mensual) y la diferencia se suma al coste de la búsqueda como un paso más.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import psycopg

from radar.fuentes.apify import coste_real
from radar.secretos import obtener_token_apify


async def conciliar_costes_apify(
    conn: psycopg.Connection, cliente_http: httpx.AsyncClient, *, desde: datetime
) -> dict[str, Any]:
    """Relee las ejecuciones registradas en `uso_apify` desde `desde`. Si hay
    dos búsquedas a la vez, la diferencia se atribuye a la que concilie antes
    (el total del mes siempre queda bien)."""
    token = obtener_token_apify(conn)
    filas = conn.execute(
        "select id, run_id, coste_usd from uso_apify where run_id is not null and creado_en >= %s", (desde,)
    ).fetchall()
    if not token or not filas:
        return {"ejecuciones": 0, "ajuste_usd": 0.0, "coste_eur": 0.0}
    cab = {"Authorization": f"Bearer {token}"}
    ajuste = 0.0
    corregidas = 0
    for id_, run_id, coste in filas:
        real = await coste_real(cliente_http, cab, run_id)
        if real is not None and real > float(coste) + 1e-6:
            conn.execute("update uso_apify set coste_usd = %s where id = %s", (real, id_))
            ajuste += real - float(coste)
            corregidas += 1
    conn.commit()
    # 1 USD ≈ 1 EUR, mismo criterio que el resto de herramientas de Apify (D-04)
    return {"ejecuciones": len(filas), "corregidas": corregidas, "ajuste_usd": round(ajuste, 4), "coste_eur": round(ajuste, 4)}
