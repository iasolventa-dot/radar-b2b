"""Acceso a base de datos del orquestador (doc 03b): registros_brutos,
observaciones, empresas, sedes, canales_contacto, identificadores.

Todas las funciones reciben una `conn: psycopg.Connection` ya abierta y
NO hacen commit — la transacción la controla quien llama (`procesar.py`
hace todas las escrituras de un `RegistroBruto` en una sola transacción;
ver `Cola`/`radar.resolucion.blocking` para el patrón contrario, de
conexión-por-llamada, que aquí no vale porque necesitamos atomicidad entre
varias tablas).

Los parámetros jsonb se pasan como `json.dumps(...)` + `::jsonb` en el SQL,
igual que `radar.cola.Cola` — es el patrón ya usado en este proyecto en vez
del adaptador `Jsonb` de psycopg.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

import psycopg

from radar.fuentes.base import CamposExtraidos, RegistroBruto

EstadoRegistroBruto = Literal["pendiente", "vinculado", "nueva_empresa", "en_revision", "descartado", "error"]


@dataclass
class FuenteInfo:
    id: int
    codigo: str
    tipo: str
    fiabilidad_base: float
    permite_almacenar: bool
    grupo_independencia: str | None
    activa: bool


def obtener_fuente(codigo: str, conn: psycopg.Connection) -> FuenteInfo:
    with conn.cursor() as cur:
        cur.execute(
            "select id, codigo, tipo, fiabilidad_base, permite_almacenar, grupo_independencia, activa "
            "from fuentes where codigo = %s",
            (codigo,),
        )
        fila = cur.fetchone()
    if fila is None:
        raise ValueError(f"Fuente '{codigo}' no existe en la tabla `fuentes` (doc 03b §12)")
    fuente = FuenteInfo(id=fila[0], codigo=fila[1], tipo=fila[2], fiabilidad_base=float(fila[3]),
                         permite_almacenar=fila[4], grupo_independencia=fila[5], activa=fila[6])
    if not fuente.activa:
        raise ValueError(f"Fuente '{codigo}' está desactivada (fuentes.activa = false)")
    return fuente


@dataclass
class RegistroBrutoDB:
    id: str
    estado: EstadoRegistroBruto
    empresa_id: str | None
    puntuacion_match: float | None


def insertar_registro_bruto(
    registro: RegistroBruto, fuente: FuenteInfo, conn: psycopg.Connection, busqueda_id: str | None = None
) -> RegistroBrutoDB:
    """Inserta en `registros_brutos`. Si ya existe un registro con el mismo
    `(fuente_id, hash_contenido)` (mismo conector, mismo contenido exacto —
    p. ej. una re-ejecución del mismo día de BORME), NO lo duplica: devuelve
    la fila existente tal cual está (con su `estado`/`empresa_id` actuales),
    para que `procesar.py` pueda saltarse el resto del pipeline si ya se
    procesó (idempotencia, índice `ux_brutos_hash`, doc 03b §6).
    """
    payload = registro.payload if fuente.permite_almacenar else {}
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into registros_brutos
                (busqueda_id, fuente_id, id_externo, url, payload, campos, hash_contenido, capturado_en)
            values (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
            on conflict (fuente_id, hash_contenido) where hash_contenido is not null
            do update set capturado_en = registros_brutos.capturado_en
            returning id, estado, empresa_id, puntuacion_match
            """,
            (
                busqueda_id,
                fuente.id,
                registro.id_externo,
                registro.url,
                json.dumps(payload, default=str),
                json.dumps(asdict(registro.campos), default=str),
                registro.hash_contenido,
                registro.capturado_en,
            ),
        )
        fila = cur.fetchone()
    assert fila is not None  # "returning" de un insert siempre devuelve una fila
    return RegistroBrutoDB(
        id=str(fila[0]), estado=fila[1], empresa_id=str(fila[2]) if fila[2] else None,
        puntuacion_match=float(fila[3]) if fila[3] is not None else None,
    )


