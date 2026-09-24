"""Rellena el índice local del BORME (`borme_actos`, migración 202609251200)
para una o varias provincias y un rango de días hacia atrás.

Solo descarga los días que falten (`borme_dias_cargados`): se puede relanzar
sin coste. Cuanto más histórico tenga el índice, más empresas encontradas en
Maps/webs se pueden enriquecer con administradores y hoja registral
(`radar.agente.enriquecer_borme`). Gratis: el BORME es una fuente pública.

Uso (con el entorno virtual del worker activado):

    python scripts\\cargar_indice_borme.py --provincia MADRID --provincia SEVILLA --dias 365
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import psycopg

from radar.config import get_settings
from radar.fuentes.borme_indice import cargar_dias

TRAMO_DIAS = 15  # se informa del avance cada tramo; un corte no pierde lo ya guardado


async def _ejecutar(provincias: list[str], dias: int) -> None:
    settings = get_settings()
    if not settings.supabase_db_url:
        raise SystemExit("SUPABASE_DB_URL no está configurada — ver .env.example")
    hasta = datetime.now(UTC).date()
    inicio = hasta - timedelta(days=dias)
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as cliente:
        with psycopg.connect(settings.supabase_db_url, autocommit=False) as conn:
            for provincia in provincias:
                # Del más reciente al más antiguo: lo reciente es lo más útil.
                fin_tramo = hasta
                while fin_tramo >= inicio:
                    ini_tramo = max(inicio, fin_tramo - timedelta(days=TRAMO_DIAS - 1))
                    resumen = await cargar_dias(conn, cliente, provincia.title(), ini_tramo, fin_tramo)
                    print(f"{provincia} {ini_tramo}..{fin_tramo}: {resumen}", flush=True)
                    fin_tramo = ini_tramo - timedelta(days=1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provincia", action="append", required=True, help="p. ej. MADRID (repetible)")
    parser.add_argument("--dias", type=int, default=365)
    args = parser.parse_args()
    asyncio.run(_ejecutar([p.upper() for p in args.provincia], args.dias))


if __name__ == "__main__":
    main()
