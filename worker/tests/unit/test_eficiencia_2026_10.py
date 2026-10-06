"""Ineficiencias corregidas el 2026-10-02 (sin red ni BD)."""

from __future__ import annotations

import asyncio
from typing import Any

import radar.agente.herramientas as h
from radar.agente.interpretacion import FiltrosBusqueda


class _Conexion:
    def rollback(self) -> None:
        pass

    def commit(self) -> None:
        pass


def _contexto() -> h.ContextoHerramientas:
    return h.ContextoHerramientas(conn=_Conexion(), cliente_http=None, filtros=FiltrosBusqueda(), presupuesto_restante_eur=1.0)  # type: ignore[arg-type]


def test_osm_deja_de_llamarse_tras_dos_llamadas_sin_fruto(monkeypatch) -> None:
    llamadas = {"n": 0}

    async def osm_vacio(*_a: Any, **_k: Any) -> dict[str, Any]:
        llamadas["n"] += 1
        return {"error_overpass": "timeout", "coste_eur": 0.0}

    monkeypatch.setattr(h, "descubrir_osm", osm_vacio)
    ctx = _contexto()
    for _ in range(4):
        r = asyncio.run(h.ejecutar_herramienta("descubrir_osm", {}, ctx))
    assert llamadas["n"] == 2
    assert "no se vuelve a consultar" in r["motivo_parada"]


def test_buscar_web_va_por_apify_si_hay_token(monkeypatch) -> None:
    import radar.agente.descubrir_google_search as dgs
    from radar import secretos

    monkeypatch.setattr(secretos, "obtener_token_apify", lambda _c: "tok")
    monkeypatch.setattr(secretos, "presupuesto_mensual_apify_usd", lambda _c: 5.0)
    monkeypatch.setattr(secretos, "gasto_mes_apify_usd", lambda _c: 1.0)
    monkeypatch.setattr(h, "provincias_de_zona", lambda *_a: set())

    async def google(*_a: Any, **k: Any) -> dict[str, Any]:
        return {"nueva_empresa": 3, "coste_eur": 0.009, "consultas": k["consultas"]}

    async def no_debe(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise AssertionError("no debería usar el buscador del modelo")

    monkeypatch.setattr(dgs, "descubrir_google_search", google)
    monkeypatch.setattr(h, "buscar_web", no_debe)
    r = asyncio.run(h.ejecutar_herramienta("buscar_web", {"consultas": ["fontaneros Utrera"], "max_coste_eur": 0.05}, _contexto()))
    assert r["via"] == "Google (Apify)" and r["nueva_empresa"] == 3


def test_buscar_web_sin_token_usa_el_buscador_del_modelo(monkeypatch) -> None:
    from radar import secretos

    monkeypatch.setattr(secretos, "obtener_token_apify", lambda _c: None)
    monkeypatch.setattr(h, "provincias_de_zona", lambda *_a: set())

    async def modelo(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {"nueva_empresa": 1, "coste_eur": 0.01}

    monkeypatch.setattr(h, "buscar_web", modelo)
    r = asyncio.run(h.ejecutar_herramienta("buscar_web", {"consultas": ["x"], "max_coste_eur": 0.05}, _contexto()))
    assert "via" not in r and r["nueva_empresa"] == 1


def test_tope_de_empresas_por_busqueda(monkeypatch) -> None:
    """2026-10-06: una búsqueda nacional llegó a 1.740 empresas y no pudo verificarlas."""
    monkeypatch.setattr(h, "progreso_busqueda", lambda _c, _b: {"empresas": h.MAX_EMPRESAS_BUSQUEDA})

    async def no_debe(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise AssertionError("no debería descubrir más")

    monkeypatch.setattr(h, "descubrir_osm", no_debe)
    ctx = _contexto()
    ctx.busqueda_id = "b"
    r = asyncio.run(h.ejecutar_herramienta("descubrir_osm", {}, ctx))
    assert "tope" in r["motivo_parada"] and r["coste_eur"] == 0.0


def test_empresas_extranjeras_fuera_de_zona() -> None:
    from radar.agente.herramientas import en_zona

    assert not en_zona(None, set(), telefonos=["+56227550549"], web="bielco.cl")
    assert not en_zona(None, set(), telefonos=[], web="https://constructora.com.co")
    assert en_zona(None, set(), telefonos=["+34954000000"], web="constructora.es")
    assert en_zona(None, set(), telefonos=["954000000"], web=None)
    assert en_zona("41001", {"41"}, telefonos=None, web="obras.com")


def test_formatos_de_telefono_espanol() -> None:
    from radar.agente.herramientas import parece_extranjera

    for t in ("(+34) 954 12 34 56", "954 12 34 56", "0034954123456", "+34-954-123-456"):
        assert not parece_extranjera([t], None), t
    assert parece_extranjera(["+57 310 425 8421"], None)
