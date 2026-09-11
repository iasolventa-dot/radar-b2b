"""Bloqueo: reduce qué empresas de la base hay que comparar con un registro
nuevo (doc 05 §2.1) antes de puntuar con `radar.resolucion.scoring.comparar`.

Usa la función SQL `buscar_candidatos_empresa` (migración
`202609100001_esquema_inicial.sql` §10): similitud trigram sobre nombres
normalizados + radio geográfico cuando hay coordenadas. Conexión directa
por psycopg, igual que `radar.cola` — es una única consulta de solo
lectura, no necesita el cliente REST de Supabase.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

from radar.config import get_settings


@dataclass
class CandidatoBloqueo:
    empresa_id: str
    razon_social: str | None
    nombre_comercial: str | None
    nif: str | None
    similitud: float
    distancia_m: float | None


def _conectar() -> psycopg.Connection:
    settings = get_settings()
    if not settings.supabase_db_url:
        raise RuntimeError("SUPABASE_DB_URL no está configurada — ver .env.example")
    return psycopg.connect(settings.supabase_db_url)


def buscar_candidatos(
    nombre: str,
    lon: float | None = None,
    lat: float | None = None,
    radio_m: int = 20_000,
    limite: int = 20,
    conexion: psycopg.Connection | None = None,
) -> list[CandidatoBloqueo]:
    """Empresas existentes parecidas por nombre (y, si hay coordenadas, cerca).

    Primer paso de bloqueo antes de puntuar con `comparar()`. No decide
    nada por sí sola: cada candidato devuelto todavía hay que puntuarlo.
    """
    conn = conexion or _conectar()
    cerrar = conexion is None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select empresa_id, razon_social, nombre_comercial, nif, similitud, distancia_m "
                "from buscar_candidatos_empresa(%s, %s, %s, %s, %s)",
                (nombre, lon, lat, radio_m, limite),
            )
            filas = cur.fetchall()
        return [
            CandidatoBloqueo(
                empresa_id=str(f[0]),
                razon_social=f[1],
                nombre_comercial=f[2],
                nif=f[3],
                similitud=float(f[4]) if f[4] is not None else 0.0,
                distancia_m=float(f[5]) if f[5] is not None else None,
            )
            for f in filas
        ]
    finally:
        if cerrar:
            conn.close()


def telefonos_compartidos(umbral_empresas: int = 3, conexion: psycopg.Connection | None = None) -> set[str]:
    """Teléfonos que aparecen en más de `umbral_empresas` empresas con NIF
    distinto (gestorías, centralitas de polígono) — doc 05 §2.3: dejan de
    puntuar como señal de identidad en `comparar()`.
    """
    conn = conexion or _conectar()
    cerrar = conexion is None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                select c.valor_norm
                from canales_contacto c
                join empresas e on e.id = c.empresa_id and e.fusionada_en is null
                where c.tipo = 'telefono'
                group by c.valor_norm
                having count(distinct coalesce(e.nif, e.id::text)) > %s
                """,
                (umbral_empresas,),
            )
            return {fila[0] for fila in cur.fetchall()}
    finally:
        if cerrar:
            conn.close()
