"""Acceso a base de datos del orquestador (doc 03b): registros_brutos,
observaciones, empresas, sedes, canales_contacto, identificadores,
personas, cargos.

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
from radar.normalizacion.nombre import normalizar_texto

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


def normalizar_codigos_cnae(codigos: list[str], version_destino: str, conn: psycopg.Connection) -> list[str]:
    """Traduce códigos CNAE de cualquier versión a `version_destino` con
    `cnae_correspondencias` (INE) cuando el código no existe ya en esa
    versión.

    `radar.agente.interpretacion` no sabe de versiones de la CNAE -- el
    LLM suele dar los códigos CNAE-2009 con los que está más entrenado,
    aunque el catálogo real que usa el resto del pipeline (`empresas.cnae_version`,
    `cnae_coincide`) sea CNAE-2025 por defecto. Confirmado en vivo
    (2026-09-18): "empresas de informática en Sevilla" interpretó
    `codigos_cnae=["6201","6202","6203","6209"]` (división 62 en
    CNAE-2009) -- códigos que NO EXISTEN en CNAE-2025, donde esa misma
    división se renumeró a 6210/6220/6290 -- así que `consultar_bd` no
    encontraba nada aunque hubiera empresas de informática reales ya
    clasificadas con el código correcto (`radar.clasificacion`).

    Nunca inventa: un código que no exista en ninguna versión ni tenga
    correspondencia conocida se descarta en silencio -- mejor buscar con
    un código de menos que con uno que no existe en el catálogo."""
    if not codigos:
        return []
    resultado: set[str] = set()
    with conn.cursor() as cur:
        for codigo in codigos:
            cur.execute("select 1 from cnae where codigo = %s and version = %s", (codigo, version_destino))
            if cur.fetchone():
                resultado.add(codigo)
                continue
            cur.execute(
                "select codigo_destino from cnae_correspondencias where codigo_origen = %s and version_destino = %s",
                (codigo, version_destino),
            )
            resultado.update(fila[0] for fila in cur.fetchall())
    return sorted(resultado)


def buscar_municipio_ine(nombre: str | None, provincia: str | None, conn: psycopg.Connection) -> str | None:
    """Código INE del municipio (función SQL `buscar_municipio_ine`,
    migración 202609140001) -- fuente de verdad DETERMINISTA a partir del
    nombre tal como lo escribe el BORME, no de lo que devuelva un
    geocodificador externo. Se usa para VALIDAR el resultado de
    `radar.fuentes.cartociudad.geocodificar()`: confirmado en vivo
    (2026-09-18) que CartoCiudad a veces resuelve una calle a un municipio
    homónimo de OTRA provincia con coordenadas totalmente equivocadas (p.
    ej. "C/ Molino 11-B, Sevilla" -> un punto cerca de Madrid) sin que la
    API lo señale de ninguna forma -- el `type` sigue siendo "portal", como
    si fuera un acierto. Si el `municipio_ine` que devuelve CartoCiudad no
    coincide con este, el resultado se descarta (mejor sin coordenadas que
    con unas falsas)."""
    if not nombre or not provincia:
        return None
    with conn.cursor() as cur:
        cur.execute("select buscar_municipio_ine(%s, %s)", (nombre, provincia))
        fila = cur.fetchone()
    return fila[0] if fila and fila[0] else None


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


def buscar_candidatos_por_contacto(
    dominio: str | None,
    telefonos: list[str],
    emails: list[str],
    place_id: str | None,
    telefonos_excluidos: set[str],
    conn: psycopg.Connection,
    hoja_registral: str | None = None,
) -> list[str]:
    """Candidatos por señal de contacto EXACTA (mismo dominio propio, mismo
    teléfono, mismo email o mismo place_id), sin mirar el nombre.

    Hasta 2026-09-21 el bloqueo era solo por similitud de nombre
    (`radar.resolucion.blocking.buscar_candidatos`), así que un registro con
    el mismo dominio o teléfono que una empresa ya guardada pero con nombre
    distinto (caso típico entre fuentes: nombre comercial "Meta360" en
    OpenStreetMap vs razón social "TECNOLOGIAS Y SERVICIOS X SL" en el
    BORME) nunca llegaba a compararse -- las reglas de `scoring.comparar`
    para dominio/teléfono (dominio garantiza al menos revisión) eran
    inalcanzables en ese caso. Esto solo AMPLÍA quién se compara; la
    decisión sigue siendo de `comparar`/`decidir_resolucion`, nunca se
    vincula solo por compartir un dato.

    `telefonos_excluidos`: teléfonos compartidos (gestorías/centralitas) y
    especiales -- no son señal de identidad (doc 05 §2.3).
    """
    ids: list[str] = []

    def anadir(filas: list[tuple]) -> None:
        for (eid,) in filas:
            if str(eid) not in ids:
                ids.append(str(eid))

    with conn.cursor() as cur:
        if dominio:
            cur.execute(
                "select id from empresas where fusionada_en is null and dominio_web = %s "
                "union select empresa_id from identificadores where tipo = 'dominio' and valor = %s",
                (dominio, dominio),
            )
            anadir(cur.fetchall())
        tels = [t for t in telefonos if t not in telefonos_excluidos]
        if tels:
            cur.execute(
                "select distinct c.empresa_id from canales_contacto c "
                "join empresas e on e.id = c.empresa_id and e.fusionada_en is null "
                "where c.tipo = 'telefono' and c.estado <> 'invalido' and c.valor_norm = any(%s)",
                (tels,),
            )
            anadir(cur.fetchall())
        if emails:
            cur.execute(
                "select distinct c.empresa_id from canales_contacto c "
                "join empresas e on e.id = c.empresa_id and e.fusionada_en is null "
                "where c.tipo = 'email' and c.estado <> 'invalido' and c.valor_norm = any(%s)",
                (emails,),
            )
            anadir(cur.fetchall())
        if hoja_registral:
            cur.execute(
                "select i.empresa_id from identificadores i "
                "join empresas e on e.id = i.empresa_id and e.fusionada_en is null "
                "where i.tipo = 'borme_hoja' and i.valor = %s",
                (hoja_registral,),
            )
            anadir(cur.fetchall())
        if place_id:
            cur.execute(
                "select i.empresa_id from identificadores i "
                "join empresas e on e.id = i.empresa_id and e.fusionada_en is null "
                "where i.tipo = 'google_place_id' and i.valor = %s",
                (place_id,),
            )
            anadir(cur.fetchall())
    return ids


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
    (select i.valor from identificadores i where i.empresa_id = e.id and i.tipo = 'google_place_id' limit 1) as place_id,
    (select i.valor from identificadores i where i.empresa_id = e.id and i.tipo = 'borme_hoja' limit 1) as hoja_registral
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
     telefonos, emails, cp, provincia, lat, lon, place_id, hoja_registral) = fila
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
        "hoja_registral": hoja_registral,
    }


def crear_empresa(campos_norm: dict, campos_originales: CamposExtraidos, conn: psycopg.Connection) -> str:
    """Crea la fila mínima en `empresas`. Deliberadamente NO intenta ya
    aquí calcular confianza ni resolver conflictos entre fuentes: eso lo
    hace `actualizar_empresa` justo después, a partir de las observaciones
    (incluida la que se acaba de insertar) — así el mismo camino sirve
    tanto para una empresa recién creada como para una ya existente que
    recibe una observación más.

    `cnae_principal`/`cnae_version` solo se escriben si el conector dio
    AMBOS (doc 08 D-18: la clave de `cnae` es compuesta). Hoy ningún
    conector conectado los da — BORME solo publica objeto social en texto
    libre, nunca un código CNAE — así que en la práctica esto queda a null
    hasta que exista un conector que sí lo aporte (PLACSP, proveedor
    comercial) o un paso de clasificación de objeto_social → CNAE (sin
    construir todavía). Si el par no existe en la tabla `cnae`, la FK
    compuesta `empresas_cnae_fkey` rechaza el insert — deliberado: mejor
    que falle alto y claro que guardar un código que no verifica.

    `empresas.cnae_version` es `not null default 'CNAE-2025'` (migración
    202609140001): nunca se puede pasar `None` ahí, aunque `cnae_principal`
    sí quede a null (la FK compuesta usa MATCH SIMPLE — se salta la
    comprobación si `cnae_principal` es null, sea lo que sea `cnae_version`).

    `objeto_social` se escribe aquí (antes nunca llegaba a `empresas`,
    solo a `registros_brutos.campos` y, desde esta sesión, a
    `observaciones`) — es lo que permite que `sector.palabras_clave`
    filtre algo real en `consultar_bd`. Limitación conocida: solo se fija
    al CREAR la empresa; si una empresa ya existente recibe más adelante
    una observación con objeto social (p. ej. la enriquece la web tras
    haberla creado el BORME), ese texto no se propaga aquí — haría falta
    sumarlo a `actualizar_empresa`/`_consolidar_y_actualizar_empresa`
    (`radar.orquestador.procesar`), que hoy no reciben los campos crudos.
    """
    nif = campos_norm["nif"] if campos_norm.get("nif_valido") else None
    hay_cnae = bool(campos_originales.cnae and campos_originales.cnae_version)
    cnae = campos_originales.cnae if hay_cnae else None
    cnae_version = campos_originales.cnae_version if hay_cnae else "CNAE-2025"
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into empresas
                (nif, nif_valido, razon_social, nombre_comercial, forma_juridica, es_persona_fisica,
                 objeto_social, cnae_principal, cnae_version)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                nif,
                campos_norm.get("nif_valido"),
                campos_originales.razon_social,
                campos_originales.nombre_comercial,
                campos_norm.get("forma_juridica"),
                bool(campos_norm.get("persona_fisica")),
                campos_originales.objeto_social,
                cnae,
                cnae_version,
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

    Hasta esta versión solo se registraban aquí `nif`, `razon_social`,
    `nombre_comercial`, `telefono`, `email` y `web` — los únicos campos que
    `_consolidar_y_actualizar_empresa` (`radar.orquestador.procesar`) lee
    de vuelta con `cargar_observaciones_vigentes`. El resto de lo que un
    `RegistroBruto` aporta (dirección, municipio, objeto social, hoja
    registral…) se escribía directamente en `sedes`/`identificadores` sin
    dejar ninguna fila aquí, así que no había forma de responder "¿de dónde
    sale este dato?" salvo para la razón social — de las 276 empresas del
    piloto, las 276 filas de `observaciones` eran ese único campo (doc 08).
    Se añaden ahora como evidencia adicional, en paralelo, SIN entrar en la
    consolidación de `procesar.py` (que sigue leyendo solo los 6 campos de
    siempre) — es puramente trazabilidad para poder mostrar la fuente de
    cada dato, no cambia qué gana cuando hay conflicto entre fuentes.
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

    # --- Trazabilidad ampliada (antes se perdían sin dejar evidencia) ---
    if campos_originales.domicilio:
        fila("direccion", campos_originales.domicilio, campos_originales.domicilio)
    if campos_originales.municipio:
        fila("municipio", campos_originales.municipio, campos_originales.municipio)
    if campos_originales.provincia:
        fila("provincia", campos_originales.provincia, campos_originales.provincia)
    if campos_norm.get("cp"):
        fila("codigo_postal", campos_originales.codigo_postal, campos_norm["cp"])
    if campos_norm.get("forma_juridica"):
        fila("forma_juridica", campos_originales.forma_juridica, campos_norm["forma_juridica"])
    if campos_originales.estado:
        fila("estado_declarado", campos_originales.estado, campos_originales.estado)
    if campos_originales.empleados:
        fila("empleados", campos_originales.empleados, campos_originales.empleados)
    if campos_originales.cnae and campos_originales.cnae_version:
        fila("cnae", campos_originales.cnae, campos_originales.cnae)
    objeto_social = campos_originales.objeto_social
    if objeto_social:
        fila("objeto_social", objeto_social, objeto_social)
    hoja_registral = (campos_originales.extra or {}).get("hoja_registral")
    if hoja_registral:
        fila("hoja_registral", hoja_registral, hoja_registral)

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


def registrar_evento(
    empresa_id: str, tipo: str, detalle: dict, fuente_id: int | None, conn: psycopg.Connection
) -> None:
    """`eventos_empresa` (doc 03b) existía desde el primer commit -- con
    'cambio_estado', 'cambio_domicilio', 'telefono_invalido', 'web_caida'
    y 'borme_acto' como ejemplos de `tipo` en el propio comentario del
    esquema -- pero nada escribía en ella nunca. Esta sesión conecta los
    dos primeros (`_consolidar_y_actualizar_empresa`, `upsert_sede`) y
    'borme_acto' (`procesar_registro`), porque son los únicos que ya
    tenían detección real en el código; 'telefono_invalido'/'web_caida'
    siguen sin conectar -- no existe ningún paso que vuelva a comprobar
    si un teléfono o una web siguen vivos, así que no hay nada que
    detectar todavía (haría falta una re-verificación activa, no solo
    dejar constancia de un hecho que el resto del código ya sabe)."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into eventos_empresa (empresa_id, tipo, detalle, fuente_id) values (%s, %s, %s::jsonb, %s)",
            (empresa_id, tipo, json.dumps(detalle, default=str), fuente_id),
        )


