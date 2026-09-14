"""Orquestador (doc 02 §2, pasos 6-8): convierte un `RegistroBruto` de un
conector en escrituras en `registros_brutos` / `observaciones` / `empresas`
/ `sedes` / `canales_contacto` / `identificadores` / `personas` / `cargos`,
usando `radar.normalizacion` (paso 6), `radar.resolucion` (paso 7) y
`radar.verificacion` (paso 8).

`procesar_registro` NO abre ni cierra la conexión ni hace commit — quien
llama controla la transacción (normalmente: una transacción por
`RegistroBruto`, para no dejar una empresa a medio escribir si algo
falla a mitad).

Simplificaciones conocidas de esta primera versión (documentadas también
en `bd.py` y `senales_borme.py` donde aplica), a revisar en tareas
posteriores:
- El arbitraje LLM de la zona de revisión (doc 05 §2.5) no está conectado
  todavía (tarea #21, el agente); mientras tanto, "revisión" crea una
  empresa nueva y dejar un `candidatos_duplicado` pendiente.
- Las señales de estado (doc 05 §4) solo se calculan a partir del propio
  `RegistroBruto` que se está procesando (hoy, solo BORME aporta señales);
  no se re-derivan a partir de todo el historial de observaciones en cada
  pasada.
- Las sedes se resuelven con "última observación gana" (`bd.upsert_sede`),
  no con la consolidación multi-fuente de NIF/nombre/teléfono/email.
- Tamaño/empleados todavía no se procesa (ningún conector conectado hoy lo
  aporta de forma estructurada).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import psycopg

from radar.fuentes.base import RegistroBruto
from radar.normalizacion.dominio import normalizar_email
from radar.normalizacion.registro import normalizar_registro
from radar.orquestador import bd
from radar.orquestador.logica import (
    campos_a_dict_normalizacion,
    combinar_dimension_contacto,
    combinar_dimension_identidad,
    decidir_resolucion,
    texto_representativo,
)
from radar.orquestador.senales_borme import mapear_senales_borme
from radar.resolucion.blocking import buscar_candidatos
from radar.resolucion.blocking import telefonos_compartidos as cargar_telefonos_compartidos
from radar.verificacion.confianza import consolidar_campo
from radar.verificacion.estado import SenalesEstado, determinar_estado
from radar.verificacion.global_ import calcular_confianza_global

AccionFinal = Literal["ya_procesado", "vinculado", "nueva_empresa", "en_revision"]

# doc 03b §6 `estado_resolucion`: mapea 1:1 con `AccionFinal` salvo
# "ya_procesado", que no vuelve a tocar la fila.
_ACCION_A_ESTADO_REGISTRO: dict[str, bd.EstadoRegistroBruto] = {
    "vinculado": "vinculado",
    "nueva_empresa": "nueva_empresa",
    "en_revision": "en_revision",
}


@dataclass
class ResultadoResolucion:
    accion: AccionFinal
    empresa_id: str | None
    registro_bruto_id: str
    puntuacion_match: float | None
    n_candidatos_evaluados: int


def _calcular_senales_estado(registro: RegistroBruto, fuente: bd.FuenteInfo) -> SenalesEstado:
    if fuente.codigo == "borme":
        return mapear_senales_borme(registro.campos.extra.get("tipos_acto", []))
    return SenalesEstado()  # sin señales de estado desde esta fuente (fuentes #18-20, todavía no conectadas)


def _consolidar_y_actualizar_empresa(
    empresa_id: str, campos_norm: dict, senales: SenalesEstado, conn: psycopg.Connection
) -> None:
    obs_nif = bd.cargar_observaciones_vigentes(empresa_id, "nif", conn)
    obs_rs = bd.cargar_observaciones_vigentes(empresa_id, "razon_social", conn)
    obs_nc = bd.cargar_observaciones_vigentes(empresa_id, "nombre_comercial", conn)
    obs_tel = bd.cargar_observaciones_vigentes(empresa_id, "telefono", conn)
    obs_email = bd.cargar_observaciones_vigentes(empresa_id, "email", conn)
    obs_web = bd.cargar_observaciones_vigentes(empresa_id, "web", conn)

    ahora = datetime.now(UTC)
    res_nif = consolidar_campo("nif", obs_nif, ahora) if obs_nif else None
    res_rs = consolidar_campo("razon_social", obs_rs, ahora) if obs_rs else None
    res_nc = consolidar_campo("nombre_comercial", obs_nc, ahora) if obs_nc else None
    res_tel = consolidar_campo("telefono", obs_tel, ahora) if obs_tel else None
    res_email = consolidar_campo("email", obs_email, ahora) if obs_email else None
    res_web = consolidar_campo("web", obs_web, ahora) if obs_web else None

    actual = bd.cargar_empresa_actual(empresa_id, conn)

    tiene_senales = senales != SenalesEstado()
    if tiene_senales:
        estado, estado_confianza = determinar_estado(senales)
    else:
        estado, estado_confianza = actual["estado"], actual["estado_confianza"]

    identidad = combinar_dimension_identidad(res_nif, res_rs)
    contacto = combinar_dimension_contacto(res_tel, res_email)
    ubicacion = actual["sede_confianza"] or 0.0
    confianza_global = calcular_confianza_global(
        confianza_identidad=identidad,
        confianza_estado=estado_confianza,
        confianza_ubicacion=ubicacion,
        confianza_contacto=contacto,
        nif_confirmado=bool(res_nif and res_nif.ganador),
    )

    bd.actualizar_empresa(
        empresa_id,
        nif=res_nif.ganador.valor if res_nif and res_nif.ganador else None,
        nif_valido=True if res_nif and res_nif.ganador else None,
        razon_social=texto_representativo(obs_rs, res_rs.ganador.valor) if res_rs and res_rs.ganador else None,
        nombre_comercial=texto_representativo(obs_nc, res_nc.ganador.valor) if res_nc and res_nc.ganador else None,
        forma_juridica=campos_norm.get("forma_juridica"),
        dominio_web=res_web.ganador.valor if res_web and res_web.ganador else None,
        estado=estado if tiene_senales else None,
        estado_confianza=estado_confianza if tiene_senales else None,
        estado_actualizado=tiene_senales,
        confianza_global=confianza_global,
        conn=conn,
    )

    if res_tel:
        for v in res_tel.multivalor:
            bd.upsert_canal_contacto(empresa_id, "telefono", v.valor, v.confianza_efectiva, conn)
    if res_email:
        for v in res_email.multivalor:
            # es_generico se deriva del propio valor, no del campos_norm del
            # registro que lo trajo -- las observaciones que se consolidan
            # aquí pueden venir de varias fuentes/momentos distintos, así
            # que no hay un único "campos_norm" de referencia en este punto.
            bd.upsert_canal_contacto(
                empresa_id, "email", v.valor, v.confianza_efectiva, conn,
                es_generico=normalizar_email(v.valor)["es_generico"],
            )


def procesar_registro(
    registro: RegistroBruto,
    conn: psycopg.Connection,
    *,
    busqueda_id: str | None = None,
    telefonos_compartidos: set[str] | None = None,
) -> ResultadoResolucion:
    """Procesa UN `RegistroBruto` de principio a fin (pasos 6-8 de doc 02
    §2). Idempotente por `(fuente, hash_contenido)`: reprocesar el mismo
    registro no crea una empresa duplicada (ver `bd.insertar_registro_bruto`).

    `telefonos_compartidos` (doc 05 §2.3: teléfonos de gestorías/centralitas
    que no cuentan como señal de identidad) se puede precalcular una vez por
    lote y pasarlo aquí — si no, se calcula con una consulta a toda la tabla
    `canales_contacto` en cada llamada, caro para procesar muchos registros
    seguidos.
    """
    fuente = bd.obtener_fuente(registro.fuente, conn)
    rb = bd.insertar_registro_bruto(registro, fuente, conn, busqueda_id)
    if rb.estado != "pendiente":
        return ResultadoResolucion("ya_procesado", rb.empresa_id, rb.id, rb.puntuacion_match, 0)

    campos_norm = normalizar_registro(campos_a_dict_normalizacion(registro.campos))
    compartidos = (
        telefonos_compartidos if telefonos_compartidos is not None else cargar_telefonos_compartidos(conexion=conn)
    )

    candidatos_ids: list[str] = []
    if campos_norm["nif_valido"]:
        exacto = bd.buscar_candidato_por_nif(campos_norm["nif"], conn)
        if exacto:
            candidatos_ids.append(exacto)
    nombre_para_bloqueo = registro.campos.razon_social or registro.campos.nombre_comercial
    if nombre_para_bloqueo:
        for c in buscar_candidatos(nombre_para_bloqueo, campos_norm.get("lon"), campos_norm.get("lat"), conexion=conn):
            if c.empresa_id not in candidatos_ids:
                candidatos_ids.append(c.empresa_id)

    candidatos = [bd.cargar_registro_empresa_normalizado(cid, conn) for cid in candidatos_ids]
    decision = decidir_resolucion(campos_norm, candidatos, compartidos)

    if decision.accion == "vincular":
        assert decision.empresa_id is not None
        empresa_id = decision.empresa_id
    else:
        empresa_id = bd.crear_empresa(campos_norm, registro.campos, conn)
        if decision.accion == "crear_y_revisar" and decision.mejor_candidato_id and decision.resultado_comparacion:
            bd.insertar_candidato_duplicado(empresa_id, decision.mejor_candidato_id, decision.resultado_comparacion, conn)

    bd.insertar_observaciones(
        empresa_id, rb.id, fuente, campos_norm, registro.campos, registro.url, registro.capturado_en, conn
    )

    tiene_direccion = bool(registro.campos.domicilio or campos_norm.get("cp") or registro.campos.municipio)
    if tiene_direccion:
        bd.upsert_sede(empresa_id, registro.campos, campos_norm, fuente, conn)

    senales = _calcular_senales_estado(registro, fuente)
    _consolidar_y_actualizar_empresa(empresa_id, campos_norm, senales, conn)
    bd.upsert_identificadores(empresa_id, campos_norm, registro.campos, fuente, conn)
    bd.upsert_administradores(empresa_id, registro.campos, fuente, rb.id, registro.url, conn)

    accion_final: AccionFinal = (
        "vinculado" if decision.accion == "vincular" else ("en_revision" if decision.accion == "crear_y_revisar" else "nueva_empresa")
    )
    bd.actualizar_registro_bruto(rb.id, _ACCION_A_ESTADO_REGISTRO[accion_final], empresa_id, decision.puntuacion, conn)

    return ResultadoResolucion(accion_final, empresa_id, rb.id, decision.puntuacion, len(candidatos))
