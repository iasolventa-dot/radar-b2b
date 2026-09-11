"""Ejecuta el conector BORME y procesa cada acto con el orquestador
(`radar.orquestador.procesar_registro`): primera vía end-to-end que
escribe en `empresas`/`sedes`/`canales_contacto`/`identificadores` de
verdad, en vez de en las tablas del golden set.

Uso (con el entorno virtual del worker activado):

    python scripts\\ejecutar_borme.py --provincia SEVILLA --dias 7

Cada `RegistroBruto` se procesa y confirma (`commit`) por separado: si uno
falla, no se pierde el trabajo de los anteriores y el error se imprime
para poder reprocesar solo ese acto más tarde (queda con `estado='error'`
en `registros_brutos`, no bloquea nada).
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import psycopg

from radar.config import get_settings
from radar.fuentes.borme import ConectorBorme
from radar.orquestador import procesar_registro
from radar.resolucion.blocking import telefonos_compartidos as cargar_telefonos_compartidos


async def _ejecutar(provincia: str, dias: int) -> None:
    settings = get_settings()
    if not settings.supabase_db_url:
        raise SystemExit("SUPABASE_DB_URL no está configurada — ver .env.example")

    hasta = datetime.now(UTC).date()
    desde = hasta - timedelta(days=dias)
    contadores = {"vinculado": 0, "nueva_empresa": 0, "en_revision": 0, "ya_procesado": 0, "error": 0}

    async with httpx.AsyncClient() as cliente:
        conector = ConectorBorme(cliente)
        with psycopg.connect(settings.supabase_db_url, autocommit=False) as conn:
            compartidos = cargar_telefonos_compartidos(conexion=conn)
            conn.commit()  # la consulta anterior es de solo lectura; cierra su transacción

            async for registro in conector.descubrir(
                {"provincia_titulo": provincia, "desde": desde, "hasta": hasta}, max_coste_eur=0.0
            ):
                try:
                    resultado = procesar_registro(registro, conn, telefonos_compartidos=compartidos)
                    conn.commit()
                    contadores[resultado.accion] += 1
                    print(
                        f"  [{resultado.accion}] {registro.campos.razon_social!r} "
                        f"-> empresa {resultado.empresa_id} (puntuación {resultado.puntuacion_match})"
                    )
                except Exception as exc:  # noqa: BLE001 — se informa y se sigue con el siguiente acto
                    conn.rollback()
                    contadores["error"] += 1
                    print(f"  [error] {registro.campos.razon_social!r}: {exc}")

    print(f"\nBORME {provincia}, últimos {dias} días ({desde} a {hasta}):")
    for accion, n in contadores.items():
        print(f"  - {accion}: {n}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provincia", default="SEVILLA", help='Título de provincia tal como lo usa el BORME (p. ej. "SEVILLA")')
    parser.add_argument("--dias", type=int, default=7, help="Días hacia atrás desde hoy (por defecto 7)")
    args = parser.parse_args()
    asyncio.run(_ejecutar(args.provincia, args.dias))


if __name__ == "__main__":
    main()
