"""Exportación de una búsqueda a Solventa DB (el mini-CRM de Solventa IA,
repo iasolventa-dot/solventa-db) en XML — formato «solventa-db», versión 1.

Solventa DB guarda cada cliente como un objeto JSON con nombres de campo en
español tal cual venían de Airtable («Razón Social», «NIF», «TELEFONO 1»,
«Email», «Población»...). Este XML usa EXACTAMENTE esos nombres en
`<campo nombre="...">`, ya con los formatos que espera (teléfono español de 9
cifras sin +34, NIF en mayúsculas, provincia por nombre, web con https://), de
modo que el importador de Solventa DB solo tiene que copiar cada campo a la
ficha. Las personas adicionales van en `<contactos-adicionales>` con la misma
forma que su campo `ContactosAdicionales` ({nombre, cargo, telefono, email}).
Lo propio de Radar (completitud, confianza, de qué fuente sale cada dato) va en
atributos y en `<evidencias>`: informativo, no altera la ficha.

Especificación completa: docs/formato_exportacion_solventa_db.md.

Estructura:

    <?xml version="1.0" encoding="UTF-8"?>
    <exportacion origen="Radar B2B" formato="solventa-db" version="1" generado="ISO-8601">
      <lista radar-busqueda-id="uuid" nombre="..." creada="ISO-8601" total="N">
        <descripcion>Zona: ... · Sector: ...</descripcion>
      </lista>
      <clientes>
        <cliente radar-id="uuid" completitud="0-5" confianza="0.00-1.00" clasificacion="relevante|dudoso|">
          <campo nombre="Razón Social">...</campo>
          ...
          <contactos-adicionales>
            <contacto><nombre/><cargo/><telefono/><email/></contacto>
          </contactos-adicionales>
          <evidencias>
            <evidencia campo="NIF" fuente="..." url="..." fecha="AAAA-MM-DD"/>
          </evidencias>
        </cliente>
      </clientes>
    </exportacion>
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import psycopg

from radar.normalizacion.dominio import normalizar_email

FORMATO = "solventa-db"
VERSION = "1"

# Mismos rótulos que el panel de Radar (web/src/lib/tipos.ts::ETIQUETA_CARGO).
ETIQUETA_CARGO = {
    "administrador_unico": "Administrador único",
    "administrador_solidario": "Administrador solidario",
    "administrador_mancomunado": "Administrador mancomunado",
    "consejero_delegado": "Consejero delegado",
    "consejero": "Consejero",
    "presidente": "Presidente",
}
PRIORIDAD_CARGO = {"presidente": 1, "consejero_delegado": 2, "administrador_unico": 3, "administrador_solidario": 4,
                   "administrador_mancomunado": 5, "consejero": 6}
# En Solventa DB el titular de un negocio sin sociedad figura como «Propietario».
CARGO_AUTONOMO = "Propietario"
ESTADO_INICIAL = "Lead"
ORIGEN = "RADAR B2B"
MAX_ACTIVIDAD = 300


@dataclass
class PersonaCargo:
    nombre: str
    cargo: str
    fuente: str | None = None


@dataclass
class EmpresaExportable:
    """Todo lo que Radar sabe de una empresa de la búsqueda (sin decidir
    todavía cómo se escribe en Solventa DB)."""

    id: str
    razon_social: str | None
    nombre_comercial: str | None
    nif: str | None
    es_persona_fisica: bool = False
    dominio_web: str | None = None
    cnae: str | None = None
    objeto_social: str | None = None
    empleados_min: int | None = None
    empleados_max: int | None = None
    direccion: str | None = None
    codigo_postal: str | None = None
    municipio: str | None = None
    provincia: str | None = None
    telefonos: list[str] = field(default_factory=list)
    emails: list[tuple[str, bool]] = field(default_factory=list)  # (email, es_generico)
    personas: list[PersonaCargo] = field(default_factory=list)
    completitud: int = 0
    confianza: float | None = None
    clasificacion: str | None = None
    motivo: str | None = None
    evidencias: list[dict[str, str]] = field(default_factory=list)


def telefono_nacional(telefono: str) -> str:
    """'+34954123456' -> '954123456' (como guarda Solventa DB); los
    extranjeros se dejan con su prefijo internacional."""
    digitos = re.sub(r"\D", "", telefono or "")
    if len(digitos) == 11 and digitos.startswith("34"):
        return digitos[2:]
    if len(digitos) == 13 and digitos.startswith("0034"):
        return digitos[4:]
    if len(digitos) == 9:
        return digitos
    return telefono.strip()


_MINUSCULAS = {"de", "del", "la", "las", "los", "el", "y", "e", "o", "en", "a"}


def capitalizar(nombre: str) -> str:
    """'ALCALA DE GUADAIRA' -> 'Alcala de Guadaira' (solo si viene todo en mayúsculas)."""
    if not nombre.isupper():
        return nombre
    palabras = nombre.lower().split()
    return " ".join(w if (i and w in _MINUSCULAS) else w[:1].upper() + w[1:] for i, w in enumerate(palabras))


def _texto(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v)).strip() if v is not None else ""


def persona_principal(e: EmpresaExportable) -> tuple[str, str]:
    """(nombre, cargo) del contacto preferente: el cargo de la web (gerente,
    CEO...) o el de mayor jerarquía registral; en un autónomo, el titular."""
    if e.personas:
        p = min(e.personas, key=lambda x: PRIORIDAD_CARGO.get(x.cargo, 0))
        return p.nombre, ETIQUETA_CARGO.get(p.cargo, p.cargo)
    if e.es_persona_fisica and e.razon_social:
        return e.razon_social, CARGO_AUTONOMO
    return "", ""


def empresa_a_cliente(e: EmpresaExportable, *, peticion: str, sector: str | None, fecha: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Ficha de Solventa DB (solo campos con valor) y contactos adicionales."""
    nombre, cargo = persona_principal(e)
    tels = list(dict.fromkeys(telefono_nacional(t) for t in e.telefonos if t))
    # Email del contacto: uno personal si lo hay; el genérico (info@...) va a
    # «E-MAIL CORPORATIVO» si además hay otro.
    personales = [m for m, generico in e.emails if not generico]
    genericos = [m for m, generico in e.emails if generico]
    email = (personales or genericos or [""])[0]
    corporativo = next((m for m in genericos + personales if m != email), "")
    empleados = e.empleados_max or e.empleados_min
    observaciones = [
        f"Importado de Radar B2B el {fecha} (búsqueda «{peticion}»).",
        f"Completitud {e.completitud}/5" + (f", confianza {e.confianza:.2f}." if e.confianza is not None else "."),
    ]
    if e.nombre_comercial and e.nombre_comercial != e.razon_social:
        observaciones.append(f"Nombre comercial: {e.nombre_comercial}.")
    if e.clasificacion == "dudoso":
        observaciones.append("Radar no pudo confirmar que sea del sector buscado.")

    cliente = {
        "Razón Social": _texto(e.razon_social or e.nombre_comercial),
        "NIF": _texto(e.nif).upper(),
        "Contacto": _texto(nombre),
        "Cargo": _texto(cargo),
        "TELEFONO 1": tels[0] if tels else "",
        "TELEFONO 2": tels[1] if len(tels) > 1 else "",
        "Email": email,
        "E-MAIL CORPORATIVO": corporativo,
        "Web": f"https://{e.dominio_web}" if e.dominio_web else "",
        "Dirección": _texto(e.direccion),
        "CP": _texto(e.codigo_postal),
        "Población": capitalizar(_texto(e.municipio)),
        "Provincia": _texto(e.provincia),
        "CNAE": _texto(e.cnae),
        "ACTIVIDAD": _texto(e.objeto_social)[:MAX_ACTIVIDAD],
        "SECTORES": _texto(sector).upper(),
        "TRABAJADORES": str(empleados) if empleados else "",
        "Estado": ESTADO_INICIAL,
        "Origen Cliente": ORIGEN,
        "Observaciones": " ".join(observaciones),
    }
    adicionales = [
        {"nombre": _texto(p.nombre), "cargo": ETIQUETA_CARGO.get(p.cargo, p.cargo), "telefono": "", "email": ""}
        for p in e.personas if _texto(p.nombre) and _texto(p.nombre) != cliente["Contacto"]
    ]
    adicionales = list({(a["nombre"].lower(), a["cargo"]): a for a in adicionales}.values())
    return {k: v for k, v in cliente.items() if v}, adicionales


