"""Carga `supabase/seed/dirce.csv` en la tabla `dirce_cobertura` de
Supabase. Upsert por la restricción unique (ccaa, codigo_cnae,
version_cnae, estrato_asalariados, anyo) -- se puede ejecutar tantas
veces como se quiera sin duplicar filas.

Requisitos previos:
  1. Aplicar la migración 202609150001:
         python scripts\\aplicar_migracion.py 202609150001
  2. Tener el CSV generado:
         python scripts\\generar_dirce.py

Uso (con el entorno virtual del worker activado):
    python scripts\\cargar_dirce.py
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]  # .../radar-b2b
SEED = RAIZ / "supabase" / "seed"

SQL_UPSERT = """
insert into dirce_cobertura (ccaa, codigo_cnae, version_cnae, estrato_asalariados, anyo, empresas)
values (%(ccaa)s, %(codigo_cnae)s, 'CNAE-2009', %(estrato_asalariados)s, %(anyo)s, %(empresas)s)
on conflict (ccaa, codigo_cnae, version_cnae, estrato_asalariados, anyo)
do update set empresas = excluded.empresas
"""


def main() -> None:
    load_dotenv(RAIZ / ".env")
    db_url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if not db_url:
        sys.exit(f"SUPABASE_DB_URL no está definida en {RAIZ / '.env'}")

    ruta = SEED / "dirce.csv"
    if not ruta.exists():
        sys.exit(f"No encuentro {ruta}.\nGenera el CSV antes: python scripts\\generar_dirce.py")

    with ruta.open(encoding="utf-8", newline="") as f:
        filas = [
            {
                "ccaa": f["ccaa"],
                "codigo_cnae": f["codigo_cnae"],
                "estrato_asalariados": f["estrato_asalariados"],
                "anyo": int(f["anyo"]),
                "empresas": int(f["empresas"]),
            }
            for f in csv.DictReader(f)
        ]

    print(f"Filas a cargar: {len(filas)}")
    print("Conectando a la base de datos...")
    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.executemany(SQL_UPSERT, filas)
            conn.commit()

            with conn.cursor() as cur:
                cur.execute("select count(*) from dirce_cobertura")
                (total,) = cur.fetchone() or (0,)
                cur.execute("select count(distinct ccaa) from dirce_cobertura")
                (n_ccaa,) = cur.fetchone() or (0,)
                cur.execute("select max(anyo) from dirce_cobertura")
                (anyo_max,) = cur.fetchone() or (None,)
    except psycopg.Error as exc:
        sys.exit(f"\nError cargando dirce_cobertura:\n{exc}")

    print("\nCarga terminada.")
    print(f"  dirce_cobertura: {total} filas, {n_ccaa} comunidades autónomas, año más reciente: {anyo_max}")


if __name__ == "__main__":
    main()
