"""Filtro de relevancia de los resultados de una búsqueda (2026-09-25).

Medido en búsquedas reales (fontanería en Colmenar Viejo, carpintería de
aluminio en Tres Cantos): entre el 30 y el 40 % de las empresas enlazadas no
eran del sector pedido -- un ayuntamiento, un directorio local, una app, una
aseguradora nacional, una fuente pública de Maps... Entraban porque las
fuentes de descubrimiento (sobre todo Google Search) devuelven cualquier web
que mencione las palabras buscadas, y nada comprobaba a qué se dedica de
verdad cada empresa.

Al terminar la búsqueda, un LLM barato (`modelo_extraccion`) clasifica cada
empresa a partir de lo que se sabe de ella (categoría de Google Maps, título
y descripción de su web, objeto social del BORME, CNAE, municipio):
  relevante  -> se muestra
  dudoso     -> se muestra marcada y va a la «Cola de revisión»
  descartado -> se oculta de los resultados y va a la «Cola de revisión»
Nada se borra: la empresa sigue en la base, solo cambia si pertenece a esta
búsqueda. Una decisión humana (aceptado/rechazado) nunca se reevalúa.
"""

from __future__ import annotations

import json
from typing import Any, Literal

import psycopg
from pydantic import BaseModel, ConfigDict

from radar.agente.interpretacion import FiltrosBusqueda
from radar.llm_json import pedir_json

MAX_POR_LLAMADA = 25

PROMPT = """Clasifica si cada empresa corresponde a lo que busca el usuario de una base de datos B2B de empresas españolas.

Búsqueda:
- Sector: {sector}
- Palabras clave: {palabras}
- Excluir: {exclusiones}
- Zona: {zona}

Empresas (lo que sabemos de cada una):
{empresas_json}

Para cada empresa decide:
- "relevante": su actividad principal es la del sector buscado o una muy cercana que lo incluye (p. ej. "instalaciones" de fontanería y calefacción, o una empresa de reformas que hace fontanería, para "fontanería"). La categoría de Google Maps es una buena señal.
- "descartado": solo si claramente NO es del sector: otra actividad (tienda o distribuidor de material, ferretería, persianas, aseguradora, agencia de marketing...), un organismo público, un directorio o portal de empresas, un medio de comunicación, una app o software, un marketplace, o un lugar que no es una empresa. También si consta que está en OTRA PROVINCIA.
- "dudoso": no hay información suficiente sobre su actividad, o es del sector pero consta en otro municipio de la misma provincia (dilo en el motivo; no la descartes por eso).
No inventes: decide solo con los datos dados. "motivo": una frase corta en español.

Responde SOLO con JSON: {{"clasificaciones": [{{"id": "...", "relevancia": "relevante|dudoso|descartado", "motivo": "..."}}]}}"""


class ClasificacionLLM(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    relevancia: Literal["relevante", "dudoso", "descartado"]
    motivo: str = ""


class RespuestaRelevancia(BaseModel):
    model_config = ConfigDict(extra="ignore")
    clasificaciones: list[ClasificacionLLM] = []


_SQL_PENDIENTES = """
select e.id::text,
       coalesce(e.razon_social, e.nombre_comercial) as nombre,
       e.nombre_comercial, e.dominio_web, left(e.objeto_social, 300), e.cnae_principal,
       (select s.municipio_nombre from sedes s where s.empresa_id = e.id and s.municipio_nombre is not null limit 1),
       (select string_agg(distinct rb.campos->'extra'->>'categoria', ', ') from registros_brutos rb
          where rb.empresa_id = e.id and rb.campos->'extra'->>'categoria' is not null),
       (select rb.campos->'extra'->>'titulo_web' from registros_brutos rb
          where rb.empresa_id = e.id and rb.campos->'extra'->>'titulo_web' is not null limit 1),
       (select rb.campos->'extra'->>'descripcion_web' from registros_brutos rb
          where rb.empresa_id = e.id and rb.campos->'extra'->>'descripcion_web' is not null limit 1),
       br.motivo
from busqueda_resultados br join empresas e on e.id = br.empresa_id
where br.busqueda_id = %s and br.clasificacion is null and not br.relevancia_revisada and e.fusionada_en is null
"""


def perfil_para_prompt(fila: tuple) -> dict[str, Any]:
    claves = ("id", "nombre", "nombre_comercial", "web", "objeto_social", "cnae", "municipio",
              "categoria_google_maps", "titulo_web", "descripcion_web", "encontrada_por")
    return {k: v for k, v in zip(claves, fila, strict=True) if v}


def construir_prompt(filtros: FiltrosBusqueda, perfiles: list[dict[str, Any]]) -> str:
    u = filtros.ubicacion
    zona = ", ".join(u.municipios or u.provincias or u.ccaa) or "sin zona"
    return PROMPT.format(
        sector=filtros.sector.sector_interno or "sin especificar",
        palabras=", ".join(filtros.sector.palabras_clave) or "-",
        exclusiones=", ".join(filtros.sector.exclusiones) or "-",
        zona=zona,
        empresas_json=json.dumps(perfiles, ensure_ascii=False),
    )


def evaluar_relevancia(
    conn: psycopg.Connection, filtros: FiltrosBusqueda, busqueda_id: str, *, max_coste_eur: float
) -> dict[str, Any]:
    filas = conn.execute(_SQL_PENDIENTES, (busqueda_id,)).fetchall()
    contadores = {"evaluadas": 0, "relevante": 0, "dudoso": 0, "descartado": 0, "sin_evaluar": 0}
    coste = 0.0
    error: str | None = None
    for i in range(0, len(filas), MAX_POR_LLAMADA):
        if coste >= max_coste_eur:
            contadores["sin_evaluar"] += len(filas) - i
            break
        perfiles = [perfil_para_prompt(f) for f in filas[i : i + MAX_POR_LLAMADA]]
        r = pedir_json(construir_prompt(filtros, perfiles), RespuestaRelevancia)
        coste += r.coste_eur
        if r.datos is None:
            error = r.error
            contadores["sin_evaluar"] += len(perfiles)
            continue
        ids_lote = {p["id"] for p in perfiles}
        for c in r.datos.clasificaciones:
            if c.id not in ids_lote:
                continue
            conn.execute(
                "update busqueda_resultados set clasificacion = %s, motivo_relevancia = %s "
                "where busqueda_id = %s and empresa_id = %s and not relevancia_revisada",
                (c.relevancia, c.motivo[:300], busqueda_id, c.id),
            )
            contadores["evaluadas"] += 1
            contadores[c.relevancia] += 1
        conn.commit()
    return {**contadores, "error": error, "coste_eur": round(coste, 4)}
