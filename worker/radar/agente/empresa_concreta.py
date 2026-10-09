"""Búsqueda de UNA empresa concreta, al detalle (petición del usuario
2026-10-09: «añade la opción de buscar una sola empresa al detalle»).

A diferencia de una búsqueda por sector y zona, aquí el usuario ya sabe qué
empresa quiere (nombre y, si lo sabe, CIF, localidad o web), así que no hay
nada que interpretar ni que planificar con el LLM: el flujo es determinista.

1. `localizar_en_bd` (gratis): si la empresa ya está en la base de datos
   (mismo CIF, misma web o nombre parecido), se enlaza con la búsqueda.
2. Descubrimiento dirigido, con las fuentes de pago marcadas: Google Maps
   (Apify) y Google Places con «nombre + localidad», y búsqueda web con el
   nombre entre comillas, el CIF y la web.
3. `identificar_empresa` (gratis, código): de todo lo encontrado, se queda con
   la empresa buscada y descarta el resto (otras del mismo nombre, directorios,
   empresas que salían en los mismos resultados). Mismo criterio que el resto
   del proyecto: el CIF manda; sin CIF, nombre + localidad + web, y si no es
   seguro queda como «dudoso», nunca se da por buena.
4. Las mismas fases de verificación y contacto que una búsqueda normal, que
   solo trabajan con lo no descartado: completar contacto, LinkedIn/Facebook/
   rastreo si están marcados, CIF por Google, administradores del BORME y
   resolución de dudas.

El resultado es una búsqueda normal (misma pantalla de progreso, misma tabla,
mismas exportaciones), con la empresa buscada como resultado.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import psycopg

from radar.agente.herramientas import ContextoHerramientas, ejecutar_herramienta
from radar.agente.interpretacion import FiltrosBusqueda, UbicacionFiltro
from radar.agente.planificador import (
    HERRAMIENTAS_QUE_CONSUMEN_PRESUPUESTO,
    ResultadoPlanificador,
    RondaPlanificador,
)
from radar.normalizacion.dominio import extraer_dominio
from radar.normalizacion.nif import normalizar_nif, validar_nif
from radar.normalizacion.nombre import normalizar_nombre, similitud_nombres, tokens_distintivos
from radar.orquestador import bd

# Umbrales de `puntuar_candidato` (0-1).
UMBRAL_ES_LA_EMPRESA = 0.8
UMBRAL_DUDOSO = 0.6
MAX_DUDOSAS = 3
# Negocios que se piden a Maps por la consulta del nombre: el primero suele ser
# el bueno; unos pocos más cubren homónimos y sedes (0,004 $ cada uno).
LUGARES_MAPS = 5

OnRonda = Callable[[RondaPlanificador], Awaitable[None]]
DebeCancelar = Callable[[], Awaitable[bool]]


@dataclass
class EmpresaObjetivo:
    nombre: str
    nif: str | None = None
    localidad: str | None = None
    web: str | None = None

    @classmethod
    def desde_dict(cls, datos: dict[str, Any]) -> EmpresaObjetivo:
        def limpio(clave: str) -> str | None:
            valor = str(datos.get(clave) or "").strip()
            return valor or None

        return cls(nombre=limpio("nombre") or "", nif=limpio("nif"), localidad=limpio("localidad"), web=limpio("web"))

    def a_dict(self) -> dict[str, str | None]:
        return {"nombre": self.nombre, "nif": self.nif, "localidad": self.localidad, "web": self.web}

    @property
    def nif_normalizado(self) -> str | None:
        return normalizar_nif(self.nif) or None if self.nif else None

    @property
    def dominio(self) -> str | None:
        return extraer_dominio(self.web) if self.web else None


def peticion_de(objetivo: EmpresaObjetivo) -> str:
    """Texto de la búsqueda en el panel (y nombre de la lista al exportar)."""
    extra = [x for x in (objetivo.nif_normalizado, objetivo.localidad) if x]
    return f"Empresa: {objetivo.nombre}" + (f" ({', '.join(extra)})" if extra else "")


def filtros_de(objetivo: EmpresaObjetivo) -> FiltrosBusqueda:
    """Filtros que se guardan con la búsqueda. Sin sector ni tamaño (no se
    filtra por ellos), con autónomos (si el usuario busca uno, lo quiere) y
    la localidad como zona: la usan Maps y completar contacto al buscar por
    nombre."""
    ubicacion = UbicacionFiltro(tipo="municipios", municipios=[objetivo.localidad]) if objetivo.localidad else UbicacionFiltro()
    supuestos = ["Búsqueda de una empresa concreta: se descarta todo lo que no sea esa empresa."]
    if not objetivo.nif:
        supuestos.append("Sin CIF: la empresa se identifica por nombre, localidad y web; si no es seguro, queda como dudosa.")
    return FiltrosBusqueda(
        ubicacion=ubicacion, incluir_autonomos=True, limite_resultados=1, supuestos=supuestos,
    )


def consulta_mapas(objetivo: EmpresaObjetivo) -> str:
    return f"{objetivo.nombre} {objetivo.localidad or ''}".strip()


def consultas_web(objetivo: EmpresaObjetivo) -> list[str]:
    """Consultas literales dirigidas a esta empresa (como `radar.agente.profundizar`)."""
    nombre = objetivo.nombre.replace('"', "")
    consultas = [f'"{nombre}" {objetivo.localidad}' if objetivo.localidad else f'"{nombre}" empresa contacto']
    if objetivo.nif_normalizado:
        consultas.append(f'"{objetivo.nif_normalizado}"')
    else:
        consultas.append(f'"{nombre}" CIF')
    if objetivo.dominio:
        consultas.append(f"site:{objetivo.dominio} aviso legal")
    return consultas


# --- Identificación (código puro) ----------------------------------------------


@dataclass
class Candidato:
    empresa_id: str
    razon_social: str | None = None
    nombre_comercial: str | None = None
    nif: str | None = None
    dominio_web: str | None = None
    lugares: list[str] = field(default_factory=list)  # municipios y provincias de sus sedes
    clasificacion: str | None = None
    revisada_por_persona: bool = False


def _sin_tildes(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode().strip()


def _misma_localidad(localidad: str, lugares: list[str]) -> bool:
    buscada = _sin_tildes(localidad)
    return any(buscada == _sin_tildes(lugar) or buscada in _sin_tildes(lugar).split(" / ") for lugar in lugares if lugar)


def similitud_con(objetivo: str, candidato: str | None) -> float:
    """0-1. Nombre parecido, o el candidato contiene TODAS las palabras
    distintivas del nombre buscado ("Sevilla Fugas" en «SEVILLA FUGAS
    SOCIEDAD LIMITADA»)."""
    if not candidato:
        return 0.0
    a, b = normalizar_nombre(objetivo), normalizar_nombre(candidato)
    if not a or not b:
        return 0.0
    puntos = similitud_nombres(a, b)
    distintivas_a, distintivas_b = tokens_distintivos(a), tokens_distintivos(b)
    if distintivas_a and distintivas_a <= distintivas_b:
        puntos = max(puntos, 0.85)
    elif distintivas_a and not distintivas_a & distintivas_b:
        # Ninguna palabra distintiva en común ("Sevilla Fugas" frente a
        # "Fontaneros Sevilla 24h"): parecido solo en lo genérico.
        puntos = min(puntos, 0.4)
    return puntos


def puntuar_candidato(objetivo: EmpresaObjetivo, c: Candidato) -> tuple[float, str]:
    """¿Es este candidato la empresa buscada? (puntuación 0-1, motivo)."""
    nif = objetivo.nif_normalizado
    if nif and c.nif:
        if normalizar_nif(c.nif) == nif:
            return 1.0, "mismo CIF que el indicado"
        return 0.0, f"otro CIF ({c.nif})"
    if objetivo.dominio and c.dominio_web and c.dominio_web == objetivo.dominio:
        return 0.95, "misma web que la indicada"

    puntos = max(similitud_con(objetivo.nombre, c.razon_social), similitud_con(objetivo.nombre, c.nombre_comercial))
    motivos = [f"nombre {round(puntos * 100)}% parecido"]
    if puntos < 0.5:
        return round(puntos, 2), "; ".join(motivos)
    if objetivo.localidad:
        if _misma_localidad(objetivo.localidad, c.lugares):
            puntos += 0.1
            motivos.append("misma localidad")
        elif c.lugares:
            puntos -= 0.25
            motivos.append(f"en otra localidad ({c.lugares[0]})")
    if objetivo.dominio and c.dominio_web and c.dominio_web != objetivo.dominio:
        puntos -= 0.2
        motivos.append(f"otra web ({c.dominio_web})")
    return round(max(0.0, min(1.0, puntos)), 2), "; ".join(motivos)


def clasificar_candidatos(objetivo: EmpresaObjetivo, candidatos: list[Candidato]) -> dict[str, tuple[str, str]]:
    """empresa_id -> (clasificación, motivo). «relevante» = es la empresa
    buscada; «dudoso» = podría serlo (como mucho `MAX_DUDOSAS`, las mejores);
    «descartado» = el resto. Si hay CIF indicado y alguna candidata lo tiene,
    solo esa (y las que no se pueden descartar por CIF) cuentan."""
    puntuados = sorted(
        ((c, *puntuar_candidato(objetivo, c)) for c in candidatos), key=lambda t: t[1], reverse=True
    )
    decision: dict[str, tuple[str, str]] = {}
    dudosas = 0
    for c, puntos, motivo in puntuados:
        if puntos >= UMBRAL_ES_LA_EMPRESA:
            decision[c.empresa_id] = ("relevante", f"Es la empresa buscada: {motivo}")
        elif puntos >= UMBRAL_DUDOSO and dudosas < MAX_DUDOSAS:
            dudosas += 1
            decision[c.empresa_id] = ("dudoso", f"Podría ser la empresa buscada: {motivo}")
        else:
            decision[c.empresa_id] = ("descartado", f"No es la empresa buscada: {motivo}")
    return decision


# --- Base de datos ---------------------------------------------------------------

_SQL_LUGARES = """
coalesce((select array_agg(distinct x) from sedes s,
  lateral unnest(array[s.municipio_nombre, s.provincia]) x where s.empresa_id = e.id and x is not null), '{}')
