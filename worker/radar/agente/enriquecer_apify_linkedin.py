"""Enriquecimiento con LinkedIn vía Apify (`automation-lab/linkedin-company-scraper`).
Acepta nombres de empresa (el Actor resuelve la página pública más probable) o
URLs/slugs de LinkedIn ya conocidos. El dato es el que la empresa publica en su
propia página de empresa -- fuente 'linkedin' (fiabilidad 0.60), igual que
cualquier otra fuente: pasa por `procesar_registro` y se cruza con lo ya
guardado, nunca se da por buena solo porque lo diga el Actor.
"""

from __future__ import annotations

from typing import Any

import httpx
import psycopg

from radar.fuentes.apify import ejecutar_actor
from radar.fuentes.apify_linkedin import empresa_a_registro
from radar.orquestador import bd, procesar_registro
from radar.secretos import gasto_mes_apify_usd, obtener_token_apify, presupuesto_mensual_apify_usd

ACTOR_LINKEDIN = "automation-lab/linkedin-company-scraper"
MAX_EMPRESAS_POR_LLAMADA = 10


async def enriquecer_con_linkedin(
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    *,
    nombres: list[str] | None = None,
    urls: list[str] | None = None,
    max_coste_eur: float,
    busqueda_id: str | None = None,
    telefonos_compartidos: set[str] | None = None,
) -> dict[str, Any]:
    token = obtener_token_apify(conn)
    if not token:
        return {"soportado": False, "motivo": "Apify no está configurado (falta el token en Ajustes)", "coste_eur": 0.0}

    nombres = list(dict.fromkeys(nombres or []))[:MAX_EMPRESAS_POR_LLAMADA]
    urls = list(dict.fromkeys(urls or []))[: MAX_EMPRESAS_POR_LLAMADA - len(nombres)]
    if not nombres and not urls:
        return {"error": "enriquecer_con_linkedin requiere 'nombres' y/o 'urls'", "coste_eur": 0.0}

    restante_mes = presupuesto_mensual_apify_usd(conn) - gasto_mes_apify_usd(conn)
    tope = min(max_coste_eur, restante_mes)
    if tope <= 0:
        return {"motivo_parada": "presupuesto_mensual_de_apify_agotado", "coste_eur": 0.0}

    entrada = {"companyNames": nombres, "companyUrls": urls, "maxCompanies": len(nombres) + len(urls), "maxConcurrency": 3}
    res = await ejecutar_actor(cliente_http, token, ACTOR_LINKEDIN, entrada, max_coste_usd=tope, timeout_s=120)

    bd.registrar_uso_apify(ACTOR_LINKEDIN, res.run_id, res.estado, res.coste_usd, {"nombres": nombres, "urls": urls}, conn)
    conn.commit()

    contadores = {
        "empresas_buscadas": len(nombres) + len(urls), "sin_resolver": 0,
        "vinculado": 0, "nueva_empresa": 0, "en_revision": 0, "ya_procesado": 0, "error_procesado": 0,
    }
    for item in res.items:
        registro = empresa_a_registro(item)
        if registro is None:
            contadores["sin_resolver"] += 1
            continue
        try:
            r = procesar_registro(registro, conn, busqueda_id=busqueda_id, telefonos_compartidos=telefonos_compartidos)
            if busqueda_id and r.empresa_id:
                bd.registrar_resultado_busqueda(busqueda_id, r.empresa_id, f"linkedin: {r.accion}", r.puntuacion_match, conn)
            conn.commit()
            contadores[r.accion] += 1
        except Exception:  # noqa: BLE001
            conn.rollback()
            contadores["error_procesado"] += 1

    return {**contadores, "estado_apify": res.estado, "error": res.error, "coste_eur": round(res.coste_usd, 4)}
