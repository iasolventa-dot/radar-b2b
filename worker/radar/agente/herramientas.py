"""Herramientas del planificador (doc 07 §5, skill `agente-busqueda-empresas`
`references/herramientas.json`): lo único que el LLM puede invocar durante
el bucle de tool use — nunca escribe en la BD ni decide una fusión por sí
mismo, solo pide a estas funciones que lo hagan de forma determinista y le
devuelvan un resumen compacto (doc 07 §1, regla "el agente no escribe en
la BD ni lee páginas enteras").

De las 9 herramientas del doc 07 §5, esta entrega implementa las que ya
tienen todas sus piezas construidas:

- **consultar_bd**: cuenta empresas que cumplen los filtros en la BD propia
  (+ una muestra). El filtro SQL (`construir_where_empresas`) usa
  `cnae_coincide()` (doc 08 D-18) para que `sector.codigos_cnae` case por
  prefijo, no por igualdad exacta, y resuelve `ubicacion.municipios` a
  `sedes.municipio_ine` vía `resolver_codigos_municipio` en vez de comparar
  contra el texto crudo del BORME (que nunca coincidía con lo que escribe
  el LLM, p. ej. "ALCALA DE GUADAIRA" vs "Alcalá de Guadaíra"). También
  aplica `sector.palabras_clave` contra `objeto_social`/`razon_social` —
  antes esto solo se aplicaba al descubrir (`_coincide_sector`), nunca al
  consultar lo ya guardado, así que una petición sin `codigos_cnae`
  explícitos (el caso normal: BORME nunca da CNAE) no filtraba nada por
  sector. `ubicacion.ccaa` ya se aplica también (migración 202609141200,
  función `normalizar_ccaa`), uniéndose a `municipios` por
  `sedes.municipio_ine`.
- **descubrir_borme**: ejecuta `ConectorBorme.descubrir` (ya construido,
  doc 08 D-11) para un rango de fechas/provincia, descarta los actos que no
  coinciden con `sector.palabras_clave` (o, si la interpretación no dio
  ninguna, con las listas de construcción de `radar.fuentes.borme`) y
  procesa cada uno con `radar.orquestador.procesar_registro` — mismo patrón
  que `scripts/ejecutar_borme.py`, con el filtro de sector añadido.
- **buscar_web**: ejecuta `radar.fuentes.buscador_web.buscar` (D-06) y, por
  cada URL encontrada, la enriquece con
  `radar.extraccion.enriquecer_desde_web` y la procesa — mismo patrón que
  `scripts/buscar_web.py --enriquecer --guardar`, en bucle con presupuesto.
- **preguntar_usuario** / **finalizar_busqueda**: sin efectos secundarios;
  el planificador (`radar.agente.planificador`, siguiente entrega) decide
  qué hacer con la respuesta (parar el bucle, mostrar la pregunta...).

Deliberadamente NO implementadas todavía, porque dependen de piezas que no
existen (ver `radar/agente/__init__.py` y el mensaje del agente en
`08_registro_decisiones.md` del 2026-09-11):

- **estimar_cobertura** — necesita datos INE DIRCE, no descargados aún.
- **lanzar_descubrimiento** / **estado_trabajos** — el diseño del doc 07
  es asíncrono (encola un trabajo, se consulta su estado más tarde,
  tabla `busquedas`); `radar.cola` solo tiene el wrapper de pgmq, sin
  worker consumidor. Aquí `descubrir_borme`/`buscar_web` son sus
  equivalentes SÍNCRONOS (se ejecutan y devuelven el resultado en la
  misma llamada) — válido para un primer planificador de un solo proceso,
  a sustituir cuando haya cola de verdad.
- **arbitrar_duplicados** — el prompt de arbitraje existe en la skill,
  pero no hay código; hoy `procesar_registro` mete la zona gris en
  `candidatos_duplicado` como "nueva_empresa" pendiente de revisión
  (ver docstring de `radar.orquestador.procesar`).
- **verificar_empresa** — verificación profunda de una empresa concreta;
  no construida.
- **enriquecer_pendientes** — en esta entrega, `buscar_web` ya enriquece
  en el mismo paso; un `enriquecer_pendientes` aparte (para candidatos que
  quedaron sin enriquecer, p. ej. de `descubrir_borme`) queda pendiente.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
import psycopg

from radar.agente.interpretacion import FiltrosBusqueda
from radar.extraccion import enriquecer_desde_web
from radar.fuentes.borme import (
    PALABRAS_CONSTRUCCION_NOMBRE,
    PALABRAS_CONSTRUCCION_OBJETO,
    ConectorBorme,
)
from radar.fuentes.buscador_web import COSTE_POR_BUSQUEDA_EUR, buscar
from radar.orquestador import bd, procesar_registro

_TABLA_TILDES = str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN")


def _sin_tildes(s: str) -> str:
    return s.translate(_TABLA_TILDES)


# --- Definición de herramientas (esquema JSON, igual para openai/anthropic) ---


@dataclass(frozen=True)
class Herramienta:
    nombre: str
    descripcion: str
    parametros: dict[str, Any]  # JSON Schema de un objeto — mismo formato para "input_schema" (anthropic) y "parameters" (openai)


def a_tool_param_openai(h: Herramienta) -> dict[str, Any]:
    """`openai.types.responses.FunctionToolParam` — se devuelve como `dict`
    (no se importa el TypedDict) porque este módulo no depende del SDK de
    ningún proveedor, a diferencia de `radar.extraccion.llm` /
    `radar.fuentes.buscador_web`: aquí solo se describen herramientas, no
    se llama a ninguna API."""
    return {"type": "function", "name": h.nombre, "description": h.descripcion, "parameters": h.parametros, "strict": False}


def a_tool_param_anthropic(h: Herramienta) -> dict[str, Any]:
    return {"name": h.nombre, "description": h.descripcion, "input_schema": h.parametros}


HERRAMIENTAS: list[Herramienta] = [
    Herramienta(
        nombre="consultar_bd",
        descripcion=(
            "Busca en la base de datos propia empresas que cumplen los filtros y devuelve un recuento, "
            "estadísticas de calidad (confianza media, % con teléfono verificado, % con NIF válido) y una "
            "muestra de hasta 10 empresas. Úsala al principio de cada búsqueda y tras cada ronda para medir "
            "el progreso. No devuelve la lista completa."
        ),
        parametros={
            "type": "object",
            "properties": {
                "incluir_muestra": {"type": "boolean", "default": True},
            },
            "required": [],
        },
    ),
    Herramienta(
        nombre="descubrir_borme",
        descripcion=(
            "Busca constituciones, disoluciones y otros actos en el BORME de una provincia en un rango de "
            "días hacia atrás, descarta los que no coinciden con el sector de la búsqueda y guarda el resto "
            "como candidatos (o los vincula/descarta si ya existen). Gratuito (fuente pública). No da NIF: "
            "para confirmarlo hace falta buscar_web sobre la web de la empresa."
        ),
        parametros={
            "type": "object",
            "properties": {
                "provincia_titulo": {"type": "string", "description": "Título de provincia tal como lo usa el BORME, p. ej. 'SEVILLA'."},
                "dias": {"type": "integer", "default": 30, "description": "Días hacia atrás desde hoy."},
            },
            "required": ["provincia_titulo"],
        },
    ),
    Herramienta(
        nombre="buscar_web",
        descripcion=(
            "Ejecuta hasta el presupuesto indicado una o varias consultas literales en el buscador web, y por "
            "cada URL encontrada descarga y analiza su aviso legal/contacto (nunca se fía de los extractos del "
            "buscador) para guardar los datos como candidato. Usa los patrones de consulta del doc 04 §5: "
            "'palabra clave' 'municipio', site:dominio.es aviso legal, \"NIF entre comillas\"."
        ),
        parametros={
            "type": "object",
            "properties": {
                "consultas": {"type": "array", "items": {"type": "string"}, "description": "Consultas literales a ejecutar tal cual."},
                "max_resultados_por_consulta": {"type": "integer", "default": 5},
                "max_coste_eur": {"type": "number", "description": "Tope de gasto para esta llamada."},
            },
            "required": ["consultas", "max_coste_eur"],
        },
    ),
    Herramienta(
        nombre="preguntar_usuario",
        descripcion=(
            "Hace una pregunta al usuario cuando una ambigüedad cambia mucho el resultado. Úsala como mucho "
            "una vez por búsqueda salvo necesidad real; en lo demás, aplica un supuesto razonable y decláralo."
        ),
        parametros={
            "type": "object",
            "properties": {
                "pregunta": {"type": "string"},
                "opciones": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["pregunta"],
        },
    ),
    Herramienta(
        nombre="finalizar_busqueda",
        descripcion="Termina el bucle de búsqueda y explica por qué (presupuesto agotado, cobertura alcanzada, rendimientos decrecientes, máximo de rondas...).",
        parametros={
            "type": "object",
            "properties": {
                "motivo": {
                    "type": "string",
                    "enum": ["cobertura_alcanzada", "presupuesto_agotado", "rendimientos_decrecientes", "max_rondas", "cancelada_usuario"],
                },
                "resumen": {"type": "string", "description": "Resumen para el informe final del usuario."},
            },
            "required": ["motivo", "resumen"],
        },
    ),
]


# --- consultar_bd ------------------------------------------------------


def construir_where_empresas(
    filtros: FiltrosBusqueda, *, codigos_municipio: list[str] | None = None
) -> tuple[str, list[Any]]:
    """Aparte de `consultar_bd` para poder testear el SQL generado sin
    base de datos (igual que `radar.orquestador.logica` separa lo puro de
    lo que toca `conn`).

    `codigos_municipio` son los códigos INE ya resueltos (por
    `resolver_codigos_municipio`, que sí toca `conn`) a partir de
    `filtros.ubicacion.municipios` — esta función no resuelve nombres, solo
    construye SQL. Si `filtros.ubicacion.municipios` no está vacío pero
    `codigos_municipio` es `None`/vacío (ningún nombre resolvió contra el
    catálogo `municipios`), no se añade condición de ubicación por municipio:
    es preferible no filtrar que fingir un filtro con nombres que nunca van
    a casar contra `sedes.municipio_ine` (principio 5, nunca inventar).
    """
    condiciones = ["e.fusionada_en is null"]
    parametros: list[Any] = []

    if filtros.estados:
        condiciones.append("e.estado = any(%s)")
        parametros.append(list(filtros.estados))
    if not filtros.incluir_autonomos:
        condiciones.append("e.es_persona_fisica = false")
    if filtros.sector.codigos_cnae:
        # cnae_coincide (doc 08 D-18) compara por prefijo ignorando puntos:
        # ["41"] casa con "4101"/"41.02"/etc., no solo con "41" exacto.
        condiciones.append("cnae_coincide(e.cnae_principal, %s)")
        parametros.append(list(filtros.sector.codigos_cnae))
    if filtros.sector.palabras_clave:
        # Antes esta rama no existía: el filtro por palabras clave se
        # aplicaba al DESCUBRIR (descubrir_borme -> _coincide_sector),
        # pero nunca al CONSULTAR lo ya guardado en `empresas` -- si la
        # interpretación daba palabras_clave sin codigos_cnae (el caso
        # normal, porque BORME nunca da CNAE), consultar_bd ignoraba el
        # sector por completo y devolvía cualquier empresa. Busca en
        # objeto_social y razón social, sin tildes ni mayúsculas, igual
        # que hace _coincide_sector en Python -- mismo criterio, aquí en
        # SQL porque aquí no hay un `campos.objeto_social` en memoria, hay
        # que ir contra lo ya guardado en `empresas`.
        condiciones.append(
            "exists ("
            "  select 1 from unnest(%s::text[]) as p(palabra)"
            "  where strpos("
            "    extensions.unaccent(lower(coalesce(e.objeto_social, '') || ' ' || coalesce(e.razon_social, ''))),"
            "    extensions.unaccent(lower(p.palabra))"
            "  ) > 0"
            ")"
        )
        parametros.append(list(filtros.sector.palabras_clave))
    if filtros.sector.exclusiones:
        # Mismo criterio que palabras_clave, pero negado -- la interpretación
        # ya capturaba esto (doc 07 §3) pero nunca se aplicaba: se declaraba
        # "excluir reformas menores" y consultar_bd lo ignoraba en silencio.
        condiciones.append(
            "not exists ("
            "  select 1 from unnest(%s::text[]) as p(palabra)"
            "  where strpos("
            "    extensions.unaccent(lower(coalesce(e.objeto_social, '') || ' ' || coalesce(e.razon_social, ''))),"
            "    extensions.unaccent(lower(p.palabra))"
            "  ) > 0"
            ")"
        )
        parametros.append(list(filtros.sector.exclusiones))
    if filtros.tamano.empleados_min is not None:
        condiciones.append("(e.empleados_max is null or e.empleados_max >= %s)")
        parametros.append(filtros.tamano.empleados_min)
    if filtros.tamano.empleados_max is not None:
        condiciones.append("(e.empleados_min is null or e.empleados_min <= %s)")
        parametros.append(filtros.tamano.empleados_max)
    if filtros.formas_juridicas:
        condiciones.append("e.forma_juridica = any(%s)")
        parametros.append(list(filtros.formas_juridicas))

    if filtros.ubicacion.provincias:
        condiciones.append(
            "exists (select 1 from sedes s where s.empresa_id = e.id and s.activa and s.provincia = any(%s))"
        )
        parametros.append(list(filtros.ubicacion.provincias))
    elif filtros.ubicacion.municipios and codigos_municipio:
        condiciones.append(
            "exists (select 1 from sedes s where s.empresa_id = e.id and s.activa and s.municipio_ine = any(%s))"
        )
        parametros.append(list(codigos_municipio))
    elif filtros.ubicacion.ccaa:
        # normalizar_ccaa (migración 202609141200) ignora tildes, mayúsculas,
        # artículos y el orden de las palabras -- el INE escribe "Rioja, La"
        # / "Madrid, Comunidad de", pero el LLM (o una persona) escribe
        # "La Rioja" / "Comunidad de Madrid". No hace falta resolver nada en
        # Python antes (a diferencia de los municipios): al ser una función
        # SQL inmutable, se puede comparar en ambos lados dentro de la misma
        # consulta.
        condiciones.append(
            "exists ("
            "  select 1 from sedes s"
            "  join municipios m on m.codigo_ine = s.municipio_ine"
            "  where s.empresa_id = e.id and s.activa"
            "    and normalizar_ccaa(m.ccaa) = any(select normalizar_ccaa(x) from unnest(%s::text[]) as x)"
            ")"
        )
        parametros.append(list(filtros.ubicacion.ccaa))

    if filtros.requisitos.web:
        # requisitos.* se capturaba desde la primera sesión de interpretación
        # (doc 07 §3) pero nunca se aplicaba aquí -- pedir "solo con web" no
        # filtraba nada.
        condiciones.append("e.dominio_web is not null")
    if filtros.requisitos.telefono:
        condiciones.append(
            "exists (select 1 from canales_contacto c where c.empresa_id = e.id and c.tipo = 'telefono' and c.estado <> 'invalido')"
        )
    if filtros.requisitos.email_generico:
        # canales_contacto.es_generico (doc 03b §4: "info@, centralita... vs.
        # personal") tampoco se escribía nunca hasta esta sesión -- ver
        # radar.orquestador.bd.upsert_canal_contacto.
        condiciones.append(
            "exists (select 1 from canales_contacto c where c.empresa_id = e.id and c.tipo = 'email' "
            "and c.es_generico is true and c.estado <> 'invalido')"
        )
    if filtros.calidad.confianza_minima > 0:
        # coalesce a 0: una empresa sin confianza_global calculada todavía
        # (recién creada, antes de que _consolidar_y_actualizar_empresa
        # corra) no debe colarse como si "no tuviera este filtro" -- debe
        # tratarse como la confianza más baja posible, no como excluida del
        # filtro.
        condiciones.append("coalesce(e.confianza_global, 0) >= %s")
        parametros.append(filtros.calidad.confianza_minima)
    if filtros.calidad.frescura_max_dias and filtros.calidad.frescura_max_dias > 0:
        condiciones.append(
            "exists (select 1 from observaciones o where o.empresa_id = e.id "
            "and o.observado_en >= now() - (%s || ' days')::interval)"
        )
        parametros.append(filtros.calidad.frescura_max_dias)

    return " and ".join(condiciones), parametros


def resolver_codigos_municipio(nombres: list[str], conn: psycopg.Connection) -> list[str]:
    """Traduce nombres de municipio (tal como los escribe el LLM, p. ej.
    "Alcalá de Guadaíra") a códigos INE, usando la misma normalización que
    `buscar_municipio_ine` en Postgres (doc 08 D-18) — una sola consulta
    para toda la lista.

    Puede devolver más de un código por nombre si el nombre existe en
    varias provincias (17 casos en toda España, verificado 2026-09-14): sin
    la provincia como filtro adicional aquí, se acepta esa ambigüedad en
    vez de perder la coincidencia — es un `elif` frente a `provincias` en
    `construir_where_empresas`, así que solo se usa cuando el filtro no
    especificó provincia."""
    if not nombres:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            select distinct m.codigo_ine
            from municipios m
            where m.nombre_norm = any(select normalizar_texto(n) from unnest(%s::text[]) as n)
            """,
            (list(nombres),),
        )
        return [fila[0] for fila in cur.fetchall()]


