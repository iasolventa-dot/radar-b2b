"""Exportación de una búsqueda a Solventa DB (el mini-CRM de Solventa IA,
repo iasolventa-dot/solventa-db) en XML — formato «solventa-db», versión 2.

Cada `<cliente>` es una ficha de Solventa DB tal cual la guarda en
`data/clientes.json`: los MISMOS campos (todos los de `lib/campos.ts::BLOQUES`,
en ese orden, también los vacíos), con los MISMOS formatos y vocabularios que
ya usan sus 1.079 clientes (perfilados el 2026-10-14):

- «Razón Social» en mayúsculas; «Contacto» capitalizado («Ruiz Bulnes Francisco Javier»: el
  BORME da los apellidos primero y no se reordenan, porque los compuestos lo harían adivinar).
- «TELEFONO 1» = móvil y «TELEFONO 2» = fijo, 9 cifras sin +34.
- «Web» como `www.dominio.es` (sin https://).
- «Cargo», «SECTORES» y «Estado» con los valores que ya existen en Solventa
  («DIRECTOR GRAL», «Propietario», «Admon.»…; «FONTANERIA», «CONSTRUCCIÓN»…; «Lead»).
- Las demás personas, en `<ContactosAdicionales>` con la forma de ese campo.

Nada de la estructura de Radar (completitud, confianza, clasificación,
evidencias por campo): eso es para filtrar búsquedas dentro de Radar. Lo que
Radar sabe y Solventa no tiene campo para ello (nombre comercial, forma
jurídica, administradores con su cargo exacto del BORME, otros teléfonos y
emails, objeto social...) va en «Observaciones».

Especificación: docs/formato_exportacion_solventa_db.md.

    <?xml version="1.0" encoding="UTF-8"?>
    <exportacion origen="Radar B2B" formato="solventa-db" version="2" generado="ISO-8601">
      <lista radar-busqueda-id="uuid" nombre="..." creada="ISO-8601" total="N">
        <descripcion>Zona: ... · Sector: ...</descripcion>
      </lista>
      <clientes>
        <cliente>
          <campo nombre="Contacto">...</campo>      <!-- todos los campos, vacíos incluidos -->
          ...
          <ContactosAdicionales>                     <!-- opcional -->
            <contacto><nombre/><cargo/><telefono/><email/></contacto>
          </ContactosAdicionales>
        </cliente>
      </clientes>
    </exportacion>
"""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import psycopg

from radar.normalizacion.direccion import PROVINCIAS
from radar.normalizacion.dominio import normalizar_email

FORMATO = "solventa-db"
VERSION = "2"

# Campos de una ficha de Solventa DB, en el orden de lib/campos.ts::BLOQUES.
CAMPOS_SOLVENTA = (
    # Datos de contacto
    "Contacto", "Cargo", "Email", "E-MAIL CORPORATIVO", "TELEFONO 1", "TELEFONO 2", "Web",
    # Datos de la empresa
    "Razón Social", "NIF", "Dirección", "CP", "Población", "Provincia", "CNAE", "ACTIVIDAD", "SECTORES",
    "TRABAJADORES", "FACTURACION",
    # Asesoría
    "Asesoría", "Contacto Asesoría", "Teléfono Asesoría", "Email Asesoría",
    # Gestión comercial
    "Estado", "Agente Responsable", "Origen Cliente", "SERVICIO-PRODUCTO", "FECHA GESTION", "Gestiones",
    "Resumen IA de Gestiones", "Acción", "Observaciones",
    # Seguros y energía
    "SEGURO (TIPO)", "ASEGURADORA", "POLIZAS", "COMPAÑÍA ENERGÍA", "CONTRATO ENERGÍA",
    # Otros
    "Fotos de la Empresa",
)

ORIGEN = "RADAR B2B"
ESTADO_LEAD = "Lead"
MAX_ACTIVIDAD = 150

# --- Vocabularios de Solventa DB -------------------------------------------------

# Cargo (valores existentes en clientes.json): de más a menos prioritario como
# contacto preferente.
CARGO_DIRECCION = "DIRECTOR GRAL"
CARGO_PROPIETARIO = "Propietario"
CARGO_GERENTE = "Gerente"
CARGO_SOCIO = "Socio"
CARGO_ADMON = "Admon."
CARGO_RRHH = "RRHH"
CARGO_TECNICO = "TECNICO"
PRIORIDAD_CARGO_SOLVENTA = {
    CARGO_DIRECCION: 1, CARGO_PROPIETARIO: 1, CARGO_GERENTE: 2, CARGO_SOCIO: 3, CARGO_ADMON: 4, CARGO_RRHH: 5,
    CARGO_TECNICO: 6,
}
# Dentro de «DIRECTOR GRAL», el orden registral (mismo criterio que el panel de Radar).
PRIORIDAD_REGISTRAL = {"presidente": 1, "consejero_delegado": 2, "administrador_unico": 3, "administrador_solidario": 4,
                       "administrador_mancomunado": 5, "consejero": 6}