"""


def candidatos_de_busqueda(conn: psycopg.Connection, busqueda_id: str) -> list[Candidato]:
    filas = conn.execute(
        f"""
        select e.id::text, e.razon_social, e.nombre_comercial, e.nif, e.dominio_web, {_SQL_LUGARES},
               br.clasificacion, br.relevancia_revisada
        from busqueda_resultados br join empresas e on e.id = br.empresa_id
        where br.busqueda_id = %s and e.fusionada_en is null
        """,
        (busqueda_id,),
    ).fetchall()
    return [Candidato(f[0], f[1], f[2], f[3], f[4], list(f[5] or []), f[6], bool(f[7])) for f in filas]


def candidatos_en_bd(conn: psycopg.Connection, objetivo: EmpresaObjetivo, limite: int = 30) -> list[Candidato]:
    """Empresas ya guardadas que podrían ser la buscada: mismo CIF, misma web
    o nombre parecido (`word_similarity` de pg_trgm: el nombre buscado dentro
    de la razón social, que suele llevar la forma jurídica detrás)."""
    filas = conn.execute(
        f"""
        select e.id::text, e.razon_social, e.nombre_comercial, e.nif, e.dominio_web, {_SQL_LUGARES}
        from empresas e
        where e.fusionada_en is null and (
          (%(nif)s::text is not null and e.nif = %(nif)s)
          or (%(dominio)s::text is not null and e.dominio_web = %(dominio)s)
          or word_similarity(%(nombre)s, lower(coalesce(e.razon_social, ''))) > 0.5
          or word_similarity(%(nombre)s, lower(coalesce(e.nombre_comercial, ''))) > 0.5
        )
        order by (e.nif = %(nif)s) desc nulls last, (e.dominio_web = %(dominio)s) desc nulls last,
          greatest(word_similarity(%(nombre)s, lower(coalesce(e.razon_social, ''))),
                   word_similarity(%(nombre)s, lower(coalesce(e.nombre_comercial, '')))) desc
        limit %(limite)s
        """,
        {"nif": objetivo.nif_normalizado, "dominio": objetivo.dominio, "nombre": objetivo.nombre.lower(), "limite": limite},
    ).fetchall()
    return [Candidato(f[0], f[1], f[2], f[3], f[4], list(f[5] or [])) for f in filas]


def localizar_en_bd(conn: psycopg.Connection, objetivo: EmpresaObjetivo, busqueda_id: str) -> dict[str, Any]:
    candidatos = candidatos_en_bd(conn, objetivo)
    vinculadas = 0
    for c in candidatos:
        puntos, _ = puntuar_candidato(objetivo, c)
        if puntos >= UMBRAL_DUDOSO:
            bd.registrar_resultado_busqueda(busqueda_id, c.empresa_id, "base_datos: ya_conocida", puntos, conn)
            vinculadas += 1
    conn.commit()
    return {"candidatas_revisadas": len(candidatos), "ya_en_bd": vinculadas, "coste_eur": 0.0}


def identificar_empresa(conn: psycopg.Connection, objetivo: EmpresaObjetivo, busqueda_id: str) -> dict[str, Any]:
    """Clasifica los resultados de la búsqueda (no toca lo que haya decidido
    una persona: `relevancia_revisada`, «aceptado»/«rechazado»)."""
    candidatos = [
        c for c in candidatos_de_busqueda(conn, busqueda_id)
        if not c.revisada_por_persona and c.clasificacion not in ("aceptado", "rechazado")
    ]
    decision = clasificar_candidatos(objetivo, candidatos)
    cambios = 0
    with conn.cursor() as cur:
        for c in candidatos:
            clasificacion, motivo = decision[c.empresa_id]
            if clasificacion != c.clasificacion:
                cambios += 1
            cur.execute(
                "update busqueda_resultados set clasificacion = %s, motivo_relevancia = %s "
                "where busqueda_id = %s and empresa_id = %s and not relevancia_revisada",
                (clasificacion, motivo, busqueda_id, c.empresa_id),
            )
    conn.commit()
    cuenta = {k: sum(1 for v in decision.values() if v[0] == k) for k in ("relevante", "dudoso", "descartado")}
    return {"revisadas": len(candidatos), **cuenta, "cambios": cambios, "coste_eur": 0.0}


def ficha_encontrada(conn: psycopg.Connection, busqueda_id: str) -> dict[str, Any] | None:
    fila = conn.execute(
        "select razon_social, nombre_comercial, nif, telefono, email, contacto_nombre, completitud, clasificacion "
        "from resultados_busqueda(%s, 50, 0) order by (clasificacion = 'relevante') desc nulls last, completitud desc limit 1",
        (busqueda_id,),
    ).fetchone()
    conn.commit()
    if fila is None:
        return None
    return {
        "nombre": fila[0] or fila[1], "nif": fila[2], "telefono": fila[3], "email": fila[4], "contacto": fila[5],
        "completitud": fila[6], "clasificacion": fila[7],
    }


def resumen_final(objetivo: EmpresaObjetivo, ficha: dict[str, Any] | None) -> tuple[str, str]:
    """(motivo_fin, resumen) para el panel."""
    if not ficha:
        return "rendimientos_decrecientes", f"No se ha encontrado «{objetivo.nombre}» en ninguna fuente."
    datos = [f"{k} {ficha[k]}" for k in ("nif", "telefono", "email") if ficha.get(k)]
    if ficha.get("contacto"):
        datos.append(f"contacto {ficha['contacto']}")
    texto = f"{ficha['nombre']} ({ficha['completitud']}/5" + (f": {', '.join(datos)}" if datos else "") + ")"
    if ficha.get("clasificacion") == "relevante":
        return "cobertura_alcanzada", f"Encontrada: {texto}."
    return "rendimientos_decrecientes", f"No hay una coincidencia segura; la más parecida es {texto}. Revísala."


# --- Flujo completo --------------------------------------------------------------


async def buscar_empresa_concreta(
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    objetivo: EmpresaObjetivo,
    *,
    presupuesto_eur: float,
    busqueda_id: str,
    usar_places: bool = False,
    apify_actores: frozenset[str] | set[str] = frozenset(),
    on_ronda: OnRonda | None = None,
    debe_cancelar: DebeCancelar | None = None,
) -> ResultadoPlanificador:
    from radar.agente.completar_contacto import completar_contacto
    from radar.agente.completar_identidad import completar_identidad
    from radar.agente.costes_apify import conciliar_costes_apify
    from radar.agente.descubrir_apify_maps import (
        COSTE_ARRANQUE_USD,
        COSTE_POR_LUGAR_USD,
        ejecutar_maps,
        procesar_items_maps,
    )
    from radar.agente.descubrir_places import descubrir_places
    from radar.agente.enriquecer_borme import enriquecer_con_borme
    from radar.agente.redes_marcadas import fuentes_marcadas_finales, reserva_redes
    from radar.agente.resolver_dudas import resolver_dudas
    from radar.secretos import (
        gasto_mes_apify_usd,
        obtener_token_apify,
        presupuesto_mensual_apify_usd,
    )

    actores = frozenset(apify_actores)
    inicio = datetime.now(UTC) - timedelta(seconds=5)
    filtros = filtros_de(objetivo)
    # Para buscar en la web, sin zona: el filtro por provincia de `buscar_web`
    # descartaría la propia empresa si la localidad indicada no es la de su CP.
    contexto_web = ContextoHerramientas(
        conn=conn, cliente_http=cliente_http, filtros=FiltrosBusqueda(incluir_autonomos=True),
        presupuesto_restante_eur=presupuesto_eur, busqueda_id=busqueda_id, usar_places=usar_places, apify_actores=actores,
    )
    total = ResultadoPlanificador()
    telefonos_compartidos: set[str] = set()

    async def registrar(nombre: str, argumentos: dict[str, Any], resultado: dict[str, Any]) -> bool:
        """Añade el paso, descuenta su coste y avisa. `True` = hay que parar."""
        coste = float(resultado.get("coste_eur", 0.0) or 0.0) if nombre in HERRAMIENTAS_QUE_CONSUMEN_PRESUPUESTO else 0.0
        contexto_web.presupuesto_restante_eur -= coste
        total.coste_gastado_eur += coste
        ronda = RondaPlanificador(len(total.rondas) + 1, nombre, argumentos, resultado)
        total.rondas.append(ronda)
        if on_ronda is not None:
            try:
                await on_ronda(ronda)
            except Exception as exc:  # noqa: BLE001
                total.error = f"fallo guardando progreso: {exc}"
                return True
        if debe_cancelar is not None:
            try:
                if await debe_cancelar():
                    total.motivo_fin = "cancelada_por_usuario"
                    return True
            except Exception as exc:  # noqa: BLE001
                total.error = f"fallo comprobando cancelación: {exc}"
                return True
        return False

    def restante() -> float:
        return max(0.0, contexto_web.presupuesto_restante_eur)

    def cerrar() -> ResultadoPlanificador:
        total.coste_gastado_eur = round(total.coste_gastado_eur, 4)
        return total

    # 1. ¿Ya la tenemos?
    if await registrar("localizar_en_bd", objetivo.a_dict(), await asyncio.to_thread(localizar_en_bd, conn, objetivo, busqueda_id)):
        return cerrar()

    # 2. Descubrimiento dirigido con las fuentes marcadas.
    if "google_maps" in actores and obtener_token_apify(conn):
        tope = min(presupuesto_eur * 0.25, 0.05, restante(), presupuesto_mensual_apify_usd(conn) - gasto_mes_apify_usd(conn))
        lugares = min(LUGARES_MAPS, int((tope - COSTE_ARRANQUE_USD) / COSTE_POR_LUGAR_USD)) if tope > 0 else 0
        if lugares > 0:
            zona = f"{objetivo.localidad}, España" if objetivo.localidad else None
            busquedas = [objetivo.nombre if zona else consulta_mapas(objetivo)]
            items, coste, estado, error = await ejecutar_maps(
                conn, cliente_http, busquedas=busquedas, zona=zona, lugares_por_busqueda=lugares, tope_usd=tope,
                detalle={"empresa_concreta": objetivo.a_dict(), "lugares_por_busqueda": lugares},
            )
            contadores = await procesar_items_maps(
                conn, cliente_http, items, busqueda_id=busqueda_id, telefonos_compartidos=telefonos_compartidos
            )
            resultado_maps = {**contadores, "zona": zona, "estado_apify": estado, "error": error, "coste_eur": round(coste, 4)}
            if await registrar("descubrir_apify_maps", {"palabras_clave": busquedas}, resultado_maps):
                return cerrar()

    if usar_places:
        consultas_places = [consulta_mapas(objetivo)]
        resultado_places = await descubrir_places(
            conn, cliente_http, consultas=consultas_places, max_coste_eur=min(presupuesto_eur * 0.2, 0.05, restante()),
            max_paginas=1, busqueda_id=busqueda_id,
        )
        if await registrar("descubrir_places", {"consultas": consultas_places}, resultado_places):
            return cerrar()

    consultas = consultas_web(objetivo)
    args_web: dict[str, Any] = {"consultas": consultas, "max_coste_eur": round(min(presupuesto_eur * 0.15, 0.06, restante()), 4)}
    if args_web["max_coste_eur"] > 0:
        try:
            resultado_web = await ejecutar_herramienta("buscar_web", args_web, contexto_web)
        except ValueError as exc:
            resultado_web = {"error": str(exc), "coste_eur": 0.0}
        if await registrar("buscar_web", args_web, resultado_web):
            return cerrar()

    # 3. De todo lo encontrado, ¿cuál es?
    if await registrar("identificar_empresa", {}, await asyncio.to_thread(identificar_empresa, conn, objetivo, busqueda_id)):
        return cerrar()

    # 4. Verificar y completar (solo lo no descartado).
    reserva_final = reserva_redes(actores, presupuesto_eur) + min(0.08, presupuesto_eur * 0.2)
    resultado_contacto = await completar_contacto(
        conn, cliente_http, filtros, busqueda_id=busqueda_id, max_coste_eur=max(0.0, restante() - reserva_final),
        apify_actores=actores, telefonos_compartidos=telefonos_compartidos, max_empresas=1 + MAX_DUDOSAS,
    )
    if await registrar("completar_contacto", {}, resultado_contacto):
        return cerrar()

    for nombre_fuente, args_fuente, resultado_fuente in await fuentes_marcadas_finales(
        conn, cliente_http, busqueda_id=busqueda_id, actores=actores,
        max_coste_eur=max(0.0, restante() - min(0.08, presupuesto_eur * 0.2)), telefonos_compartidos=telefonos_compartidos,
    ):
        if await registrar(nombre_fuente, args_fuente, resultado_fuente):
            return cerrar()

    # Lo que hayan traído contacto y redes (otras fichas) también se clasifica.
    resultado_id_2 = await asyncio.to_thread(identificar_empresa, conn, objetivo, busqueda_id)
    if resultado_id_2["cambios"] and await registrar("identificar_empresa", {}, resultado_id_2):
        return cerrar()

    resultado_identidad = await completar_identidad(
        conn, cliente_http, busqueda_id=busqueda_id, max_coste_eur=restante(), telefonos_compartidos=telefonos_compartidos,
    )
    if await registrar("completar_identidad", {}, resultado_identidad):
        return cerrar()

    resultado_borme = await asyncio.to_thread(
        enriquecer_con_borme, conn, busqueda_id, telefonos_compartidos=telefonos_compartidos
    )
    if await registrar("enriquecer_borme", {}, resultado_borme):
        return cerrar()

    resultado_dudas = await resolver_dudas(conn, cliente_http, busqueda_id=busqueda_id, max_coste_eur=restante())
    if await registrar("resolver_dudas", {}, resultado_dudas):
        return cerrar()

    # Con el CIF y el BORME pueden haberse unido fichas: última clasificación.
    resultado_id_3 = await asyncio.to_thread(identificar_empresa, conn, objetivo, busqueda_id)
    if resultado_id_3["cambios"] and await registrar("identificar_empresa", {}, resultado_id_3):
        return cerrar()

    if actores:
        resultado_costes = await conciliar_costes_apify(conn, cliente_http, desde=inicio)
        if await registrar("conciliar_costes_apify", {}, resultado_costes):
            return cerrar()

    total.motivo_fin, total.resumen = resumen_final(objetivo, await asyncio.to_thread(ficha_encontrada, conn, busqueda_id))
    return cerrar()


def nif_valido(nif: str | None) -> bool:
    """Para validar lo que escribe el usuario en el formulario."""
    return not nif or bool(validar_nif(re.sub(r"\s", "", nif))["valido"])
