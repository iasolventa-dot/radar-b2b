"""Prueba manual end-to-end del agente (tarea #21): interpreta una petición
en lenguaje natural, muestra los filtros resultantes y, si se confirma,
ejecuta el planificador (`radar.agente.planificador.planificar`) contra tu
Supabase real hasta que termine o pare a preguntar algo.

Uso (con el entorno virtual del worker activado):

    python scripts\\planificar.py "constructoras de Sevilla de 10 a 50 empleados" --presupuesto 2 --max-rondas 3

Sin `--ejecutar`, solo interpreta y muestra los filtros (no toca Supabase
ni gasta presupuesto) — para revisar que la interpretación es razonable
antes de lanzar nada.
"""

from __future__ import annotations

import argparse
import asyncio
import json

import httpx
import psycopg

from radar.agente.interpretacion import FiltrosBusqueda, interpretar_peticion
from radar.agente.planificador import planificar
from radar.config import get_settings


def _imprimir_filtros(filtros: FiltrosBusqueda) -> None:
    print(json.dumps(filtros.model_dump(), ensure_ascii=False, indent=2))


async def _ejecutar(peticion: str, contexto: str | None, presupuesto: float, max_rondas: int, ejecutar: bool) -> None:
    resultado_interpretacion = interpretar_peticion(peticion, contexto)
    if resultado_interpretacion.error:
        print(f"La interpretación falló: {resultado_interpretacion.error}")
        return
    filtros = resultado_interpretacion.filtros
    assert filtros is not None  # si no hay error, interpretar_peticion siempre devuelve filtros

    print("Filtros interpretados:")
    _imprimir_filtros(filtros)
    if filtros.supuestos:
        print("\nSupuestos declarados:")
        for s in filtros.supuestos:
            print(f"  - {s}")
    if filtros.preguntas:
        print("\nPreguntas del módulo de interpretación:")
        for p in filtros.preguntas:
            print(f"  - {p}")

    if not ejecutar:
        print("\n(pasa --ejecutar para lanzar el planificador con estos filtros)")
        return

    settings = get_settings()
    if not settings.supabase_db_url:
        raise SystemExit("SUPABASE_DB_URL no está configurada — ver .env.example")

    print(f"\nEjecutando planificador (presupuesto {presupuesto} EUR, máx. {max_rondas} rondas)...\n")
    async with httpx.AsyncClient() as cliente_http:
        with psycopg.connect(settings.supabase_db_url, autocommit=False) as conn:
            resultado = await planificar(conn, cliente_http, filtros, presupuesto_eur=presupuesto, max_rondas=max_rondas)

    for ronda in resultado.rondas:
        print(f"[ronda {ronda.numero}] {ronda.herramienta}({json.dumps(ronda.argumentos, ensure_ascii=False)})")
        print(f"  -> {json.dumps(ronda.resultado, ensure_ascii=False, default=str)}")

    print(f"\nFin: {resultado.motivo_fin}")
    if resultado.resumen:
        print(f"Resumen: {resultado.resumen}")
    if resultado.pregunta:
        print(f"Pregunta al usuario: {resultado.pregunta['pregunta']}")
        if resultado.pregunta.get("opciones"):
            print(f"  Opciones: {resultado.pregunta['opciones']}")
    if resultado.error:
        print(f"Error: {resultado.error}")
    print(f"Coste gastado: {resultado.coste_gastado_eur} EUR")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("peticion", help="Petición en lenguaje natural, p. ej. 'constructoras de Sevilla de 10 a 50 empleados'")
    parser.add_argument("--contexto", default=None, help="Contexto adicional opcional para la interpretación")
    parser.add_argument("--presupuesto", type=float, default=2.0, help="Presupuesto en EUR para el planificador (por defecto 2)")
    parser.add_argument("--max-rondas", type=int, default=5, help="Máximo de rondas del planificador (por defecto 5)")
    parser.add_argument("--ejecutar", action="store_true", help="Lanzar el planificador de verdad (si no, solo interpreta)")
    args = parser.parse_args()
    asyncio.run(_ejecutar(args.peticion, args.contexto, args.presupuesto, args.max_rondas, args.ejecutar))


if __name__ == "__main__":
    main()
