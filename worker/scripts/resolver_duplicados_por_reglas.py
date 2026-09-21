"""Cierra los «posibles duplicados» pendientes que las reglas deterministas ya
resuelven (sin LLM ni coste):

- MISMA hoja registral en ambas empresas (identidad del Registro Mercantil,
  regla R3b) -> se fusionan (`fusionar_empresas`, queda registro en `fusiones`).
- Series numeradas («... REN 410» vs «... REN 414», regla R7) -> se rechaza el
  candidato: son sociedades distintas.

El resto se deja pendiente (LLM: `arbitrar_duplicados.py`, o revisión humana).
Por defecto NO escribe nada (simulación); usar --aplicar.

Uso: python scripts\\resolver_duplicados_por_reglas.py [--aplicar]
"""

from __future__ import annotations

import argparse

import psycopg

from radar.config import get_settings
from radar.orquestador import bd
from radar.resolucion.scoring import comparar

_SQL_HOJAS = """
select coalesce(array_agg(distinct upper(h)) filter (where h is not null), '{}') from (
  select rb.campos->'extra'->>'hoja_registral' as h from registros_brutos rb where rb.empresa_id = %s
  union all select i.valor from identificadores i where i.empresa_id = %s and i.tipo = 'borme_hoja'
) t
"""


def _hojas(conn: psycopg.Connection, empresa_id: str) -> set[str]:
    return set(conn.execute(_SQL_HOJAS, (empresa_id, empresa_id)).fetchone()[0])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    args = ap.parse_args()

    resumen = {"fusionar_por_hoja": 0, "rechazar_por_serie_numerica": 0, "sin_cambio": 0, "error": 0}
    with psycopg.connect(get_settings().supabase_db_url) as conn:
        pendientes = conn.execute(
            "select id, empresa_a, empresa_b, puntuacion from candidatos_duplicado where estado = 'pendiente' order by id"
        ).fetchall()
        for cid, a, b, punt in pendientes:
            a, b = str(a), str(b)
            try:
                if _hojas(conn, a) & _hojas(conn, b):
                    resumen["fusionar_por_hoja"] += 1
                    if args.aplicar:
                        # destino = la primera en crearse (la que conserva el identificador borme_hoja)
                        bd.fusionar_empresas_rpc(
                            b, a, "misma hoja registral (R3b)", "regla_hoja_registral",
                            float(punt) if punt is not None else None, cid, conn,
                        )
                        conn.commit()
                    continue
                ra = bd.cargar_registro_empresa_normalizado(a, conn)
                rb = bd.cargar_registro_empresa_normalizado(b, conn)
                if comparar(ra, rb)["regla"] == "R7_numeros_distintos":
                    resumen["rechazar_por_serie_numerica"] += 1
                    if args.aplicar:
                        bd.descartar_candidato_duplicado(cid, "regla_series_numeradas", conn)
                        conn.commit()
                    continue
                resumen["sin_cambio"] += 1
            except Exception as exc:  # noqa: BLE001 -- un par que falla no debe parar el resto
                conn.rollback()
                resumen["error"] += 1
                print(f"candidato {cid}: {exc}")
    print("APLICADO" if args.aplicar else "SIMULACIÓN (no se ha escrito nada)", resumen)


if __name__ == "__main__":
    main()
