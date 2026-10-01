"""Filtro de autónomos sobre los resultados de una búsqueda (2026-10-01).

Antes, «incluir_autonomos = false» solo se aplicaba a la consulta interna del
agente y solo reconocía como autónomo a quien tenía un DNI/NIE como NIF; los
autónomos sin NIF conocido salían en los resultados igualmente.

Se decide en dos capas (principio 4: el código verifica, el LLM juzga):
1. Evidencia determinista:
   - NIF de persona física (DNI/NIE) → autónomo.
   - CIF de sociedad, forma jurídica societaria (SL, SA, cooperativa...) o
     administradores del BORME (solo hay actos de sociedades) → no lo es.
2. Si no hay evidencia, el juicio del filtro de IA (`busqueda_resultados.
   autonomo_ia`, `radar.agente.relevancia`).

Se aplica al final de la búsqueda (cuando ya se conocen los CIF localizados):
si la búsqueda omite autónomos, pasan a «descartado» con el motivo; no salen
en los resultados ni en el CSV y se pueden recuperar en la Cola de revisión.
Nunca se toca un resultado que una persona ya revisó.
"""

from __future__ import annotations

from typing import Any

import psycopg

from radar.agente.interpretacion import FiltrosBusqueda
from radar.normalizacion.nif import FORMAS_SOCIETARIAS, validar_nif
from radar.normalizacion.nombre import extraer_forma_juridica

MOTIVO = "Autónomo (persona física sin sociedad): excluido por el filtro de la búsqueda"

_SQL = """
select br.empresa_id::text, e.es_persona_fisica, e.nif, e.forma_juridica, e.razon_social, e.nombre_comercial,
  br.autonomo_ia,
  exists (select 1 from cargos c join fuentes f on f.id = c.fuente_id where c.empresa_id = e.id and f.codigo = 'borme')
from busqueda_resultados br join empresas e on e.id = br.empresa_id
where br.busqueda_id = %s and e.fusionada_en is null and not br.relevancia_revisada
  and coalesce(br.clasificacion, '') not in ('descartado', 'rechazado')
"""


def es_autonomo(
    *,
    es_persona_fisica: bool | None,
    nif: str | None,
    forma_juridica: str | None,
    nombres: list[str | None],
    tiene_cargos_borme: bool,
    autonomo_ia: bool | None,
) -> bool:
    if nif:
        v = validar_nif(nif)
        if v["valido"] and v["tipo"] == "sociedad":
            return False
        if v["valido"] and v["persona_fisica"]:
            return True
    if es_persona_fisica:
        return True
    formas = {forma_juridica} | {extraer_forma_juridica(n)[0] for n in nombres if n}
    if formas & FORMAS_SOCIETARIAS:
        return False
    if tiene_cargos_borme:
        return False
    return bool(autonomo_ia)


def filtrar_autonomos(conn: psycopg.Connection, filtros: FiltrosBusqueda, busqueda_id: str) -> dict[str, Any]:
    if filtros.incluir_autonomos:
        return {"omitidos": 0, "motivo_parada": "la búsqueda incluye autónomos", "coste_eur": 0.0}
    revisadas = omitidos = 0
    for empresa_id, fisica, nif, forma, razon, comercial, ia, cargos in conn.execute(_SQL, (busqueda_id,)).fetchall():
        revisadas += 1
        if es_autonomo(
            es_persona_fisica=fisica, nif=nif, forma_juridica=forma, nombres=[razon, comercial],
            tiene_cargos_borme=cargos, autonomo_ia=ia,
        ):
            conn.execute(
                "update busqueda_resultados set clasificacion = 'descartado', motivo_relevancia = %s "
                "where busqueda_id = %s and empresa_id = %s and not relevancia_revisada",
                (MOTIVO, busqueda_id, empresa_id),
            )
            omitidos += 1
    conn.commit()
    return {"revisadas": revisadas, "omitidos": omitidos, "coste_eur": 0.0}
