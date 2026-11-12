"""Vuelve a aplicar el filtro de plantilla a las búsquedas ya hechas que piden
un número de empleados (2026-11-12): con la plantilla recogida después
(LinkedIn, relectura de webs), descarta las de plantilla conocida fuera del
rango, con el motivo y recuperables en la Cola de revisión. Gratis.

    python scripts\\reaplicar_plantilla.py
"""

from __future__ import annotations

import psycopg

import radar  # noqa: F401 -- truststore (certificados de Windows)
from radar.agente.interpretacion import FiltrosBusqueda
from radar.agente.tamano import filtrar_por_plantilla, tiene_filtro_de_plantilla
from radar.config import get_settings


def main() -> None:
    with psycopg.connect(get_settings().supabase_db_url) as conn:
        conn.execute("set statement_timeout = 0")
        for busqueda_id, peticion, filtros in conn.execute(
            "select id::text, peticion, filtros from busquedas where estado <> 'en_curso' order by creado_en"
        ).fetchall():
            f = FiltrosBusqueda.model_validate(filtros)
            if tiene_filtro_de_plantilla(f):
                print(peticion[:70], filtrar_por_plantilla(conn, f, busqueda_id), flush=True)


if __name__ == "__main__":
    main()
