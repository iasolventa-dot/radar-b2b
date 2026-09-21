"""Comprobación de `descubrir_places` contra la base REAL con Google SIMULADO
(no hace falta clave ni gasta nada): todo se ejecuta dentro de una transacción
que se revierte al final.

Verifica el cumplimiento de las condiciones de Google y el cruce:
  1. Un lugar que ya tenemos (mismo nombre + mismas coordenadas) -> se
     vincula y SOLO se guarda su place_id.
  2. Un lugar `CLOSED_PERMANENTLY` -> se ignora.
  3. Un lugar desconocido sin web -> NO se guarda nada (no almacenable).
  4. Un lugar desconocido con web -> se sigue su web propia y se guarda lo
     que ella publica + el place_id.
  5. Nunca aparece ninguna observación con fuente google_places.

Uso: python scripts\\verificar_places_simulado.py
"""

from __future__ import annotations

import asyncio

import httpx
import psycopg

import radar.agente.descubrir_places as dp
from radar.config import get_settings
from radar.fuentes.base import CamposExtraidos, RegistroBruto


class SinCommit:
    """Envoltorio que ignora commit/rollback para poder revertir todo al final."""

    def __init__(self, conn: psycopg.Connection):
        self._c = conn

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def __getattr__(self, nombre):
        return getattr(self._c, nombre)


async def main() -> None:
    conn = psycopg.connect(get_settings().supabase_db_url)
    base = conn.execute(
        """
        select e.id, e.razon_social, extensions.st_y(s.geom::extensions.geometry), extensions.st_x(s.geom::extensions.geometry)
        from empresas e join sedes s on s.empresa_id = e.id and s.activa and s.geom is not null
        where e.fusionada_en is null and e.razon_social is not null limit 1
        """
    ).fetchone()
    assert base, "no hay empresa geocodificada para probar"
    eid, razon, lat, lon = base

    conn.execute(
        "insert into configuracion_secretos (clave, valor) values ('google_places_api_key', 'AIzaSy-SIMULADA-0000000000') "
        "on conflict (clave) do update set valor = excluded.valor"
    )

    respuesta = {
        "places": [
            {"id": "PLACE_CONOCIDA", "displayName": {"text": razon}, "formattedAddress": "Sevilla",
             "location": {"latitude": lat, "longitude": lon}, "businessStatus": "OPERATIONAL"},
            {"id": "PLACE_CERRADA", "displayName": {"text": "Negocio Cerrado SL"}, "businessStatus": "CLOSED_PERMANENTLY"},
            {"id": "PLACE_SIN_WEB", "displayName": {"text": "Reformas Sin Web Prueba"}, "businessStatus": "OPERATIONAL",
             "location": {"latitude": 37.30, "longitude": -5.90}},
            {"id": "PLACE_CON_WEB", "displayName": {"text": "Instalaciones Con Web Prueba"}, "businessStatus": "OPERATIONAL",
             "websiteUri": "https://instalaciones-con-web-prueba.es/", "nationalPhoneNumber": "955 000 111",
             "location": {"latitude": 37.31, "longitude": -5.91}},
        ]
    }

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=respuesta)

    async def web_falsa(cliente, url, dominio=None):
        return RegistroBruto(
            fuente="web_empresa", id_externo=None, url=url, payload={"prueba": True},
            campos=CamposExtraidos(razon_social="INSTALACIONES CON WEB PRUEBA SL", web="instalaciones-con-web-prueba.es",
                                   telefonos=["955000111"]),
        )

    dp.enriquecer_desde_web = web_falsa  # type: ignore[assignment]

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as cliente:
        r = await dp.descubrir_places(SinCommit(conn), cliente, consultas=["reformas Sevilla"], max_coste_eur=0.10)  # type: ignore[arg-type]
    for k, v in r.items():
        if v:
            print(f"{k}: {v}")

    print("\n--- comprobaciones en BD (antes de revertir) ---")
    print("place_ids guardados:", conn.execute("select valor, empresa_id = %s as es_la_conocida from identificadores where tipo='google_place_id' order by valor", (eid,)).fetchall())
    print("observaciones de fuente google_places:", conn.execute(
        "select count(*) from observaciones o join fuentes f on f.id=o.fuente_id where f.codigo='google_places' and o.observado_en > now() - interval '5 minutes'").fetchone()[0])
    print("registros_brutos de fuente google_places:", conn.execute(
        "select count(*) from registros_brutos rb join fuentes f on f.id=rb.fuente_id where f.codigo='google_places' and rb.capturado_en > now() - interval '5 minutes'").fetchone()[0])
    print("empresas con 'Sin Web'/'Cerrado' creadas:", conn.execute(
        "select count(*) from empresas where razon_social ilike '%Sin Web Prueba%' or razon_social ilike '%Negocio Cerrado%' or nombre_comercial ilike '%Sin Web Prueba%' or nombre_comercial ilike '%Negocio Cerrado%'").fetchone()[0])
    print("uso registrado:", conn.execute("select operacion, peticiones, coste_eur from uso_google_places").fetchall())

    conn.rollback()
    conn.close()
    print("\n(transacción revertida)")


if __name__ == "__main__":
    asyncio.run(main())
