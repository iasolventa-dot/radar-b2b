"""Aplica a una búsqueda ya hecha la regla de zona corregida del BORME (2026-11-12).

Con municipios (o códigos postales) en los filtros Y una provincia, el BORME
solo comprobaba la provincia: «empresas de Madrid con CP 28108» metió 19.252
sociedades de toda la provincia de Madrid. Esto marca como «descartado» (con el
motivo; recuperable en la Cola de revisión, nada se borra) las empresas que esa
búsqueda solo trajo del BORME y cuyo domicilio conocido no es de la zona, o no
se conoce (el BORME solo lo da en las constituciones: no se puede afirmar que
estén en la zona pedida).

    python scripts\\limpiar_borme_fuera_de_zona.py <busqueda_id> [--prueba]
"""

from __future__ import annotations

import argparse

import psycopg

import radar  # noqa: F401 -- truststore (certificados de Windows)
from radar.agente.cumplimiento import normalizar_lugar
from radar.agente.interpretacion import FiltrosBusqueda
from radar.config import get_settings

_SQL = """
select br.empresa_id::text,
  coalesce((select array_agg(distinct s.municipio_nombre) from sedes s where s.empresa_id = br.empresa_id and s.municipio_nombre is not null), '{}'),
  coalesce((select array_agg(distinct s.codigo_postal) from sedes s where s.empresa_id = br.empresa_id and s.codigo_postal is not null), '{}')
from busqueda_resultados br
where br.busqueda_id = %s and br.motivo like 'borme:%%' and not br.relevancia_revisada
  and coalesce(br.clasificacion, '') not in ('descartado', 'rechazado', 'aceptado')
"""


def main(busqueda_id: str, prueba: bool) -> None:
    with psycopg.connect(get_settings().supabase_db_url) as conn:
        conn.execute("set statement_timeout = 0")
        filtros = FiltrosBusqueda.model_validate(conn.execute("select filtros from busquedas where id = %s", (busqueda_id,)).fetchone()[0])
        municipios = {normalizar_lugar(m) for m in filtros.ubicacion.municipios}
        cps = set(filtros.ubicacion.codigos_postales)
        if not municipios and not cps:
            print("La búsqueda no pide municipios ni códigos postales: no hay nada que limpiar.")
            return
        cuenta = {"revisadas": 0, "en_zona": 0, "fuera": 0, "sin_municipio": 0}
        for empresa_id, suyos, sus_cps in conn.execute(_SQL, (busqueda_id,)).fetchall():
            cuenta["revisadas"] += 1
            if (cps and set(sus_cps) & cps) or (municipios and {normalizar_lugar(m) for m in suyos} & municipios):
                cuenta["en_zona"] += 1
                continue
            if suyos or sus_cps:
                cuenta["fuera"] += 1
                motivo = f"BORME: domicilio fuera de la zona ({', '.join(list(suyos) + list(sus_cps))})"
            else:
                cuenta["sin_municipio"] += 1
                motivo = "BORME: sin domicilio conocido; la búsqueda pide un municipio o código postal concreto"
            if not prueba:
                conn.execute(
                    "update busqueda_resultados set clasificacion = 'descartado', motivo_relevancia = %s "
                    "where busqueda_id = %s and empresa_id = %s and not relevancia_revisada",
                    (motivo, busqueda_id, empresa_id),
                )
        if not prueba:
            conn.commit()
        print(cuenta)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("busqueda_id")
    parser.add_argument("--prueba", action="store_true")
    args = parser.parse_args()
    main(args.busqueda_id, args.prueba)
