"""Descubrimiento por zona y palabras clave con Google Maps vía Apify
(`compass/crawler-google-places`), alternativa de scraping no oficial a
`radar.agente.descubrir_places` (API oficial de Google). A diferencia de
Places, aquí SÍ se guarda el registro completo (nombre, dirección, teléfono,
web, coordenadas) como una fuente normal más -- igual que OSM --, porque no
está sujeto a las condiciones de la API oficial de Google que solo permiten
persistir el `place_id`. La fiabilidad de la fuente ('apify_google_maps',
0.55, grupo_independencia='google') ya refleja que es scraping, no un
contrato con SLA.

Es la fuente que más datos de CONTACTO trae (teléfono en casi todos los
negocios, web en muchos). Por eso, además, cada web que devuelve Maps se lee
gratis con nuestro propio extractor (`enriquecer_desde_web`: aviso legal ->
razón social, NIF, email) y se procesa como una `web_empresa` más -- así el
registro de Maps y el de su web se unen en la misma empresa por dominio/NIF.

Coste (tarifas reales del plan FREE, `pricingInfo` del Actor, 2026-09-23):
0,004 $ por negocio + 0,00005 $ por arranque. NO se usa `skipClosedPlaces`
porque cobra 0,001 $ extra por negocio: los cerrados se descartan aquí
(`lugar_a_registro`). El número de negocios se calcula a partir del
presupuesto de la llamada y del tope mensual compartido de Apify.
"""

from __future__ import annotations

from typing import Any

import httpx
import psycopg

from radar.agente.consultas import zona_texto
from radar.agente.interpretacion import FiltrosBusqueda
from radar.extraccion import enriquecer_varias
from radar.fuentes.apify import ejecutar_actor
from radar.fuentes.apify_maps import lugar_a_registro
from radar.normalizacion.dominio import es_dominio_plataforma, extraer_dominio
from radar.orquestador import bd, procesar_registro
from radar.secretos import gasto_mes_apify_usd, obtener_token_apify, presupuesto_mensual_apify_usd

ACTOR_MAPS = "compass/crawler-google-places"
COSTE_POR_LUGAR_USD = 0.004
COSTE_ARRANQUE_USD = 0.001
MAX_LUGARES_POR_LLAMADA = 40


def lugares_para_presupuesto(tope_usd: float) -> int:
    """Cuántos negocios se pueden pedir sin pasar del tope (0 si no llega ni a uno)."""
    return max(0, min(MAX_LUGARES_POR_LLAMADA, int((tope_usd - COSTE_ARRANQUE_USD) / COSTE_POR_LUGAR_USD)))


def _web_propia(url: str | None) -> bool:
    dominio = extraer_dominio(url) if url else None
    return bool(dominio) and not es_dominio_plataforma(dominio)


async def procesar_items_maps(
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    items: list[dict[str, Any]],
    *,
    busqueda_id: str | None,
    telefonos_compartidos: set[str] | None,
    etiqueta: str = "apify_maps",
) -> dict[str, int]:
    """Procesa los negocios de Maps y, para cada uno con web propia, lee esa
    web (gratis) y la procesa también. Compartida con `completar_contacto`."""
    contadores = {
        "lugares_encontrados": len(items), "sin_nombre_o_cerrados": 0, "con_telefono": 0, "con_web": 0,
        "webs_leidas": 0, "vinculado": 0, "nueva_empresa": 0, "en_revision": 0, "ya_procesado": 0, "error_procesado": 0,
    }
    registros = [lugar_a_registro(item) for item in items]
    # Todas las webs a la vez (antes, una tras otra: minutos por búsqueda).
    webs = await enriquecer_varias(
        cliente_http, [r.campos.web for r in registros if r is not None and r.campos.web and _web_propia(r.campos.web)]
    )
    for registro in registros:
        if registro is None:
            contadores["sin_nombre_o_cerrados"] += 1
            continue
        contadores["con_telefono"] += bool(registro.campos.telefonos)
        contadores["con_web"] += bool(registro.campos.web)
        try:
            r = procesar_registro(registro, conn, busqueda_id=busqueda_id, telefonos_compartidos=telefonos_compartidos)
            if busqueda_id and r.empresa_id:
                bd.registrar_resultado_busqueda(busqueda_id, r.empresa_id, f"{etiqueta}: {r.accion}", r.puntuacion_match, conn)
            conn.commit()
            contadores[r.accion] += 1
        except Exception:  # noqa: BLE001 -- un lugar que falla no debe tirar el resto
            conn.rollback()
            contadores["error_procesado"] += 1
            continue

        if not _web_propia(registro.campos.web):
            continue
        registro_web = webs.get(registro.campos.web or "")
        if registro_web is None:
            continue
        contadores["webs_leidas"] += 1
        try:
            rw = procesar_registro(registro_web, conn, busqueda_id=busqueda_id, telefonos_compartidos=telefonos_compartidos)
            if busqueda_id and rw.empresa_id:
                bd.registrar_resultado_busqueda(busqueda_id, rw.empresa_id, f"{etiqueta}+web: {rw.accion}", rw.puntuacion_match, conn)
            conn.commit()
        except Exception:  # noqa: BLE001
            conn.rollback()
            contadores["error_procesado"] += 1
    return contadores


