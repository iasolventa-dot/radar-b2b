"""Enriquecimiento de webs PROPIAS de empresas con el rastreador de Apify
(`apify/website-content-crawler`), como alternativa de pago a
`radar.extraccion.enriquecer_desde_web` para webs que el descargador propio no
lee bien (p. ej. las que necesitan JavaScript). Solo se ofrece al planificador
si el usuario marca «Apify» en la búsqueda y hay token en Ajustes.

Esta herramienta es solo para enriquecer webs de empresa (esa es su función:
las URLs que no lo son -- directorios, redes, boletines -- no tienen un titular
del que extraer datos, igual que en `buscar_web`). El texto que devuelve el
rastreador pasa por las MISMAS reglas y validaciones que el resto de webs
(`registro_desde_texto` + `procesar_registro`): nada se guarda solo porque lo
diga Apify. Controla el gasto con un tope por llamada y otro mensual.
"""

from __future__ import annotations

from typing import Any

import httpx
import psycopg

from radar.extraccion import registro_desde_texto
from radar.fuentes.apify import ejecutar_actor
from radar.normalizacion.dominio import es_dominio_plataforma, extraer_dominio
from radar.orquestador import bd, procesar_registro
from radar.secretos import gasto_mes_apify_usd, obtener_token_apify, presupuesto_mensual_apify_usd

ACTOR_RASTREADOR = "apify/website-content-crawler"
MAX_URLS_POR_LLAMADA = 5
PAGINAS_POR_WEB = 3
_NO_WEB_PROPIA = {"boe.es"}


def _es_web_propia(url: str) -> bool:
    dominio = extraer_dominio(url)
    return bool(dominio) and not es_dominio_plataforma(dominio) and dominio not in _NO_WEB_PROPIA


def agrupar_por_dominio(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{dominio: {"portada": url, "urls": [...], "texto": "..."}} a partir de los
    items del dataset (`url` + `text`); ignora items sin texto."""
    grupos: dict[str, dict[str, Any]] = {}
    for it in items:
        url, texto = it.get("url"), (it.get("text") or "").strip()
        dominio = extraer_dominio(url) if url else None
        if not url or not texto or not dominio:
            continue
        g = grupos.setdefault(dominio, {"portada": url, "urls": [], "texto": []})
        g["urls"].append(url)
        g["texto"].append(texto)
    for g in grupos.values():
        g["texto"] = "\n\n".join(g["texto"])
    return grupos


async def enriquecer_con_apify(
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    *,
    urls: list[str],
    max_coste_eur: float,
    telefonos_compartidos: set[str] | None = None,
    busqueda_id: str | None = None,
) -> dict[str, Any]:
    token = obtener_token_apify(conn)
    if not token:
        return {"soportado": False, "motivo": "Apify no está configurado (falta el token en Ajustes)", "coste_eur": 0.0}

    validas = [u for u in dict.fromkeys(urls) if _es_web_propia(u)][:MAX_URLS_POR_LLAMADA]
    descartadas = len(set(urls)) - len(validas)
    if not validas:
        return {"error": "ninguna URL es una web propia de empresa", "urls_descartadas": descartadas, "coste_eur": 0.0}

    restante_mes = presupuesto_mensual_apify_usd(conn) - gasto_mes_apify_usd(conn)
    tope = min(max_coste_eur, restante_mes)  # 1 USD ≈ 1 EUR (D-04)
    if tope <= 0:
        return {"motivo_parada": "presupuesto_mensual_de_apify_agotado", "coste_eur": 0.0}

    entrada = {
        "startUrls": [{"url": u} for u in validas],
        "maxCrawlPages": PAGINAS_POR_WEB * len(validas),
        "maxCrawlDepth": 1,
        "crawlerType": "cheerio",
    }
    res = await ejecutar_actor(cliente_http, token, ACTOR_RASTREADOR, entrada, max_coste_usd=tope, timeout_s=120)

    bd.registrar_uso_apify(ACTOR_RASTREADOR, res.run_id, res.estado, res.coste_usd, {"urls": validas}, conn)
    conn.commit()

    contadores = {"vinculado": 0, "nueva_empresa": 0, "en_revision": 0, "ya_procesado": 0, "error_procesado": 0}
    grupos = agrupar_por_dominio(res.items)
    for dominio, g in grupos.items():
        try:
            registro = registro_desde_texto(g["texto"], g["urls"], g["portada"], dominio)
            r = procesar_registro(registro, conn, busqueda_id=busqueda_id, telefonos_compartidos=telefonos_compartidos)
            if busqueda_id and r.empresa_id:
                bd.registrar_resultado_busqueda(busqueda_id, r.empresa_id, f"apify+web: {r.accion}", r.puntuacion_match, conn)
            conn.commit()
            contadores[r.accion] += 1
        except Exception:  # noqa: BLE001 -- una web que falla no debe tirar el resto
            conn.rollback()
            contadores["error_procesado"] += 1

    return {
        **contadores, "webs_enviadas": len(validas), "webs_con_texto": len(grupos), "urls_descartadas": descartadas,
        "estado_apify": res.estado, "error": res.error, "coste_eur": round(res.coste_usd, 4),
    }
