"""Descubrimiento por zona y palabras clave con Google Maps vía Apify
(`compass/crawler-google-places`), alternativa de scraping no oficial a
`radar.agente.descubrir_places` (API oficial de Google). A diferencia de
Places, aquí SÍ se guarda el registro completo (nombre, dirección, teléfono,
web, coordenadas) como una fuente normal más -- igual que OSM --, porque no
está sujeto a las condiciones de la API oficial de Google que solo permiten
persistir el `place_id`. La fiabilidad de la fuente ('apify_google_maps',
0.55, grupo_independencia='google') ya refleja que es scraping, no un
contrato con SLA.

Presupuesto: tope por llamada y tope mensual compartido con el resto de usos
de Apify (`radar.secretos.presupuesto_mensual_apify_usd`/`gasto_mes_apify_usd`).
"""

from __future__ import annotations

from typing import Any

import httpx
import psycopg

from radar.agente.consultas import zona_texto
from radar.agente.interpretacion import FiltrosBusqueda
from radar.fuentes.apify import ejecutar_actor
from radar.fuentes.apify_maps import lugar_a_registro
from radar.orquestador import bd, procesar_registro
from radar.secretos import gasto_mes_apify_usd, obtener_token_apify, presupuesto_mensual_apify_usd

ACTOR_MAPS = "compass/crawler-google-places"
MAX_LUGARES_POR_CONSULTA = 30


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
    token = obtener_token_apify(conn)
    if not token:
        return {"soportado": False, "motivo": "Apify no está configurado (falta el token en Ajustes)", "coste_eur": 0.0}

    zona = zona_texto(filtros)
    if not zona:
        return {"error": "la búsqueda no tiene ninguna zona (municipio/provincia/CCAA)", "coste_eur": 0.0}
    if not palabras_clave:
        return {"error": "sin palabras clave para buscar en Maps", "coste_eur": 0.0}

    restante_mes = presupuesto_mensual_apify_usd(conn) - gasto_mes_apify_usd(conn)
    tope = min(max_coste_eur, restante_mes)
    if tope <= 0:
        return {"motivo_parada": "presupuesto_mensual_de_apify_agotado", "coste_eur": 0.0}

    entrada = {
        "searchStringsArray": palabras_clave,
        "locationQuery": zona,
        "language": "es",
        "countryCode": "es",
        "maxCrawledPlacesPerSearch": MAX_LUGARES_POR_CONSULTA,
        "skipClosedPlaces": True,
    }
    res = await ejecutar_actor(cliente_http, token, ACTOR_MAPS, entrada, max_coste_usd=tope, timeout_s=180)

    bd.registrar_uso_apify(ACTOR_MAPS, res.run_id, res.estado, res.coste_usd, {"zona": zona, "palabras_clave": palabras_clave}, conn)
    conn.commit()

    contadores = {
        "lugares_encontrados": len(res.items), "sin_nombre_o_cerrados": 0,
        "vinculado": 0, "nueva_empresa": 0, "en_revision": 0, "ya_procesado": 0, "error_procesado": 0,
    }
    for item in res.items:
        registro = lugar_a_registro(item)
        if registro is None:
            contadores["sin_nombre_o_cerrados"] += 1
            continue
        try:
            r = procesar_registro(registro, conn, busqueda_id=busqueda_id, telefonos_compartidos=telefonos_compartidos)
            if busqueda_id and r.empresa_id:
                bd.registrar_resultado_busqueda(busqueda_id, r.empresa_id, f"apify_maps: {r.accion}", r.puntuacion_match, conn)
            conn.commit()
            contadores[r.accion] += 1
        except Exception:  # noqa: BLE001 -- un lugar que falla no debe tirar el resto
            conn.rollback()
            contadores["error_procesado"] += 1

    return {**contadores, "zona": zona, "estado_apify": res.estado, "error": res.error, "coste_eur": round(res.coste_usd, 4)}
