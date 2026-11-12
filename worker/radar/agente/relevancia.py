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
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

import psycopg
from pydantic import BaseModel, ConfigDict

from radar.agente.interpretacion import FiltrosBusqueda
from radar.llm_json import pedir_json

MAX_POR_LLAMADA = 25
LLAMADAS_EN_PARALELO = 6

PROMPT = """Clasifica si cada empresa corresponde a lo que busca el usuario de una base de datos B2B de empresas españolas.

Búsqueda:
- Sector: {sector}
- Palabras clave: {palabras}
- Excluir: {exclusiones}
- Zona: {zona}
- Solo interesan negocios que cumplan: {solo_si}
- Descartar estos tipos de negocio aunque sean del sector: {descartar_si}

Empresas (lo que sabemos de cada una):
{empresas_json}

{sin_sector}Para cada empresa decide:
- "relevante": su actividad principal es la del sector buscado o una muy cercana que lo incluye (p. ej. "instalaciones" de fontanería y calefacción, o una empresa de reformas que hace fontanería, para "fontanería"). La categoría de Google Maps es una buena señal.
- "descartado": solo si claramente NO es del sector: otra actividad (tienda o distribuidor de material, ferretería, persianas, aseguradora, agencia de marketing...), un organismo público, un directorio o portal de empresas, un medio de comunicación, una app o software, un marketplace, o un lugar que no es una empresa. También si consta que está en OTRA PROVINCIA.
- "dudoso": no hay información suficiente sobre su actividad, o es del sector pero consta en otro municipio de la misma provincia (dilo en el motivo; no la descartes por eso). También si parece una web de captación de clientes (dominio genérico "servicio + ciudad", p. ej. desatascos-ciudad.es) y no consta quién es el titular.
- Pero "descartado" si esa web de captación es de una agencia de marketing/SEO/publicidad, de una plataforma o red que deriva clientes a profesionales de muchas ciudades, o de una empresa extranjera (SARL, GmbH, Ltd...), o si su teléfono es de otra provincia (el prefijo fijo indica la provincia: 954/955 Sevilla, 91 Madrid, 943 Gipuzkoa...): no es una empresa del sector en la zona.
Además, "autonomo": true si parece una persona física que trabaja por su cuenta, sin sociedad (el nombre es el de una persona, o se presenta como autónomo/profesional independiente); false si es una empresa o sociedad (SL, SA, cooperativa, "Grupo", marca comercial con equipo...); null si no se puede saber.
Filtros avanzados (si los hay): "descartado" si la empresa es claramente de un tipo de "Descartar" o claramente NO cumple "Solo interesan"; "dudoso" si no hay datos para saber si los cumple (dilo en el motivo); "relevante" solo si es del sector Y no hay nada que indique que incumple esos filtros. Una cadena o franquicia conocida se reconoce por su nombre.
Código postal: si la búsqueda pide códigos postales concretos y la empresa tiene OTRO código postal, "descartado".
No inventes: decide solo con los datos dados. "motivo": una frase corta en español.

Responde SOLO con JSON: {{"clasificaciones": [{{"id": "...", "relevancia": "relevante|dudoso|descartado", "autonomo": true|false|null, "motivo": "..."}}]}}"""


# 2026-11-12 («empresas de Madrid con CP 28108»): sin sector, el modelo marcaba
# «dudoso» 233 de 260 empresas porque no sabía contra qué sector compararlas.
AVISO_SIN_SECTOR = (
    "IMPORTANTE: esta búsqueda NO pide ningún sector concreto (quiere empresas de cualquier actividad de la zona). "
    "Cualquier empresa o negocio real es \"relevante\". \"descartado\" solo si no es una empresa (organismo público, "
    "directorio, medio, app, lugar), si es de otro país o si consta fuera de la zona; \"dudoso\" solo si no hay datos "
    "para saber si es una empresa real.\n\n"
)


def busqueda_sin_sector(filtros: FiltrosBusqueda) -> bool:
    s = filtros.sector
    sector = (s.sector_interno or "").strip().lower()
    return sector in {"", "todos", "todos los sectores", "cualquiera", "general"} and not (
        s.codigos_cnae or s.palabras_clave or s.solo_si or s.descartar_si
    )


