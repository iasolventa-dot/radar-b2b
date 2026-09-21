"""Descubrimiento con Google Places respetando sus condiciones de uso (ver
docstring de `radar.fuentes.places`): los datos que devuelve Google se usan
solo EN VIVO y solo se guarda el `place_id`.

Por cada lugar encontrado:
1. Se cruza (sin escribir nada) con lo que ya tenemos, con el MISMO criterio
   que cualquier otra fuente (`radar.orquestador.procesar.reunir_candidatos`
   + `decidir_resolucion`: dominio/teléfono/place_id exactos, nombre y
   cercanía). Si es una empresa conocida -> se guarda su `place_id`
   (`identificadores`) y nada más.
2. Si no la conocemos y Google da su web -> se sigue la web PROPIA de la
   empresa (`enriquecer_desde_web`) y se procesa como cualquier `web_empresa`
   (datos que ELLA publica, almacenables); después se enlaza el `place_id`.
3. Si no la conocemos y no hay web utilizable -> NO se puede guardar (solo
   tendríamos datos de Google): se cuenta como `sin_web_no_almacenable`.
   Nunca se crea una empresa con datos copiados de Places.
4. Un lugar `CLOSED_PERMANENTLY` no se procesa (no se guarda la señal: es
   contenido de Google).

Control de gasto: tope por llamada (`max_coste_eur`) y tope mensual del panel
(`uso_google_places`); si falta la clave o se agota el mes, devuelve un
resultado explicativo en vez de lanzar.
"""

from __future__ import annotations

from typing import Any

import httpx
import psycopg

from radar.extraccion import enriquecer_desde_web
from radar.fuentes.base import CamposExtraidos
from radar.fuentes.places import COSTE_PETICION_EUR, LugarPlaces, buscar_lugares
from radar.normalizacion.dominio import es_dominio_plataforma, extraer_dominio
from radar.normalizacion.registro import normalizar_registro
from radar.orquestador import bd, procesar_registro
from radar.orquestador.logica import campos_a_dict_normalizacion, decidir_resolucion
from radar.orquestador.procesar import reunir_candidatos
from radar.resolucion.blocking import telefonos_compartidos as cargar_telefonos_compartidos
from radar.secretos import (
    gasto_mes_places_eur,
    obtener_clave_places,
    presupuesto_mensual_places_eur,
)

MAX_PAGINAS_POR_CONSULTA = 3
_DOMINIOS_NO_UTILES = {"boe.es"}


def _web_util(url: str | None) -> bool:
    if not url:
        return False
    dominio = extraer_dominio(url)
    return bool(dominio) and not es_dominio_plataforma(dominio) and dominio not in _DOMINIOS_NO_UTILES


def campos_transitorios(lugar: LugarPlaces) -> CamposExtraidos:
    """Solo para cruzar en memoria: este objeto NUNCA se persiste."""
    return CamposExtraidos(
        nombre_comercial=lugar.nombre,
        domicilio=lugar.direccion,
        telefonos=[lugar.telefono] if lugar.telefono else [],
        web=lugar.web,
        lat=lugar.lat,
        lon=lugar.lon,
        extra={"place_id": lugar.place_id},
    )


