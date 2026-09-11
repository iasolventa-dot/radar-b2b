"""Aplica la migración inicial del esquema directamente por psycopg,
sin pasar por el SQL Editor del navegador.

Lee SUPABASE_DB_URL del archivo .env en la raíz del proyecto
(dos niveles por encima de este script: worker/scripts/ -> worker/ -> raíz),
ejecuta supabase/migrations/202609100001_esquema_inicial.sql tal cual,
y al final lista las tablas creadas y cuenta las filas de `fuentes`
(debe dar 11) para confirmar que ha funcionado.

Uso (con el entorno virtual del worker activado):
    python scripts\\aplicar_migracion.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]  # .../radar-b2b
MIGRACION = RAIZ / "supabase" / "migrations" / "202609100001_esquema_inicial.sql"


def main() -> None:
    load_dotenv(RAIZ / ".env")
    db_url = os.environ.get("SUPABASE_DB_URL", "").strip()

    if not db_url:
        sys.exit(
            "SUPABASE_DB_URL no está definida (o está vacía) en el .env.\n"
            f"Revisa: {RAIZ / '.env'}"
        )
    if "TU_CONTRASEÑA" in db_url or "[YOUR-PASSWORD]" in db_url:
        sys.exit(
            "SUPABASE_DB_URL todavía tiene el placeholder de la contraseña sin "
            "sustituir. Edita el .env con la contraseña real de la base de datos."
        )
    if not MIGRACION.exists():
        sys.exit(f"No encuentro el archivo de migración en {MIGRACION}")

    sql = MIGRACION.read_text(encoding="utf-8")

    print(f"Migración: {MIGRACION.name}")
    print("Conectando a la base de datos...")
    try:
        with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
            print("Aplicando migración (puede tardar unos segundos)...")
            cur.execute(sql)
    except psycopg.Error as exc:
        sys.exit(f"\nError aplicando la migración:\n{exc}")

    print("Migración aplicada sin errores.\n")

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables "
            "where table_schema = 'public' order by table_name"
        )
        tablas = [r[0] for r in cur.fetchall()]
        print(f"Tablas en 'public' ({len(tablas)}):")
        for t in tablas:
            print(f"  - {t}")

        cur.execute("select count(*) from fuentes")
        fila = cur.fetchone()
        if fila is None:
            sys.exit("select count(*) from fuentes no devolvió ninguna fila (no debería pasar nunca)")
        (n,) = fila
        print(f"\nFilas en 'fuentes': {n} (esperado: 11)")
        if n != 11:
            print("Ojo: no son 11 — revisa la sección 12 de la migración.")


if __name__ == "__main__":
    main()