def upsert_sede(
    empresa_id: str,
    campos: CamposExtraidos,
    campos_norm: dict,
    fuente: FuenteInfo,
    conn: psycopg.Connection,
    tipo: str = "domicilio_social",
    *,
    geocodificador: str | None = None,
    precision_geo: str | None = None,
    municipio_ine: str | None = None,
) -> None:
    """Simplificación deliberada (fuera de lo que detalla doc 05, que solo
    fija la semivida de la sede operativa, no un algoritmo de fusión entre
    fuentes): una única sede por `tipo` y empresa, "gana la última
    observación" — sin combinar varias fuentes como si hace
    `radar.verificacion.confianza` con NIF/nombre/teléfono/email. No borra
    sedes anteriores (principio de no sobrescribir evidencia): si ya existe
    una fila `activa` de este `tipo`, la actualiza; si no, crea una nueva.
    A mejorar cuando haya más de una fuente de direcciones en juego.

    Si la dirección nueva difiere de la que había, se deja constancia en
    `eventos_empresa` (tipo `cambio_domicilio`) -- el propio "gana la
    última observación" ya se encarga de decidir qué dirección queda,
    esto solo registra que hubo un cambio, no cambia ese criterio.

    `geocodificador`/`precision_geo`/`municipio_ine` (2026-09-18): hasta
    ahora `radar.orquestador.procesar` llamaba a `geocodificar()`
    (CartoCiudad) y solo copiaba `lat`/`lon` a `campos` -- el resto de lo
    que devuelve `ResultadoGeocodificacion` (`tipo`: "portal"/"callejero",
    y el `municipio_ine` real del IGN) se descartaba, así que esas dos
    columnas de `sedes` estaban siempre a NULL aunque hubiera geocodificado
    con éxito. Quien llama decide si los pasa; por defecto None (no
    sobreescribe nada, mismo patrón `coalesce` que el resto de columnas).
    """
    cp = campos_norm.get("cp")
    lat, lon = campos.lat, campos.lon
    with conn.cursor() as cur:
        cur.execute(
            "select id, direccion_original from sedes where empresa_id = %s and tipo = %s and activa limit 1",
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
            direccion_anterior = existente[1]
            cur.execute(
                f"""
                update sedes set
                    direccion_original = coalesce(%s, direccion_original),
                    codigo_postal = coalesce(%s, codigo_postal),
                    municipio_nombre = coalesce(%s, municipio_nombre),
                    municipio_ine = coalesce(%s, municipio_ine),
                    provincia = coalesce(%s, provincia),
                    geom = coalesce({geom_sql}, geom),
                    geocodificador = coalesce(%s, geocodificador),
                    precision_geo = coalesce(%s, precision_geo),
                    confianza = %s, ultima_verificacion = now()
                where id = %s
                """,
                (campos.domicilio, cp, campos.municipio, municipio_ine, campos.provincia, *parametros_geom,
                 geocodificador, precision_geo, fuente.fiabilidad_base, existente[0]),
            )
            if campos.domicilio and direccion_anterior and campos.domicilio != direccion_anterior:
                registrar_evento(
                    empresa_id, "cambio_domicilio",
                    {"tipo_sede": tipo, "antes": direccion_anterior, "despues": campos.domicilio},
                    fuente.id, conn,
                )
        else:
            cur.execute(
                f"""
                insert into sedes
                    (empresa_id, tipo, direccion_original, codigo_postal, municipio_nombre, municipio_ine, provincia,
                     geom, geocodificador, precision_geo, confianza, ultima_verificacion)
                values (%s, %s, %s, %s, %s, %s, %s, {geom_sql}, %s, %s, %s, now())
                """,
                (empresa_id, tipo, campos.domicilio, cp, campos.municipio, municipio_ine, campos.provincia,
                 *parametros_geom, geocodificador, precision_geo, fuente.fiabilidad_base),
            )


def upsert_canal_contacto(
    empresa_id: str,
    tipo: Literal["telefono", "email"],
    valor: str,
    confianza: float,
    conn: psycopg.Connection,
    *,
    es_generico: bool | None = None,
) -> None:
    """`es_generico` (doc 03b §4: "info@, centralita... vs. personal") es
    una columna del esquema desde el principio que nunca se escribía —
    `requisitos.email_generico` (interpretación del agente) se capturaba
    pero no tenía nada que comprobar. `radar.normalizacion.dominio.normalizar_email`
    ya lo calcula por email; quien llama (`procesar.py`) se lo pasa aquí."""
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into canales_contacto (empresa_id, tipo, valor, valor_norm, confianza, es_generico, ultima_verificacion)
            values (%s, %s, %s, %s, %s, %s, now())
            on conflict (empresa_id, tipo, valor_norm)
            do update set confianza = excluded.confianza, es_generico = excluded.es_generico, ultima_verificacion = now()
            """,
            (empresa_id, tipo, valor, valor, confianza, es_generico),
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


def registrar_place_id(empresa_id: str, place_id: str, fuente_id: int, conn: psycopg.Connection) -> bool:
    """Guarda SOLO el `place_id` de Google (lo único que sus términos permiten
    almacenar indefinidamente, `fuentes.campos_almacenables`). `True` si se
    insertó, `False` si ese place_id ya estaba (de esta u otra empresa)."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into identificadores (empresa_id, tipo, valor, fuente_id) values (%s, 'google_place_id', %s, %s) "
            "on conflict (tipo, valor) do nothing",
            (empresa_id, place_id, fuente_id),
        )
        return cur.rowcount > 0