def actualizar_registro_bruto(
    registro_bruto_id: str,
    estado: EstadoRegistroBruto,
    empresa_id: str | None,
    puntuacion_match: float | None,
    conn: psycopg.Connection,
    error: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "update registros_brutos set estado = %s, empresa_id = %s, puntuacion_match = %s, error = %s "
            "where id = %s",
            (estado, empresa_id, puntuacion_match, error, registro_bruto_id),
        )


def buscar_candidato_por_nif(nif: str, conn: psycopg.Connection) -> str | None:
    """Regla dura 1-2 (doc 05 §2.2): si ya existe una empresa con este NIF
    exacto, es el candidato más fuerte posible — atajo a la búsqueda
    trigram de `radar.resolucion.blocking.buscar_candidatos` cuando ya
    tenemos NIF."""
    with conn.cursor() as cur:
        cur.execute("select id from empresas where nif = %s and fusionada_en is null", (nif,))
        fila = cur.fetchone()
    return str(fila[0]) if fila else None


_SQL_CANDIDATO_NORMALIZADO = """
select
    e.nif, e.nif_valido, e.razon_social_norm, e.nombre_comercial_norm, e.forma_juridica, e.dominio_web,
    coalesce((
        select array_agg(distinct c.valor_norm) from canales_contacto c
        where c.empresa_id = e.id and c.tipo = 'telefono' and c.estado <> 'invalido'
          and c.valor_norm !~ '^\\+34(90|80)'
    ), '{}') as telefonos,
    coalesce((
        select array_agg(distinct c.valor_norm) from canales_contacto c
        where c.empresa_id = e.id and c.tipo = 'email' and c.estado <> 'invalido'
    ), '{}') as emails,
    s.codigo_postal, s.provincia,
    extensions.st_y(s.geom::extensions.geometry) as lat,
    extensions.st_x(s.geom::extensions.geometry) as lon,
    (select i.valor from identificadores i where i.empresa_id = e.id and i.tipo = 'google_place_id' limit 1) as place_id
from empresas e
left join lateral (
    select * from sedes sd
    where sd.empresa_id = e.id and sd.activa
    order by (sd.tipo = 'sede_operativa') desc, (sd.tipo = 'domicilio_social') desc, sd.confianza desc nulls last
    limit 1
) s on true
where e.id = %s
"""


def cargar_registro_empresa_normalizado(empresa_id: str, conn: psycopg.Connection) -> dict:
    """Carga una empresa existente con la misma forma que
    `radar.normalizacion.registro.normalizar_registro` (para poder pasarla
    directamente a `radar.resolucion.scoring.comparar`).

    Aproximación conocida: `razon_social_norm`/`nombre_comercial_norm` los
    calcula el trigger SQL `normalizar_razon_social` (doc 03b §2), que solo
    quita la forma jurídica — a diferencia de
    `radar.normalizacion.nombre.normalizar_nombre`, no quita además las
    palabras vacías españolas ("de", "la"…). La similitud de nombre puede
    salir un pelín distinta a la de dos registros normalizados 100% en
    Python. No afecta a los casos con NIF o dominio en común (reglas
    duras / +0,45 mínimo 0,60), que son los que más importan.
    """
    with conn.cursor() as cur:
        cur.execute(_SQL_CANDIDATO_NORMALIZADO, (empresa_id,))
        fila = cur.fetchone()
    if fila is None:
        raise ValueError(f"Empresa {empresa_id} no existe")
    (nif, nif_valido, nombre_norm, comercial_norm, forma_juridica, dominio,
     telefonos, emails, cp, provincia, lat, lon, place_id) = fila
    return {
        "empresa_id": str(empresa_id),
        "nif": nif,
        "nif_valido": nif_valido,
        "nombre_norm": nombre_norm or "",
        "comercial_norm": comercial_norm or "",
        "forma_juridica": forma_juridica,
        "dominio": dominio,
        "telefonos": list(telefonos or []),
        "telefonos_especiales": [],  # ya excluidos por el filtro `!~ '^\+34(90|80)'` de arriba
        "emails": list(emails or []),
        "cp": cp,
        "provincia": provincia,
        "cod_provincia": (cp or "")[:2] or None,
        "lat": lat,
        "lon": lon,
        "place_id": place_id,
    }


