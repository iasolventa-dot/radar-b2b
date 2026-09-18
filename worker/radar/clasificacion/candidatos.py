"""Parte de `radar.clasificacion` que sí toca la base de datos: valida los
códigos que `radar.clasificacion.reglas` extrae del texto (el catálogo
`cnae` es la fuente de verdad, no hay que fiarse de que el BORME nunca se
equivoca) y busca candidatos por similitud cuando el texto no trae el
código explícito (`buscar_candidatos_cnae`, migración 202609181000) --
mismo patrón que `radar.resolucion.blocking` para duplicados.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

from radar.config import get_settings


@dataclass
class CandidatoCnae:
    codigo: str
    descripcion: str
    similitud: float


def _conectar() -> psycopg.Connection:
    settings = get_settings()
    if not settings.supabase_db_url:
        raise RuntimeError("SUPABASE_DB_URL no está configurada — ver .env.example")
    return psycopg.connect(settings.supabase_db_url)


def validar_codigo(
    codigo: str, version: str = "CNAE-2025", *, conexion: psycopg.Connection | None = None
) -> str | None:
    """Confirma que `codigo` (4 dígitos, sin punto -- el mismo formato que
    devuelve `radar.clasificacion.reglas` y en el que ya está guardado
    `cnae.codigo`, p. ej. "4399") existe de verdad en el catálogo, nivel 4,
    para `version`. Devuelve el código si existe o None -- las reglas de
    extracción solo miran el texto, nunca asumen que el número que
    encontraron es un CNAE real."""
    conn = conexion or _conectar()
    cerrar = conexion is None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select codigo from cnae where nivel = 4 and version = %s and codigo = %s",
                (version, codigo),
            )
            fila = cur.fetchone()
        return fila[0] if fila else None
    finally:
        if cerrar:
            conn.close()


def buscar_candidatos(
    texto: str, version: str = "CNAE-2025", limite: int = 8, *, conexion: psycopg.Connection | None = None
) -> list[CandidatoCnae]:
    """Candidatos de nivel 4 por similitud trigram contra `cnae.descripcion`
    -- para que `radar.clasificacion.llm` elija entre ellos cuando el
    texto no trae el código explícito (o el que trae no valida)."""
    conn = conexion or _conectar()
    cerrar = conexion is None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select codigo, descripcion, similitud from buscar_candidatos_cnae(%s, %s, %s)",
                (texto, version, limite),
            )
            filas = cur.fetchall()
        return [CandidatoCnae(codigo=f[0], descripcion=f[1], similitud=float(f[2])) for f in filas]
    finally:
        if cerrar:
            conn.close()