async def _procesar_lugar(
    lugar: LugarPlaces, conn: psycopg.Connection, cliente_http: httpx.AsyncClient, fuente_places_id: int,
    compartidos: set[str], busqueda_id: str | None, contadores: dict[str, int],
) -> None:
    if lugar.estado == "CLOSED_PERMANENTLY":
        contadores["cerrados_ignorados"] += 1
        return

    campos = campos_transitorios(lugar)
    campos_norm = normalizar_registro(campos_a_dict_normalizacion(campos))
    candidatos = reunir_candidatos(campos, campos_norm, compartidos, conn)
    decision = decidir_resolucion(campos_norm, candidatos, compartidos)

    if decision.accion == "vincular" and decision.empresa_id:
        bd.registrar_place_id(decision.empresa_id, lugar.place_id, fuente_places_id, conn)
        if busqueda_id:
            bd.registrar_resultado_busqueda(busqueda_id, decision.empresa_id, "google_places: vinculado", decision.puntuacion, conn)
        contadores["vinculado_existente"] += 1
        return

    if decision.accion == "crear_y_revisar":
        # Duda sobre si es una empresa que ya tenemos: no se crea nada ni se
        # enlaza el place_id a ciegas (enlazarlo mal contaminaría el cruce).
        contadores["ambiguo_sin_guardar"] += 1
        return

    if not _web_util(lugar.web):
        contadores["sin_web_no_almacenable"] += 1
        return

    registro = await enriquecer_desde_web(cliente_http, lugar.web or "")
    if registro is None:
        contadores["web_no_legible"] += 1
        return
    resolucion = procesar_registro(registro, conn, busqueda_id=busqueda_id, telefonos_compartidos=compartidos)
    if resolucion.empresa_id:
        bd.registrar_place_id(resolucion.empresa_id, lugar.place_id, fuente_places_id, conn)
        if busqueda_id:
            bd.registrar_resultado_busqueda(
                busqueda_id, resolucion.empresa_id, f"google_places+web: {resolucion.accion}", resolucion.puntuacion_match, conn
            )
    contadores["nueva_via_web" if resolucion.accion == "nueva_empresa" else "vinculado_via_web"] += 1


async def descubrir_places(
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    *,
    consultas: list[str],
    max_coste_eur: float,
    max_paginas: int = 1,
    busqueda_id: str | None = None,
) -> dict[str, Any]:
    clave = obtener_clave_places(conn)
    if not clave:
        return {"soportado": False, "motivo": "Google Places no está configurado (falta la clave en Ajustes)", "coste_eur": 0.0}

    presupuesto_mes = presupuesto_mensual_places_eur(conn)
    gasto_mes = gasto_mes_places_eur(conn)
    fuente = bd.obtener_fuente("google_places", conn)
    compartidos = cargar_telefonos_compartidos(conexion=conn)

    contadores = {
        "consultas_ejecutadas": 0, "peticiones": 0, "lugares_encontrados": 0, "vinculado_existente": 0,
        "nueva_via_web": 0, "vinculado_via_web": 0, "sin_web_no_almacenable": 0, "web_no_legible": 0,
        "ambiguo_sin_guardar": 0, "cerrados_ignorados": 0, "error_lugar": 0,
    }
    coste = 0.0
    motivo_parada: str | None = None
    error: str | None = None

    for consulta in consultas:
        token: str | None = None
        for _ in range(max(1, min(max_paginas, MAX_PAGINAS_POR_CONSULTA))):
            if coste + COSTE_PETICION_EUR > max_coste_eur:
                motivo_parada = "presupuesto_de_la_llamada_agotado"
                break
            if gasto_mes + coste + COSTE_PETICION_EUR > presupuesto_mes:
                motivo_parada = "presupuesto_mensual_de_places_agotado"
                break
            res = await buscar_lugares(cliente_http, clave, consulta, pagina=token)
            contadores["peticiones"] += 1
            if res.error:
                error = res.error
                break
            coste += res.coste_eur
            bd.registrar_uso_places("text_search", 1, res.coste_eur, {"consulta": consulta}, conn)
            conn.commit()
            contadores["lugares_encontrados"] += len(res.lugares)
            for lugar in res.lugares:
                try:
                    await _procesar_lugar(lugar, conn, cliente_http, fuente.id, compartidos, busqueda_id, contadores)
                    conn.commit()
                except Exception:  # noqa: BLE001 -- un lugar que falla no debe tirar el resto
                    conn.rollback()
                    contadores["error_lugar"] += 1
            token = res.siguiente_pagina
            if not token:
                break
        contadores["consultas_ejecutadas"] += 1
        if motivo_parada or error:
            break

    return {
        **contadores, "coste_eur": round(coste, 4), "motivo_parada": motivo_parada, "error": error,
        "gasto_mes_eur": round(gasto_mes + coste, 4), "presupuesto_mes_eur": presupuesto_mes,
    }
