"""Índice local del BORME (tablas `borme_actos` / `borme_dias_cargados`,
migración 202609251200).

Cada día y provincia se descarga una sola vez con `ConectorBorme` y sus actos
se guardan ya parseados. Así:
- `descubrir_borme` deja de descargar y parsear miles de actos en cada búsqueda
  (solo baja los días que falten);
- se puede buscar una empresa por su DENOMINACIÓN para enriquecerla con sus
  administradores, hoja registral y domicilio (`radar.agente.enriquecer_borme`),
  que es lo que de verdad aporta el BORME en búsquedas por municipio.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import httpx
import psycopg

from radar.fuentes.borme import ActoBorme, ConectorBorme
from radar.normalizacion.nombre import normalizar_nombre

_COLUMNAS = (
    "fecha, provincia, identificador_boletin, id_borme, razon_social, razon_social_norm, hoja_registral, tipos, "
    "domicilio, codigo_postal, municipio, objeto_social, capital_eur, administradores, texto, url_html, url_xml"
)
DIAS_PARA_DAR_POR_VACIO = 7


def dias_pendientes(conn: psycopg.Connection, provincia: str, desde: date, hasta: date) -> list[date]:
    cargados = {
        f[0] for f in conn.execute(
            "select fecha from borme_dias_cargados where provincia = %s and fecha between %s and %s",
            (provincia.upper(), desde, hasta),
        ).fetchall()
    }
    dias, dia = [], desde
    while dia <= hasta:
        if dia.weekday() < 5 and dia not in cargados:
            dias.append(dia)
        dia += timedelta(days=1)
    return dias


def _guardar_actos(conn: psycopg.Connection, dia: date, provincia: str, actos: list[ActoBorme]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            f"insert into borme_actos ({_COLUMNAS}) values "
            "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s) on conflict do nothing",
            [
                (
                    dia, provincia, a.identificador_boletin, a.id_borme, a.razon_social, normalizar_nombre(a.razon_social),
                    a.hoja_registral, a.tipos, a.domicilio, a.codigo_postal, a.municipio, a.objeto_social, a.capital_eur,
                    json.dumps(a.administradores, ensure_ascii=False), a.texto_completo, a.url_html, a.url_xml,
                )
                for a in actos
            ],
        )
        cur.execute(
            "insert into borme_dias_cargados (fecha, provincia, n_actos) values (%s, %s, %s) "
            "on conflict (fecha, provincia) do update set n_actos = excluded.n_actos, cargado_en = now()",
            (dia, provincia, len(actos)),
        )
    conn.commit()


async def cargar_dias(
    conn: psycopg.Connection, cliente: httpx.AsyncClient, provincia_titulo: str, desde: date, hasta: date
) -> dict[str, int]:
    """Descarga y guarda los días laborables que falten. Un día que falla no
    se marca como cargado (se reintentará la próxima vez)."""
    provincia = provincia_titulo.upper()
    conector = ConectorBorme(cliente)
    resumen = {"dias_descargados": 0, "actos_nuevos": 0, "dias_con_error": 0}
    for dia in dias_pendientes(conn, provincia, desde, hasta):
        try:
            actos = await conector._actos_de_provincia(dia, provincia)
        except httpx.HTTPError:
            resumen["dias_con_error"] += 1
            continue
        # Un día reciente sin actos puede ser que aún no se haya publicado (el
        # de hoy, antes de mediodía): no se marca, se volverá a pedir. Pasada
        # una semana, vacío = festivo de verdad.
        if not actos and (datetime.now(UTC).date() - dia).days < DIAS_PARA_DAR_POR_VACIO:
            continue
        _guardar_actos(conn, dia, provincia, actos)
        resumen["dias_descargados"] += 1
        resumen["actos_nuevos"] += len(actos)
    return resumen


def _acto(fila: tuple) -> ActoBorme:
    (_fecha, _prov, identificador, id_borme, razon, _norm, hoja, tipos, domicilio, cp, municipio, objeto, capital,
     administradores, texto, url_html, url_xml) = fila
    return ActoBorme(
        id_borme=id_borme, razon_social=razon, tipos=list(tipos or []), domicilio=domicilio, codigo_postal=cp,
        municipio=municipio, hoja_registral=hoja, objeto_social=objeto, capital_eur=capital,
        administradores=list(administradores or []), texto_completo=texto or "", identificador_boletin=identificador,
        url_html=url_html or "", url_xml=url_xml or "", fecha_publicacion=str(_fecha),
    )


def actos_en_rango(conn: psycopg.Connection, provincia_titulo: str, desde: date, hasta: date) -> Iterator[ActoBorme]:
    filas = conn.execute(
        f"select {_COLUMNAS} from borme_actos where provincia = %s and fecha between %s and %s order by fecha, id",
        (provincia_titulo.upper(), desde, hasta),
    ).fetchall()
    for fila in filas:
        yield _acto(fila)


def buscar_por_denominacion(conn: psycopg.Connection, razon_social: str, limite: int = 5) -> list[tuple[str, ActoBorme]]:
    """Actos de la sociedad con esa denominación (sin forma jurídica ni
    palabras vacías), del más reciente al más antiguo. Devuelve (provincia, acto)."""
    clave = normalizar_nombre(razon_social)
    if not clave:
        return []
    filas = conn.execute(
        f"select {_COLUMNAS} from borme_actos where razon_social_norm = %s order by fecha desc limit %s",
        (clave, limite),
    ).fetchall()
    return [(fila[1], _acto(fila)) for fila in filas]
