"""Identificar empresas sin CIF (2026-10-01) — fase 3d de toda búsqueda.

Medido en búsquedas reales: solo un 25-40 % de las empresas de cada búsqueda
tenía CIF, y por eso casi ninguna tenía también persona de contacto (sin
razón social no hay acto del BORME que dé el administrador). Muchas pymes no
publican el CIF en su web; donde sí aparece es en los directorios de
empresas (infocif, empresite, einforma...), y basta con el TÍTULO y el
EXTRACTO del resultado de búsqueda: no se entra en el directorio.

Dos vías, según lo que haya marcado el usuario:
- «Búsqueda en Google» (Apify) marcada: una consulta `"nombre" municipio CIF`
  por empresa en una sola ejecución; se leen título y extracto.
- Si no: el modelo con búsqueda web localiza el CIF y la página donde lo vio.

En ambos casos el LLM/buscador solo PROPONE; el código verifica (principio
4): NIF de sociedad con dígito de control válido, nombre que coincide con la
empresa buscada, forma jurídica coherente con la letra del CIF y un único CIF
candidato (si hay dos distintos, no se arriesga). El dato se guarda como
fuente 'directorio_cif' (fiabilidad 0,55, con la URL como evidencia) y se une
a ESA empresa (`procesar_registro(..., empresa_destino=...)`); si el CIF ya
era de otra fila, queda como posible duplicado. Después, la fase del BORME
puede añadir el administrador con la razón social ya conocida.
"""

from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any

import httpx
import psycopg

from radar.agente.completar_contacto import coincide, nombre_para_buscar
from radar.agente.descubrir_google_search import (
    ACTOR_GOOGLE_SEARCH,
    COSTE_ARRANQUE_USD,
    COSTE_POR_PAGINA_USD,
)
from radar.extraccion.reglas import RX_NIF
from radar.fuentes.apify import ejecutar_actor
from radar.fuentes.base import CamposExtraidos, RegistroBruto
from radar.fuentes.buscador_web import consultar_con_busqueda
from radar.normalizacion.nif import forma_compatible_con_nif, validar_nif
from radar.normalizacion.nombre import extraer_forma_juridica
from radar.orquestador import bd, procesar_registro
from radar.secretos import gasto_mes_apify_usd, obtener_token_apify, presupuesto_mensual_apify_usd

MAX_EMPRESAS = 20
COSTE_ESTIMADO_LLM_EUR = 0.025  # por empresa (búsqueda web + tokens); se descuenta el real
CONCURRENCIA_LLM = 4

_SQL_CANDIDATAS = """
select e.id::text, e.razon_social, e.nombre_comercial,
  (select s.municipio_nombre from sedes s where s.empresa_id = e.id and s.municipio_nombre is not null limit 1)
from busqueda_resultados br join empresas e on e.id = br.empresa_id
where br.busqueda_id = %s and e.fusionada_en is null and e.nif is null and not e.es_persona_fisica
  and coalesce(br.clasificacion, '') not in ('descartado', 'rechazado')
order by (br.clasificacion = 'relevante') desc nulls last,
  exists (select 1 from canales_contacto c where c.empresa_id = e.id and c.tipo = 'telefono') desc
limit %s
"""


@dataclass
class EmpresaSinCif:
    id: str
    nombre: str
    municipio: str | None


@dataclass
class CifPropuesto:
    nif: str
    razon_social: str | None
    url: str | None


def nombre_limpio(nombre: str) -> str:
    """'EMIF | Alcalá de Guadaira' -> 'EMIF'; quita la forma jurídica."""
    base = re.split(r"\s+[|·–—]\s+|\s+-\s+", nombre)[0].strip()
    return nombre_para_buscar(base) or base


