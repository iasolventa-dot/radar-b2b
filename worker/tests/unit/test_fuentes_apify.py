"""Tests de `radar.fuentes.apify` con `httpx.MockTransport` -- sin red ni token real."""

import asyncio
import json

import httpx
import pytest

from radar.fuentes.apify import ActorNoPermitido, ejecutar_actor, probar_token, verificar_solicitud

TOKEN = "apify_api_TOKEN-SECRETO-DE-PRUEBA-123"


def _cliente(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "actor,entrada",
    [
        ("curious_coder/linkedin-profile-scraper", {}),
        ("compass/crawler-google-places", {"searchStringsArray": ["reformas"]}),
        ("apify/website-content-crawler", {"startUrls": [{"url": "https://www.linkedin.com/company/x"}]}),
        ("apify/instagram-scraper", None),
        ("apify/website-content-crawler", {"startUrls": [{"url": "https://facebook.com/x"}]}),
        ("apify/website-content-crawler", {"startUrls": [{"url": "https://www.google.com/maps/place/x"}]}),
    ],
)
def test_bloquea_plataformas_prohibidas(actor, entrada):
    with pytest.raises(ActorNoPermitido):
        verificar_solicitud(actor, entrada)


def test_permite_rastrear_una_web_propia():
    verificar_solicitud("apify/website-content-crawler", {"startUrls": [{"url": "https://reformasgarcia.es/"}]})


def test_dominio_que_solo_contiene_x_com_no_se_bloquea():
    verificar_solicitud("apify/website-content-crawler", {"startUrls": [{"url": "https://index.com/"}]})


def test_probar_token_ok_y_ko():
    async def run(status):
        def handler(req):
            assert req.headers["Authorization"] == f"Bearer {TOKEN}"
            if status == 200:
                return httpx.Response(200, json={"data": {"username": "solventa"}})
            return httpx.Response(status, json={"error": {"message": "User was not found or authentication token is not valid"}})

        async with _cliente(handler) as c:
            return await probar_token(c, TOKEN)

    ok, msg = asyncio.run(run(200))
    assert ok and "solventa" in msg
    ko, msg = asyncio.run(run(401))
    assert not ko and "not valid" in msg and TOKEN not in msg


def test_ejecutar_actor_flujo_completo_con_tope_de_coste():
    vistos = {"polls": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        ruta = req.url.path
        if req.method == "POST" and ruta == "/v2/actors/apify~website-content-crawler/runs":
            assert req.url.params["maxTotalChargeUsd"] == "0.25"
            vistos["entrada"] = json.loads(req.content)
            return httpx.Response(201, json={"data": {"id": "RUN1", "status": "READY"}})
        if ruta == "/v2/actor-runs/RUN1":
            vistos["polls"] += 1
            estado = "RUNNING" if vistos["polls"] < 2 else "SUCCEEDED"
            return httpx.Response(200, json={"data": {"id": "RUN1", "status": estado, "defaultDatasetId": "DS1", "usageTotalUsd": 0.0123}})
        if ruta == "/v2/datasets/DS1/items":
            return httpx.Response(200, json=[{"url": "https://a.es", "text": "hola"}])
        return httpx.Response(404)

    async def run():
        async with _cliente(handler) as c:
            return await ejecutar_actor(
                c, TOKEN, "apify/website-content-crawler", {"startUrls": [{"url": "https://a.es"}]},
                max_coste_usd=0.25, timeout_s=30, intervalo_s=0.0,
            )

    r = asyncio.run(run())
    assert r.error is None and r.estado == "SUCCEEDED"
    assert r.coste_usd == pytest.approx(0.0123)
    assert r.items == [{"url": "https://a.es", "text": "hola"}]
    assert vistos["entrada"]["startUrls"][0]["url"] == "https://a.es"


def test_ejecucion_fallida_devuelve_error_y_coste():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(201, json={"data": {"id": "R", "status": "READY"}})
        return httpx.Response(200, json={"data": {"status": "FAILED", "usageTotalUsd": 0.002}})

    async def run():
        async with _cliente(handler) as c:
            return await ejecutar_actor(c, TOKEN, "a/b", {}, intervalo_s=0.0)

    r = asyncio.run(run())
    assert r.error and "FAILED" in r.error and r.coste_usd == pytest.approx(0.002) and r.items == []


def test_error_http_no_filtra_el_token():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("fallo con " + TOKEN)

    async def run():
        async with _cliente(handler) as c:
            return await ejecutar_actor(c, TOKEN, "a/b", {}, intervalo_s=0.0)

    r = asyncio.run(run())
    assert r.error and TOKEN not in r.error


def test_ejecutar_actor_prohibido_no_hace_ninguna_peticion():
    llamadas = []

    def handler(req: httpx.Request) -> httpx.Response:
        llamadas.append(req)
        return httpx.Response(200, json={})

    async def run():
        async with _cliente(handler) as c:
            await ejecutar_actor(c, TOKEN, "curious_coder/linkedin-profile-scraper", {})

    with pytest.raises(ActorNoPermitido):
        asyncio.run(run())
    assert llamadas == []
