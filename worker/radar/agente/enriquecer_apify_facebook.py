"""Enriquecimiento con páginas de empresa de Facebook vía Apify
(`apify/facebook-pages-scraper`). Recibe URLs de páginas de Facebook (p. ej.
encontradas por `descubrir_google_search` y devueltas sin procesar en
`candidatos_facebook` porque esa herramienta solo lee webs propias) y las pasa
por las mismas reglas que cualquier fuente (`procesar_registro`), con la
fuente 'facebook' (fiabilidad 0.60).
"""

from __future__ import annotations

from typing import Any

import httpx
import psycopg

from radar.fuentes.apify import ejecutar_actor
from radar.fuentes.apify_facebook import pagina_a_registro
from radar.normalizacion.dominio import extraer_dominio
from radar.orquestador import bd, procesar_registro
from radar.secretos import gasto_mes_apify_usd, obtener_token_apify, presupuesto_mensual_apify_usd

ACTOR_FACEBOOK = "apify/facebook-pages-scraper"
MAX_PAGINAS_POR_LLAMADA = 10
_DOMINIOS_FACEBOOK = {"facebook.com", "m.facebook.com", "fb.com"}


def _es_pagina_facebook(url: str) -> bool:
    return extraer_dominio(url) in _DOMINIOS_FACEBOOK


async def enriquecer_con_facebook(
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    *,
    urls: list[str],
    max_coste_eur: float,
    busqueda_id: str | None = None,
    telefonos_compartidos: set[str] | None = None,
) -> dict[str, Any]:
    token = obtener_token_apify(conn)
    if not token:
        return {"soportado": False, "motivo": "Apify no está configurado (falta el token en Ajustes)", "coste_eur": 0.0}

    validas = [u for u in dict.fromkeys(urls) if _es_pagina_facebook(u)][:MAX_PAGINAS_POR_LLAMADA]
    descartadas = len(set(urls)) - len(validas)
    if not validas:
        return {"error": "ninguna URL es una página de Facebook", "urls_descartadas": descartadas, "coste_eur": 0.0}

    restante_mes = presupuesto_mensual_apify_usd(conn) - gasto_mes_apify_usd(conn)
    tope = min(max_coste_eur, restante_mes)
    if tope <= 0:
        return {"motivo_parada": "presupuesto_mensual_de_apify_agotado", "coste_eur": 0.0}

    entrada = {"startUrls": [{"url": u} for u in validas]}
    res = await ejecutar_actor(cliente_http, token, ACTOR_FACEBOOK, entrada, max_coste_usd=tope, timeout_s=120)

    bd.registrar_uso_apify(ACTOR_FACEBOOK, res.run_id, res.estado, res.coste_usd, {"urls": validas}, conn)
    conn.commit()

    contadores = {
        "paginas_enviadas": len(validas), "urls_descartadas": descartadas, "sin_nombre": 0,
        "vinculado": 0, "nueva_empresa": 0, "en_revision": 0, "ya_procesado": 0, "error_procesado": 0,
    }
    for item in res.items:
        registro = pagina_a_registro(item)
        if registro is None:
            contadores["sin_nombre"] += 1
            continue
        try:
            r = procesar_registro(registro, conn, busqueda_id=busqueda_id, telefonos_compartidos=telefonos_compartidos)
            if busqueda_id and r.empresa_id:
                bd.registrar_resultado_busqueda(busqueda_id, r.empresa_id, f"facebook: {r.accion}", r.puntuacion_match, conn)
            conn.commit()
            contadores[r.accion] += 1
        except Exception:  # noqa: BLE001
            conn.rollback()
            contadores["error_procesado"] += 1

    return {**contadores, "estado_apify": res.estado, "error": res.error, "coste_eur": round(res.coste_usd, 4)}
