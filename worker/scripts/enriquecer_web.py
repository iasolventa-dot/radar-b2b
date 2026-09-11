"""Prueba manual de `radar.extraccion.enriquecer_desde_web`: descarga la
portada de una URL (+ aviso legal/contacto si los encuentra), extrae con
reglas y, si hace falta, con el LLM de respaldo, e imprime el
`RegistroBruto` resultante.

Uso (con el entorno virtual del worker activado):

    python scripts\\enriquecer_web.py https://www.ejemplo-empresa.es

Con `--guardar`, además lo procesa con el orquestador
(`radar.orquestador.procesar_registro`) contra tu Supabase — igual que
`scripts/ejecutar_borme.py`, pero para una sola URL. Sin esa opción, es
solo de lectura: no toca la base de datos.
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
from radar.orquestador import procesar_registro


async def _ejecutar(url: str, guardar: bool) -> None:
    async with httpx.AsyncClient() as cliente:
        registro = await enriquecer_desde_web(cliente, url)

    if registro is None:
        print("No se pudo leer nada de esa URL (robots.txt lo prohíbe, o la web no responde).")
        return

    print("Campos extraídos:")
    print(json.dumps(dataclasses.asdict(registro.campos), ensure_ascii=False, indent=2, default=str))
    print(f"\nFuente del dato: {registro.campos.extra.get('fuente_dato')}")
    if registro.campos.extra.get("avisos"):
        print(f"Avisos: {registro.campos.extra['avisos']}")

    if not guardar:
        print("\n(no se ha guardado nada — pasa --guardar para procesarlo con el orquestador)")
        return

    settings = get_settings()
    if not settings.supabase_db_url:
        raise SystemExit("SUPABASE_DB_URL no está configurada — ver .env.example")
    with psycopg.connect(settings.supabase_db_url, autocommit=False) as conn:
        resultado = procesar_registro(registro, conn)
        conn.commit()
    print(f"\n[{resultado.accion}] empresa {resultado.empresa_id} (puntuación {resultado.puntuacion_match})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="URL de la portada de la web a analizar")
    parser.add_argument("--guardar", action="store_true", help="Procesarlo con el orquestador contra Supabase")
    args = parser.parse_args()
    asyncio.run(_ejecutar(args.url, args.guardar))


if __name__ == "__main__":
    main()
