"""Prueba manual de `radar.fuentes.buscador_web.buscar`: ejecuta UNA
consulta literal contra el buscador web (D-06) e imprime las URLs
encontradas. No extrae ningún dato de empresa (doc 04 §5: los snippets no
son evidencia) — para eso, pasa cada URL a `scripts/enriquecer_web.py`.

Uso (con el entorno virtual del worker activado):

    python scripts\\buscar_web.py "site:construccionesperez.es aviso legal"

Con `--enriquecer`, además descarga y analiza cada URL encontrada con
`radar.extraccion.enriquecer_desde_web` (igual que `enriquecer_web.py`) e
imprime lo que saca de cada una. Añade `--guardar` para, sobre eso,
procesarlo con el orquestador contra tu Supabase.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json

import httpx
import psycopg

from radar.config import get_settings
from radar.extraccion import enriquecer_desde_web
from radar.fuentes.buscador_web import buscar
from radar.orquestador import procesar_registro


async def _enriquecer_y_opcionalmente_guardar(url: str, guardar: bool) -> None:
    async with httpx.AsyncClient() as cliente:
        registro = await enriquecer_desde_web(cliente, url)
    if registro is None:
        print(f"  [{url}] no se pudo leer (robots.txt lo prohíbe, o la web no responde)")
        return

    print(f"  [{url}] campos extraídos:")
    print("    " + json.dumps(dataclasses.asdict(registro.campos), ensure_ascii=False, default=str))

    if not guardar:
        return
    settings = get_settings()
    if not settings.supabase_db_url:
        raise SystemExit("SUPABASE_DB_URL no está configurada — ver .env.example")
    with psycopg.connect(settings.supabase_db_url, autocommit=False) as conn:
        resultado = procesar_registro(registro, conn)
        conn.commit()
    print(f"    -> [{resultado.accion}] empresa {resultado.empresa_id} (puntuación {resultado.puntuacion_match})")


async def _ejecutar(consulta: str, max_resultados: int, enriquecer: bool, guardar: bool) -> None:
    resultado = buscar(None, consulta, max_resultados=max_resultados)

    if resultado.error:
        print(f"La herramienta de búsqueda falló: {resultado.error}")
        return
    if not resultado.resultados:
        print(f"Sin resultados (búsquedas facturadas: {resultado.numero_busquedas}).")
        if resultado.numero_busquedas == 0:
            print("El modelo no llegó a invocar la herramienta de búsqueda — no es un fallo de red, hay que revisar el prompt/tool_choice.")
        return

    print(f"{len(resultado.resultados)} URL(s) encontradas ({resultado.numero_busquedas} búsqueda(s) facturada(s)):\n")
    for r in resultado.resultados:
        print(f"- {r.url}  ({r.titulo})")

    if not enriquecer:
        print("\n(pasa --enriquecer para descargar y analizar cada URL)")
        return

    print("\nAnalizando cada URL con radar.extraccion.enriquecer_desde_web:")
    for r in resultado.resultados:
        await _enriquecer_y_opcionalmente_guardar(r.url, guardar)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("consulta", help="Consulta literal a ejecutar tal cual (doc 04 §5 da ejemplos de patrones)")
    parser.add_argument("--max-resultados", type=int, default=5, help="URLs a quedarse (por defecto 5)")
    parser.add_argument("--enriquecer", action="store_true", help="Descargar y analizar cada URL encontrada")
    parser.add_argument("--guardar", action="store_true", help="Con --enriquecer: procesarlo con el orquestador contra Supabase")
    args = parser.parse_args()
    if args.guardar and not args.enriquecer:
        parser.error("--guardar requiere --enriquecer")
    asyncio.run(_ejecutar(args.consulta, args.max_resultados, args.enriquecer, args.guardar))


if __name__ == "__main__":
    main()
