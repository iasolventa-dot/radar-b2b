"""Gasto real de Apify: relectura hasta estabilizarse, aborto al agotar la
espera y conciliación final (2026-10-01, contrastado con la consola de Apify)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

import radar.agente.costes_apify as costes
from radar.fuentes.apify import ejecutar_actor

TOKEN = "apify_api_PRUEBA"


def test_el_coste_se_relee_hasta_que_se_estabiliza() -> None:
    lecturas = iter([0.0, 0.010, 0.012, 0.012, 0.012])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={"data": {"id": "r1", "status": "SUCCEEDED", "defaultDatasetId": "d1"}})
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"data": {"id": "r1", "status": "SUCCEEDED", "usageTotalUsd": next(lecturas)}})

    async def correr() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await ejecutar_actor(c, TOKEN, "a/b", {}, intervalo_s=0.0)

    assert asyncio.run(correr()).coste_usd == 0.012


def test_si_se_agota_la_espera_se_aborta_la_ejecucion() -> None:
    abortadas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/abort"):
            abortadas.append(request.url.path)
            return httpx.Response(200, json={"data": {"status": "ABORTING"}})
        if request.method == "POST":
            return httpx.Response(201, json={"data": {"id": "r9", "status": "RUNNING"}})
        return httpx.Response(200, json={"data": {"id": "r9", "status": "RUNNING", "usageTotalUsd": 0.01}})

    async def correr() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await ejecutar_actor(c, TOKEN, "a/b", {}, intervalo_s=0.0, timeout_s=0)

    res = asyncio.run(correr())
    assert abortadas == ["/v2/actor-runs/r9/abort"]
    assert res.error


class _Conexion:
    def __init__(self, filas: list[tuple]) -> None:
        self.filas = filas
        self.actualizadas: list[tuple] = []

    def execute(self, sql: str, params: tuple) -> _Conexion:
        if sql.startswith("update"):
            self.actualizadas.append(params)
        return self

    def fetchall(self) -> list[tuple]:
        return self.filas

    def commit(self) -> None:
        pass


def test_conciliacion_corrige_solo_lo_que_cobro_de_mas(monkeypatch) -> None:
    reales = {"a": 0.0142, "b": 0.05}

    async def coste_real(_c: Any, _cab: Any, run_id: str) -> float:
        return reales[run_id]

    monkeypatch.setattr(costes, "coste_real", coste_real)
    monkeypatch.setattr(costes, "obtener_token_apify", lambda _c: TOKEN)
    conn = _Conexion([(1, "a", 0.0001), (2, "b", 0.05)])
    res = asyncio.run(costes.conciliar_costes_apify(conn, None, desde=datetime.now(UTC)))  # type: ignore[arg-type]
    assert conn.actualizadas == [(0.0142, 1)]
    assert res["ajuste_usd"] == 0.0141 and res["coste_eur"] == 0.0141
