"""Decisiones humanas sobre `conflictos_datos` (pantallas «Datos sin contrastar»
y «Cola de revisión», 2026-09-24).

- confirmar: el valor elegido por el sistema es el correcto.
- elegir: otro de los valores en juego es el correcto.
- separar (solo campo '_identidad'): el registro unido por coincidencia
  parcial NO es de esta empresa; se retira y se procesa como empresa nueva.

Las decisiones de valor se guardan como una observación más de la fuente
'manual' (fiabilidad 0,98): el dato queda trazado (quién, cuándo) y la
consolidación normal lo hace ganar -- no se sobreescribe nada a mano.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Literal

import psycopg

from radar.fuentes.base import CamposExtraidos, RegistroBruto
from radar.orquestador import bd
from radar.orquestador.procesar import procesar_registro, reconsolidar_empresa

Accion = Literal["confirmar", "elegir", "separar"]

# Columna de `empresas` que se vacía si, tras separar un registro, el campo se
# queda sin ninguna observación vigente (`actualizar_empresa` usa coalesce y
# nunca borra por sí sola).
_COLUMNA_EMPRESA = {"nif": "nif", "razon_social": "razon_social", "nombre_comercial": "nombre_comercial", "web": "dominio_web"}


class ConflictoNoValido(ValueError):
    pass


def _cargar(conflicto_id: int, conn: psycopg.Connection) -> dict[str, Any]:
    fila = conn.execute(
        "select id, empresa_id::text, campo, estado, valor_elegido, alternativas, registro_bruto_id::text, busqueda_id::text "
        "from conflictos_datos where id = %s",
        (conflicto_id,),
    ).fetchone()
    if fila is None:
        raise ConflictoNoValido("contradicción no encontrada")
    claves = ("id", "empresa_id", "campo", "estado", "valor_elegido", "alternativas", "registro_bruto_id", "busqueda_id")
    return dict(zip(claves, fila, strict=True))


def _observacion_manual(c: dict[str, Any], valor: str, usuario: str, conn: psycopg.Connection) -> str:
    alternativa = next(
        (a for a in c["alternativas"] if valor in (a.get("valor"), a.get("valor_norm"))), None
    )
    if alternativa is None:
        raise ConflictoNoValido("el valor no es ninguno de los que están en juego")
    fuente = bd.obtener_fuente("manual", conn)
    conn.execute(
        "insert into observaciones (empresa_id, registro_bruto_id, fuente_id, campo, valor_original, valor_norm, "
        "url_evidencia, observado_en, confianza_fuente, vigente) values (%s, null, %s, %s, %s, %s, %s, now(), %s, true)",
        (c["empresa_id"], fuente.id, c["campo"], alternativa.get("valor"), alternativa.get("valor_norm"),
         f"panel:{usuario}", fuente.fiabilidad_base),
    )
    return str(alternativa.get("valor"))


def _cerrar(c: dict[str, Any], estado: str, valor_final: str | None, usuario: str, conn: psycopg.Connection) -> None:
    conn.execute(
        "update conflictos_datos set estado = %s, valor_final = %s, resuelto_por = %s, resuelto_en = now(), "
        "actualizado_en = now() where id = %s",
        (estado, valor_final, usuario, c["id"]),
    )


def _registro_desde_bd(registro_bruto_id: str, conn: psycopg.Connection) -> RegistroBruto:
    fila = conn.execute(
        "select f.codigo, rb.id_externo, rb.url, rb.payload, rb.campos, rb.capturado_en "
        "from registros_brutos rb join fuentes f on f.id = rb.fuente_id where rb.id = %s",
        (registro_bruto_id,),
    ).fetchone()
    if fila is None:
        raise ConflictoNoValido("el registro original ya no existe")
    nombres = {f.name for f in dataclasses.fields(CamposExtraidos)}
    campos = CamposExtraidos(**{k: v for k, v in (fila[4] or {}).items() if k in nombres})
    return RegistroBruto(fuente=fila[0], id_externo=fila[1], url=fila[2], payload=fila[3] or {}, campos=campos, capturado_en=fila[5])


def _separar(c: dict[str, Any], usuario: str, conn: psycopg.Connection) -> str | None:
    empresa_id, rb_id = c["empresa_id"], c["registro_bruto_id"]
    if not rb_id:
        raise ConflictoNoValido("no hay registro que separar")
    # 1. Retirar de la empresa todo lo que aportó ese registro.
    canales = conn.execute(
        "select campo, valor_norm from observaciones where empresa_id = %s and registro_bruto_id = %s "
        "and campo in ('telefono', 'email') and vigente",
        (empresa_id, rb_id),
    ).fetchall()
    conn.execute("update observaciones set vigente = false where empresa_id = %s and registro_bruto_id = %s", (empresa_id, rb_id))
    conn.execute("delete from cargos where empresa_id = %s and registro_bruto_id = %s", (empresa_id, rb_id))
    for tipo, valor_norm in canales:
        otra = conn.execute(
            "select 1 from observaciones where empresa_id = %s and campo = %s and valor_norm = %s and vigente limit 1",
            (empresa_id, tipo, valor_norm),
        ).fetchone()
        if not otra:
            conn.execute(
                "delete from canales_contacto where empresa_id = %s and tipo = %s and valor_norm = %s",
                (empresa_id, tipo, valor_norm),
            )
    for campo, columna in _COLUMNA_EMPRESA.items():
        if not conn.execute(
            "select 1 from observaciones where empresa_id = %s and campo = %s and vigente limit 1", (empresa_id, campo)
        ).fetchone():
            conn.execute(f"update empresas set {columna} = null where id = %s", (empresa_id,))  # columna de lista fija
    reconsolidar_empresa(empresa_id, conn)

    # 2. Procesar el registro como empresa propia.
    registro = _registro_desde_bd(rb_id, conn)
    conn.execute("update registros_brutos set estado = 'pendiente', empresa_id = null where id = %s", (rb_id,))
    r = procesar_registro(registro, conn, forzar_nueva=True)
    if c["busqueda_id"] and r.empresa_id:
        bd.registrar_resultado_busqueda(c["busqueda_id"], r.empresa_id, "separado: nueva_empresa", None, conn)
    return r.empresa_id


def resolver_conflicto(
    conn: psycopg.Connection, conflicto_id: int, accion: Accion, *, valor: str | None = None, usuario: str = "panel"
) -> dict[str, Any]:
    """Aplica la decisión y hace commit. Devuelve el nuevo estado."""
    c = _cargar(conflicto_id, conn)
    if c["estado"] != "pendiente":
        raise ConflictoNoValido(f"ya está resuelta ({c['estado']})")

    nueva_empresa: str | None = None
    if accion == "separar":
        if c["campo"] != "_identidad":
            raise ConflictoNoValido("solo se puede separar una duda de identidad")
        nueva_empresa = _separar(c, usuario, conn)
        estado = "separado"
        _cerrar(c, estado, None, usuario, conn)
    elif c["campo"] == "_identidad":
        # Confirmar que el registro sí es de esta empresa: no hay valor que fijar.
        estado = "confirmado"
        _cerrar(c, estado, c["valor_elegido"], usuario, conn)
    else:
        elegido = valor if accion == "elegir" else c["valor_elegido"]
        if not elegido:
            raise ConflictoNoValido("falta el valor elegido")
        valor_final = _observacion_manual(c, elegido, usuario, conn)
        estado = "corregido" if accion == "elegir" and valor_final != c["valor_elegido"] else "confirmado"
        _cerrar(c, estado, valor_final, usuario, conn)
        reconsolidar_empresa(c["empresa_id"], conn)
    conn.commit()
    return {"id": conflicto_id, "estado": estado, "empresa_separada_id": nueva_empresa}
