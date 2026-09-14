"""Carga los catálogos `cnae`, `cnae_correspondencias` y `municipios` en
Supabase desde los CSV de `supabase/seed/`.

Es un *upsert*: se puede ejecutar tantas veces como se quiera sin duplicar
filas (mismo criterio que `importar_candidatos_supabase.py`). Los catálogos
son datos de referencia, no trabajo humano, así que aquí sí se sobreescribe
la descripción cuando el INE la cambia.

Requisitos previos:
  1. Aplicar la migración 202609140001:
         python scripts\\aplicar_migracion.py 202609140001_catalogos_cnae_municipios.sql
  2. Tener los CSV generados:
         python scripts\\generar_catalogos.py

Uso (con el entorno virtual del worker activado):
    python scripts\\cargar_catalogos.py

Lee SUPABASE_DB_URL del .env de la raíz, igual que el resto de scripts.
Al terminar, lanza `actualizar_municipio_ine_sedes()` para rellenar el
código INE de las sedes que ya estuvieran guardadas sin él.
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

SQL_CNAE = """
insert into cnae (codigo, version, descripcion, nivel, codigo_padre)
values (%(codigo)s, %(version)s, %(descripcion)s, %(nivel)s, %(codigo_padre)s)
on conflict (codigo, version) do update set
    descripcion  = excluded.descripcion,
    nivel        = excluded.nivel,
    codigo_padre = excluded.codigo_padre
"""

SQL_CORRESPONDENCIAS = """
insert into cnae_correspondencias
    (codigo_origen, version_origen, codigo_destino, version_destino, nivel)
values
    (%(codigo_origen)s, %(version_origen)s, %(codigo_destino)s, %(version_destino)s, %(nivel)s)
on conflict (codigo_origen, version_origen, codigo_destino, version_destino)
do update set nivel = excluded.nivel
"""

SQL_MUNICIPIOS = """
insert into municipios (codigo_ine, nombre, provincia, cod_provincia, ccaa)
values (%(codigo_ine)s, %(nombre)s, %(provincia)s, %(cod_provincia)s, %(ccaa)s)
on conflict (codigo_ine) do update set
    nombre        = excluded.nombre,
    provincia     = excluded.provincia,
    cod_provincia = excluded.cod_provincia,
    ccaa          = excluded.ccaa
"""


def leer_csv(nombre: str) -> list[dict[str, str]]:
    ruta = SEED / nombre
    if not ruta.exists():
        sys.exit(f"No encuentro {ruta}.\nGenera los CSV antes: python scripts\\generar_catalogos.py")
    with ruta.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def preparar_cnae(filas: list[dict[str, str]]) -> list[dict]:
    """Ordena por nivel: la clave ajena `codigo_padre` se comprueba fila a
    fila, así que una división no puede entrar antes que su sección."""
    preparadas = [
        {
            "codigo": f["codigo"],
            "version": f["version"],
            "descripcion": f["descripcion"],
            "nivel": int(f["nivel"]),
            "codigo_padre": f["codigo_padre"] or None,
        }
        for f in filas
    ]
    return sorted(preparadas, key=lambda f: (f["nivel"], f["codigo"]))


def main() -> None:
    load_dotenv(RAIZ / ".env")
    db_url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if not db_url:
        sys.exit(f"SUPABASE_DB_URL no está definida en {RAIZ / '.env'}")
    if "TU_CONTRASEÑA" in db_url or "[YOUR-PASSWORD]" in db_url:
        sys.exit("SUPABASE_DB_URL todavía tiene el placeholder de la contraseña sin sustituir.")

    cnae = preparar_cnae(leer_csv("cnae.csv"))
    correspondencias = [
        {
            "codigo_origen": f["codigo_origen"],
            "version_origen": f["version_origen"],
            "codigo_destino": f["codigo_destino"],
            "version_destino": f["version_destino"],
            "nivel": int(f["nivel"]),
        }
        for f in leer_csv("cnae_correspondencias.csv")
    ]
    municipios = [dict(f) for f in leer_csv("municipios.csv")]

    print(f"CNAE: {len(cnae)} | correspondencias: {len(correspondencias)} | municipios: {len(municipios)}")
    print("Conectando a la base de datos...")

    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                print("Cargando cnae...")
                cur.executemany(SQL_CNAE, cnae)
                print("Cargando cnae_correspondencias...")
                cur.executemany(SQL_CORRESPONDENCIAS, correspondencias)
                print("Cargando municipios...")
                cur.executemany(SQL_MUNICIPIOS, municipios)
            conn.commit()

            with conn.cursor() as cur:
                cur.execute("select actualizar_municipio_ine_sedes()")
                fila = cur.fetchone()
                actualizadas = fila[0] if fila else 0
                conn.commit()

                cur.execute("select count(*) from cnae")
                n_cnae = (cur.fetchone() or [0])[0]
                cur.execute("select count(*) from cnae_correspondencias")
                n_corr = (cur.fetchone() or [0])[0]
                cur.execute("select count(*) from municipios")
                n_mun = (cur.fetchone() or [0])[0]
                cur.execute(
                    "select count(*) filter (where municipio_ine is not null), count(*) from sedes"
                )
                resueltas, total = cur.fetchone() or (0, 0)
    except psycopg.Error as exc:
        sys.exit(f"\nError cargando los catálogos:\n{exc}")

    print("\nCarga terminada.")
    print(f"  cnae:                  {n_cnae}")
    print(f"  cnae_correspondencias: {n_corr}")
    print(f"  municipios:            {n_mun}")
    print(f"\nSedes con código INE: {resueltas} de {total} ({actualizadas} resueltas ahora).")
    if total and resueltas < total:
        print("Las que falten, con su motivo:")
        print("  select municipio_nombre, provincia from sedes where municipio_ine is null;")


if __name__ == "__main__":
    main()