def registrar_uso_places(operacion: str, peticiones: int, coste_eur: float, detalle: dict, conn: psycopg.Connection) -> None:
    import json

    with conn.cursor() as cur:
        cur.execute(
            "insert into uso_google_places (operacion, peticiones, coste_eur, detalle) values (%s, %s, %s, %s::jsonb)",
            (operacion, peticiones, coste_eur, json.dumps(detalle)),
        )


def registrar_uso_apify(
    actor: str, run_id: str | None, estado: str | None, coste_usd: float, detalle: dict, conn: psycopg.Connection
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "insert into uso_apify (actor, run_id, estado, coste_usd, detalle) values (%s, %s, %s, %s, %s::jsonb)",
            (actor, run_id, estado, coste_usd, json.dumps(detalle)),
        )


def upsert_persona(nombre: str, conn: psycopg.Connection) -> str:
    """Busca una persona por `nombre_norm` exacto; si no existe, la crea
    (migración 202609141600). Deduplicación deliberadamente simple: sin
    NIF (el BORME casi nunca lo da de personas físicas), no hay una clave
    dura como la que sí tiene `buscar_candidato_por_nif` para empresas —
    dos personas reales con el mismo nombre normalizado se tratan como la
    misma fila. No inventa ningún dato: solo puede sub-separar identidades
    homónimas, y queda documentado como limitación conocida, no oculta."""
    nombre = nombre.strip()
    nombre_norm = normalizar_texto(nombre)
    with conn.cursor() as cur:
        cur.execute("select id from personas where nombre_norm = %s limit 1", (nombre_norm,))
        fila = cur.fetchone()
        if fila:
            return str(fila[0])
        cur.execute(
            "insert into personas (nombre, nombre_norm) values (%s, %s) returning id",
            (nombre, nombre_norm),
        )
        fila = cur.fetchone()
    assert fila is not None
    return str(fila[0])


