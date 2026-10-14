"""Exportación XML para Solventa DB (formato «solventa-db» v2: la ficha tal
cual la guarda Solventa DB en data/clientes.json). Sin BD."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime

from radar.exportacion.solventa import (
    CAMPOS_SOLVENTA,
    EmpresaExportable,
    PersonaCargo,
    capitalizar,
    cargo_solventa,
    construir_xml_solventa,
    empresa_a_cliente,
    provincia_solventa,
    sector_solventa,
    telefono_nacional,
    web_solventa,
)

HOY = date(2026, 10, 14)


def _empresa(**k) -> EmpresaExportable:
    base = {
        "id": "e1", "razon_social": "Sevilla Fugas Sociedad Limitada", "nombre_comercial": "Sevilla Fugas", "nif": "b26816876",
        "forma_juridica": "SL", "estado": "probablemente_activa", "fecha_constitucion": date(2019, 3, 5),
        "dominio_web": "sevillafugas.es", "objeto_social": "Instalaciones de fontanería", "municipio": "ALCALA DE GUADAIRA",
        "provincia": "Sevilla", "codigo_postal": "41500", "direccion": "Pol. San Nicolás 8",
        "telefonos": ["+34 954 00 00 00", "+34625739424", "+34955111222"],
        "emails": [("info@sevillafugas.es", True), ("javier@sevillafugas.es", False), ("obras@sevillafugas.es", True)],
        "personas": [
            PersonaCargo("CONSEJERO UNO", "consejero"),
            PersonaCargo("RUIZ BULNES FRANCISCO JAVIER", "administrador_solidario"),
            PersonaCargo("Ana López", "Responsable de RRHH"),
            PersonaCargo("Quien Sea", "Responsable del tratamiento de datos"),
        ],
    }
    base.update(k)
    return EmpresaExportable(**base)  # type: ignore[arg-type]


def test_formatos_de_solventa() -> None:
    assert telefono_nacional("+34625739424") == "625739424"
    assert telefono_nacional("0034 954 00 00 00") == "954000000"
    assert telefono_nacional("+56227550549") == "+56227550549"
    assert capitalizar("ALCALA DE GUADAIRA") == "Alcala de Guadaira"
    assert capitalizar("Dos Hermanas") == "Dos Hermanas"
    assert capitalizar("c/ san jose 28 (dos hermanas)") == "C/ San Jose 28 (Dos Hermanas)"
    assert provincia_solventa(None, "41701") == "Sevilla" and provincia_solventa("MALAGA", None) == "Malaga"
    assert web_solventa("sevillafugas.es") == "www.sevillafugas.es"
    assert web_solventa("www.x.com") == "www.x.com"


def test_vocabulario_de_cargos_y_sectores() -> None:
    assert cargo_solventa("administrador_unico") == "DIRECTOR GRAL"
    assert cargo_solventa("CEO") == "DIRECTOR GRAL"
    assert cargo_solventa("Gerente") == "Gerente"
    assert cargo_solventa("Socio fundador") == "Socio"
    assert cargo_solventa("Director de Recursos Humanos") == "RRHH"
    assert cargo_solventa("Dpto. Facturación") == "Admon."
    assert cargo_solventa("Arquitecto Técnico") == "TECNICO"
    assert cargo_solventa("vocal") == "Vocal"
    assert sector_solventa("Fontanería") == "FONTANERIA"
    assert sector_solventa("construcción") == "CONSTRUCCIÓN"
    assert sector_solventa("reformas integrales") == "CONSTRUCCIÓN"
    assert sector_solventa("", []) == ""
    assert sector_solventa("Astrología") == "ASTROLOGÍA"


def test_ficha_completa_con_campos_y_orden_de_solventa() -> None:
    ficha, adicionales = empresa_a_cliente(_empresa(), peticion="fontaneros", sector="FONTANERIA", fecha=HOY)
    assert tuple(ficha) == CAMPOS_SOLVENTA  # todos, en el orden de lib/campos.ts
    assert ficha["Razón Social"] == "SEVILLA FUGAS SOCIEDAD LIMITADA"
    assert ficha["NIF"] == "B26816876"
    # contacto preferente: el de más rango, en «Nombre Apellidos» capitalizado y con el cargo de Solventa
    assert ficha["Contacto"] == "Ruiz Bulnes Francisco Javier" and ficha["Cargo"] == "DIRECTOR GRAL"
    # móvil en TELEFONO 1, fijo en TELEFONO 2, el resto a observaciones
    assert ficha["TELEFONO 1"] == "625739424" and ficha["TELEFONO 2"] == "954000000"
    assert ficha["Email"] == "javier@sevillafugas.es" and ficha["E-MAIL CORPORATIVO"] == "info@sevillafugas.es"
    assert ficha["Web"] == "www.sevillafugas.es"
    assert ficha["Población"] == "Alcala de Guadaira" and ficha["CP"] == "41500" and ficha["Provincia"] == "Sevilla"
    assert ficha["Estado"] == "Lead" and ficha["Origen Cliente"] == "RADAR B2B" and ficha["SECTORES"] == "FONTANERIA"
    assert ficha["ACTIVIDAD"] == "Instalaciones de fontanería"
    assert ficha["Agente Responsable"] == "" and ficha["FACTURACION"] == ""
    obs = ficha["Observaciones"]
    assert "14/10/2026" in obs and "Nombre comercial: Sevilla Fugas" in obs
    assert "Forma jurídica: SL; constituida el 05/03/2019" in obs
    assert "Cargos en el BORME: Ruiz Bulnes Francisco Javier (Administrador solidario); Consejero Uno (Consejero)" in obs
    assert "Otros teléfonos: 955111222" in obs and "Otros emails: obras@sevillafugas.es" in obs
    # el responsable del tratamiento de datos de un aviso legal no es un contacto
    assert adicionales == [
        {"nombre": "Consejero Uno", "cargo": "DIRECTOR GRAL", "telefono": "", "email": ""},
        {"nombre": "Ana López", "cargo": "RRHH", "telefono": "", "email": ""},
    ]


def test_autonomo_es_propietario() -> None:
    ficha, _ = empresa_a_cliente(
        _empresa(razon_social="LORENA PÉREZ CASTRO", nif="47207714F", es_persona_fisica=True, personas=[], forma_juridica=None),
        peticion="x", sector="", fecha=HOY,
    )
    assert ficha["Contacto"] == "Lorena Pérez Castro" and ficha["Cargo"] == "Propietario"


def test_empresa_extinguida_y_vacios() -> None:
    ficha, adicionales = empresa_a_cliente(
        EmpresaExportable(id="e2", razon_social=None, nombre_comercial="Fontanero JT", nif=None, estado="extinguida",
                          telefonos=["+34954000000"]),
        peticion="x", sector="", fecha=HOY,
    )
    assert ficha["Razón Social"] == "FONTANERO JT" and ficha["Estado"] == "Extinguida"
    assert ficha["TELEFONO 1"] == "" and ficha["TELEFONO 2"] == "954000000"
    assert ficha["NIF"] == "" and ficha["Contacto"] == "" and adicionales == []


def test_xml_valido_sin_estructura_de_radar() -> None:
    xml = construir_xml_solventa(
        busqueda_id="b1", peticion="fontaneros en Dos Hermanas", descripcion="Zona: Dos Hermanas · Sector: Fontanería",
        creada="2026-10-02T06:40:05+00:00", sector="Fontanería", empresas=[_empresa()],
        generado=datetime(2026, 10, 14, 12, 0, tzinfo=UTC),
    )
    assert xml.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
    raiz = ET.fromstring(xml)
    assert raiz.get("formato") == "solventa-db" and raiz.get("version") == "2"
    lista = raiz.find("lista")
    assert lista is not None and lista.get("total") == "1" and lista.get("radar-busqueda-id") == "b1"
    cliente = raiz.find("clientes/cliente")
    assert cliente is not None and cliente.attrib == {}  # sin completitud/confianza/clasificación
    assert cliente.find("evidencias") is None
    campos = {c.get("nombre"): c.text or "" for c in cliente.findall("campo")}
    assert tuple(campos) == CAMPOS_SOLVENTA and campos["SECTORES"] == "FONTANERIA"
    contacto = cliente.find("ContactosAdicionales/contacto")
    assert contacto is not None and contacto.findtext("nombre") == "Consejero Uno"
