"""Resolución automática de «Datos sin contrastar» (2026-09-25).

Para cada duda pendiente, por orden:

1. Verificación dirigida en la web PROPIA de la empresa (gratis): se lee su
   web (portada + aviso legal/contacto/equipo) y se busca el dato en disputa.
   - Duda de identidad: si el teléfono, email, NIF o el nombre del registro
     unido aparece en la web de la empresa, es la misma -> se confirma.
   - Contradicción de NIF / razón social: si exactamente UNO de los valores en
     juego aparece en la web de la empresa, ese es el bueno -> se aplica.
2. Si no hay evidencia, se pregunta a un LLM con todos los datos (fuentes,
   antigüedad, perfil de la empresa, extracto de su web). Si responde con
   confianza >= `CONFIANZA_MINIMA_AUTOMATICA` se aplica; si no, se guarda como
   SUGERENCIA visible en «Datos sin contrastar» para que decida una persona.

Lo que se resuelve solo pasa a la «Cola de revisión» (tipo
'resuelto_con_evidencia') con el motivo exacto, para que una persona pueda
confirmarlo o deshacerlo. Los valores elegidos se guardan como observación de
la fuente 'verificacion_automatica' (0,90): trazables y siempre corregibles
por una decisión humana (0,98). Separar una empresa (crear otra) nunca se hace
solo: como mucho se sugiere.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Literal

import httpx
import psycopg
from pydantic import BaseModel, ConfigDict

from radar.extraccion.conector import leer_texto_web
from radar.llm_json import pedir_json
from radar.normalizacion.nombre import normalizar_nombre, normalizar_texto, tokens_distintivos
from radar.orquestador import bd
from radar.orquestador.procesar import reconsolidar_empresa

CONFIANZA_MINIMA_AUTOMATICA = 0.85
MAX_TEXTO_WEB_PROMPT = 2500


class SugerenciaValor(BaseModel):
    model_config = ConfigDict(extra="ignore")
    valor: str | None = None
    confianza: float = 0.0
    motivo: str = ""


class SugerenciaIdentidad(BaseModel):
    model_config = ConfigDict(extra="ignore")
    decision: Literal["misma", "distinta", "incierto"]
    confianza: float = 0.0
    motivo: str = ""


PROMPT_VALOR = """Una empresa española tiene datos contradictorios en el campo «{campo}» según varias fuentes. Decide cuál es el valor correcto.

Empresa: {empresa_json}
Valores en juego (con sus fuentes, confianza y antigüedad del último dato):
{alternativas_json}
Extracto de la web propia de la empresa (puede estar vacío):
<web>{texto_web}</web>

Reglas: el valor correcto es el de la entidad jurídica titular de la empresa. Un registro oficial o la web propia de la empresa pesan más que un directorio. Si no hay base suficiente, devuelve valor null y confianza baja; no adivines.
Responde SOLO con JSON: {{"valor": "uno de los valores en juego o null", "confianza": 0.0, "motivo": "una frase"}}"""

PROMPT_IDENTIDAD = """Un sistema unió estos datos a una empresa sin estar seguro de que sean de la misma empresa. Decide.

Empresa: {empresa_json}
Datos unidos (de otra fuente): {registro_json}
Señales del sistema: {senales}
Extracto de la web propia de la empresa (puede estar vacío):
<web>{texto_web}</web>

