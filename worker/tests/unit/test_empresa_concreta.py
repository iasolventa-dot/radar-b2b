"""Búsqueda de una empresa concreta: consultas e identificación. Sin BD ni red."""

from __future__ import annotations

from radar.agente.empresa_concreta import (
    Candidato,
    EmpresaObjetivo,
    clasificar_candidatos,
    consulta_mapas,
    consultas_web,
    filtros_de,
    nif_valido,
    peticion_de,
    puntuar_candidato,
    resumen_final,
)

OBJETIVO = EmpresaObjetivo(nombre="Sevilla Fugas", localidad="Alcalá de Guadaíra")


def test_datos_del_formulario_se_limpian() -> None:
    o = EmpresaObjetivo.desde_dict({"nombre": "  Sevilla Fugas ", "nif": " b-26816876 ", "localidad": "", "web": None})
    assert o.nombre == "Sevilla Fugas" and o.localidad is None and o.web is None
    assert o.nif_normalizado == "B26816876"
    assert peticion_de(o) == "Empresa: Sevilla Fugas (B26816876)"


def test_filtros_sin_sector_con_autonomos_y_localidad_como_zona() -> None:
    f = filtros_de(OBJETIVO)
    assert f.ubicacion.municipios == ["Alcalá de Guadaíra"] and f.incluir_autonomos and f.sector.sector_interno == ""
    assert filtros_de(EmpresaObjetivo(nombre="X")).ubicacion.municipios == []


def test_consultas_dirigidas() -> None:
    assert consulta_mapas(OBJETIVO) == "Sevilla Fugas Alcalá de Guadaíra"
    assert consultas_web(OBJETIVO) == ['"Sevilla Fugas" Alcalá de Guadaíra', '"Sevilla Fugas" CIF']
    con_todo = EmpresaObjetivo(nombre="Sevilla Fugas", nif="B26816876", web="https://www.sevillafugas.es/contacto")
    assert consultas_web(con_todo) == ['"Sevilla Fugas" empresa contacto', '"B26816876"', "site:sevillafugas.es aviso legal"]


def test_el_cif_manda() -> None:
    objetivo = EmpresaObjetivo(nombre="Sevilla Fugas", nif="B26816876")
    assert puntuar_candidato(objetivo, Candidato("1", "OTRO NOMBRE SL", nif="B26816876"))[0] == 1.0
    # mismo nombre, otro CIF: es otra sociedad
    assert puntuar_candidato(objetivo, Candidato("2", "SEVILLA FUGAS SL", nif="B91234567"))[0] == 0.0


def test_nombre_y_localidad() -> None:
    misma = Candidato("1", "SEVILLA FUGAS SOCIEDAD LIMITADA", lugares=["ALCALA DE GUADAIRA", "Sevilla"])
    otra_localidad = Candidato("2", "Sevilla Fugas", lugares=["Málaga"])
    distinta = Candidato("3", "Fontanería Pérez", lugares=["Alcalá de Guadaíra"])
    assert puntuar_candidato(OBJETIVO, misma)[0] >= 0.8
    assert puntuar_candidato(OBJETIVO, otra_localidad)[0] < 0.8
    assert puntuar_candidato(OBJETIVO, distinta)[0] < 0.6


def test_misma_web() -> None:
    objetivo = EmpresaObjetivo(nombre="Fugas", web="sevillafugas.es")
    assert puntuar_candidato(objetivo, Candidato("1", "Lo que sea", dominio_web="sevillafugas.es"))[0] == 0.95


def test_clasificacion_se_queda_con_la_buscada() -> None:
    decision = clasificar_candidatos(
        OBJETIVO,
        [
            Candidato("buena", "SEVILLA FUGAS SL", lugares=["Alcalá de Guadaíra"]),
            Candidato("homonima", "Sevilla Fugas", lugares=["Málaga"]),
            Candidato("directorio", "Fontaneros Sevilla 24h"),
        ],
    )
    assert decision["buena"][0] == "relevante"
    assert decision["homonima"][0] == "dudoso"
    assert decision["directorio"][0] == "descartado"
    assert decision["buena"][1].startswith("Es la empresa buscada")


def test_validacion_del_cif_del_formulario() -> None:
    assert nif_valido(None) and nif_valido("B26816876")
    assert not nif_valido("B26816877")


def test_resumen_final() -> None:
    assert resumen_final(OBJETIVO, None)[0] == "rendimientos_decrecientes"
    motivo, texto = resumen_final(
        OBJETIVO,
        {"nombre": "SEVILLA FUGAS SL", "nif": "B26816876", "telefono": "+34625739424", "email": None, "contacto": None,
         "completitud": 3, "clasificacion": "relevante"},
    )
    assert motivo == "cobertura_alcanzada" and texto.startswith("Encontrada: SEVILLA FUGAS SL (3/5")