def construir_xml_solventa(
    *, busqueda_id: str, peticion: str, descripcion: str, creada: str, sector: str | None, empresas: list[EmpresaExportable],
    generado: datetime | None = None,
) -> bytes:
    generado = generado or datetime.now(UTC)
    fecha = generado.date().isoformat()
    raiz = ET.Element("exportacion", {"origen": "Radar B2B", "formato": FORMATO, "version": VERSION,
                                      "generado": generado.isoformat(timespec="seconds")})
    lista = ET.SubElement(raiz, "lista", {"radar-busqueda-id": busqueda_id, "nombre": peticion, "creada": creada,
                                          "total": str(len(empresas))})
    ET.SubElement(lista, "descripcion").text = descripcion
    clientes = ET.SubElement(raiz, "clientes")
    for e in empresas:
        ficha, adicionales = empresa_a_cliente(e, peticion=peticion, sector=sector, fecha=fecha)
        atributos = {"radar-id": e.id, "completitud": str(e.completitud), "clasificacion": e.clasificacion or ""}
        if e.confianza is not None:
            atributos["confianza"] = f"{e.confianza:.2f}"
        nodo = ET.SubElement(clientes, "cliente", atributos)
        for nombre, valor in ficha.items():
            ET.SubElement(nodo, "campo", {"nombre": nombre}).text = valor
        if adicionales:
            contactos = ET.SubElement(nodo, "contactos-adicionales")
            for a in adicionales:
                c = ET.SubElement(contactos, "contacto")
                for k in ("nombre", "cargo", "telefono", "email"):
                    ET.SubElement(c, k).text = a[k]
        if e.evidencias:
            ev = ET.SubElement(nodo, "evidencias")
            for d in e.evidencias:
                ET.SubElement(ev, "evidencia", {k: v for k, v in d.items() if v})
    ET.indent(raiz)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(raiz, encoding="utf-8") + b"\n"


