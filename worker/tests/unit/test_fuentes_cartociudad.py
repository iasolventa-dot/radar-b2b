"""Tests de `radar.fuentes.cartociudad.geocodificar` con la API simulada
(`httpx.MockTransport`) — no dependen de red. La llamada real contra
`https://www.cartociudad.es` se verificó a mano el 2026-09-14 (ver
docstring del módulo): estos tests fijan ese comportamiento observado
para que no se rompa en silencio si algo cambia el código.
"""

from __future__ import annotations

import httpx
import pytest

from radar.fuentes.cartociudad import geocodificar


def _transporte(cuerpo: dict | list | None, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if cuerpo is None:
            return httpx.Response(status)
        return httpx.Response(status, json=cuerpo)

    return httpx.MockTransport(handler)


# Respuesta real observada para "Avenida de la Constitución 20, Sevilla, Sevilla"
RESPUESTA_PORTAL = {
    "province": "Sevilla", "muniCode": "41091", "type": "portal",
    "lat": 37.38594784454645, "lng": -5.994142844760804, "state": 0, "stateMsg": "",
}
RESPUESTA_CALLEJERO = {**RESPUESTA_PORTAL, "type": "callejero"}
# Observado con solo municipio+provincia, sin calle: apunta a un barrio
# cualquiera del municipio, no al centro -- por eso se rechaza (doc módulo).
RESPUESTA_POBLACION = {**RESPUESTA_PORTAL, "type": "poblacion", "address": "Urbanización Residencial Sevilla-Golf"}


def test_sin_direccion_no_llama_a_la_api():
    """Ni siquiera construye el `httpx.Client` -- si llamara, `_transporte`
    lanzaría porque no se le ha dado ninguno."""
    assert geocodificar(None, "Sevilla", "Sevilla") is None
    assert geocodificar("", "Sevilla", "Sevilla") is None


def test_portal_se_acepta():
    r = geocodificar("Avenida de la Constitución 20", "Sevilla", "Sevilla", _transporte=_transporte(RESPUESTA_PORTAL))
    assert r is not None
    assert r.tipo == "portal"
    assert r.lat == pytest.approx(37.38594784454645)
    assert r.lon == pytest.approx(-5.994142844760804)
    assert r.municipio_ine == "41091"


def test_callejero_se_acepta():
    r = geocodificar("Calle Sierpes", "Sevilla", "Sevilla", _transporte=_transporte(RESPUESTA_CALLEJERO))
    assert r is not None and r.tipo == "callejero"


def test_poblacion_se_rechaza():
    """El caso real que motivó el filtro: sin calle, CartoCiudad puede
    devolver un barrio cualquiera del municipio, no el centro -- guardarlo
    sería peor que no guardar nada (principio 5, nunca inventar)."""
    r = geocodificar("algo", "Alcalá de Guadaíra", "Sevilla", _transporte=_transporte(RESPUESTA_POBLACION))
    assert r is None


def test_sin_resultados_204():
    r = geocodificar("Calle Que No Existe De Verdad 987654", "Sevilla", "Sevilla", _transporte=_transporte(None, status=204))
    assert r is None


def test_state_distinto_de_cero_se_rechaza():
    r = geocodificar("algo", _transporte=_transporte({**RESPUESTA_PORTAL, "state": 1}))
    assert r is None


def test_json_invalido_no_lanza():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"no es json")

    r = geocodificar("algo", _transporte=httpx.MockTransport(handler))
    assert r is None


def test_error_de_red_no_lanza():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout simulado")

    r = geocodificar("algo", _transporte=httpx.MockTransport(handler))
    assert r is None


def test_municipio_igual_a_provincia_no_se_duplica_en_la_consulta():
    """El bug real que se encontró probando en vivo: "Calle Sierpes, Sevilla,
    Sevilla" (municipio y provincia con el mismo texto) resolvía a un
    municipio de OTRA provincia -- la query duplicada confundía el ranking
    del geocodificador. Aquí se comprueba que la consulta enviada no repite
    el nombre, no el resultado (eso ya lo cubre test_callejero_se_acepta)."""
    consultas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        consultas.append(request.url.params["q"])
        return httpx.Response(200, json=RESPUESTA_CALLEJERO)

    geocodificar("Calle Sierpes", "Sevilla", "Sevilla", _transporte=httpx.MockTransport(handler))
    assert consultas == ["Calle Sierpes, Sevilla"]


def test_municipio_distinto_de_provincia_si_se_incluyen_ambos():
    consultas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        consultas.append(request.url.params["q"])
        return httpx.Response(200, json=RESPUESTA_PORTAL)

    geocodificar("Calle Mayor 1", "Alcalá de Guadaíra", "Sevilla", _transporte=httpx.MockTransport(handler))
    assert consultas == ["Calle Mayor 1, Alcalá de Guadaíra, Sevilla"]
