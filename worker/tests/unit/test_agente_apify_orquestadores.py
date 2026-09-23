"""Tests de las rutas de guarda (sin token / sin presupuesto / argumentos
que faltan) de los cuatro orquestadores nuevos de Apify -- no llegan a tocar
BD ni red, así que no hace falta una conexión real."""

import asyncio

import pytest

from radar.agente.descubrir_apify_maps import descubrir_apify_maps
from radar.agente.descubrir_google_search import descubrir_google_search
from radar.agente.enriquecer_apify_facebook import enriquecer_con_facebook
from radar.agente.enriquecer_apify_linkedin import enriquecer_con_linkedin
from radar.agente.interpretacion import FiltrosBusqueda, UbicacionFiltro


def _sin_token(monkeypatch, modulo):
    monkeypatch.setattr(f"radar.agente.{modulo}.obtener_token_apify", lambda conn: None)


def _con_token_sin_presupuesto(monkeypatch, modulo):
    monkeypatch.setattr(f"radar.agente.{modulo}.obtener_token_apify", lambda conn: "apify_api_x" * 3)
    monkeypatch.setattr(f"radar.agente.{modulo}.presupuesto_mensual_apify_usd", lambda conn: 5.0)
    monkeypatch.setattr(f"radar.agente.{modulo}.gasto_mes_apify_usd", lambda conn: 5.0)


@pytest.mark.parametrize("modulo", ["descubrir_apify_maps", "descubrir_google_search", "enriquecer_apify_linkedin", "enriquecer_apify_facebook"])
def test_sin_token_no_soportado(monkeypatch, modulo):
    _sin_token(monkeypatch, modulo)
    filtros = FiltrosBusqueda(ubicacion=UbicacionFiltro(tipo="municipios", municipios=["Sevilla"]))
    llamadas = {
        "descubrir_apify_maps": lambda: descubrir_apify_maps(None, None, filtros, palabras_clave=["fontanería"], max_coste_eur=1.0),
        "descubrir_google_search": lambda: descubrir_google_search(None, None, consultas=["x"], max_coste_eur=1.0),
        "enriquecer_apify_linkedin": lambda: enriquecer_con_linkedin(None, None, nombres=["Acme"], max_coste_eur=1.0),
        "enriquecer_apify_facebook": lambda: enriquecer_con_facebook(None, None, urls=["https://facebook.com/x"], max_coste_eur=1.0),
    }
    r = asyncio.run(llamadas[modulo]())
    assert r["soportado"] is False and r["coste_eur"] == 0.0


def test_maps_sin_zona_en_filtros_da_error(monkeypatch):
    _con_token_sin_presupuesto(monkeypatch, "descubrir_apify_maps")
    r = asyncio.run(descubrir_apify_maps(None, None, FiltrosBusqueda(), palabras_clave=["fontanería"], max_coste_eur=1.0))
    assert "zona" in r["error"]


def test_maps_presupuesto_mensual_agotado(monkeypatch):
    monkeypatch.setattr("radar.agente.descubrir_apify_maps.obtener_token_apify", lambda conn: "apify_api_x" * 3)
    monkeypatch.setattr("radar.agente.descubrir_apify_maps.presupuesto_mensual_apify_usd", lambda conn: 5.0)
    monkeypatch.setattr("radar.agente.descubrir_apify_maps.gasto_mes_apify_usd", lambda conn: 5.0)
    filtros = FiltrosBusqueda(ubicacion=UbicacionFiltro(tipo="municipios", municipios=["Sevilla"]))
    r = asyncio.run(descubrir_apify_maps(None, None, filtros, palabras_clave=["fontanería"], max_coste_eur=1.0))
    assert r["motivo_parada"] == "presupuesto_insuficiente_para_apify"


def test_linkedin_sin_nombres_ni_urls_da_error(monkeypatch):
    _con_token_sin_presupuesto(monkeypatch, "enriquecer_apify_linkedin")
    r = asyncio.run(enriquecer_con_linkedin(None, None, max_coste_eur=1.0))
    assert "requiere" in r["error"]


def test_facebook_descarta_urls_que_no_son_de_facebook(monkeypatch):
    monkeypatch.setattr("radar.agente.enriquecer_apify_facebook.obtener_token_apify", lambda conn: "apify_api_x" * 3)
    r = asyncio.run(enriquecer_con_facebook(None, None, urls=["https://reformasx.es"], max_coste_eur=1.0))
    assert r["urls_descartadas"] == 1 and "ninguna" in r["error"]


def test_google_search_sin_consultas_da_error(monkeypatch):
    _con_token_sin_presupuesto(monkeypatch, "descubrir_google_search")
    r = asyncio.run(descubrir_google_search(None, None, consultas=[], max_coste_eur=1.0))
    assert "requiere" in r["error"]


def test_solo_paginas_de_facebook_no_posts_ni_grupos():
    from radar.agente.descubrir_google_search import es_pagina_facebook

    assert es_pagina_facebook("https://www.facebook.com/aluminiosperez/") is True
    assert es_pagina_facebook("https://www.facebook.com/groups/tricantinos3.0/posts/3495600063902626/") is False