def crear_empresa(campos_norm: dict, campos_originales: CamposExtraidos, conn: psycopg.Connection) -> str:
    """Crea la fila mínima en `empresas`. Deliberadamente NO intenta ya
    aquí calcular confianza ni resolver conflictos entre fuentes: eso lo
    hace `actualizar_empresa` justo después, a partir de las observaciones
    (incluida la que se acaba de insertar) — así el mismo camino sirve
    tanto para una empresa recién creada como para una ya existente que
    recibe una observación más.
    """
    nif = campos_norm["nif"] if campos_norm.get("nif_valido") else None
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into empresas (nif, nif_valido, razon_social, nombre_comercial, forma_juridica, es_persona_fisica)
            values (%s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                nif,
                campos_norm.get("nif_valido"),
                campos_originales.razon_social,
                campos_originales.nombre_comercial,
                campos_norm.get("forma_juridica"),
                bool(campos_norm.get("persona_fisica")),
            ),
        )
        fila = cur.fetchone()
    assert fila is not None
    return str(fila[0])


def insertar_observaciones(
    empresa_id: str,
    registro_bruto_id: str,
    fuente: FuenteInfo,
    campos_norm: dict,
    campos_originales: CamposExtraidos,
    registro_url: str | None,
    observado_en: datetime,
    conn: psycopg.Connection,
) -> None:
    """Una fila por cada dato que aporta este `RegistroBruto` (capa plata,
    doc 03b §7). Confianza inicial = `fuente.fiabilidad_base` para todos
    los campos — el doc 05 §3 permite afinarla por campo más adelante
    ("la web propia es excelente para teléfono pero regular para
    empleados"), no implementado todavía.
    """
    filas: list[tuple] = []

    def fila(campo: str, valor_original: str | None, valor_norm: str | None) -> None:
        if valor_norm:
            filas.append((empresa_id, registro_bruto_id, fuente.id, campo, valor_original, valor_norm,
                          registro_url, observado_en, fuente.fiabilidad_base))

    if campos_norm.get("nif_valido"):
        fila("nif", campos_originales.nif, campos_norm["nif"])
    if campos_originales.razon_social:
        fila("razon_social", campos_originales.razon_social, campos_norm["nombre_norm"])
    if campos_originales.nombre_comercial:
        fila("nombre_comercial", campos_originales.nombre_comercial, campos_norm["comercial_norm"])
    for tel in campos_norm.get("telefonos") or []:
        fila("telefono", tel, tel)
    for email in campos_norm.get("emails") or []:
        fila("email", email, email)
    if campos_norm.get("dominio"):
        fila("web", campos_originales.web, campos_norm["dominio"])

    if not filas:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into observaciones
                (empresa_id, registro_bruto_id, fuente_id, campo, valor_original, valor_norm,
                 url_evidencia, observado_en, confianza_fuente)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            filas,
        )


def cargar_observaciones_vigentes(empresa_id: str, campo: str, conn: psycopg.Connection) -> list[dict]:
    """Observaciones vigentes de un campo, con la forma que espera
    `radar.verificacion.confianza.consolidar_campo` (más `valor_original`,
    que esa función ignora pero `logica.texto_representativo` sí usa)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select o.valor_original, o.valor_norm, o.confianza_fuente, f.grupo_independencia,
                   o.observado_en, (f.tipo = 'registro_oficial') as es_registro_oficial
            from observaciones o
            join fuentes f on f.id = o.fuente_id
            where o.empresa_id = %s and o.campo = %s and o.vigente
            """,
            (empresa_id, campo),
        )
        filas = cur.fetchall()
    return [
        {
            "valor_original": f[0],
            "valor_norm": f[1],
            "confianza_fuente": float(f[2]) if f[2] is not None else 0.0,
            "grupo_independencia": f[3],
            "observado_en": f[4],
            "es_registro_oficial": bool(f[5]),
        }
        for f in filas
    ]