async def ejecutar_maps(
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    *,
    busquedas: list[str],
    zona: str | None,
    lugares_por_busqueda: int,
    tope_usd: float,
    detalle: dict[str, Any],
) -> tuple[list[dict[str, Any]], float, str | None, str | None]:
    """Lanza el Actor y registra el gasto. Devuelve (items, coste_usd, estado, error)."""
    token = obtener_token_apify(conn)
    if not token:
        return [], 0.0, None, "Apify no está configurado (falta el token en Ajustes)"
    entrada: dict[str, Any] = {
        "searchStringsArray": busquedas,
        "language": "es",
        "countryCode": "es",
        "maxCrawledPlacesPerSearch": lugares_por_busqueda,
    }
    if zona:
        entrada["locationQuery"] = zona
    res = await ejecutar_actor(
        cliente_http, token, ACTOR_MAPS, entrada,
        max_coste_usd=tope_usd, max_items=lugares_por_busqueda * len(busquedas), timeout_s=240,
    )
    bd.registrar_uso_apify(ACTOR_MAPS, res.run_id, res.estado, res.coste_usd, detalle, conn)
    conn.commit()
    return res.items, res.coste_usd, res.estado, res.error


async def descubrir_apify_maps(
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    filtros: FiltrosBusqueda,
    *,
    palabras_clave: list[str],
    max_coste_eur: float,
    busqueda_id: str | None = None,
    telefonos_compartidos: set[str] | None = None,
) -> dict[str, Any]:
    if not obtener_token_apify(conn):
        return {"soportado": False, "motivo": "Apify no está configurado (falta el token en Ajustes)", "coste_eur": 0.0}

    zona = zona_texto(filtros)
    if not zona:
        return {"error": "la búsqueda no tiene ninguna zona (municipio/provincia/CCAA)", "coste_eur": 0.0}
    palabras = [p.strip() for p in palabras_clave if p and p.strip()][:5]
    if not palabras:
        return {"error": "sin palabras clave para buscar en Maps", "coste_eur": 0.0}

    restante_mes = presupuesto_mensual_apify_usd(conn) - gasto_mes_apify_usd(conn)
    tope = min(max_coste_eur, restante_mes)
    total = lugares_para_presupuesto(tope)
    if total == 0:
        return {"motivo_parada": "presupuesto_insuficiente_para_apify", "coste_eur": 0.0}
    por_busqueda = max(1, total // len(palabras))

    items, coste, estado, error = await ejecutar_maps(
        conn, cliente_http, busquedas=palabras, zona=zona, lugares_por_busqueda=por_busqueda, tope_usd=tope,
        detalle={"zona": zona, "palabras_clave": palabras, "lugares_por_busqueda": por_busqueda},
    )
    contadores = await procesar_items_maps(
        conn, cliente_http, items, busqueda_id=busqueda_id, telefonos_compartidos=telefonos_compartidos
    )
    return {**contadores, "zona": zona, "estado_apify": estado, "error": error, "coste_eur": round(coste, 4)}