# --- Lectura desde la base de datos --------------------------------------------

_SQL_EMPRESAS = """
select r.empresa_id::text, r.razon_social, r.nombre_comercial, r.nif, r.es_persona_fisica, r.dominio_web,
       e.cnae_principal, e.objeto_social, e.empleados_min, e.empleados_max,
       r.completitud, r.confianza_global, r.clasificacion, r.motivo
from resultados_busqueda(%s, 100000, 0) r join empresas e on e.id = r.empresa_id
"""
_SQL_SEDES = """
select distinct on (s.empresa_id) s.empresa_id::text, s.direccion_original, s.codigo_postal, s.municipio_nombre, s.provincia
from sedes s where s.empresa_id = any(%s)
order by s.empresa_id, s.activa desc nulls last, (s.tipo = 'domicilio_social') desc, s.confianza desc nulls last
"""
_SQL_CANALES = """
select c.empresa_id::text, c.tipo, c.valor, coalesce(c.es_generico, false)
from canales_contacto c where c.empresa_id = any(%s) and c.estado is distinct from 'invalido'
order by c.empresa_id, c.confianza desc nulls last
"""
_SQL_CARGOS = """
select c.empresa_id::text, p.nombre, c.cargo, f.nombre
from cargos c join personas p on p.id = c.persona_id left join fuentes f on f.id = c.fuente_id
where c.empresa_id = any(%s)
"""
_SQL_EVIDENCIAS = """
select distinct on (o.empresa_id, o.campo) o.empresa_id::text, o.campo, f.nombre, o.url_evidencia, o.observado_en::date::text
from observaciones o join fuentes f on f.id = o.fuente_id
where o.empresa_id = any(%s) and o.vigente and o.campo in ('nif', 'razon_social', 'telefono', 'email')
order by o.empresa_id, o.campo, o.confianza_fuente desc nulls last, o.observado_en desc
"""
_CAMPO_SOLVENTA = {"nif": "NIF", "razon_social": "Razón Social", "telefono": "TELEFONO 1", "email": "Email"}