def cargar_empresa_actual(empresa_id: str, conn: psycopg.Connection) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "select estado, estado_confianza, forma_juridica, razon_social, nombre_comercial, dominio_web "
            "from empresas where id = %s",
            (empresa_id,),
        )
        fila = cur.fetchone()
        cur.execute(
            "select confianza from sedes where empresa_id = %s and activa order by confianza desc nulls last limit 1",
            (empresa_id,),
        )
        sede = cur.fetchone()
    assert fila is not None  # la empresa ya existe (la acabamos de crear o venía de un candidato cargado)
    return {
        "estado": fila[0],
        "estado_confianza": float(fila[1]) if fila[1] is not None else None,
        "forma_juridica": fila[2],
        "razon_social": fila[3],
        "nombre_comercial": fila[4],
        "dominio_web": fila[5],
        "sede_confianza": float(sede[0]) if sede and sede[0] is not None else 0.0,
    }


def actualizar_empresa(
    empresa_id: str,
    *,
    nif: str | None,
    nif_valido: bool | None,
    razon_social: str | None,
    nombre_comercial: str | None,
    forma_juridica: str | None,
    dominio_web: str | None,
    estado: str | None,
    estado_confianza: float | None,
    estado_actualizado: bool,
    confianza_global: float,
    conn: psycopg.Connection,
) -> None:
    with conn.cursor() as cur:
        if estado_actualizado:
            cur.execute(
                """
                update empresas set
                    nif = coalesce(%s, nif), nif_valido = coalesce(%s, nif_valido),
                    razon_social = coalesce(%s, razon_social),
                    nombre_comercial = coalesce(%s, nombre_comercial),
                    forma_juridica = coalesce(%s, forma_juridica),
                    dominio_web = coalesce(%s, dominio_web),
                    estado = %s, estado_confianza = %s, estado_verificado_en = now(),
                    confianza_global = %s, ultima_verificacion = now()
                where id = %s
                """,
                (nif, nif_valido, razon_social, nombre_comercial, forma_juridica, dominio_web,
                 estado, estado_confianza, confianza_global, empresa_id),
            )
        else:
            cur.execute(
                """
                update empresas set
                    nif = coalesce(%s, nif), nif_valido = coalesce(%s, nif_valido),
                    razon_social = coalesce(%s, razon_social),
                    nombre_comercial = coalesce(%s, nombre_comercial),
                    forma_juridica = coalesce(%s, forma_juridica),
                    dominio_web = coalesce(%s, dominio_web),
                    confianza_global = %s, ultima_verificacion = now()
                where id = %s
                """,
                (nif, nif_valido, razon_social, nombre_comercial, forma_juridica, dominio_web,
                 confianza_global, empresa_id),
            )