class ClasificacionLLM(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    relevancia: Literal["relevante", "dudoso", "descartado"]
    autonomo: bool | None = None
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
       br.motivo,
       (select c.valor from canales_contacto c where c.empresa_id = e.id and c.tipo = 'telefono' limit 1),
       (select s.codigo_postal from sedes s where s.empresa_id = e.id and s.codigo_postal is not null limit 1),
       e.forma_juridica, e.empleados_min, e.empleados_max
from busqueda_resultados br join empresas e on e.id = br.empresa_id
where br.busqueda_id = %s and br.clasificacion is null and not br.relevancia_revisada and e.fusionada_en is null
"""


def perfil_para_prompt(fila: tuple) -> dict[str, Any]:
    claves = ("id", "nombre", "nombre_comercial", "web", "objeto_social", "cnae", "municipio",
              "categoria_google_maps", "titulo_web", "descripcion_web", "encontrada_por", "telefono",
              "codigo_postal", "forma_juridica", "empleados_min", "empleados_max")
    return {k: v for k, v in zip(claves, fila, strict=False) if v}  # filas antiguas sin teléfono: se toleran


def construir_prompt(filtros: FiltrosBusqueda, perfiles: list[dict[str, Any]]) -> str:
    u = filtros.ubicacion
    zona = ", ".join(u.municipios or u.provincias or u.ccaa) or "sin zona"
    if u.codigos_postales:
        zona += f" (solo códigos postales {', '.join(u.codigos_postales)})"
    return PROMPT.format(
        sector=filtros.sector.sector_interno or "sin especificar",
        palabras=", ".join(filtros.sector.palabras_clave) or "-",
        exclusiones=", ".join(filtros.sector.exclusiones) or "-",
        zona=zona,
        sin_sector=AVISO_SIN_SECTOR if busqueda_sin_sector(filtros) else "",
        solo_si="; ".join(filtros.sector.solo_si) or "-",
        descartar_si="; ".join(filtros.sector.descartar_si) or "-",
        empresas_json=json.dumps(perfiles, ensure_ascii=False),
    )


def evaluar_relevancia(
    conn: psycopg.Connection, filtros: FiltrosBusqueda, busqueda_id: str, *, max_coste_eur: float
) -> dict[str, Any]:
    filas = conn.execute(_SQL_PENDIENTES, (busqueda_id,)).fetchall()
    conn.commit()
    contadores = {"evaluadas": 0, "relevante": 0, "dudoso": 0, "descartado": 0, "sin_evaluar": 0}
    coste = 0.0
    error: str | None = None
    lotes = [[perfil_para_prompt(f) for f in filas[i : i + MAX_POR_LLAMADA]] for i in range(0, len(filas), MAX_POR_LLAMADA)]
    # Varias llamadas al modelo a la vez (2026-11-12): sin tope de empresas por
    # búsqueda puede haber miles, y de una en una eran horas. La BD se escribe
    # en este hilo, de una tanda en otra; el presupuesto se comprueba por tanda.
    with ThreadPoolExecutor(max_workers=LLAMADAS_EN_PARALELO) as hilos:
        for t in range(0, len(lotes), LLAMADAS_EN_PARALELO):
            tanda = lotes[t : t + LLAMADAS_EN_PARALELO]
            if coste >= max_coste_eur:
                contadores["sin_evaluar"] += sum(len(lote) for lote in lotes[t:])
                break
            respuestas = list(hilos.map(lambda lote: pedir_json(construir_prompt(filtros, lote), RespuestaRelevancia), tanda))
            for perfiles, r in zip(tanda, respuestas, strict=True):
                coste += r.coste_eur
                if r.datos is None:
                    error = r.error
                    contadores["sin_evaluar"] += len(perfiles)
                    continue
                _guardar(conn, busqueda_id, perfiles, r.datos, contadores)
            conn.commit()
    return {**contadores, "error": error, "coste_eur": round(coste, 4)}


def _guardar(
    conn: psycopg.Connection, busqueda_id: str, perfiles: list[dict[str, Any]], datos: RespuestaRelevancia,
    contadores: dict[str, int],
) -> None:
    ids_lote = {p["id"] for p in perfiles}
    for c in datos.clasificaciones:
        if c.id not in ids_lote:
            continue
        conn.execute(
            "update busqueda_resultados set clasificacion = %s, motivo_relevancia = %s, autonomo_ia = %s "
            "where busqueda_id = %s and empresa_id = %s and not relevancia_revisada",
            (c.relevancia, c.motivo[:300], c.autonomo, busqueda_id, c.id),
        )
        contadores["evaluadas"] += 1
        contadores[c.relevancia] += 1
