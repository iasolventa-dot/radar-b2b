"""Fuentes de Apify marcadas por el usuario que no descubren por zona
(LinkedIn, Facebook, rastreo de webs) — fase 3c de toda búsqueda (2026-10-01).

Antes solo se usaban si el agente LLM decidía llamarlas (o, Facebook/LinkedIn,
si `descubrir_google_search` devolvía páginas suyas): en una búsqueda real con
las cinco casillas marcadas, Facebook y el rastreo de webs no se ejecutaron
nunca y LinkedIn recibió nombres de sociedades del BORME sin web (0
resultados: este Actor casi nunca resuelve por nombre). Ahora, si están
marcadas, se ejecutan siempre al final, con lo que la propia búsqueda ha
encontrado:

- LinkedIn y Facebook, con las URLs EXACTAS que enlaza la web de cada empresa
  (`redes_linkedin` / `redes_facebook`, extraídas de su portada en
  `radar.extraccion.conector.enlaces_redes`).
- Rastreo de webs (Apify), con las webs de empresas a las que aún les falta
  teléfono o email: suelen ser webs con JavaScript que el lector propio no lee.

Si una fuente marcada no tiene con qué trabajar, se registra igualmente con el
motivo, para que el panel muestre que se intentó.
"""

from __future__ import annotations

from typing import Any

import httpx
import psycopg

from radar.agente.enriquecer_apify import MAX_URLS_POR_LLAMADA as MAX_WEBS_RASTREO
from radar.agente.enriquecer_apify import enriquecer_con_apify
from radar.agente.enriquecer_apify_facebook import MAX_PAGINAS_POR_LLAMADA, enriquecer_con_facebook
from radar.agente.enriquecer_apify_linkedin import MAX_EMPRESAS_POR_LLAMADA, enriquecer_con_linkedin

# Parte del presupuesto que se reserva para esta fase por cada fuente marcada
# (tarifas del plan FREE: LinkedIn 0,005 $ + 0,00345 $/empresa; Facebook
# 0,012 $/página; rastreo ~0,01 $/web). Ver `reserva_redes`.
RESERVA_POR_FUENTE_EUR = {"linkedin": 0.04, "facebook": 0.08, "web_crawler": 0.06}

_SQL_REDES = """
select distinct red
from busqueda_resultados br
join registros_brutos rb on rb.empresa_id = br.empresa_id
cross join lateral jsonb_array_elements_text(
  case when jsonb_typeof(rb.campos->'extra'->%(clave)s) = 'array' then rb.campos->'extra'->%(clave)s else '[]'::jsonb end
) as red
where br.busqueda_id = %(busqueda)s and coalesce(br.clasificacion, '') not in ('descartado', 'rechazado')
limit %(limite)s
"""

_SQL_WEBS_SIN_CONTACTO = """
select e.dominio_web
from busqueda_resultados br join empresas e on e.id = br.empresa_id
where br.busqueda_id = %s and e.fusionada_en is null and e.dominio_web is not null
  and coalesce(br.clasificacion, '') not in ('descartado', 'rechazado')
  and (
    not exists (select 1 from canales_contacto c where c.empresa_id = e.id and c.tipo = 'email')
    or not exists (select 1 from canales_contacto c where c.empresa_id = e.id and c.tipo = 'telefono')
  )
order by e.confianza_global desc nulls last
limit %s
"""


def reserva_redes(actores: frozenset[str] | set[str], presupuesto_eur: float) -> float:
    """Presupuesto que el bucle del agente debe dejar libre para esta fase
    (como mucho el 30 % del total)."""
    return min(presupuesto_eur * 0.3, sum(v for k, v in RESERVA_POR_FUENTE_EUR.items() if k in actores))


def urls_redes(conn: psycopg.Connection, busqueda_id: str, clave: str, limite: int) -> list[str]:
    filas = conn.execute(_SQL_REDES, {"clave": clave, "busqueda": busqueda_id, "limite": limite}).fetchall()
    return [f[0] for f in filas]


async def fuentes_marcadas_finales(
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    *,
    busqueda_id: str,
    actores: frozenset[str] | set[str],
    max_coste_eur: float,
    telefonos_compartidos: set[str] | None,
) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Ejecuta, en orden, las fuentes marcadas de esta fase y devuelve
    (herramienta, argumentos, resultado) de cada una para registrarla como
    ronda. El presupuesto se reparte entre las marcadas según su reserva."""
    marcadas = [f for f in ("linkedin", "facebook", "web_crawler") if f in actores]
    if not marcadas:
        return []
    peso_total = sum(RESERVA_POR_FUENTE_EUR[f] for f in marcadas)
    rondas: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    restante = max_coste_eur

    for fuente in marcadas:
        tope = round(min(restante, max_coste_eur * RESERVA_POR_FUENTE_EUR[fuente] / peso_total), 4)
        if fuente == "linkedin":
            urls = urls_redes(conn, busqueda_id, "redes_linkedin", MAX_EMPRESAS_POR_LLAMADA)
            args: dict[str, Any] = {"urls": urls, "max_coste_eur": tope}
            if not urls:
                res: dict[str, Any] = {"motivo_parada": "ninguna web encontrada enlaza a su página de LinkedIn", "coste_eur": 0.0}
            else:
                res = await enriquecer_con_linkedin(
                    conn, cliente_http, urls=urls, max_coste_eur=tope, busqueda_id=busqueda_id,
                    telefonos_compartidos=telefonos_compartidos,
                )
            rondas.append(("enriquecer_con_linkedin", args, res))
        elif fuente == "facebook":
            urls = urls_redes(conn, busqueda_id, "redes_facebook", MAX_PAGINAS_POR_LLAMADA)
            args = {"urls": urls, "max_coste_eur": tope}
            if not urls:
                res = {"motivo_parada": "ninguna web encontrada enlaza a su página de Facebook", "coste_eur": 0.0}
            else:
                res = await enriquecer_con_facebook(
                    conn, cliente_http, urls=urls, max_coste_eur=tope, busqueda_id=busqueda_id,
                    telefonos_compartidos=telefonos_compartidos,
                )
            rondas.append(("enriquecer_con_facebook", args, res))
        else:
            dominios = [f[0] for f in conn.execute(_SQL_WEBS_SIN_CONTACTO, (busqueda_id, MAX_WEBS_RASTREO)).fetchall()]
            urls = [f"https://{d}" for d in dominios]
            args = {"urls": urls, "max_coste_eur": tope}
            if not urls:
                res = {"motivo_parada": "todas las empresas con web ya tienen teléfono y email", "coste_eur": 0.0}
            else:
                res = await enriquecer_con_apify(
                    conn, cliente_http, urls=urls, max_coste_eur=tope, busqueda_id=busqueda_id,
                    telefonos_compartidos=telefonos_compartidos,
                )
            rondas.append(("enriquecer_con_apify", args, res))
        restante = max(0.0, restante - float(res.get("coste_eur") or 0.0))
    return rondas