ETIQUETA_CARGO_BORME = {
    "administrador_unico": "Administrador único",
    "administrador_solidario": "Administrador solidario",
    "administrador_mancomunado": "Administrador mancomunado",
    "consejero_delegado": "Consejero delegado",
    "consejero": "Consejero",
    "presidente": "Presidente",
}
# (patrón sobre el cargo sin tildes y en minúsculas, cargo de Solventa). El
# primero que encaja gana: "Socio fundador, director y gerente" -> DIRECTOR GRAL.
_REGLAS_CARGO = (
    (r"recursos humanos|\brrhh\b|people", CARGO_RRHH),
    (
        (r"director(a)? (general|gerente|ejecutiv)|\bceo\b|managing director|consejero delegado|presidente|"
         r"administrador|direccion general|representante legal"),
        CARGO_DIRECCION,
    ),
    (r"propietari|titular", CARGO_PROPIETARIO),
    (r"gerent|gerencia", CARGO_GERENTE),
    (r"fundador|socio|socia\b", CARGO_SOCIO),
    (r"administraci|administrativ|facturaci|contab|financ|tesorer|secretari", CARGO_ADMON),
    (r"tecnic|ingenier|arquitect|jefe de obra|jefa de obra|produccion|delineante|encargado", CARGO_TECNICO),
)
# Cargos que no describen a una persona de la empresa (el responsable del
# tratamiento de datos de un aviso legal...): no son contacto.
_CARGO_SIN_VALOR = re.compile(r"responsable del tratamiento|nuestros|colaborador", re.IGNORECASE)
# «Contacto» no es un cargo: la persona se exporta, pero sin cargo y la última.
_SOLO_CONTACTO = re.compile(r"^(persona de )?contacto$", re.IGNORECASE)

# SECTORES (valores existentes en clientes.json). Palabras del sector de la
# búsqueda -> sector de Solventa; el primero que encaja gana.
_REGLAS_SECTOR = (
    (r"fontaner", "FONTANERIA"),
    (r"carpinteria metal", "CARPINTERIA METALICA"),
    (r"carpinter", "CARPINTERIA"),
    (r"pintur|decoraci", "PINTURA Y DECORACION"),
    (r"electric|energ|solar|fotovolt", "ELECTRICIDAD , ENERGIA"),
    (r"constru|reforma|obra|albañil|albanil|edifica|promoci|inmobiliari", "CONSTRUCCIÓN"),
    (r"hostel|restaura|\bbar\b|cafeter|hotel|catering", "HOSTELERIA"),
    (r"transport|logistic|mudanz|mensajer", "TRANSPORTES Y LOGISTICA"),
    (r"limpieza", "LIMPIEZA"),
    (r"automo|taller|vehicul|concesionari", "AUTOMOCIÓN"),
    (r"metal|soldad|cerrajer|forja", "METAL"),
    (r"asesor|gestori|contabl", "ASESORÍAS Y GESTORIAS"),
    (r"abogad|jurid", "DESPACHOS DE ABOGADOS"),
    (r"administraci(o|ó)n de fincas|administrador de fincas", "ADMINISTRACIÓN DE FINCAS"),
    (r"aliment|bebida|panader|bodega", "ALIMENTACIÓN Y BEBIDAS"),
    (r"agricol|agricult|ganader", "AGRICULTURA"),
    (r"farmac|quimic|sanitari|clinic|dental", "QUÍMICA, FARMACÉUTICA Y SANITARIA"),
    (r"deport|gimnas", "ACTIVIDADES DEPORTIVAS"),
    (r"financ|seguros|banca", "SERVICIOS FINANCIEROS"),
    (r"comunicaci|marketing|publicidad", "COMUNICACIÓN"),
    (r"mayorista|al por mayor|distribu", "COMERCIO AL POR MAYOR"),
    (r"comercio|tienda", "COMERCIO EN GENERAL"),
    (r"industri|fabrica", "INDUSTRIA"),
)