def upsert_administradores(
    empresa_id: str,
    campos: CamposExtraidos,
    fuente: FuenteInfo,
    registro_bruto_id: str,
    registro_url: str | None,
    conn: psycopg.Connection,
) -> None:
    """Lee `campos.extra["administradores"]` (lista de `{"nombre",
    "cargo"}`, `radar.fuentes.borme.PATRONES_CARGO`) y enlaza cada persona
    con esta empresa en `cargos` (migración 202609141600, doc 08). Se
    llama tanto si la empresa se acaba de crear como si ya existía y solo
    se vinculó — un acto posterior (cambio de administrador) debe poder
    añadir cargos a una empresa que el BORME ya conocía.

    `on conflict (persona_id, empresa_id, cargo) do nothing`: nunca se
    sobreescribe evidencia (mismo principio que `observaciones`) — un
    cambio de cargo en la misma empresa añade una fila nueva, no sustituye
    la anterior. Solo se ignora si es EXACTAMENTE la misma combinación ya
    vista (p. ej. un acto que reconfirma al mismo administrador único).
    """
    administradores = (campos.extra or {}).get("administradores") or []
    if not administradores:
        return
    with conn.cursor() as cur:
        for admin in administradores:
            nombre = admin.get("nombre") if isinstance(admin, dict) else None
            cargo = admin.get("cargo") if isinstance(admin, dict) else None
            if not nombre or not cargo:
                continue
            persona_id = upsert_persona(nombre, conn)
            cur.execute(
                "insert into cargos (persona_id, empresa_id, cargo, fuente_id, registro_bruto_id, url_evidencia) "
                "values (%s, %s, %s, %s, %s, %s) "
                "on conflict (persona_id, empresa_id, cargo) do nothing",
                (persona_id, empresa_id, cargo, fuente.id, registro_bruto_id, registro_url),
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


def candidatos_duplicado_pendientes(conn: psycopg.Connection) -> list[dict]:
    """Candidatos de `candidatos_duplicado` en `estado='pendiente'` que
    TODAVÍA no tienen `opinion_llm`, para `scripts/arbitrar_duplicados.py`
    (`radar.resolucion.arbitraje`, doc 05 §2.5). `senales` guarda el dict
    completo que devolvió `radar.resolucion.scoring.comparar` (ver
    `insertar_candidato_duplicado`), de ahí sacamos la lista de señales
    legibles para el prompt.

    `opinion_llm is null` hace el script reanudable sin gastar LLM de más:
    un candidato que ya se arbitró como "incierto" (confianza insuficiente)
    se queda `pendiente` para revisión humana a propósito, y no hace falta
    volver a preguntarle al modelo en la siguiente pasada -- solo los que
    fallaron antes de guardar opinión (p. ej. por un error de red o, como
    pasó en la sesión de 2026-09-18, un bug de tipos en
    `fusionar_empresas_rpc`) se reintentan."""
    with conn.cursor() as cur:
        cur.execute(
            "select id, empresa_a, empresa_b, puntuacion, senales from candidatos_duplicado "
            "where estado = 'pendiente' and opinion_llm is null order by creado_en"
        )
        filas = cur.fetchall()
    return [
        {
            "id": f[0],
            "empresa_a": str(f[1]),
            "empresa_b": str(f[2]),
            "puntuacion": float(f[3]) if f[3] is not None else None,
            "senales": (f[4] or {}).get("senales", []),
        }
        for f in filas
    ]


def cargar_contexto_arbitraje(empresa_id: str, conn: psycopg.Connection) -> dict:
    """Todo lo que un humano miraría para decidir si dos fichas son la
    misma empresa o dos homónimas: nombre, NIF, sedes, administradores,
    objeto social y de qué fuente viene cada una — para
    `radar.resolucion.arbitraje.arbitrar` (doc 05 §2.5)."""
    with conn.cursor() as cur:
        cur.execute("select razon_social, nif, forma_juridica, estado from empresas where id = %s", (empresa_id,))
        fila = cur.fetchone()
        if fila is None:
            raise ValueError(f"Empresa {empresa_id} no existe")
        cur.execute(
            "select direccion_original, municipio_nombre, provincia, codigo_postal "
            "from sedes where empresa_id = %s and activa",
            (empresa_id,),
        )
        sedes = cur.fetchall()
        cur.execute(
            "select p.nombre, c.cargo from cargos c join personas p on p.id = c.persona_id "
            "where c.empresa_id = %s and c.vigente",
            (empresa_id,),
        )
        administradores = cur.fetchall()
        cur.execute(
            "select distinct f.nombre from registros_brutos rb join fuentes f on f.id = rb.fuente_id where rb.empresa_id = %s",
            (empresa_id,),
        )
        fuentes = [r[0] for r in cur.fetchall()]
        cur.execute(
            "select valor_original from observaciones where empresa_id = %s and campo = 'objeto_social' and vigente "
            "order by observado_en desc limit 1",
            (empresa_id,),
        )
        objeto = cur.fetchone()
    return {
        "empresa_id": str(empresa_id),
        "razon_social": fila[0],
        "nif": fila[1],
        "forma_juridica": fila[2],
        "estado": fila[3],
        "sedes": [{"direccion": s[0], "municipio": s[1], "provincia": s[2], "codigo_postal": s[3]} for s in sedes],
        "administradores": [{"nombre": a[0], "cargo": a[1]} for a in administradores],
        "fuentes": fuentes,
        "objeto_social": objeto[0] if objeto else None,
    }


def guardar_opinion_llm_candidato(candidato_id: int, opinion: dict, conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "update candidatos_duplicado set opinion_llm = %s::jsonb where id = %s",
            (json.dumps(opinion, default=str), candidato_id),
        )


def descartar_candidato_duplicado(candidato_id: int, decidido_por: str, conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "update candidatos_duplicado set estado = 'rechazado', revisado_por = %s, revisado_en = now() where id = %s",
            (decidido_por, candidato_id),
        )


def fusionar_empresas_rpc(
    origen: str, destino: str, motivo: str, decidido_por: str,
    puntuacion: float | None, candidato_id: int | None, conn: psycopg.Connection,
) -> None:
    """Llama a la función Postgres `fusionar_empresas` (migración
    202609142000) — misma función que usa el panel via `supabase.rpc()`,
    aquí invocada directamente por SQL porque el worker ya tiene una
    conexión psycopg abierta.

    Los casts explícitos son necesarios: sin ellos psycopg manda los
    parámetros como tipo "unknown" y Postgres no encuentra ninguna función
    `fusionar_empresas` que encaje (el propio mensaje de error lo dice:
    "function fusionar_empresas(unknown, unknown, unknown, unknown, double
    precision, smallint) does not exist") -- confirmado en vivo arbitrando
    los primeros candidatos reales de duplicados de esta sesión."""
    with conn.cursor() as cur:
        cur.execute(
            "select fusionar_empresas(%s::uuid, %s::uuid, %s::text, %s::text, %s::numeric, %s::bigint)",
            (origen, destino, motivo, decidido_por, puntuacion, candidato_id),
        )


def empresas_con_objeto_social_sin_cnae(conn: psycopg.Connection) -> list[dict]:
    """Empresas con una observación vigente de `objeto_social` pero
    todavía sin `cnae_principal` -- candidatas para
    `scripts/clasificar_cnae.py`. Si una empresa tiene más de una
    observación de `objeto_social` (varias fuentes o varios actos), se usa
    la más reciente; no hace falta la maquinaria completa de
    `consolidar_campo` porque aquí no hay que arbitrar "cuál texto es más
    fiable", solo con cuál clasificar -- el nivel 4 de la CNAE es
    mutuamente excluyente, no un valor que puedan reforzar dos fuentes."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select distinct on (e.id) e.id, e.cnae_version, o.valor_original, o.fuente_id
            from empresas e
            join observaciones o on o.empresa_id = e.id and o.campo = 'objeto_social' and o.vigente
            where e.cnae_principal is null and e.fusionada_en is null
            order by e.id, o.observado_en desc
            """
        )
        filas = cur.fetchall()
    return [{"empresa_id": str(f[0]), "cnae_version": f[1], "objeto_social": f[2], "fuente_id": f[3]} for f in filas]


