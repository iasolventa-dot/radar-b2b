"""Importa `worker/tests/golden/registros_entrada.csv` a la tabla
`golden_candidatos` de Supabase (migración `202609102000_golden_set_revision.sql`),
para poder revisarlo desde el panel web en vez de editar el CSV a mano.

Es un *upsert* por `id_fila`: se puede ejecutar tantas veces como se quiera
(por ejemplo, tras regenerar el CSV con `generar_candidatos_golden.py`)
sin duplicar filas ni pisar el trabajo de revisión ya hecho — `estado_revision`,
`entidad_id_real` y `notas` solo se sobreescriben si la fila en Supabase
seguía `pendiente` (si ya se promovió o descartó a mano, se conserva).

Uso (con el entorno virtual del worker activado, tras aplicar la migración
202609102000 en Supabase):
    python scripts\\importar_candidatos_supabase.py
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.types.array import ListDumper

RAIZ = Path(__file__).resolve().parents[2]  # .../radar-b2b
ENTRADA = RAIZ / "worker" / "tests" / "golden" / "registros_entrada.csv"

COLUMNAS_TEXTO = [
    "id_fila", "categoria_candidato", "confianza_sector", "fuente", "id_externo",
    "razon_social", "municipio", "codigo_postal", "hoja_registral", "objeto_social",
    "capital_eur", "url_evidencia", "fecha_publicacion", "identificador_boletin", "notas",
]
COLUMNAS_ARRAY = ["tipos_acto", "administradores", "posible_homonimo_de", "posible_grupo_con"]


def dividir(valor: str) -> list[str]:
    return [v.strip() for v in valor.split(";") if v.strip()] if valor else []


def fila_a_parametros(fila: dict) -> dict:
    parametros = {col: (fila.get(col) or None) for col in COLUMNAS_TEXTO}
    for col in COLUMNAS_ARRAY:
        parametros[col] = dividir(fila.get(col, ""))
    parametros["es_municipio_principal"] = fila.get("es_municipio_principal", "").strip().lower() == "si"
    return parametros


SQL_UPSERT = """
insert into golden_candidatos (
    id_fila, categoria_candidato, confianza_sector, fuente, id_externo,
    razon_social, municipio, codigo_postal, es_municipio_principal, hoja_registral,
    tipos_acto, objeto_social, capital_eur, administradores,
    posible_homonimo_de, posible_grupo_con, url_evidencia, fecha_publicacion,
    identificador_boletin, notas
) values (
    %(id_fila)s, %(categoria_candidato)s, %(confianza_sector)s, %(fuente)s, %(id_externo)s,
    %(razon_social)s, %(municipio)s, %(codigo_postal)s, %(es_municipio_principal)s, %(hoja_registral)s,
    %(tipos_acto)s, %(objeto_social)s, %(capital_eur)s, %(administradores)s,
    %(posible_homonimo_de)s, %(posible_grupo_con)s, %(url_evidencia)s, %(fecha_publicacion)s,
    %(identificador_boletin)s, %(notas)s
)
on conflict (id_fila) do update set
    categoria_candidato    = excluded.categoria_candidato,
    confianza_sector       = excluded.confianza_sector,
    fuente                 = excluded.fuente,
    id_externo             = excluded.id_externo,
    razon_social           = excluded.razon_social,
    municipio              = excluded.municipio,
    codigo_postal          = excluded.codigo_postal,
    es_municipio_principal = excluded.es_municipio_principal,
    hoja_registral         = excluded.hoja_registral,
    tipos_acto             = excluded.tipos_acto,
    objeto_social          = excluded.objeto_social,
    capital_eur            = excluded.capital_eur,
    administradores        = excluded.administradores,
    posible_homonimo_de    = excluded.posible_homonimo_de,
    posible_grupo_con      = excluded.posible_grupo_con,
    url_evidencia          = excluded.url_evidencia,
    fecha_publicacion      = excluded.fecha_publicacion,
    identificador_boletin  = excluded.identificador_boletin
    -- notas, estado_revision y entidad_id_real se omiten a propósito: son
    -- el trabajo de revisión humana. Al no listarlas aquí, ON CONFLICT DO
    -- UPDATE las deja tal cual estaban si la fila ya existía (doc 05,
    -- "nunca se sobreescribe evidencia").
"""


def main() -> None:
    load_dotenv(RAIZ / ".env")
    db_url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if not db_url:
        sys.exit(f"SUPABASE_DB_URL no está definida en el .env. Revisa: {RAIZ / '.env'}")
    if "TU_CONTRASEÑA" in db_url or "[YOUR-PASSWORD]" in db_url:
        sys.exit("SUPABASE_DB_URL todavía tiene el placeholder de la contraseña sin sustituir.")
    if not ENTRADA.exists():
        sys.exit(
            f"No encuentro {ENTRADA}. Genera candidatos primero con "
            "scripts/generar_candidatos_golden.py."
        )

    with ENTRADA.open(newline="", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    print(f"Leídas {len(filas)} filas de {ENTRADA.name}")

    print("Conectando a Supabase...")
    with psycopg.connect(db_url, autocommit=False) as conn:
        # los campos text[] necesitan que psycopg sepa adaptar listas de Python
        conn.adapters.register_dumper(list, ListDumper)
        with conn.cursor() as cur:
            for fila in filas:
                cur.execute(SQL_UPSERT, fila_a_parametros(fila))
        conn.commit()

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("select estado_revision, count(*) from golden_candidatos group by estado_revision")
        print("\nEstado de golden_candidatos tras la importación:")
        for estado, n in cur.fetchall():
            print(f"  - {estado}: {n}")
        cur.execute("select categoria_candidato, count(*) from golden_candidatos group by categoria_candidato order by 1")
        print("\nPor categoría:")
        for categoria, n in cur.fetchall():
            print(f"  - {categoria}: {n}")


if __name__ == "__main__":
    main()
