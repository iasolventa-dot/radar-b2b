"""Descubrimiento con el buscador de Google vía Apify
(`apify/google-search-scraper`), alternativa con más control (paginación,
país, filtros) a `buscar_web` (que usa la búsqueda web nativa del LLM).

Cada URL de resultado orgánico se clasifica:
- web propia de empresa (no un boletín ni un directorio/red social) -> se
  descarga y se procesa como cualquier `web_empresa`
  (`radar.extraccion.enriquecer_desde_web` + `procesar_registro`), igual que
  `buscar_web`.
- facebook.com / linkedin.com -> no se procesan aquí (esta herramienta solo
  lee webs propias): se devuelven en `candidatos_facebook`/`candidatos_linkedin`
  para que el planificador decida si merece la pena llamar a
  `enriquecer_con_facebook` / `enriquecer_con_linkedin` con ellas.
- el resto de plataformas/boletines -> descartadas, igual que en `buscar_web`.
"""

from __future__ import annotations

from typing import Any

import httpx
import psycopg

from radar.agente.herramientas import _url_no_apta_para_enriquecer, en_zona
from radar.extraccion import enriquecer_desde_web
from radar.fuentes.apify import ejecutar_actor
from radar.normalizacion.dominio import extraer_dominio
from radar.orquestador import bd, procesar_registro
from radar.secretos import gasto_mes_apify_usd, obtener_token_apify, presupuesto_mensual_apify_usd

ACTOR_GOOGLE_SEARCH = "apify/google-search-scraper"
# Tarifas reales del plan FREE (pricingInfo del Actor, 2026-09-23).
COSTE_POR_PAGINA_USD = 0.0045
COSTE_ARRANQUE_USD = 0.001
MAX_CANDIDATOS_DEVUELTOS = 10
_DOMINIOS_FACEBOOK = {"facebook.com", "m.facebook.com", "fb.com"}
_DOMINIOS_LINKEDIN = {"linkedin.com"}
# Solo páginas de empresa: un post, grupo o evento de Facebook no tiene
# titular que extraer (visto en vivo 2026-09-23: se envió un post de grupo).
_RUTAS_NO_PAGINA_FACEBOOK = ("/groups/", "/posts/", "/events/", "/watch", "/photo", "/story.php", "/permalink.php", "/share/")
# Idem LinkedIn: solo /company/ (ofertas de empleo, perfiles personales y posts no).
_RUTA_EMPRESA_LINKEDIN = "/company/"


def es_pagina_facebook(url: str) -> bool:
    return not any(r in url for r in _RUTAS_NO_PAGINA_FACEBOOK)


async def descubrir_google_search(
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    *,
    consultas: list[str],
    max_paginas_por_consulta: int = 1,
    max_coste_eur: float,
    busqueda_id: str | None = None,
    telefonos_compartidos: set[str] | None = None,
    provincias_zona: set[str] | None = None,
) -> dict[str, Any]:
    token = obtener_token_apify(conn)
    if not token:
        return {"soportado": False, "motivo": "Apify no está configurado (falta el token en Ajustes)", "coste_eur": 0.0}
    if not consultas:
        return {"error": "descubrir_google_search requiere 'consultas' (lista no vacía)", "coste_eur": 0.0}

    restante_mes = presupuesto_mensual_apify_usd(conn) - gasto_mes_apify_usd(conn)
    tope = min(max_coste_eur, restante_mes)
    paginas_por_consulta = max(1, max_paginas_por_consulta)
    consultas = consultas[: int((tope - COSTE_ARRANQUE_USD) / COSTE_POR_PAGINA_USD) // paginas_por_consulta]
    if not consultas:
        return {"motivo_parada": "presupuesto_insuficiente_para_apify", "coste_eur": 0.0}

    entrada = {"queries": "\n".join(consultas), "maxPagesPerQuery": paginas_por_consulta, "countryCode": "es", "languageCode": "es"}
    res = await ejecutar_actor(
        cliente_http, token, ACTOR_GOOGLE_SEARCH, entrada,
        max_coste_usd=tope, max_items=len(consultas) * paginas_por_consulta, timeout_s=120,
    )

    bd.registrar_uso_apify(ACTOR_GOOGLE_SEARCH, res.run_id, res.estado, res.coste_usd, {"consultas": consultas}, conn)
    conn.commit()

    contadores = {
        "consultas_ejecutadas": len(consultas), "urls_encontradas": 0, "urls_no_legibles": 0, "urls_descartadas": 0,
        "vinculado": 0, "nueva_empresa": 0, "en_revision": 0, "ya_procesado": 0, "error_procesado": 0, "fuera_de_zona": 0,
    }
    candidatos_facebook: list[str] = []
    candidatos_linkedin: list[str] = []

    for item in res.items:
        for organico in item.get("organicResults") or []:
            url = organico.get("url")
            if not url:
                continue
            contadores["urls_encontradas"] += 1
            dominio = extraer_dominio(url)
            if dominio in _DOMINIOS_FACEBOOK:
                if es_pagina_facebook(url) and url not in candidatos_facebook and len(candidatos_facebook) < MAX_CANDIDATOS_DEVUELTOS:
                    candidatos_facebook.append(url)
                continue
            if dominio in _DOMINIOS_LINKEDIN:
                if _RUTA_EMPRESA_LINKEDIN in url and url not in candidatos_linkedin and len(candidatos_linkedin) < MAX_CANDIDATOS_DEVUELTOS:
                    candidatos_linkedin.append(url)
                continue
            if _url_no_apta_para_enriquecer(url):
                contadores["urls_descartadas"] += 1
                continue
            registro = await enriquecer_desde_web(cliente_http, url)
            if registro is None:
                contadores["urls_no_legibles"] += 1
                continue
            if not en_zona(registro.campos.codigo_postal, provincias_zona or set()):
                contadores["fuera_de_zona"] += 1
                continue
            try:
                r = procesar_registro(registro, conn, busqueda_id=busqueda_id, telefonos_compartidos=telefonos_compartidos)
                if busqueda_id and r.empresa_id:
                    bd.registrar_resultado_busqueda(busqueda_id, r.empresa_id, f"apify_google_search: {r.accion}", r.puntuacion_match, conn)
                conn.commit()
                contadores[r.accion] += 1
            except Exception:  # noqa: BLE001
                conn.rollback()
                contadores["error_procesado"] += 1

    return {
        **contadores, "candidatos_facebook": candidatos_facebook, "candidatos_linkedin": candidatos_linkedin,
        "estado_apify": res.estado, "error": res.error, "coste_eur": round(res.coste_usd, 4),
    }
