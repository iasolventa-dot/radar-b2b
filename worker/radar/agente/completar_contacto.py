"""Fase final de toda búsqueda: completar el CONTACTO (web, teléfono, email)
de las empresas que ha encontrado. Sin este paso, lo que viene del BORME (el
grueso del descubrimiento) llega sin ningún dato de contacto -- el BORME no
publica ni web, ni teléfono, ni email -- y la base no sirve para lo que se
quiere (confirmado en la BD real 2026-09-23: 32 teléfonos y 5 emails en
~2.600 empresas).

Se ejecuta siempre al terminar el planificador (no depende de que el LLM se
acuerde de pedirlo) y usa, por orden de coste:

1. Empresas con web y sin teléfono/email -> se lee su web con nuestro propio
   extractor (`enriquecer_desde_web`, gratis): aviso legal -> NIF, email,
   teléfono, razón social.
2. Empresas sin web -> se busca por nombre y zona con la mejor fuente
   disponible: Google Maps vía Apify si la búsqueda lo tiene marcado (da
   teléfono y web directamente, 0,004 $ por empresa); si no, Google Search
   vía Apify si está marcado; si no, la búsqueda web nativa del LLM
   (0,01 € por consulta). Lo encontrado solo se procesa si el nombre (o el
   NIF) coincide con la empresa buscada -- un resultado de otro negocio no se
   atribuye a esta empresa. Y aunque se procese, la unión con la empresa la
   decide la resolución de entidades normal (`procesar_registro`), no esta fase.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import httpx
import psycopg

from radar.agente.consultas import zona_texto
from radar.agente.descubrir_apify_maps import (
    COSTE_ARRANQUE_USD as COSTE_ARRANQUE_MAPS_USD,
)
from radar.agente.descubrir_apify_maps import (
    COSTE_POR_LUGAR_USD,
    ejecutar_maps,
    procesar_items_maps,
)
from radar.agente.interpretacion import FiltrosBusqueda
from radar.extraccion import enriquecer_desde_web
from radar.fuentes.apify import ejecutar_actor
from radar.fuentes.apify_maps import lugar_a_registro
from radar.fuentes.base import RegistroBruto
from radar.fuentes.buscador_web import COSTE_POR_BUSQUEDA_EUR, buscar
from radar.normalizacion.dominio import (
    es_dominio_plataforma,
    extraer_dominio,
    parece_ficha_de_directorio,
)
from radar.normalizacion.nombre import (
    extraer_forma_juridica,
    normalizar_nombre,
    similitud_nombres,
    tokens_distintivos,
)
from radar.orquestador import bd, procesar_registro
from radar.secretos import gasto_mes_apify_usd, obtener_token_apify, presupuesto_mensual_apify_usd

MAX_EMPRESAS = 25
UMBRAL_SIMILITUD = 0.6
_NO_WEB_PROPIA = {"boe.es"}

_SQL_EMPRESAS = """
select e.id::text, coalesce(e.razon_social, e.nombre_comercial), e.nif, e.dominio_web,
  (select s.municipio_nombre from sedes s where s.empresa_id = e.id and s.municipio_nombre is not null limit 1),
  exists(select 1 from canales_contacto c where c.empresa_id = e.id and c.tipo = 'telefono' and c.estado <> 'invalido'),
  exists(select 1 from canales_contacto c where c.empresa_id = e.id and c.tipo = 'email' and c.estado <> 'invalido'),
  coalesce((select array_agg(c.valor) from canales_contacto c where c.empresa_id = e.id and c.tipo = 'telefono'), '{}')
