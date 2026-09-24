"""Enriquecimiento con el BORME de las empresas encontradas en una búsqueda
(2026-09-25).

En búsquedas por municipio, descubrir en el BORME casi nunca aporta nada (solo
las constituciones traen domicilio). Donde sí aporta es en IDENTIDAD y
DIRECTIVOS: para una empresa encontrada en Maps o en su web cuya razón social
se conoce (aviso legal), su acto del BORME da administradores (administrador
único, consejeros... = los directivos de una SL/SA), hoja registral y, si es
de constitución o cambio de domicilio, el domicilio social.

Se busca la denominación en el índice local (`radar.fuentes.borme_indice`;
solo lo ya descargado: el índice crece con cada búsqueda y con
`scripts/cargar_indice_borme.py`) y el acto se procesa como un registro más:
la resolución lo une a la empresa por la regla R9 (misma denominación y forma
jurídica) y el resto del pipeline añade administradores, hoja y domicilio.
Gratis: no hay llamadas externas.
"""

from __future__ import annotations

from typing import Any

import psycopg

from radar.fuentes.borme import acto_a_registro_bruto
from radar.fuentes.borme_indice import buscar_por_denominacion
from radar.normalizacion.nombre import extraer_forma_juridica
from radar.orquestador import procesar_registro

_SQL_CANDIDATAS = """
select e.id::text, e.razon_social
from busqueda_resultados br join empresas e on e.id = br.empresa_id
where br.busqueda_id = %s and e.fusionada_en is null and e.razon_social is not null
  and coalesce(br.clasificacion, '') not in ('descartado', 'rechazado')
  and not exists (
    select 1 from cargos c join fuentes f on f.id = c.fuente_id where c.empresa_id = e.id and f.codigo = 'borme'
  )
"""


def enriquecer_con_borme(
    conn: psycopg.Connection, busqueda_id: str, *, telefonos_compartidos: set[str] | None = None, max_actos_por_empresa: int = 3
) -> dict[str, Any]:
    contadores = {"empresas_revisadas": 0, "encontradas_en_borme": 0, "actos_procesados": 0, "unidas": 0, "con_duda": 0, "error": 0}
    for empresa_id, razon_social in conn.execute(_SQL_CANDIDATAS, (busqueda_id,)).fetchall():
        forma, _ = extraer_forma_juridica(razon_social)
        if not forma:  # sin forma jurídica no es una denominación registral
            continue
        contadores["empresas_revisadas"] += 1
        # El índice busca sin forma jurídica: "X SA" y "X SL" son sociedades distintas.
        actos = [
            (prov, acto) for prov, acto in buscar_por_denominacion(conn, razon_social, limite=max_actos_por_empresa * 2)
            if extraer_forma_juridica(acto.razon_social)[0] == forma
        ][:max_actos_por_empresa]
        if not actos:
            continue
        contadores["encontradas_en_borme"] += 1
        for provincia, acto in actos:
            try:
                r = procesar_registro(acto_a_registro_bruto(acto, provincia), conn, busqueda_id=busqueda_id,
                                      telefonos_compartidos=telefonos_compartidos)
                # Si el acto no casó con esta empresa, no se enlaza a la búsqueda.
                if r.empresa_id == empresa_id:
                    contadores["unidas" if r.accion != "en_revision" else "con_duda"] += 1
                conn.commit()
                contadores["actos_procesados"] += 1
            except Exception:  # noqa: BLE001 -- un acto que falla no para el resto
                conn.rollback()
                contadores["error"] += 1
    return {**contadores, "coste_eur": 0.0}
