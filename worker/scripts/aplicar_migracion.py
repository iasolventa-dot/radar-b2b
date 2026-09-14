"""Aplica una migración del esquema directamente por psycopg,
sin pasar por el SQL Editor del navegador.

Lee SUPABASE_DB_URL del archivo .env en la raíz del proyecto
(dos niveles por encima de este script: worker/scripts/ -> worker/ -> raíz)
y ejecuta el SQL tal cual.

Uso (con el entorno virtual del worker activado):
    python scripts\\aplicar_migracion.py
    python scripts\\aplicar_migracion.py 202609140001_catalogos_cnae_municipios.sql
    python scripts\\aplicar_migracion.py --listar

Sin argumento aplica la migración inicial, como hacía la primera versión de
este script. Con un nombre de fichero (o una ruta) aplica esa. Las
migraciones del proyecto son idempotentes, así que volver a aplicar una ya
aplicada no debería romper nada — pero se pide confirmación igualmente
cuando no es la inicial, para que no se escape un fichero equivocado.

Al terminar lista las tablas de `public` y cuenta las filas de `fuentes`
(deben ser 11) como comprobación de que la conexión es la que se espera.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]  # .../radar-b2b
MIGRACIONES = RAIZ / "supabase" / "migrations"
INICIAL = "202609100001_esquema_inicial.sql"


def listar_migraciones() -> list[Path]:
    return sorted(MIGRACIONES.glob("*.sql"))


def resolver(nombre: str) -> Path:
    """Acepta un nombre de fichero, un prefijo de fecha o una ruta."""
    candidata = Path(nombre)
    if candidata.is_file():
        return candidata

    directa = MIGRACIONES / nombre
    if directa.is_file():
        return directa

    coincidencias = [m for m in listar_migraciones() if m.name.startswith(nombre)]
    if len(coincidencias) == 1:
        return coincidencias[0]
    if len(coincidencias) > 1:
        nombres = "\n  ".join(m.name for m in coincidencias)
        sys.exit(f"'{nombre}' coincide con varias migraciones:\n  {nombres}")

    disponibles = "\n  ".join(m.name for m in listar_migraciones()) or "(ninguna)"
    sys.exit(f"No encuentro la migración '{nombre}'.\nDisponibles:\n  {disponibles}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Aplica una migración SQL a Supabase.")
    parser.add_argument(
        "migracion",
        nargs="?",
        default=INICIAL,
        help=f"nombre o ruta de la migración (por defecto {INICIAL})",
    )
    parser.add_argument("--listar", action="store_true", help="lista las migraciones y sale")
    parser.add_argument("--si", action="store_true", help="no pide confirmación")
    args = parser.parse_args()

    if args.listar:
        for m in listar_migraciones():
            print(f"  {m.name}")
        return

    ruta = resolver(args.migracion)

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

    sql = ruta.read_text(encoding="utf-8")

    print(f"Migración: {ruta.name}")
    if ruta.name != INICIAL and not args.si:
        respuesta = input("¿Aplicar esta migración? [s/N] ").strip().lower()
        if respuesta not in ("s", "si", "sí"):
            sys.exit("Cancelado.")

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
            print("Ojo: no son 11 — revisa la sección 12 de la migración inicial.")


if __name__ == "__main__":
    main()