def exportar_busqueda_solventa(conn: psycopg.Connection, busqueda_id: str) -> tuple[bytes, str]:
    """XML de los resultados visibles de una búsqueda (los mismos y en el mismo
    orden que el panel: sin descartadas, de más a menos completos) y un nombre
    de fichero sugerido."""
    b = conn.execute("select peticion, filtros, creado_en from busquedas where id = %s", (busqueda_id,)).fetchone()
    if b is None:
        raise LookupError(f"no existe la búsqueda {busqueda_id}")
    peticion, filtros, creado_en = b
    filtros = filtros or {}
    sector = ((filtros.get("sector") or {}).get("sector_interno")) or None
    ubic = filtros.get("ubicacion") or {}
    zona = ", ".join(ubic.get("municipios") or ubic.get("provincias") or ubic.get("ccaa") or []) or "sin zona"
    descripcion = f"Zona: {zona} · Sector: {sector or '—'}"

    empresas: dict[str, EmpresaExportable] = {}
    for f in conn.execute(_SQL_EMPRESAS, (busqueda_id,)).fetchall():
        empresas[f[0]] = EmpresaExportable(
            id=f[0], razon_social=f[1], nombre_comercial=f[2], nif=f[3], es_persona_fisica=bool(f[4]), dominio_web=f[5],
            cnae=f[6], objeto_social=f[7], empleados_min=f[8], empleados_max=f[9], completitud=f[10],
            confianza=float(f[11]) if f[11] is not None else None, clasificacion=f[12], motivo=f[13],
        )
    ids = list(empresas)
    if ids:
        for eid, direccion, cp, municipio, provincia in conn.execute(_SQL_SEDES, (ids,)).fetchall():
            e = empresas[eid]
            e.direccion, e.codigo_postal, e.municipio, e.provincia = direccion, cp, municipio, provincia
        for eid, tipo, valor, generico in conn.execute(_SQL_CANALES, (ids,)).fetchall():
            if tipo == "telefono":
                empresas[eid].telefonos.append(valor)
            elif tipo == "email":
                # Se recalcula con la lista actual de buzones genéricos (la marca
                # guardada es la del momento de la captura).
                empresas[eid].emails.append((valor, bool(generico) or bool(normalizar_email(valor)["es_generico"])))
        for eid, nombre, cargo, fuente in conn.execute(_SQL_CARGOS, (ids,)).fetchall():
            empresas[eid].personas.append(PersonaCargo(nombre, cargo, fuente))
        for eid, campo, fuente, url, fecha in conn.execute(_SQL_EVIDENCIAS, (ids,)).fetchall():
            empresas[eid].evidencias.append(
                {"campo": _CAMPO_SOLVENTA[campo], "fuente": fuente or "", "url": url or "", "fecha": fecha or ""}
            )
    xml = construir_xml_solventa(
        busqueda_id=busqueda_id, peticion=peticion, descripcion=descripcion,
        creada=creado_en.isoformat(timespec="seconds"), sector=sector, empresas=list(empresas.values()),
    )
    base = re.sub(r"[^a-z0-9]+", "-", peticion.lower().translate(str.maketrans("áéíóúñü", "aeiounu"))).strip("-")[:60]
    return xml, f"radar-{base or 'busqueda'}.xml"