Reglas: si ambos tienen NIF distinto son empresas distintas. Un nombre parecido no basta (homónimos, franquicias, grupos). Mismo teléfono o email propio, o que la web de la empresa nombre a la otra, son buenas pruebas. Si no hay base suficiente: "incierto".
Responde SOLO con JSON: {{"decision": "misma|distinta|incierto", "confianza": 0.0, "motivo": "una frase"}}"""


def _solo_digitos(t: str) -> str:
    return re.sub(r"\D", "", t)


def _perfil_sin_registro(conn: psycopg.Connection, empresa_id: str, registro_bruto_id: str) -> dict[str, Any]:
    """Lo que se sabe de la empresa SIN lo que aportó el registro en duda: si
    no, el LLM compara el registro consigo mismo (visto en prueba: "la razón
    social coincide exactamente" porque la ficha ya mostraba la del registro)."""
    filas = conn.execute(
        "select campo, array_agg(distinct valor_original) from observaciones "
        "where empresa_id = %s and vigente and (registro_bruto_id is distinct from %s) "
        "and campo in ('razon_social', 'nombre_comercial', 'nif', 'web', 'telefono', 'email', 'municipio', 'direccion') "
        "group by campo",
        (empresa_id, registro_bruto_id),
    ).fetchall()
    return {campo: valores for campo, valores in filas}


def _perfil_empresa(conn: psycopg.Connection, empresa_id: str) -> dict[str, Any]:
    fila = conn.execute(
        "select coalesce(razon_social, nombre_comercial), nombre_comercial, nif, dominio_web, "
        "(select s.municipio_nombre from sedes s where s.empresa_id = e.id and s.municipio_nombre is not null limit 1) "
        "from empresas e where id = %s",
        (empresa_id,),
    ).fetchone()
    canales = conn.execute("select tipo, valor from canales_contacto where empresa_id = %s", (empresa_id,)).fetchall()
    if fila is None:
        return {}
    return {
        "nombre": fila[0], "nombre_comercial": fila[1], "nif": fila[2], "web": fila[3], "municipio": fila[4],
        "telefonos": [v for t, v in canales if t == "telefono"], "emails": [v for t, v in canales if t == "email"],
    }


def _perfil_registro(conn: psycopg.Connection, registro_bruto_id: str) -> dict[str, Any]:
    fila = conn.execute(
        "select f.nombre, rb.campos from registros_brutos rb join fuentes f on f.id = rb.fuente_id where rb.id = %s",
        (registro_bruto_id,),
    ).fetchone()
    if fila is None:
        return {}
    c = fila[1] or {}
    return {k: v for k, v in {
        "fuente": fila[0], "razon_social": c.get("razon_social"), "nombre_comercial": c.get("nombre_comercial"),
        "nif": c.get("nif"), "telefonos": c.get("telefonos"), "emails": c.get("emails"), "web": c.get("web"),
        "domicilio": c.get("domicilio"), "municipio": c.get("municipio"),
    }.items() if v}


def evidencia_identidad(registro: dict[str, Any], texto_web: str) -> str | None:
    """Motivo si algún dato del registro aparece en la web de la empresa."""
    if not texto_web:
        return None
    digitos_web = _solo_digitos(texto_web)
    for tel in registro.get("telefonos") or []:
        d = _solo_digitos(str(tel))[-9:]
        if len(d) == 9 and d in digitos_web:
            return f"el teléfono {tel} aparece en la web de la empresa"
    web_min = texto_web.lower()
    for email in registro.get("emails") or []:
        if str(email).lower() in web_min:
            return f"el email {email} aparece en la web de la empresa"
    nif = registro.get("nif")
    if nif and str(nif).upper() in texto_web.upper():
        return f"el NIF {nif} aparece en la web de la empresa"
    web_norm = normalizar_texto(texto_web)
    for nombre in (registro.get("razon_social"), registro.get("nombre_comercial")):
        distintivas = tokens_distintivos(normalizar_nombre(nombre)) if nombre else set()
        if distintivas and all(t in web_norm.split() for t in distintivas):
            return f"el nombre «{nombre}» aparece en la web de la empresa"
    return None


def evidencia_valor(campo: str, alternativas: list[dict[str, Any]], texto_web: str) -> dict[str, Any] | None:
    """La única alternativa que aparece en la web de la empresa, si solo hay una."""
    if not texto_web or campo not in ("nif", "razon_social"):
        return None
    web_norm = f" {normalizar_texto(texto_web)} "
    encontradas = []
    for a in alternativas:
        valor = str(a.get("valor") or "")
        if campo == "nif":
            presente = valor.upper() in texto_web.upper().replace("-", "").replace(" ", "")
        else:
            nombre = normalizar_nombre(valor)
            presente = bool(nombre) and f" {nombre} " in web_norm
        if presente:
            encontradas.append(a)
    return encontradas[0] if len(encontradas) == 1 else None


def _aplicar_valor(conn: psycopg.Connection, conflicto: dict[str, Any], alternativa: dict[str, Any], motivo: str) -> None:
    fuente = bd.obtener_fuente("verificacion_automatica", conn)
    conn.execute(
        "insert into observaciones (empresa_id, registro_bruto_id, fuente_id, campo, valor_original, valor_norm, "
        "url_evidencia, observado_en, confianza_fuente, vigente) values (%s, null, %s, %s, %s, %s, %s, now(), %s, true)",
        (conflicto["empresa_id"], fuente.id, conflicto["campo"], alternativa.get("valor"), alternativa.get("valor_norm"),
         "verificacion_automatica", fuente.fiabilidad_base),
    )
    conn.execute(
        "update conflictos_datos set tipo = 'resuelto_con_evidencia', motivo = %s, valor_elegido = %s, actualizado_en = now() "
        "where id = %s",
        (motivo, alternativa.get("valor"), conflicto["id"]),
    )
    reconsolidar_empresa(conflicto["empresa_id"], conn)


def _marcar_resuelto(conn: psycopg.Connection, conflicto_id: int, motivo: str) -> None:
    conn.execute(
        "update conflictos_datos set tipo = 'resuelto_con_evidencia', motivo = %s, actualizado_en = now() where id = %s",
        (motivo, conflicto_id),
    )


def _guardar_sugerencia(conn: psycopg.Connection, conflicto_id: int, sugerencia: dict[str, Any]) -> None:
    conn.execute("update conflictos_datos set sugerencia = %s::jsonb where id = %s", (json.dumps(sugerencia, ensure_ascii=False), conflicto_id))


def _conflictos_pendientes(conn: psycopg.Connection, busqueda_id: str | None, ids: list[int] | None) -> list[dict[str, Any]]:
    sql = (
        "select cd.id, cd.empresa_id::text, cd.campo, cd.alternativas, cd.motivo, cd.registro_bruto_id::text "
        "from conflictos_datos cd where cd.estado = 'pendiente' and cd.tipo = 'sin_contrastar'"
    )
    params: list[Any] = []
    if ids:
        sql += " and cd.id = any(%s)"
        params.append(ids)
    elif busqueda_id:
        # Las empresas que el filtro de relevancia descartó no merecen gasto.
        sql += (
            " and cd.empresa_id in (select empresa_id from busqueda_resultados where busqueda_id = %s"
            " and coalesce(clasificacion, '') not in ('descartado', 'rechazado'))"
        )
        params.append(busqueda_id)
    claves = ("id", "empresa_id", "campo", "alternativas", "motivo", "registro_bruto_id")
    return [dict(zip(claves, f, strict=True)) for f in conn.execute(sql, params).fetchall()]


async def resolver_dudas(
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    *,
    busqueda_id: str | None = None,
    conflicto_ids: list[int] | None = None,
    max_coste_eur: float = 0.05,
) -> dict[str, Any]:
    contadores = {"revisadas": 0, "resueltas_con_evidencia_web": 0, "resueltas_por_ia": 0, "con_sugerencia": 0, "sin_resolver": 0}
    coste = 0.0
    textos_web: dict[str, str] = {}

    for c in _conflictos_pendientes(conn, busqueda_id, conflicto_ids):
        contadores["revisadas"] += 1
        empresa = _perfil_empresa(conn, c["empresa_id"])
        dominio = empresa.get("web")
        if dominio and dominio not in textos_web:
            try:
                textos_web[dominio] = await leer_texto_web(cliente_http, f"https://{dominio}")
            except Exception:  # noqa: BLE001 -- una web caída no debe parar el resto
                textos_web[dominio] = ""
        texto_web = textos_web.get(dominio or "", "")

        if c["campo"] == "_identidad":
            registro = _perfil_registro(conn, c["registro_bruto_id"]) if c["registro_bruto_id"] else {}
            motivo = evidencia_identidad(registro, texto_web)
            if motivo:
                _marcar_resuelto(conn, c["id"], f"Resuelto automáticamente (evidencia): {motivo}.")
                conn.commit()
                contadores["resueltas_con_evidencia_web"] += 1
                continue
            if coste >= max_coste_eur:
                contadores["sin_resolver"] += 1
                continue
            empresa_sin = _perfil_sin_registro(conn, c["empresa_id"], c["registro_bruto_id"]) if c["registro_bruto_id"] else empresa
            r = await asyncio.to_thread(pedir_json, PROMPT_IDENTIDAD.format(
                empresa_json=json.dumps(empresa_sin, ensure_ascii=False, default=str), registro_json=json.dumps(registro, ensure_ascii=False),
                senales=c["motivo"], texto_web=texto_web[:MAX_TEXTO_WEB_PROMPT],
            ), SugerenciaIdentidad)
            coste += r.coste_eur
            if r.datos is None:
                contadores["sin_resolver"] += 1
                continue
            if r.datos.decision == "misma" and r.datos.confianza >= CONFIANZA_MINIMA_AUTOMATICA:
                _marcar_resuelto(conn, c["id"], f"Resuelto automáticamente (IA, confianza {r.datos.confianza:.2f}): {r.datos.motivo}")
                contadores["resueltas_por_ia"] += 1
            else:
                _guardar_sugerencia(conn, c["id"], {"origen": "ia", **r.datos.model_dump()})
                contadores["con_sugerencia"] += 1
            conn.commit()
            continue

        alternativa = evidencia_valor(c["campo"], c["alternativas"], texto_web)
        if alternativa:
            _aplicar_valor(conn, c, alternativa, f"Resuelto automáticamente (evidencia): «{alternativa.get('valor')}» aparece en la web de la empresa ({dominio}).")
            conn.commit()
            contadores["resueltas_con_evidencia_web"] += 1
            continue
        if coste >= max_coste_eur:
            contadores["sin_resolver"] += 1
            continue
        rv = await asyncio.to_thread(pedir_json, PROMPT_VALOR.format(
            campo=c["campo"], empresa_json=json.dumps(empresa, ensure_ascii=False),
            alternativas_json=json.dumps(c["alternativas"], ensure_ascii=False), texto_web=texto_web[:MAX_TEXTO_WEB_PROMPT],
        ), SugerenciaValor)
        coste += rv.coste_eur
        if rv.datos is None:
            contadores["sin_resolver"] += 1
            continue
        elegida = next((a for a in c["alternativas"] if rv.datos.valor and rv.datos.valor in (a.get("valor"), a.get("valor_norm"))), None)
        if elegida and rv.datos.confianza >= CONFIANZA_MINIMA_AUTOMATICA:
            _aplicar_valor(conn, c, elegida, f"Resuelto automáticamente (IA, confianza {rv.datos.confianza:.2f}): {rv.datos.motivo}")
            contadores["resueltas_por_ia"] += 1
        else:
            _guardar_sugerencia(conn, c["id"], {"origen": "ia", **rv.datos.model_dump()})
            contadores["con_sugerencia"] += 1
        conn.commit()

    return {**contadores, "coste_eur": round(coste, 4)}
