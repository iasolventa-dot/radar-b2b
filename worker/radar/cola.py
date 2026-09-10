"""Consumo de la cola de trabajos (Supabase Queues / pgmq).

Envoltorio mínimo pero funcional sobre las funciones SQL de pgmq
(`pgmq.send`, `pgmq.read`, `pgmq.delete`, `pgmq.archive`). El worker abre
una conexión psycopg directa (no el cliente REST) porque pgmq se expone
como funciones de Postgres.

Uso típico:

    from radar.cola import Cola

    cola = Cola(nombre="descubrimiento")
    cola.encolar({"conector": "borme", "provincia": "41"})
    for mensaje in cola.leer(n=10):
        ...  # procesar
        cola.eliminar(mensaje["msg_id"])
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import psycopg

from radar.config import get_settings


@dataclass
class Cola:
    """Cliente mínimo de una cola pgmq concreta."""

    nombre: str

    def _conectar(self) -> psycopg.Connection:
        settings = get_settings()
        if not settings.supabase_db_url:
            raise RuntimeError(
                "SUPABASE_DB_URL no está configurada — ver .env.example"
            )
        return psycopg.connect(settings.supabase_db_url)

    def crear_si_no_existe(self) -> None:
        with self._conectar() as conn, conn.cursor() as cur:
            cur.execute("select pgmq.create(%s)", (self.nombre,))
            conn.commit()

    def encolar(self, mensaje: dict[str, Any], retraso_s: int = 0) -> int:
        """Añade un mensaje a la cola. Devuelve el `msg_id`."""
        with self._conectar() as conn, conn.cursor() as cur:
            cur.execute(
                "select * from pgmq.send(%s, %s::jsonb, %s)",
                (self.nombre, json.dumps(mensaje), retraso_s),
            )
            (msg_id,) = cur.fetchone()
            conn.commit()
            return int(msg_id)

    def leer(self, n: int = 10, vt_segundos: int = 30) -> list[dict[str, Any]]:
        """Lee hasta `n` mensajes, invisibles durante `vt_segundos` (visibility timeout)."""
        with self._conectar() as conn, conn.cursor() as cur:
            cur.execute(
                "select msg_id, read_ct, enqueued_at, vt, message "
                "from pgmq.read(%s, %s, %s)",
                (self.nombre, vt_segundos, n),
            )
            columnas = [d.name for d in cur.description]
            return [dict(zip(columnas, fila)) for fila in cur.fetchall()]

    def eliminar(self, msg_id: int) -> None:
        with self._conectar() as conn, conn.cursor() as cur:
            cur.execute("select pgmq.delete(%s, %s)", (self.nombre, msg_id))
            conn.commit()

    def archivar(self, msg_id: int) -> None:
        """Como eliminar, pero conserva el mensaje en la tabla de archivo (auditoría)."""
        with self._conectar() as conn, conn.cursor() as cur:
            cur.execute("select pgmq.archive(%s, %s)", (self.nombre, msg_id))
            conn.commit()
