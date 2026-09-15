"""Descarga la tabla del INE "Empresas por CCAA, actividad principal
(grupos CNAE 2009) y estrato de asalariados" (identificador API 39372,
DIRCE) y genera `supabase/seed/dirce.csv`.

No hay ninguna tabla oficial que cruce PROVINCIA + CNAE + "Empresas" a
la vez -- verificado en vivo el 2026-09-15 contra la API del INE, ver
la migración 202609150001 para el porqué. Esta es la más fina que sí
cruza CNAE con la unidad correcta ("Empresas", no "Locales"), a nivel de
Comunidad Autónoma.

No parsea por posición el campo `Nombre` de cada serie (frágil: las filas
de ámbito nacional tienen un segmento más que las de CCAA, y "Total
grupos CNAE93" no es un código real) -- usa el array `MetaData`
estructurado de cada serie, filtrando por la presencia de la variable
"Comunidades y Ciudades Autónomas" para quedarse solo con las filas de
CCAA, y extrayendo el código CNAE del propio campo `Nombre` (que sí
incluye el código, a diferencia de `MetaData` que solo da el texto) con
una expresión regular aplicada ÚNICAMENTE al segmento ya aislado por
posición estructural (tercer trozo tras partir por ". "), no a la cadena
completa.

Uso (con el entorno virtual del worker activado):
    python scripts\\generar_dirce.py
    python scripts\\generar_dirce.py --sin-descarga   # reutiliza la caché

Fuente verificada el 2026-09-15:
    https://servicios.ine.es/wstempus/js/ES/DATOS_TABLA/39372?nult=1&tip=AM
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parents[2]  # .../radar-b2b
SALIDA = RAIZ / "supabase" / "seed"
CACHE = SALIDA / "_ine"

URL_TABLA_39372 = "https://servicios.ine.es/wstempus/js/ES/DATOS_TABLA/39372?nult=1&tip=AM"
FICHERO_CACHE = "dirce_39372.json"

AGENTE = "Mozilla/5.0 (compatible; RadarB2B/1.0; +uso interno Solventa IA)"

# El tercer segmento de `Nombre` (tras partir por ". ") es, para las filas
# de CCAA, "<código> <texto>." (p. ej. "41 Construcción de edificios.").
# Las filas "Total grupos CNAE93" (el total agregado por CCAA+estrato, sin
# desagregar por actividad) no encajan en este patrón a propósito -- se
# descartan, no son un código real.
PATRON_CODIGO = re.compile(r"^(\d{2,4})\s+")


def descargar(sin_descarga: bool) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    ruta = CACHE / FICHERO_CACHE
    if sin_descarga and ruta.exists():
        print(f"  (caché) {FICHERO_CACHE}")
        return json.loads(ruta.read_text(encoding="utf-8"))
    with httpx.Client(timeout=120.0, headers={"User-Agent": AGENTE}, follow_redirects=True) as cli:
        respuesta = cli.get(URL_TABLA_39372)
        respuesta.raise_for_status()
    ruta.write_bytes(respuesta.content)
    print(f"  descargado {FICHERO_CACHE} ({len(respuesta.content):,} bytes)")
    return respuesta.json()


def es_fila_ccaa(serie: dict) -> str | None:
    """Devuelve el nombre de la CCAA si la serie está desagregada por esa
    variable, o `None` si es una fila de ámbito nacional (que tiene un
    segmento extra en `Nombre` y no interesa aquí)."""
    for meta in serie.get("MetaData", []):
        if meta.get("T3_Variable") == "Comunidades y Ciudades Autónomas":
            return str(meta["Nombre"])
    return None


def extraer_codigo(nombre_serie: str) -> str | None:
    partes = nombre_serie.split(". ")
    if len(partes) < 3:
        return None
    m = PATRON_CODIGO.match(partes[2])
    return m.group(1) if m else None


def extraer_estrato(serie: dict) -> str | None:
    for meta in serie.get("MetaData", []):
        if meta.get("T3_Variable") == "Estrato de asalariados":
            return str(meta["Nombre"])
    return None


def procesar(datos: list[dict]) -> list[tuple[str, str, str, int, int]]:
    filas: list[tuple[str, str, str, int, int]] = []
    saltadas_no_ccaa = saltadas_sin_codigo = saltadas_sin_dato = 0
    for serie in datos:
        ccaa = es_fila_ccaa(serie)
        if ccaa is None:
            saltadas_no_ccaa += 1
            continue
        codigo = extraer_codigo(serie["Nombre"])
        if codigo is None:
            saltadas_sin_codigo += 1  # incluye "Total grupos CNAE93", esperado
            continue
        estrato = extraer_estrato(serie)
        if estrato is None:
            continue
        datos_serie = serie.get("Data") or []
        if not datos_serie:
            saltadas_sin_dato += 1
            continue
        ultimo = datos_serie[-1]
        anyo = ultimo.get("Anyo")
        valor = ultimo.get("Valor")
        if anyo is None or valor is None:
            saltadas_sin_dato += 1
            continue
        filas.append((ccaa, codigo, estrato, int(anyo), int(valor)))

    print(
        f"  {len(filas)} filas útiles | descartadas: {saltadas_no_ccaa} no-CCAA, "
        f"{saltadas_sin_codigo} sin código (totales agregados), {saltadas_sin_dato} sin dato"
    )
    return filas


def verificar_contra_catalogo_cnae(filas: list[tuple[str, str, str, int, int]]) -> None:
    """Nunca inventar (principio 5): si algún código de DIRCE no existe en
    el catálogo CNAE-2009 ya cargado, la FK compuesta de la migración
    202609150001 rechazaría esa fila al cargarla -- mejor avisar aquí,
    con el código exacto, que dejar que cargar_dirce.py falle a medias."""
    ruta_cnae = SALIDA / "cnae.csv"
    if not ruta_cnae.exists():
        print("  aviso: no se encuentra cnae.csv -- no se puede verificar contra el catálogo", file=sys.stderr)
        return
    with ruta_cnae.open(encoding="utf-8") as f:
        codigos_2009 = {fila["codigo"] for fila in csv.DictReader(f) if fila["version"] == "CNAE-2009"}
    codigos_dirce = {f[1] for f in filas}
    huerfanos = codigos_dirce - codigos_2009
    if huerfanos:
        raise SystemExit(
            f"{len(huerfanos)} código(s) de DIRCE no existen en cnae.csv (CNAE-2009): {sorted(huerfanos)}\n"
            "La tabla del INE puede haber cambiado de estructura -- revisar antes de cargar."
        )
    print(f"  verificado: los {len(codigos_dirce)} códigos de DIRCE existen en el catálogo CNAE-2009")


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera supabase/seed/dirce.csv desde la API del INE.")
    parser.add_argument("--sin-descarga", action="store_true", help="reutiliza el fichero ya descargado")
    args = parser.parse_args()

    SALIDA.mkdir(parents=True, exist_ok=True)

    print("Descargando tabla 39372 del INE (Empresas por CCAA, CNAE y estrato)...")
    datos = descargar(args.sin_descarga)
    print(f"  {len(datos)} series en total")

    print("Procesando series...")
    filas = procesar(datos)

    print("Verificando contra el catálogo CNAE ya cargado...")
    verificar_contra_catalogo_cnae(filas)

    ruta_salida = SALIDA / "dirce.csv"
    with ruta_salida.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(["ccaa", "codigo_cnae", "estrato_asalariados", "anyo", "empresas"])
        escritor.writerows(filas)
    print(f"Escrito {ruta_salida} ({ruta_salida.stat().st_size:,} bytes, {len(filas)} filas)")
    print("\nListo. Cargar con: python scripts\\cargar_dirce.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