from busqueda_resultados br
join empresas e on e.id = br.empresa_id
where br.busqueda_id = %s and e.fusionada_en is null and (e.estado is null or e.estado not in ('extinguida', 'disuelta'))
"""


@dataclass
class EmpresaSinContacto:
    id: str
    nombre: str
    nif: str | None
    dominio_web: str | None
    municipio: str | None
    tiene_telefono: bool
    tiene_email: bool
    telefonos: list[str] = field(default_factory=list)

    @property
    def completa(self) -> bool:
        return bool(self.dominio_web) and self.tiene_telefono and self.tiene_email


def estado_contacto(conn: psycopg.Connection, busqueda_id: str) -> list[EmpresaSinContacto]:
    return [EmpresaSinContacto(*fila) for fila in conn.execute(_SQL_EMPRESAS, (busqueda_id,)).fetchall()]


def resumen_contacto(empresas: list[EmpresaSinContacto]) -> dict[str, int]:
    return {
        "empresas": len(empresas),
        "con_web": sum(bool(e.dominio_web) for e in empresas),
        "con_telefono": sum(e.tiene_telefono for e in empresas),
        "con_email": sum(e.tiene_email for e in empresas),
    }


def nombre_para_buscar(nombre: str) -> str:
    """Nombre sin forma jurídica ("REFORMAS GUADAIRA SOCIEDAD LIMITADA" ->
    "reformas guadaira"): así lo escribe la gente en Maps y en su web."""
    _, sin_forma = extraer_forma_juridica(nombre)
    return sin_forma or nombre


def coincide(nombre_objetivo: str, nombre_candidato: str | None) -> bool:
    """¿El nombre encontrado es plausiblemente la misma empresa? Similitud
    alta, o alguna palabra DISTINTIVA en común (no genérica como
    "reformas"/"construcciones")."""
    if not nombre_candidato:
        return False
    a, b = normalizar_nombre(nombre_objetivo), normalizar_nombre(nombre_candidato)
    if not a or not b:
        return False
    return similitud_nombres(a, b) >= UMBRAL_SIMILITUD or bool(tokens_distintivos(a) & tokens_distintivos(b))


def _digitos(t: str) -> str:
    return "".join(ch for ch in t if ch.isdigit())[-9:]


def registro_coincide(empresa: EmpresaSinContacto, registro: RegistroBruto) -> bool:
    c = registro.campos
    if empresa.nif and c.nif and empresa.nif.upper() == c.nif.upper():
        return True
    # Mismo teléfono: la web es de este negocio aunque el nombre no case (la
    # marca de Maps "Electricista Majadahonda" frente a la razón social del
    # aviso legal).
    propios = {_digitos(t) for t in empresa.telefonos if len(_digitos(t)) == 9}
    if propios & {_digitos(t) for t in c.telefonos}:
        return True
    return coincide(empresa.nombre, c.razon_social) or coincide(empresa.nombre, c.nombre_comercial)


def _web_propia(url: str | None) -> bool:
    dominio = extraer_dominio(url) if url else None
    return (
        bool(dominio) and not es_dominio_plataforma(dominio) and dominio not in _NO_WEB_PROPIA
        and not parece_ficha_de_directorio(url)
    )


def _compacto(texto: str) -> str:
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode())


def es_ficha_de_tercero(nombre_empresa: str, url: str) -> bool:
    """La ruta de la URL nombra a la empresa pero el dominio no se le parece:
    es su ficha en un portal ajeno (visto en vivo 2026-09-24:
    profymarket.com/contratistas/la-encina-gran-capitan-sl se tomó por la web
    de LA ENCINA y le puso el nombre y el email del portal)."""
    distintivos = [t for t in tokens_distintivos(normalizar_nombre(nombre_empresa) or "") if len(t) >= 4]
    if not distintivos:
        return False
    host = _compacto((extraer_dominio(url) or "").rsplit(".", 1)[0])
    resto = url.split("://", 1)[-1]
    ruta = _compacto(resto[resto.find("/"):] if "/" in resto else "")
    en_ruta = any(t in ruta for t in distintivos)
    en_host = any(t in host for t in distintivos)
    return en_ruta and not en_host


def _procesar(
    registro: RegistroBruto, conn: psycopg.Connection, busqueda_id: str, compartidos: set[str] | None, etiqueta: str,
    contadores: dict[str, int],
) -> None:
    try:
        r = procesar_registro(registro, conn, busqueda_id=busqueda_id, telefonos_compartidos=compartidos)
        if r.empresa_id:
            bd.registrar_resultado_busqueda(busqueda_id, r.empresa_id, f"{etiqueta}: {r.accion}", r.puntuacion_match, conn)
        conn.commit()
        contadores[r.accion] = contadores.get(r.accion, 0) + 1
    except Exception:  # noqa: BLE001 -- una empresa que falla no debe tirar el resto
        conn.rollback()
        contadores["error_procesado"] += 1


async def _leer_web(
    conn: psycopg.Connection, cliente_http: httpx.AsyncClient, empresa: EmpresaSinContacto, url: str,
    busqueda_id: str, compartidos: set[str] | None, contadores: dict[str, int], *, exigir_coincidencia: bool,
) -> bool:
    if es_ficha_de_tercero(empresa.nombre, url):
        contadores["fichas_de_terceros"] = contadores.get("fichas_de_terceros", 0) + 1
        return False
    registro = await enriquecer_desde_web(cliente_http, url)
    if registro is None:
        contadores["webs_no_legibles"] += 1
        return False
    if exigir_coincidencia and not registro_coincide(empresa, registro):
        contadores["no_coincide"] += 1
        return False
    contadores["webs_leidas"] += 1
    _procesar(registro, conn, busqueda_id, compartidos, "contacto_web", contadores)
    return True


async def _buscar_con_maps(
    conn: psycopg.Connection, cliente_http: httpx.AsyncClient, empresas: list[EmpresaSinContacto], zona: str | None,
    tope_usd: float, busqueda_id: str, compartidos: set[str] | None, contadores: dict[str, int],
) -> float:
    cabe = int((tope_usd - COSTE_ARRANQUE_MAPS_USD) / COSTE_POR_LUGAR_USD)
    empresas = empresas[: max(0, cabe)]
    if not empresas:
        return 0.0
    busquedas = [f"{nombre_para_buscar(e.nombre)} {e.municipio or ''}".strip() for e in empresas]
    items, coste, _, error = await ejecutar_maps(
        conn, cliente_http, busquedas=busquedas, zona=zona, lugares_por_busqueda=1, tope_usd=tope_usd,
        detalle={"fase": "completar_contacto", "busquedas": busquedas},
    )
    if error:
        contadores["error_apify"] += 1
    # Solo los lugares cuyo nombre corresponde a alguna de las empresas buscadas.
    validos = []
    for item in items:
        registro = lugar_a_registro(item)
        if registro is not None and any(coincide(e.nombre, registro.campos.nombre_comercial) for e in empresas):
            validos.append(item)
        else:
            contadores["no_coincide"] += 1
    sub = await procesar_items_maps(
        conn, cliente_http, validos, busqueda_id=busqueda_id, telefonos_compartidos=compartidos, etiqueta="contacto_maps"
    )
    contadores["encontradas_en_maps"] += len(validos)
    contadores["webs_leidas"] += sub["webs_leidas"]
    return coste


async def _buscar_con_google_apify(
    conn: psycopg.Connection, cliente_http: httpx.AsyncClient, empresas: list[EmpresaSinContacto], zona: str | None,
    tope_usd: float, busqueda_id: str, compartidos: set[str] | None, contadores: dict[str, int],
) -> float:
    from radar.agente.descubrir_google_search import (
        ACTOR_GOOGLE_SEARCH,
        COSTE_ARRANQUE_USD,
        COSTE_POR_PAGINA_USD,
    )

    token = obtener_token_apify(conn)
    cabe = int((tope_usd - COSTE_ARRANQUE_USD) / COSTE_POR_PAGINA_USD)
    empresas = empresas[: max(0, cabe)]
    if not token or not empresas:
        return 0.0
    consultas = [f'"{nombre_para_buscar(e.nombre)}" {e.municipio or zona or ""}'.strip() for e in empresas]
    res = await ejecutar_actor(
        cliente_http, token, ACTOR_GOOGLE_SEARCH,
        {"queries": "\n".join(consultas), "maxPagesPerQuery": 1, "countryCode": "es", "languageCode": "es"},
        max_coste_usd=tope_usd, max_items=len(consultas), timeout_s=120,
    )
    bd.registrar_uso_apify(ACTOR_GOOGLE_SEARCH, res.run_id, res.estado, res.coste_usd, {"fase": "completar_contacto", "consultas": consultas}, conn)
    conn.commit()
    por_consulta = {(it.get("searchQuery") or {}).get("term"): it for it in res.items}
    for i, (empresa, consulta) in enumerate(zip(empresas, consultas, strict=True)):
        # Por término; si Apify lo devuelve con otro formato, por orden.
        item = por_consulta.get(consulta) or (res.items[i] if i < len(res.items) else {})
        urls = [o.get("url") for o in item.get("organicResults") or [] if _web_propia(o.get("url"))][:3]
        for url in urls:
            if await _leer_web(conn, cliente_http, empresa, url, busqueda_id, compartidos, contadores, exigir_coincidencia=True):
                break
    return res.coste_usd


async def _buscar_con_llm(
    conn: psycopg.Connection, cliente_http: httpx.AsyncClient, cliente_llm: Any | None, empresas: list[EmpresaSinContacto],
    zona: str | None, tope_eur: float, busqueda_id: str, compartidos: set[str] | None, contadores: dict[str, int],
) -> float:
    coste = 0.0
    for empresa in empresas:
        if coste + COSTE_POR_BUSQUEDA_EUR > tope_eur:
            break
        consulta = f'"{nombre_para_buscar(empresa.nombre)}" {empresa.municipio or zona or ""}'.strip()
        res = await asyncio.to_thread(buscar, cliente_llm, consulta, max_resultados=3)
        coste += res.numero_busquedas * COSTE_POR_BUSQUEDA_EUR
        if res.error:
            contadores["error_busqueda"] += 1
            continue
        for r in res.resultados:
            if _web_propia(r.url) and await _leer_web(
                conn, cliente_http, empresa, r.url, busqueda_id, compartidos, contadores, exigir_coincidencia=True
            ):
                break
    return coste


async def completar_contacto(
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    filtros: FiltrosBusqueda,
    *,
    busqueda_id: str,
    max_coste_eur: float,
    apify_actores: frozenset[str] | set[str] = frozenset(),
    cliente_llm: Any | None = None,
    telefonos_compartidos: set[str] | None = None,
    max_empresas: int = MAX_EMPRESAS,
) -> dict[str, Any]:
    antes = estado_contacto(conn, busqueda_id)
    contadores: dict[str, int] = {
        "webs_leidas": 0, "webs_no_legibles": 0, "no_coincide": 0, "encontradas_en_maps": 0,
        "vinculado": 0, "nueva_empresa": 0, "en_revision": 0, "ya_procesado": 0,
        "error_procesado": 0, "error_apify": 0, "error_busqueda": 0,
    }
    pendientes = [e for e in antes if not e.completa][:max_empresas]
    zona = zona_texto(filtros)
    coste_eur = 0.0

    # 1. Gratis: leer la web propia de las que ya la tienen.
    for e in [e for e in pendientes if e.dominio_web]:
        await _leer_web(conn, cliente_http, e, f"https://{e.dominio_web}", busqueda_id, telefonos_compartidos, contadores, exigir_coincidencia=False)

    # 2. Sin web: buscarla. Las que no tienen NADA de contacto, primero en
    #    Maps (da teléfono y web); las que ya tienen teléfono (típico de Maps
    #    sin web) en Google, porque es su web la que da email, NIF y personas.
    hay_token = bool(obtener_token_apify(conn))
    tope_apify = min(max_coste_eur, presupuesto_mensual_apify_usd(conn) - gasto_mes_apify_usd(conn)) if hay_token else 0.0
    sin_nada = [e for e in pendientes if not e.dominio_web and not e.tiene_telefono]
    solo_telefono = [e for e in pendientes if not e.dominio_web and e.tiene_telefono]
    fuentes_usadas: list[str] = []
    if sin_nada and hay_token and "google_maps" in apify_actores and tope_apify > 0:
        fuentes_usadas.append("apify_google_maps")
        gastado = await _buscar_con_maps(conn, cliente_http, sin_nada, zona, tope_apify / 2, busqueda_id, telefonos_compartidos, contadores)
        coste_eur += gastado
        tope_apify -= gastado
        sin_nada = []
    buscar_en_google = sin_nada + solo_telefono
    if buscar_en_google and max_coste_eur - coste_eur > 0:
        if hay_token and "google_search" in apify_actores and tope_apify > 0:
            fuentes_usadas.append("apify_google_search")
            coste_eur += await _buscar_con_google_apify(conn, cliente_http, buscar_en_google, zona, tope_apify, busqueda_id, telefonos_compartidos, contadores)
        else:
            fuentes_usadas.append("buscador_web")
            coste_eur += await _buscar_con_llm(
                conn, cliente_http, cliente_llm, buscar_en_google, zona, max_coste_eur - coste_eur, busqueda_id, telefonos_compartidos, contadores
            )
    fuente = ", ".join(fuentes_usadas) or "ninguna"

    despues = estado_contacto(conn, busqueda_id)
    return {
        **contadores, "fuente_busqueda_por_nombre": fuente, "empresas_revisadas": len(pendientes),
        "antes": resumen_contacto(antes), "despues": resumen_contacto(despues), "coste_eur": round(coste_eur, 4),
    }
