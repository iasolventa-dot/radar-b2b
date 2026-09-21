"""Tests de `radar.fuentes.places` con `httpx.MockTransport` -- sin red ni clave real."""

import asyncio
import json

import httpx

from radar.fuentes.places import (
    COSTE_PETICION_EUR,
    buscar_lugares,
    mensaje_error,
    parsear_lugares,
    probar_clave,
)

CLAVE = "AIzaSy-CLAVE-SECRETA-DE-PRUEBA-123456"

RESPUESTA = {
    "places": [
        {
            "id": "ChIJ_abc",
            "displayName": {"text": "Reformas García", "languageCode": "es"},
            "formattedAddress": "Calle Sierpes 1, 41004 Sevilla, España",
            "location": {"latitude": 37.39, "longitude": -5.99},
            "businessStatus": "OPERATIONAL",
            "websiteUri": "https://reformasgarcia.es/",
            "nationalPhoneNumber": "955 12 34 56",
        },
        {"id": "ChIJ_solo_id"},
        {"displayName": {"text": "sin id"}},
    ],
    "nextPageToken": "TOKEN2",
}


def _cliente(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_parsear_lugares_ignora_los_que_no_tienen_id():
    lugares = parsear_lugares(RESPUESTA)
    assert [l.place_id for l in lugares] == ["ChIJ_abc", "ChIJ_solo_id"]
    assert lugares[0].nombre == "Reformas García"
    assert lugares[0].web == "https://reformasgarcia.es/"
    assert (lugares[0].lat, lugares[0].lon) == (37.39, -5.99)
    assert lugares[1].nombre is None


def test_buscar_lugares_envia_clave_y_fieldmask_y_devuelve_coste():
    vistos = {}

    def handler(req: httpx.Request) -> httpx.Response:
        vistos["clave"] = req.headers["X-Goog-Api-Key"]
        vistos["mask"] = req.headers["X-Goog-FieldMask"]
        vistos["cuerpo"] = json.loads(req.content)
        return httpx.Response(200, json=RESPUESTA)

    async def run():
        async with _cliente(handler) as c:
            return await buscar_lugares(c, CLAVE, "constructora Sevilla")

    r = asyncio.run(run())
    assert vistos["clave"] == CLAVE
    assert "places.websiteUri" in vistos["mask"] and "nextPageToken" in vistos["mask"]
    assert vistos["cuerpo"]["regionCode"] == "ES" and vistos["cuerpo"]["pageSize"] == 20
    assert r.siguiente_pagina == "TOKEN2"
    assert r.coste_eur == COSTE_PETICION_EUR
    assert r.error is None


def test_solo_id_no_cuesta_nada():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["X-Goog-FieldMask"].startswith("places.id")
        return httpx.Response(200, json={"places": [{"id": "x"}]})

    async def run():
        async with _cliente(handler) as c:
            return await buscar_lugares(c, CLAVE, "x", solo_id=True)

    assert asyncio.run(run()).coste_eur == 0.0


def test_error_403_no_filtra_la_clave_y_no_cuesta():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "Places API (New) has not been used in project 123"}})

    async def run():
        async with _cliente(handler) as c:
            return await buscar_lugares(c, CLAVE, "x")

    r = asyncio.run(run())
    assert r.error and "403" in r.error and "Places API (New)" in r.error
    assert CLAVE not in r.error
    assert r.coste_eur == 0.0 and r.lugares == []


def test_error_de_red_no_filtra_la_clave():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("fallo con " + CLAVE)

    async def run():
        async with _cliente(handler) as c:
            return await buscar_lugares(c, CLAVE, "x")

    r = asyncio.run(run())
    assert r.error and CLAVE not in r.error


def test_probar_clave_ok_y_ko():
    async def run(status):
        def handler(req):
            return httpx.Response(status, json={"places": []} if status == 200 else {"error": {"message": "API key not valid"}})

        async with _cliente(handler) as c:
            return await probar_clave(c, CLAVE)

    ok, msg = asyncio.run(run(200))
    assert ok and "válida" in msg
    ko, msg = asyncio.run(run(400))
    assert not ko and "API key not valid" in msg


def test_mensaje_error_sin_cuerpo():
    assert mensaje_error(500, None) == "Google Places respondió 500"