def actualizar_cnae_empresa(
    empresa_id: str, cnae_principal: str, cnae_secundarios: list[str], cnae_version: str, conn: psycopg.Connection
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "update empresas set cnae_principal = %s, cnae_secundarios = %s, cnae_version = %s where id = %s",
            (cnae_principal, cnae_secundarios, cnae_version, empresa_id),
        )


def insertar_observacion_cnae(
    empresa_id: str, cnae_principal: str, fuente_id: int, confianza: float, evidencia: str, conn: psycopg.Connection
) -> None:
    """Traza de dónde salió `cnae_principal` -- mismo patrón append-only
    que el resto de `observaciones` (nunca se sobreescribe evidencia,
    principio 2 del proyecto)."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into observaciones (empresa_id, fuente_id, campo, valor_original, valor_norm, confianza_fuente) "
            "values (%s, %s, 'cnae_principal', %s, %s, %s)",
            (empresa_id, fuente_id, evidencia, cnae_principal, confianza),
        )


def registrar_resultado_busqueda(
    busqueda_id: str, empresa_id: str, motivo: str | None, relevancia: float | None, conn: psycopg.Connection
) -> None:
    """Enlaza una empresa encontrada con la búsqueda que la encontró
    (`busqueda_resultados`, doc 03b) — sin esta función, el hilo
    `busqueda_id` que llega desde `radar.api.main` hasta las herramientas
    del agente no tenía ningún destino: nada escribía nunca en esta tabla,
    así que la lista de resultados del panel se quedaba vacía para
    siempre, con o sin el resto de esta pieza funcionando.

    `motivo` combina la fuente y la acción de resolución (p. ej.
    `"borme: nueva_empresa"`, `"buscador_web: vinculado"`) — es lo que el
    panel usa para explicar de dónde salió cada resultado (doc 08,
    petición del usuario "que indique la fuente de los datos"); para el
    detalle campo a campo con URL de evidencia, ver `observaciones`.

    Si la misma empresa ya estaba enlazada a esta búsqueda (la encontró
    otra herramienta en una ronda distinta de la misma búsqueda), se
    actualiza el motivo en vez de duplicar o fallar por la PK compuesta.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into busqueda_resultados (busqueda_id, empresa_id, relevancia, motivo)
            values (%s, %s, %s, %s)
            on conflict (busqueda_id, empresa_id) do update set
                motivo = excluded.motivo,
                relevancia = coalesce(excluded.relevancia, busqueda_resultados.relevancia)
            """,
            (busqueda_id, empresa_id, relevancia, motivo),
        )
