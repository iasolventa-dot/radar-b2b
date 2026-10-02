"""Google (Apify) en lotes paralelos y resultados parciales (2026-10-02: dos
ejecuciones se cortaban por tiempo, se cobraban y sus resultados se tiraban)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

import radar.agente.descubrir_google_search as g
from radar.fuentes.apify import ResultadoActor, ejecutar_actor


def test_resultados_parciales_de_una_ejecucion_cortada_por_tiempo() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/abort"):
            return httpx.Response(200, json={"data": {}})
        if request.method == "POST":
            return httpx.Response(201, json={"data": {"id": "r1", "status": "RUNNING", "defaultDatasetId": "d1"}})
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[{"searchQuery": {"term": "a"}, "organicResults": []}])
        return httpx.Response(200, json={"data": {"id": "r1", "status": "TIMED-OUT", "defaultDatasetId": "d1", "usageTotalUsd": 0.02}})

    async def correr() -> ResultadoActor:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await ejecutar_actor(c, "tok", "a/b", {}, intervalo_s=0.0)

    r = asyncio.run(correr())
    assert r.parcial and r.error is None and len(r.items) == 1 and r.coste_usd == 0.02


class _Conexion:
    def commit(self) -> None:
        pass


def test_las_consultas_se_reparten_en_lotes_y_se_unen_por_termino(monkeypatch) -> None:
    lotes_vistos: list[list[str]] = []

    async def actor(_c: Any, _t: str, _a: str, entrada: dict[str, Any], **k: Any) -> ResultadoActor:
        lote = entrada["queries"].split("\n")
        lotes_vistos.append(lote)
        assert k["timeout_s"] == 60 + g.SEGUNDOS_POR_CONSULTA * len(lote)
        return ResultadoActor(run_id="r", estado="SUCCEEDED", coste_usd=0.01,
                              items=[{"searchQuery": {"term": q}, "organicResults": [{"url": q}]} for q in reversed(lote)])

    monkeypatch.setattr(g, "ejecutar_actor", actor)
    monkeypatch.setattr(g.bd, "registrar_uso_apify", lambda *a, **k: None)
    consultas = [f"c{i}" for i in range(9)]
    res = asyncio.run(g.google_en_lotes(_Conexion(), None, "tok", consultas, tope_usd=0.5))  # type: ignore[arg-type]
    assert [len(lote) for lote in lotes_vistos] == [4, 4, 1]
    assert all(res.por_consulta[q]["organicResults"][0]["url"] == q for q in consultas)
    assert round(res.coste_usd, 3) == 0.03 and res.error is None