# Estado de Radar (enum estado_empresa) -> Estado de Solventa.
_ESTADO = {"extinguida": "Extinguida", "disuelta": "Extinguida", "inactiva": "Inactiva", "en_liquidacion": "Inactiva",
           "en_concurso": "Inactiva"}


@dataclass
class PersonaCargo:
    nombre: str
    cargo: str  # tal cual en Radar: "administrador_unico" (BORME) o texto libre de la web ("Gerente")
    fuente: str | None = None


@dataclass
class EmpresaExportable:
    """Todo lo que Radar sabe de una empresa de la búsqueda."""

    id: str
    razon_social: str | None
    nombre_comercial: str | None
    nif: str | None
    es_persona_fisica: bool = False
    forma_juridica: str | None = None
    estado: str | None = None
    fecha_constitucion: date | None = None
    dominio_web: str | None = None
    cnae: str | None = None
    objeto_social: str | None = None
    empleados_min: int | None = None
    empleados_max: int | None = None
    direccion: str | None = None
    codigo_postal: str | None = None
    municipio: str | None = None
    provincia: str | None = None
    otras_sedes: list[str] = field(default_factory=list)
    telefonos: list[str] = field(default_factory=list)
    emails: list[tuple[str, bool]] = field(default_factory=list)  # (email, es_generico)
    personas: list[PersonaCargo] = field(default_factory=list)
    sector_dudoso: bool = False


# --- Formatos ----------------------------------------------------------------------


def _texto(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v)).strip() if v is not None else ""


