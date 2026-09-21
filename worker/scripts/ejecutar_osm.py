"""Descubre negocios en OpenStreetMap (Overpass) para uno o varios municipios
y los procesa con el pipeline normal (cruce con lo que ya hay, sin duplicar).

Uso (venv activado, desde worker/):
    python scripts\\ejecutar_osm.py --municipio "Sevilla"
    python scripts\\ejecutar_osm.py --provincia Sevilla --lote 0
    python scripts\\ejecutar_osm.py --municipio "Alcalá de Guadaíra" --sector construccion

Gratuito. Overpass limita la carga por IP: si falla por límite, espera y repite.
"""

from __future__ import annotations

import argparse
import asyncio

import httpx
import psycopg

from radar.agente.herramientas import descubrir_osm
from radar.agente.interpretacion import FiltrosBusqueda, SectorFiltro
from radar.config import get_settings


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--municipio", action="append", default=[])
    ap.add_argument("--provincia")
    ap.add_argument("--lote", type=int, default=0, help="desplazamiento en municipios (lotes de 15)")
    ap.add_argument("--sector", default="construccion")
    args = ap.parse_args()

    filtros = FiltrosBusqueda(sector=SectorFiltro(sector_interno=args.sector))
    settings = get_settings()
    async with httpx.AsyncClient() as cliente:
        with psycopg.connect(settings.supabase_db_url) as conn:
            resultado = await descubrir_osm(
                conn, cliente, filtros, municipios=args.municipio or None, provincia=args.provincia, desplazamiento=args.lote
            )
    for k, v in resultado.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