def _sin_tildes(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()


def nombre_para_verificar(nombre: str, municipio: str | None) -> str:
    """Nombre sin el municipio: 'Climasol Alcalá' no debe "coincidir" con
    cualquier 'CLIMATIZACIONES ALCALA SL' solo por compartir la localidad."""
    base = nombre_limpio(nombre)
    if municipio:
        quitar = {_sin_tildes(w) for w in re.findall(r"\w+", municipio) if len(w) > 2}
        palabras = [w for w in base.split() if _sin_tildes(w.strip(".,")) not in quitar]
        base = " ".join(palabras) or base
    return base


def _razon_de_titulo(titulo: str) -> str:
    """El trozo del título que parece la denominación (el que lleva forma
    jurídica), p. ej. 'CLIMATIZACIONES MONTAÑO SL - CIF B9... - Alcalá'."""
    partes = [p.strip() for p in re.split(r"\s+[-|·–—:]\s+", titulo) if p.strip()]
    for p in partes:
        if extraer_forma_juridica(p)[0]:
            return p
    return partes[0] if partes else titulo


def cif_valido_para(nombre: str, nif: str, razon: str | None) -> bool:
    """Verificación determinista de un CIF propuesto para una empresa."""
    v = validar_nif(nif)
    if not v["valido"] or v["tipo"] != "sociedad":
        return False
    if not razon or not coincide(nombre, razon):
        return False
    forma, _ = extraer_forma_juridica(razon)
    return forma_compatible_con_nif(forma, v["nif"]) is not False


def elegir_de_resultados(nombre: str, resultados: list[dict[str, Any]]) -> CifPropuesto | None:
    """Del título/extracto de los resultados de búsqueda, el CIF que aparece
    junto al nombre de la empresa. `None` si no hay o si hay dos distintos."""
    votos: Counter[str] = Counter()
    datos: dict[str, CifPropuesto] = {}
    for r in resultados:
        titulo = str(r.get("title") or "")
        texto = f"{titulo} {r.get('description') or ''}"
        razon = _razon_de_titulo(titulo)
        for m in RX_NIF.finditer(texto):
            nif = validar_nif(m.group(1))["nif"]
            if cif_valido_para(nombre, nif, razon):
                votos[nif] += 1
                datos.setdefault(nif, CifPropuesto(nif, razon, r.get("url")))
    if not votos:
        return None
    (primero, n1), *resto = votos.most_common()
    if resto and resto[0][1] == n1:
        return None  # empate entre CIF distintos: no se arriesga
    return datos[primero]


_PROMPT_LLM = """Busca en la web el CIF (NIF de la sociedad) de esta empresa española:
- Nombre: {nombre}
- Municipio: {municipio}
Fíjate en directorios de empresas o en su aviso legal. Responde SOLO con JSON:
{{"cif": "B12345678 o null", "razon_social": "denominación exacta con forma jurídica o null", "url": "página donde lo viste o null"}}
Si no lo encuentras o dudas entre varias empresas, pon null. No inventes."""


def propuesta_de_texto(texto: str, urls: list[str]) -> CifPropuesto | None:
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    if not m:
        return None
    try:
        datos = json.loads(m.group(0))
    except ValueError:
        return None
    cif = datos.get("cif")
    if not cif or str(cif).lower() == "null":
        return None
    return CifPropuesto(str(cif), datos.get("razon_social") or None, datos.get("url") or (urls[0] if urls else None))


async def _propuestas_apify(
    conn: psycopg.Connection, cliente_http: httpx.AsyncClient, empresas: list[EmpresaSinCif], tope_usd: float, contadores: dict[str, Any]
) -> tuple[dict[str, CifPropuesto], float]:
    token = obtener_token_apify(conn)
    cabe = int((tope_usd - COSTE_ARRANQUE_USD) / COSTE_POR_PAGINA_USD)
    empresas = empresas[: max(0, cabe)]
    if not token or not empresas:
        return {}, 0.0
    consultas = [f'"{nombre_limpio(e.nombre)}" {e.municipio or ""} CIF'.strip() for e in empresas]
    res = await ejecutar_actor(
        cliente_http, token, ACTOR_GOOGLE_SEARCH,
        {"queries": "\n".join(consultas), "maxPagesPerQuery": 1, "countryCode": "es", "languageCode": "es"},
        max_coste_usd=tope_usd, max_items=len(consultas), timeout_s=180,
    )
    bd.registrar_uso_apify(ACTOR_GOOGLE_SEARCH, res.run_id, res.estado, res.coste_usd, {"fase": "completar_identidad", "consultas": consultas}, conn)
    conn.commit()
    if res.error:
        contadores["error"] = res.error
    por_consulta = {(it.get("searchQuery") or {}).get("term"): it for it in res.items}
    propuestas: dict[str, CifPropuesto] = {}
    for i, (e, consulta) in enumerate(zip(empresas, consultas, strict=True)):
        item = por_consulta.get(consulta) or (res.items[i] if i < len(res.items) else {})
        p = elegir_de_resultados(nombre_para_verificar(e.nombre, e.municipio), item.get("organicResults") or [])
        if p:
            propuestas[e.id] = p
    contadores["empresas_buscadas"] = len(empresas)
    return propuestas, res.coste_usd


async def _propuestas_llm(
    empresas: list[EmpresaSinCif], tope_eur: float, contadores: dict[str, Any]
) -> tuple[dict[str, CifPropuesto], float]:
    empresas = empresas[: int(tope_eur / COSTE_ESTIMADO_LLM_EUR)]
    semaforo = asyncio.Semaphore(CONCURRENCIA_LLM)

    async def una(e: EmpresaSinCif) -> tuple[str, CifPropuesto | None, float]:
        async with semaforo:
            r = await asyncio.to_thread(
                consultar_con_busqueda, None, _PROMPT_LLM.format(nombre=e.nombre, municipio=e.municipio or "España")
            )
        if r.error:
            contadores["error"] = r.error
            return e.id, None, r.coste_eur
        p = propuesta_de_texto(r.texto, r.urls)
        if p and not cif_valido_para(nombre_para_verificar(e.nombre, e.municipio), p.nif, p.razon_social):
            contadores["rechazadas_por_verificacion"] += 1
            p = None
        return e.id, p, r.coste_eur

    resultados = await asyncio.gather(*(una(e) for e in empresas))
    contadores["empresas_buscadas"] = len(empresas)
    return {i: p for i, p, _ in resultados if p}, sum(c for _, _, c in resultados)


async def completar_identidad(
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    *,
    busqueda_id: str,
    max_coste_eur: float,
    usar_google_apify: bool,
    telefonos_compartidos: set[str] | None = None,
) -> dict[str, Any]:
    contadores: dict[str, Any] = {
        "sin_cif": 0, "empresas_buscadas": 0, "cif_encontrados": 0, "unidas": 0, "posibles_duplicados": 0,
        "rechazadas_por_verificacion": 0, "error": None,
    }
    filas = conn.execute(_SQL_CANDIDATAS, (busqueda_id, MAX_EMPRESAS)).fetchall()
    empresas = [EmpresaSinCif(f[0], f[1] or f[2], f[3]) for f in filas if (f[1] or f[2])]
    contadores["sin_cif"] = len(empresas)
    if not empresas or max_coste_eur <= 0:
        return {**contadores, "motivo_parada": None if empresas else "todas tienen CIF", "coste_eur": 0.0}

    if usar_google_apify and obtener_token_apify(conn):
        tope = min(max_coste_eur, presupuesto_mensual_apify_usd(conn) - gasto_mes_apify_usd(conn))
        propuestas, coste = await _propuestas_apify(conn, cliente_http, empresas, tope, contadores)
        contadores["metodo"] = "Google (Apify)"
    else:
        propuestas, coste = await _propuestas_llm(empresas, max_coste_eur, contadores)
        contadores["metodo"] = "búsqueda web con IA"

    for empresa_id, p in propuestas.items():
        contadores["cif_encontrados"] += 1
        registro = RegistroBruto(
            fuente="directorio_cif", id_externo=p.nif, url=p.url,
            payload={"metodo": contadores["metodo"], "razon_social": p.razon_social, "url": p.url},
            campos=CamposExtraidos(razon_social=p.razon_social, nif=p.nif),
        )
        try:
            r = procesar_registro(
                registro, conn, busqueda_id=busqueda_id, telefonos_compartidos=telefonos_compartidos, empresa_destino=empresa_id
            )
            conn.commit()
            contadores["unidas" if r.accion == "vinculado" else "posibles_duplicados"] += 1
        except Exception:  # noqa: BLE001 -- una empresa que falla no para el resto
            conn.rollback()
    return {**contadores, "coste_eur": round(coste, 4)}