def consultar_bd(conn: psycopg.Connection, filtros: FiltrosBusqueda, *, incluir_muestra: bool = True) -> dict[str, Any]:
    """Toca `conn` de verdad — se prueba de forma manual/integración contra
    Supabase, igual que `radar.orquestador.bd` (ver docstring de ese
    módulo); `construir_where_empresas` sí tiene tests unitarios."""
    codigos_municipio = None
    if not filtros.ubicacion.provincias and filtros.ubicacion.municipios:
        codigos_municipio = resolver_codigos_municipio(filtros.ubicacion.municipios, conn)
    where_sql, parametros = construir_where_empresas(filtros, codigos_municipio=codigos_municipio)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            select
                count(*),
                avg(e.confianza_global),
                avg((exists (
                    select 1 from canales_contacto c
                    where c.empresa_id = e.id and c.tipo = 'telefono' and c.estado = 'verificado'
                ))::int),
                avg((e.nif is not null and e.nif_valido)::int)
            from empresas e
            where {where_sql}
            """,
            parametros,
        )
        fila = cur.fetchone()
    total, confianza_media, pct_telefono, pct_nif = fila if fila else (0, None, None, None)

    resultado: dict[str, Any] = {
        "total": total or 0,
        "confianza_media": round(float(confianza_media), 2) if confianza_media is not None else None,
        "pct_con_telefono_verificado": round(float(pct_telefono) * 100, 1) if pct_telefono is not None else 0.0,
        "pct_con_nif_valido": round(float(pct_nif) * 100, 1) if pct_nif is not None else 0.0,
        "muestra": [],
    }

    if incluir_muestra and resultado["total"]:
        with conn.cursor() as cur:
            cur.execute(
                f"select e.razon_social, e.nif, e.estado, e.confianza_global from empresas e "
                f"where {where_sql} order by e.confianza_global desc nulls last limit 10",
                parametros,
            )
            resultado["muestra"] = [
                {"razon_social": f[0], "nif": f[1], "estado": f[2], "confianza": float(f[3]) if f[3] is not None else None}
                for f in cur.fetchall()
            ]
    return resultado


# --- descubrir_borme -----------------------------------------------------


def _coincide_sector(objeto_social: str | None, razon_social: str | None, palabras_clave: list[str]) -> bool:
    if not palabras_clave:
        return True
    texto = _sin_tildes(f"{objeto_social or ''} {razon_social or ''}".lower())
    return any(_sin_tildes(p.lower()) in texto for p in palabras_clave)


async def descubrir_borme(
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    filtros: FiltrosBusqueda,
    *,
    provincia_titulo: str,
    dias: int = 30,
    telefonos_compartidos: set[str] | None = None,
    busqueda_id: str | None = None,
) -> dict[str, Any]:
    """Mismo patrón que `scripts/ejecutar_borme.py` (descubrir → procesar →
    commit por acto, uno falla y sigue con el siguiente), con el filtro de
    sector añadido — ese script procesaba TODOS los actos sin filtrar.

    `busqueda_id`, si se pasa, enlaza cada empresa nueva/vinculada con esta
    búsqueda en `busqueda_resultados` (antes esto no ocurría en ningún
    caso: nada escribía nunca en esa tabla, así que el panel siempre
    mostraba la lista de resultados vacía)."""
    palabras = filtros.sector.palabras_clave or (PALABRAS_CONSTRUCCION_OBJETO + PALABRAS_CONSTRUCCION_NOMBRE)
    hasta = datetime.now(UTC).date()
    desde = hasta - timedelta(days=dias)

    conector = ConectorBorme(cliente_http)
    contadores = {"candidatos": 0, "descartados_por_sector": 0, "vinculado": 0, "nueva_empresa": 0, "en_revision": 0, "ya_procesado": 0, "error": 0}

    async for registro in conector.descubrir({"provincia_titulo": provincia_titulo, "desde": desde, "hasta": hasta}, max_coste_eur=0.0):
        objeto_social = registro.campos.extra.get("objeto_social")
        if not _coincide_sector(objeto_social, registro.campos.razon_social, palabras):
            contadores["descartados_por_sector"] += 1
            continue
        contadores["candidatos"] += 1
        try:
            resultado = procesar_registro(
                registro, conn, busqueda_id=busqueda_id, telefonos_compartidos=telefonos_compartidos
            )
            if busqueda_id and resultado.empresa_id:
                bd.registrar_resultado_busqueda(
                    busqueda_id, resultado.empresa_id, f"borme: {resultado.accion}", resultado.puntuacion_match, conn
                )
            conn.commit()
            contadores[resultado.accion] += 1
        except Exception:  # noqa: BLE001 — un acto que falla no debe tirar el resto del descubrimiento
            conn.rollback()
            contadores["error"] += 1

    return {**contadores, "coste_eur": 0.0, "rango": f"{desde.isoformat()} a {hasta.isoformat()}"}


# --- buscar_web ------------------------------------------------------------


def _consultas_de(parametros: dict[str, Any]) -> list[str]:
    if parametros.get("consultas"):
        return list(parametros["consultas"])
    if parametros.get("consulta"):
        return [parametros["consulta"]]
    return []


async def buscar_web(
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    cliente_llm: Any | None,
    *,
    consultas: list[str],
    max_resultados_por_consulta: int = 5,
    max_coste_eur: float,
    telefonos_compartidos: set[str] | None = None,
    busqueda_id: str | None = None,
) -> dict[str, Any]:
    """Mismo patrón que `scripts/buscar_web.py --enriquecer --guardar`, en
    bucle sobre varias consultas y con presupuesto (doc 04 §5: los
    snippets del buscador nunca son evidencia — cada URL se descarga y se
    lee de verdad con `enriquecer_desde_web` antes de guardar nada).

    `busqueda_id`: ver docstring de `descubrir_borme`, mismo enlace a
    `busqueda_resultados`."""
    contadores = {
        "consultas_ejecutadas": 0, "urls_encontradas": 0, "urls_no_legibles": 0,
        "vinculado": 0, "nueva_empresa": 0, "en_revision": 0, "ya_procesado": 0, "error_busqueda": 0, "error_procesado": 0,
    }
    coste_acumulado = 0.0

    for consulta in consultas:
        if coste_acumulado + COSTE_POR_BUSQUEDA_EUR > max_coste_eur:
            break
        resultado = await asyncio.to_thread(buscar, cliente_llm, consulta, max_resultados=max_resultados_por_consulta)
        coste_acumulado += resultado.numero_busquedas * COSTE_POR_BUSQUEDA_EUR
        contadores["consultas_ejecutadas"] += 1
        if resultado.error:
            contadores["error_busqueda"] += 1
            continue

        for r in resultado.resultados:
            contadores["urls_encontradas"] += 1
            registro = await enriquecer_desde_web(cliente_http, r.url)
            if registro is None:
                contadores["urls_no_legibles"] += 1
                continue
            try:
                resolucion = procesar_registro(
                    registro, conn, busqueda_id=busqueda_id, telefonos_compartidos=telefonos_compartidos
                )
                if busqueda_id and resolucion.empresa_id:
                    bd.registrar_resultado_busqueda(
                        busqueda_id, resolucion.empresa_id,
                        f"buscador_web: {resolucion.accion}", resolucion.puntuacion_match, conn,
                    )
                conn.commit()
                contadores[resolucion.accion] += 1
            except Exception:  # noqa: BLE001 — una URL que falla no debe tirar el resto de la búsqueda
                conn.rollback()
                contadores["error_procesado"] += 1

    return {**contadores, "coste_eur": round(coste_acumulado, 4)}


# --- preguntar_usuario / finalizar_busqueda (sin efectos secundarios) ------


def preguntar_usuario(pregunta: str, opciones: list[str] | None = None) -> dict[str, Any]:
    return {"pregunta": pregunta, "opciones": opciones or []}


MotivoFin = Literal["cobertura_alcanzada", "presupuesto_agotado", "rendimientos_decrecientes", "max_rondas", "cancelada_usuario"]


def finalizar_busqueda(motivo: MotivoFin, resumen: str) -> dict[str, Any]:
    return {"motivo": motivo, "resumen": resumen}


# --- Contexto y despacho ----------------------------------------------


@dataclass
class ContextoHerramientas:
    """Todo lo que las herramientas con efectos secundarios necesitan y que
    el LLM nunca decide ni ve directamente (conexión, cliente HTTP, cliente
    del proveedor de búsqueda, filtros confirmados de esta búsqueda)."""

    conn: psycopg.Connection
    cliente_http: httpx.AsyncClient
    filtros: FiltrosBusqueda
    cliente_llm: Any | None = None
    telefonos_compartidos: set[str] | None = None
    presupuesto_restante_eur: float = field(default=0.0)
    # Id de la fila en `busquedas` que está corriendo esta ronda — permite a
    # `descubrir_borme`/`buscar_web` enlazar cada empresa que encuentren con
    # esta búsqueda en `busqueda_resultados` (bd.registrar_resultado_busqueda).
    # `None` en tests/uso suelto: las herramientas simplemente no enlazan nada.
    busqueda_id: str | None = None


async def ejecutar_herramienta(nombre: str, argumentos: dict[str, Any], contexto: ContextoHerramientas) -> dict[str, Any]:
    """Punto de entrada único del bucle de tool use
    (`radar.agente.planificador`, siguiente entrega): recibe el nombre y
    los argumentos tal como los manda el LLM, y devuelve SIEMPRE un `dict`
    serializable a JSON (nunca lanza para un fallo esperable de la propia
    búsqueda/BORME — eso ya lo capturan las funciones de arriba; sí puede
    lanzar `ValueError` si el LLM pide una herramienta o un argumento que
    no existe, para que el planificador se lo reporte al LLM como error de
    la llamada, igual que un 400)."""
    if nombre == "consultar_bd":
        return consultar_bd(contexto.conn, contexto.filtros, incluir_muestra=argumentos.get("incluir_muestra", True))

    if nombre == "descubrir_borme":
        if "provincia_titulo" not in argumentos:
            raise ValueError("descubrir_borme requiere 'provincia_titulo'")
        return await descubrir_borme(
            contexto.conn, contexto.cliente_http, contexto.filtros,
            provincia_titulo=argumentos["provincia_titulo"], dias=argumentos.get("dias", 30),
            telefonos_compartidos=contexto.telefonos_compartidos, busqueda_id=contexto.busqueda_id,
        )

    if nombre == "buscar_web":
        consultas = argumentos.get("consultas")
        if not consultas:
            raise ValueError("buscar_web requiere 'consultas' (lista no vacía)")
        max_coste_eur = argumentos.get("max_coste_eur")
        if max_coste_eur is None:
            raise ValueError("buscar_web requiere 'max_coste_eur'")
        return await buscar_web(
            contexto.conn, contexto.cliente_http, contexto.cliente_llm,
            consultas=list(consultas), max_resultados_por_consulta=argumentos.get("max_resultados_por_consulta", 5),
            max_coste_eur=min(float(max_coste_eur), contexto.presupuesto_restante_eur),
            telefonos_compartidos=contexto.telefonos_compartidos, busqueda_id=contexto.busqueda_id,
        )

    if nombre == "preguntar_usuario":
        if "pregunta" not in argumentos:
            raise ValueError("preguntar_usuario requiere 'pregunta'")
        return preguntar_usuario(argumentos["pregunta"], argumentos.get("opciones"))

    if nombre == "finalizar_busqueda":
        if "motivo" not in argumentos:
            raise ValueError("finalizar_busqueda requiere 'motivo'")
        return finalizar_busqueda(argumentos["motivo"], argumentos.get("resumen", ""))

    raise ValueError(f"herramienta desconocida: {nombre!r}")