def upsert_sede(
    empresa_id: str,
    campos: CamposExtraidos,
    campos_norm: dict,
    fuente: FuenteInfo,
    conn: psycopg.Connection,
    tipo: str = "domicilio_social",
) -> None:
    """Simplificación deliberada (fuera de lo que detalla doc 05, que solo
    fija la semivida de la sede operativa, no un algoritmo de fusión entre
    fuentes): una única sede por `tipo` y empresa, "gana la última
    observación" — sin combinar varias fuentes como si hace
    `radar.verificacion.confianza` con NIF/nombre/teléfono/email. No borra
    sedes anteriores (principio de no sobrescribir evidencia): si ya existe
    una fila `activa` de este `tipo`, la actualiza; si no, crea una nueva.
    A mejorar cuando haya más de una fuente de direcciones en juego.
    """
    cp = campos_norm.get("cp")
    lat, lon = campos.lat, campos.lon
    with conn.cursor() as cur:
        cur.execute(
            "select id from sedes where empresa_id = %s and tipo = %s and activa limit 1",
            (empresa_id, tipo),
        )
        existente = cur.fetchone()
        geom_sql = (
            "extensions.st_setsrid(extensions.st_makepoint(%s, %s), 4326)::extensions.geography"
            if lat is not None and lon is not None
            else "null"
        )
        parametros_geom = (lon, lat) if lat is not None and lon is not None else ()
        if existente:
            cur.execute(
                f"""
                update sedes set
                    direccion_original = coalesce(%s, direccion_original),
                    codigo_postal = coalesce(%s, codigo_postal),
                    municipio_nombre = coalesce(%s, municipio_nombre),
                    provincia = coalesce(%s, provincia),
                    geom = coalesce({geom_sql}, geom),
                    confianza = %s, ultima_verificacion = now()
                where id = %s
                """,
                (campos.domicilio, cp, campos.municipio, campos.provincia, *parametros_geom,
                 fuente.fiabilidad_base, existente[0]),
            )
        else:
            cur.execute(
                f"""
                insert into sedes
                    (empresa_id, tipo, direccion_original, codigo_postal, municipio_nombre, provincia,
                     geom, confianza, ultima_verificacion)
                values (%s, %s, %s, %s, %s, %s, {geom_sql}, %s, now())
                """,
                (empresa_id, tipo, campos.domicilio, cp, campos.municipio, campos.provincia,
                 *parametros_geom, fuente.fiabilidad_base),
            )


def upsert_canal_contacto(
    empresa_id: str, tipo: Literal["telefono", "email"], valor: str, confianza: float, conn: psycopg.Connection
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into canales_contacto (empresa_id, tipo, valor, valor_norm, confianza, ultima_verificacion)
            values (%s, %s, %s, %s, %s, now())
            on conflict (empresa_id, tipo, valor_norm)
            do update set confianza = excluded.confianza, ultima_verificacion = now()
            """,
            (empresa_id, tipo, valor, valor, confianza),
        )


def upsert_identificadores(
    empresa_id: str, campos_norm: dict, campos: CamposExtraidos, fuente: FuenteInfo, conn: psycopg.Connection
) -> None:
    """`identificadores.valor` es único por `tipo` en TODA la base — si ya
    perteneciera a otra empresa, esto lo ignora silenciosamente
    (`on conflict do nothing`). Para NIF y `place_id` no debería pasar: el
    NIF ya se buscó exacto en `bd.buscar_candidato_por_nif` antes de
    decidir si crear o vincular, así que si esta empresa lo tiene, es
    porque no existía en otra — misma lógica aplica de facto al resto,
    aunque no se comprueba explícitamente."""
    filas: list[tuple] = []
    if campos_norm.get("nif_valido"):
        filas.append((empresa_id, "nif", campos_norm["nif"], fuente.id))
    if campos_norm.get("dominio"):
        filas.append((empresa_id, "dominio", campos_norm["dominio"], fuente.id))
    if campos_norm.get("place_id"):
        filas.append((empresa_id, "google_place_id", campos_norm["place_id"], fuente.id))
    hoja = campos.extra.get("hoja_registral") if campos.extra else None
    if hoja:
        filas.append((empresa_id, "borme_hoja", hoja, fuente.id))
    if not filas:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "insert into identificadores (empresa_id, tipo, valor, fuente_id) values (%s, %s, %s, %s) "
            "on conflict (tipo, valor) do nothing",
            filas,
        )


def insertar_candidato_duplicado(
    empresa_nueva_id: str, empresa_candidata_id: str, resultado_comparacion: dict, conn: psycopg.Connection
) -> None:
    """doc 03b: `chk_orden` exige `empresa_a < empresa_b` (UUIDs
    comparables como texto) — hay que ordenar antes de insertar."""
    a, b = sorted([empresa_nueva_id, empresa_candidata_id])
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into candidatos_duplicado (empresa_a, empresa_b, puntuacion, senales)
            values (%s, %s, %s, %s::jsonb)
            on conflict (empresa_a, empresa_b) do nothing
            """,
            (a, b, resultado_comparacion.get("puntuacion"), json.dumps(resultado_comparacion, default=str)),
        )