def _sin_tildes(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()


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


def es_movil(telefono_9: str) -> bool:
    return len(telefono_9) == 9 and telefono_9[0] in "67"


_MINUSCULAS = {"de", "del", "la", "las", "los", "el", "y", "e", "o", "en", "a", "i"}


def capitalizar(nombre: str) -> str:
    """'ALCALA DE GUADAIRA' -> 'Alcala de Guadaira' (solo si viene todo en
    mayúsculas o todo en minúsculas; lo demás se respeta)."""
    if not (nombre.isupper() or nombre.islower()):
        return nombre
    palabras = nombre.lower().split()
    return " ".join(w if (i and w in _MINUSCULAS) else _mayuscula_inicial(w) for i, w in enumerate(palabras))


def _mayuscula_inicial(palabra: str) -> str:
    """Primera LETRA en mayúscula aunque vaya tras un signo: '(dos' -> '(Dos'."""
    for i, ch in enumerate(palabra):
        if ch.isalpha():
            return palabra[:i] + ch.upper() + palabra[i + 1:]
    return palabra


def provincia_solventa(provincia: str | None, codigo_postal: str | None) -> str:
    """Provincia por nombre; si Radar no la tiene, la del código postal."""
    if provincia and provincia.strip():
        return capitalizar(_texto(provincia))
    cp = _texto(codigo_postal)
    return PROVINCIAS.get(cp[:2], "") if len(cp) == 5 and cp.isdigit() else ""


def web_solventa(dominio: str | None) -> str:
    """Solventa DB guarda la web como 'www.dominio.es' (sin protocolo)."""
    if not dominio:
        return ""
    d = re.sub(r"^[a-z]+://", "", dominio.strip().lower()).strip("/")
    return d if d.startswith("www.") else f"www.{d}"


def cargo_solventa(cargo: str) -> str:
    """Cargo de Radar -> vocabulario de Solventa DB. Si no encaja en ninguno, se
    deja el original con mayúscula inicial (Solventa admite valores nuevos).
    Un «Director/a» a secas (de arte, de proyectos... en una ficha de equipo) no
    es la dirección general: se deja tal cual. «Contacto» no es cargo: vacío."""
    if cargo in PRIORIDAD_REGISTRAL:
        return CARGO_DIRECCION
    if _SOLO_CONTACTO.match(_texto(cargo)):
        return ""
    texto = _sin_tildes(_texto(cargo))
    for patron, valor in _REGLAS_CARGO:
        if re.search(patron, texto):
            return valor
    limpio = _texto(cargo)
    return limpio[:1].upper() + limpio[1:]


def sector_solventa(sector: str | None, palabras_clave: list[str] | None = None) -> str:
    """Sector de la búsqueda -> valor de «SECTORES» de Solventa DB."""
    texto = _sin_tildes(" ".join([sector or "", *(palabras_clave or [])]))
    if not texto.strip():
        return ""
    for patron, valor in _REGLAS_SECTOR:
        if re.search(_sin_tildes(patron), texto):
            return valor
    return _texto(sector).upper()


def _fecha(d: date | datetime | None) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def _actividad(objeto_social: str | None) -> str:
    """Solventa usa descripciones cortas; el objeto social del BORME se corta
    en una palabra (el texto completo va en Observaciones)."""
    t = _texto(objeto_social)
    if len(t) <= MAX_ACTIVIDAD:
        return t
    return t[:MAX_ACTIVIDAD].rsplit(" ", 1)[0].rstrip(",;.") + "…"


# --- Ficha ---------------------------------------------------------------------------


def _personas_validas(e: EmpresaExportable) -> list[PersonaCargo]:
    vistas: dict[str, PersonaCargo] = {}
    for p in e.personas:
        nombre = _texto(p.nombre)
        if not nombre or "\n" in p.nombre or _CARGO_SIN_VALOR.search(_texto(p.cargo)):
            continue
        clave = _sin_tildes(nombre)
        actual = vistas.get(clave)
        # Si una persona sale en el BORME y en la web, manda el cargo de más rango.
        if actual is None or _orden_persona(p) < _orden_persona(actual):
            vistas[clave] = p
    return sorted(vistas.values(), key=_orden_persona)


def _orden_persona(p: PersonaCargo) -> tuple[int, int]:
    cargo = cargo_solventa(p.cargo)
    return (PRIORIDAD_CARGO_SOLVENTA.get(cargo, 8 if cargo else 9), PRIORIDAD_REGISTRAL.get(p.cargo, 0))


def contacto_preferente(e: EmpresaExportable) -> tuple[str, str, list[PersonaCargo]]:
    """(nombre, cargo) del contacto preferente y el resto de personas. En un
    autónomo sin personas, el propio titular como «Propietario»."""
    personas = _personas_validas(e)
    if personas:
        p = personas[0]
        return capitalizar(_texto(p.nombre)), cargo_solventa(p.cargo), personas[1:]
    if e.es_persona_fisica and e.razon_social:
        return capitalizar(_texto(e.razon_social)), CARGO_PROPIETARIO, []
    return "", "", []


def empresa_a_cliente(
    e: EmpresaExportable, *, peticion: str, sector: str, fecha: date,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Ficha de Solventa DB con TODOS sus campos (vacíos incluidos, en su
    orden) y la lista de ContactosAdicionales."""
    contacto, cargo, resto = contacto_preferente(e)

    tels = list(dict.fromkeys(telefono_nacional(t) for t in e.telefonos if t))
    moviles = [t for t in tels if es_movil(t)]
    fijos = [t for t in tels if not es_movil(t)]
    telefono_1 = moviles[0] if moviles else ""
    telefono_2 = fijos[0] if fijos else (moviles[1] if len(moviles) > 1 else "")
    otros_tels = [t for t in tels if t not in (telefono_1, telefono_2)]

    personales = [m for m, generico in e.emails if not generico]
    genericos = [m for m, generico in e.emails if generico]
    email = (personales or genericos or [""])[0]
    corporativo = next((m for m in genericos + personales if m != email), "")
    otros_emails = [m for m, _ in e.emails if m not in (email, corporativo)]

    empleados = e.empleados_max or e.empleados_min

    razon = _texto(e.razon_social or e.nombre_comercial).upper()
    obs = [f"Importado de Radar B2B el {_fecha(fecha)} (búsqueda «{peticion}»)."]
    if e.nombre_comercial and _sin_tildes(_texto(e.nombre_comercial)) != _sin_tildes(_texto(e.razon_social)):
        obs.append(f"Nombre comercial: {_texto(e.nombre_comercial)}.")
    registro = []
    if e.forma_juridica:
        registro.append(f"Forma jurídica: {e.forma_juridica}")
    if e.fecha_constitucion:
        registro.append(f"constituida el {_fecha(e.fecha_constitucion)}")
    if e.estado and e.estado not in ("activa", "probablemente_activa", "desconocida"):
        registro.append(f"estado registral: {e.estado.replace('_', ' ')}")
    if registro:
        obs.append("; ".join(registro) + ".")
    administradores = [
        f"{capitalizar(_texto(p.nombre))} ({ETIQUETA_CARGO_BORME[p.cargo]})"
        for p in sorted(e.personas, key=lambda x: PRIORIDAD_REGISTRAL.get(x.cargo, 9)) if p.cargo in ETIQUETA_CARGO_BORME
    ]
    if administradores:
        obs.append("Cargos en el BORME: " + "; ".join(dict.fromkeys(administradores)) + ".")
    if otros_tels:
        obs.append("Otros teléfonos: " + ", ".join(otros_tels) + ".")
    if otros_emails:
        obs.append("Otros emails: " + ", ".join(otros_emails) + ".")
    if e.otras_sedes:
        obs.append("Otras direcciones: " + "; ".join(e.otras_sedes) + ".")
    if e.objeto_social and len(_texto(e.objeto_social)) > MAX_ACTIVIDAD:
        obs.append(f"Objeto social: {_texto(e.objeto_social)}")
    if e.sector_dudoso:
        obs.append("Sector sin confirmar: revisar si encaja.")

    valores = {
        "Contacto": contacto,
        "Cargo": cargo,
        "Email": email,
        "E-MAIL CORPORATIVO": corporativo,
        "TELEFONO 1": telefono_1,
        "TELEFONO 2": telefono_2,
        "Web": web_solventa(e.dominio_web),
        "Razón Social": razon,
        "NIF": re.sub(r"[^A-Z0-9]", "", _texto(e.nif).upper()),
        "Dirección": capitalizar(_texto(e.direccion)),
        "CP": _texto(e.codigo_postal),
        "Población": capitalizar(_texto(e.municipio)),
        "Provincia": provincia_solventa(e.provincia, e.codigo_postal),
        "CNAE": _texto(e.cnae),
        "ACTIVIDAD": _actividad(e.objeto_social),
        "SECTORES": sector,
        "TRABAJADORES": str(empleados) if empleados else "",
        "Estado": _ESTADO.get(e.estado or "", ESTADO_LEAD),
        "Origen Cliente": ORIGEN,
        "Observaciones": "\n".join(obs),
    }
    ficha = {campo: valores.get(campo, "") for campo in CAMPOS_SOLVENTA}
    adicionales = [
        {"nombre": capitalizar(_texto(p.nombre)), "cargo": cargo_solventa(p.cargo), "telefono": "", "email": ""}
        for p in resto
    ]
    return ficha, adicionales


def construir_xml_solventa(
    *, busqueda_id: str, peticion: str, descripcion: str, creada: str, sector: str | None,
    palabras_clave: list[str] | None = None, empresas: list[EmpresaExportable], generado: datetime | None = None,
) -> bytes:
    generado = generado or datetime.now(UTC)
    sector_ficha = sector_solventa(sector, palabras_clave)
    raiz = ET.Element("exportacion", {"origen": "Radar B2B", "formato": FORMATO, "version": VERSION,
                                      "generado": generado.isoformat(timespec="seconds")})
    lista = ET.SubElement(raiz, "lista", {"radar-busqueda-id": busqueda_id, "nombre": peticion, "creada": creada,
                                          "total": str(len(empresas))})
    ET.SubElement(lista, "descripcion").text = descripcion
    clientes = ET.SubElement(raiz, "clientes")
    for e in empresas:
        ficha, adicionales = empresa_a_cliente(e, peticion=peticion, sector=sector_ficha, fecha=generado.date())
        nodo = ET.SubElement(clientes, "cliente")
        for nombre, valor in ficha.items():
            ET.SubElement(nodo, "campo", {"nombre": nombre}).text = valor
        if adicionales:
            contactos = ET.SubElement(nodo, "ContactosAdicionales")
            for a in adicionales:
                c = ET.SubElement(contactos, "contacto")
                for k in ("nombre", "cargo", "telefono", "email"):
                    ET.SubElement(c, k).text = a[k]
    ET.indent(raiz)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(raiz, encoding="utf-8") + b"\n"


# --- Lectura desde la base de datos --------------------------------------------

_SQL_EMPRESAS = """
select r.empresa_id::text, r.razon_social, r.nombre_comercial, r.nif, r.es_persona_fisica, r.dominio_web,
       e.cnae_principal, e.objeto_social, e.empleados_min, e.empleados_max, e.forma_juridica, e.estado::text,
       e.fecha_constitucion, r.clasificacion
from resultados_busqueda(%s, 100000, 0) r join empresas e on e.id = r.empresa_id
"""
_SQL_SEDES = """
select s.empresa_id::text, s.direccion_original, s.codigo_postal, s.municipio_nombre, s.provincia
from sedes s where s.empresa_id = any(%s)
order by s.empresa_id, s.activa desc nulls last, (s.tipo = 'domicilio_social') desc, s.confianza desc nulls last
"""
# Mismo criterio que resultados_busqueda() (migración 202610201000): fuera los
# teléfonos que aparecen en 3 o más webs distintas, y primero los españoles y
# los que no comparte ninguna otra web.
_SQL_CANALES = """
select c.empresa_id::text, c.tipo, c.valor, coalesce(c.es_generico, false)
from canales_contacto c
cross join lateral (select case when c.tipo = 'telefono' then webs_con_telefono(c.valor_norm) else 1 end as webs) w
where c.empresa_id = any(%s) and c.estado is distinct from 'invalido' and w.webs < 3
order by c.empresa_id, (c.tipo <> 'telefono' or c.valor like '+34%%') desc, (w.webs = 1) desc, c.confianza desc nulls last
"""
_SQL_CARGOS = """
select c.empresa_id::text, p.nombre, c.cargo, f.nombre
from cargos c join personas p on p.id = c.persona_id left join fuentes f on f.id = c.fuente_id
where c.empresa_id = any(%s) and c.vigente is not false
"""


def _texto_sede(direccion: str | None, cp: str | None, municipio: str | None) -> str:
    return ", ".join(x for x in (capitalizar(_texto(direccion)), _texto(cp), capitalizar(_texto(municipio))) if x)


def exportar_busqueda_solventa(conn: psycopg.Connection, busqueda_id: str) -> tuple[bytes, str]:
    """XML de los resultados visibles de una búsqueda (los mismos y en el mismo
    orden que el panel, sin descartadas) y un nombre de fichero sugerido."""
    b = conn.execute("select peticion, filtros, creado_en from busquedas where id = %s", (busqueda_id,)).fetchone()
    if b is None:
        raise LookupError(f"no existe la búsqueda {busqueda_id}")
    peticion, filtros, creado_en = b
    filtros = filtros or {}
    sector_filtro = filtros.get("sector") or {}
    sector = sector_filtro.get("sector_interno") or None
    ubic = filtros.get("ubicacion") or {}
    zona = ", ".join(ubic.get("municipios") or ubic.get("provincias") or ubic.get("ccaa") or []) or "sin zona"
    descripcion = f"Zona: {zona} · Sector: {sector or '—'}"

    empresas: dict[str, EmpresaExportable] = {}
    for f in conn.execute(_SQL_EMPRESAS, (busqueda_id,)).fetchall():
        empresas[f[0]] = EmpresaExportable(
            id=f[0], razon_social=f[1], nombre_comercial=f[2], nif=f[3], es_persona_fisica=bool(f[4]), dominio_web=f[5],
            cnae=f[6], objeto_social=f[7], empleados_min=f[8], empleados_max=f[9], forma_juridica=f[10], estado=f[11],
            fecha_constitucion=f[12], sector_dudoso=f[13] == "dudoso",
        )
    ids = list(empresas)
    if ids:
        for eid, direccion, cp, municipio, provincia in conn.execute(_SQL_SEDES, (ids,)).fetchall():
            e = empresas[eid]
            if e.direccion is None and e.municipio is None:
                e.direccion, e.codigo_postal, e.municipio, e.provincia = direccion, cp, municipio, provincia
            else:
                texto = _texto_sede(direccion, cp, municipio)
                if texto and texto != _texto_sede(e.direccion, e.codigo_postal, e.municipio) and texto not in e.otras_sedes:
                    e.otras_sedes.append(texto)
        for eid, tipo, valor, generico in conn.execute(_SQL_CANALES, (ids,)).fetchall():
            if tipo == "telefono":
                empresas[eid].telefonos.append(valor)
            elif tipo == "email":
                # Se recalcula con la lista actual de buzones genéricos (la marca
                # guardada es la del momento de la captura).
                empresas[eid].emails.append((valor, bool(generico) or bool(normalizar_email(valor)["es_generico"])))
        for eid, nombre, cargo, fuente in conn.execute(_SQL_CARGOS, (ids,)).fetchall():
            empresas[eid].personas.append(PersonaCargo(nombre, cargo, fuente))
    xml = construir_xml_solventa(
        busqueda_id=busqueda_id, peticion=peticion, descripcion=descripcion,
        creada=creado_en.isoformat(timespec="seconds"), sector=sector,
        palabras_clave=list(sector_filtro.get("palabras_clave") or []), empresas=list(empresas.values()),
    )
    base = re.sub(r"[^a-z0-9]+", "-", peticion.lower().translate(str.maketrans("áéíóúñü", "aeiounu"))).strip("-")[:60]
    return xml, f"radar-{base or 'busqueda'}.xml"
