"""Ejecuta `ConectorPLACSP` para un mes y procesa cada contrato adjudicado
con el orquestador (`radar.orquestador.procesar_registro`) — mismo patrón
que `ejecutar_borme.py`.

Job periódico (no herramienta del agente, decisión del plan de conexión
de fuentes 2026-09-16): PLACSP publica por mes y el fichero de un mes
pesa varias decenas o cientos de MB (148.514.308 bytes para 2025-08,
verificado) — demasiado lento para que el agente lo llame en directo
dentro de una búsqueda (`descubrir_borme`/`buscar_web` responden en
segundos; esto tarda uno o dos minutos solo en descargar y recorrer el
fichero). Se ejecuta una vez al mes, a mano o programado (n8n), y el
agente simplemente encuentra estas empresas ya cargadas al hacer
`consultar_bd` — mismo patrón que `cargar_catalogos.py`/`cargar_dirce.py`
para datos que se actualizan con su propio calendario, no en directo.

Uso (con el entorno virtual del worker activado):

    python scripts\\ejecutar_placsp.py --provincia Sevilla
    python scripts\\ejecutar_placsp.py --provincia Sevilla --provincia Cádiz --anyo 2025 --mes 8
    python scripts\\ejecutar_placsp.py --todas-las-provincias --anyo 2025 --mes 8

Sin `--anyo`/`--mes`, usa el mes anterior al actual -- el mes en curso
todavía se está publicando, no está cerrado. Sin `--provincia` ni
`--todas-las-provincias`, usa "Sevilla" (el piloto de este proyecto),
igual que `ejecutar_borme.py` usa "SEVILLA" por defecto.

Cada `RegistroBruto` se procesa y confirma (`commit`) por separado: si
uno falla, no se pierde el trabajo de los anteriores.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

import httpx
import psycopg

from radar.config import get_settings
from radar.fuentes.placsp import ConectorPLACSP
from radar.orquestador import procesar_registro


def _mes_anterior(hoy: datetime) -> tuple[int, int]:
    if hoy.month == 1:
        return hoy.year - 1, 12
    return hoy.year, hoy.month - 1


async def _ejecutar(provincias: list[str] | None, anyo: int, mes: int) -> None:
    settings = get_settings()
    if not settings.supabase_db_url:
        raise SystemExit("SUPABASE_DB_URL no está configurada — ver .env.example")

    contadores = {"vinculado": 0, "nueva_empresa": 0, "en_revision": 0, "ya_procesado": 0, "error": 0}

    async with httpx.AsyncClient() as cliente:
        conector = ConectorPLACSP(cliente)
        with psycopg.connect(settings.supabase_db_url, autocommit=False) as conn:
            parametros: dict = {"anyo": anyo, "mes": mes}
            if provincias:
                parametros["provincias"] = provincias

            print(f"Descargando PLACSP {anyo}-{mes:02d}... (puede tardar uno o dos minutos)")
            n_vistos = 0
            async for registro in conector.descubrir(parametros, max_coste_eur=0.0):
                n_vistos += 1
                try:
                    resultado = procesar_registro(registro, conn)
                    conn.commit()
                    contadores[resultado.accion] += 1
                    importe = (registro.campos.extra or {}).get("importe_adjudicado")
                    print(
                        f"  [{resultado.accion}] {registro.campos.razon_social!r} "
                        f"(NIF {registro.campos.nif}, {importe} EUR) -> empresa {resultado.empresa_id}"
                    )
                except Exception as exc:  # noqa: BLE001 — se informa y se sigue con el siguiente contrato
                    conn.rollback()
                    contadores["error"] += 1
                    print(f"  [error] {registro.campos.razon_social!r}: {exc}")

    zona = ", ".join(provincias) if provincias else "toda España"
    print(f"\nPLACSP {anyo}-{mes:02d}, {zona} (CPV construcción, división 45):")
    print(f"  contratos vistos: {n_vistos}")
    for accion, n in contadores.items():
        print(f"  - {accion}: {n}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--provincia", dest="provincias", action="append",
        help='Nombre de provincia tal como lo usa municipios.provincia (p. ej. "Sevilla"). Repetible.',
    )
    parser.add_argument("--todas-las-provincias", action="store_true", help="No filtrar por provincia (toda España)")
    parser.add_argument("--anyo", type=int, help="Por defecto, el año del mes anterior al actual")
    parser.add_argument("--mes", type=int, help="Por defecto, el mes anterior al actual (1-12)")
    args = parser.parse_args()

    if args.todas_las_provincias and args.provincias:
        parser.error("--todas-las-provincias y --provincia son incompatibles entre sí")

    anyo_defecto, mes_defecto = _mes_anterior(datetime.now(UTC))
    anyo = args.anyo if args.anyo is not None else anyo_defecto
    mes = args.mes if args.mes is not None else mes_defecto

    if args.todas_las_provincias:
        provincias = None
    else:
        provincias = args.provincias or ["Sevilla"]

    asyncio.run(_ejecutar(provincias, anyo, mes))


if __name__ == "__main__":
    main()
