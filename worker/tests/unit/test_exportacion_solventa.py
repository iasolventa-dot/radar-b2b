"""Exportación XML para Solventa DB (formato «solventa-db» v1). Sin BD."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from radar.exportacion.solventa import (
    EmpresaExportable,
    PersonaCargo,
    capitalizar,
    construir_xml_solventa,
    empresa_a_cliente,
    telefono_nacional,
)

# Nombres EXACTOS de campo de Solventa DB (data/clientes.json, lib/campos.ts).
CAMPOS_SOLVENTA = {
    "Razón Social", "NIF", "Contacto", "Cargo", "TELEFONO 1", "TELEFONO 2", "Email", "E-MAIL CORPORATIVO", "Web",
    "Dirección", "CP", "Población", "Provincia", "CNAE", "ACTIVIDAD", "SECTORES", "TRABAJADORES", "Estado",
    "Origen Cliente", "Observaciones",
}


def _empresa(**k) -> EmpresaExportable:
    base = {
        "id": "e1", "razon_social": "SEVILLA FUGAS SOCIEDAD LIMITADA", "nombre_comercial": "Sevilla Fugas", "nif": "b26816876",
        "dominio_web": "sevillafugas.es", "cnae": "4322", "objeto_social": "Instalaciones de fontanería", "municipio": "ALCALA DE GUADAIRA",
        "provincia": "Sevilla", "codigo_postal": "41500", "direccion": "Pol. San Nicolás 8",
        "telefonos": ["+34625739424", "+34 954 00 00 00"], "emails": [("info@sevillafugas.es", True), ("javier@sevillafugas.es", False)],
        "personas": [PersonaCargo("CONSEJERO UNO", "consejero"), PersonaCargo("RUIZ BULNES FRANCISCO JAVIER", "administrador_solidario")],
        "completitud": 5, "confianza": 0.86, "clasificacion": "relevante",
    }
    base.update(k)
    return EmpresaExportable(**base)  # type: ignore[arg-type]


def test_telefono_en_formato_de_solventa() -> None:
    assert telefono_nacional("+34625739424") == "625739424"
    assert telefono_nacional("0034 954 00 00 00") == "954000000"
    assert telefono_nacional("954 00 00 00") == "954000000"
    assert telefono_nacional("+56227550549") == "+56227550549"


def test_capitalizar_poblacion() -> None:
    assert capitalizar("ALCALA DE GUADAIRA") == "Alcala de Guadaira"
    assert capitalizar("Dos Hermanas") == "Dos Hermanas"


def test_ficha_con_los_nombres_y_formatos_de_solventa() -> None:
    ficha, adicionales = empresa_a_cliente(_empresa(), peticion="fontaneros", sector="Fontanería", fecha="2026-10-06")
    assert set(ficha) <= CAMPOS_SOLVENTA
    assert ficha["Razón Social"] == "SEVILLA FUGAS SOCIEDAD LIMITADA"
    assert ficha["NIF"] == "B26816876"
    # contacto preferente: el de mayor jerarquía registral
    assert ficha["Contacto"] == "RUIZ BULNES FRANCISCO JAVIER" and ficha["Cargo"] == "Administrador solidario"
    assert ficha["TELEFONO 1"] == "625739424" and ficha["TELEFONO 2"] == "954000000"
    # email personal como contacto; el genérico como corporativo
    assert ficha["Email"] == "javier@sevillafugas.es" and ficha["E-MAIL CORPORATIVO"] == "info@sevillafugas.es"
    assert ficha["Web"] == "https://sevillafugas.es"
    assert ficha["Población"] == "Alcala de Guadaira" and ficha["CP"] == "41500"
    assert ficha["Estado"] == "Lead" and ficha["Origen Cliente"] == "RADAR B2B" and ficha["SECTORES"] == "FONTANERÍA"
    assert adicionales == [{"nombre": "CONSEJERO UNO", "cargo": "Consejero", "telefono": "", "email": ""}]


def test_autonomo_tiene_al_titular_como_contacto() -> None:
    ficha, _ = empresa_a_cliente(
        _empresa(razon_social="Lorena Pérez Castro", nif="47207714F", es_persona_fisica=True, personas=[]),
        peticion="x", sector=None, fecha="2026-10-06",
    )
    assert ficha["Contacto"] == "Lorena Pérez Castro" and ficha["Cargo"] == "Propietario"


def test_campos_vacios_no_se_exportan() -> None:
    ficha, adicionales = empresa_a_cliente(
        EmpresaExportable(id="e2", razon_social=None, nombre_comercial="Fontanero JT", nif=None, telefonos=["+34659075283"]),
        peticion="x", sector=None, fecha="2026-10-06",
    )
    assert ficha["Razón Social"] == "Fontanero JT"
    assert "NIF" not in ficha and "Email" not in ficha and "Contacto" not in ficha
    assert adicionales == []


def test_xml_valido_y_completo() -> None:
    xml = construir_xml_solventa(
        busqueda_id="b1", peticion="fontaneros en Dos Hermanas", descripcion="Zona: Dos Hermanas · Sector: Fontanería",
        creada="2026-10-02T06:40:05+00:00", sector="Fontanería", empresas=[_empresa()],
        generado=datetime(2026, 10, 6, 12, 0, tzinfo=UTC),
    )
    assert xml.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
    raiz = ET.fromstring(xml)
    assert raiz.tag == "exportacion" and raiz.get("formato") == "solventa-db" and raiz.get("version") == "1"
    lista = raiz.find("lista")
    assert lista is not None and lista.get("nombre") == "fontaneros en Dos Hermanas" and lista.get("total") == "1"
    cliente = raiz.find("clientes/cliente")
    assert cliente is not None and cliente.get("completitud") == "5" and cliente.get("radar-id") == "e1"
    campos = {c.get("nombre"): c.text for c in cliente.findall("campo")}
    assert campos["Razón Social"] == "SEVILLA FUGAS SOCIEDAD LIMITADA"
    contacto = cliente.find("contactos-adicionales/contacto")
    assert contacto is not None and contacto.findtext("nombre") == "CONSEJERO UNO"
