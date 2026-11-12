"""Código postal, todas las zonas, filtros avanzados y verificación final. Sin BD ni red."""

from __future__ import annotations

from radar.agente.consultas import zona_texto, zonas_busqueda
from radar.agente.cumplimiento import Criterios, DatosEmpresa, criterios_de, motivo_incumplimiento
from radar.agente.fases import combinar, consultas_google, planes_fuentes_marcadas
from radar.agente.interpretacion import (
    FiltrosBusqueda,
    RequisitosFiltro,
    SectorFiltro,
    UbicacionFiltro,
)
from radar.agente.relevancia import construir_prompt


def _f(**ubicacion) -> FiltrosBusqueda:
    return FiltrosBusqueda(
        ubicacion=UbicacionFiltro(**ubicacion), sector=SectorFiltro(sector_interno="supermercados")
    )


def test_codigos_postales_se_limpian() -> None:
    u = UbicacionFiltro(codigos_postales=["41.500", "8001", "41500", "99999", "abc"])
    assert u.codigos_postales == ["41500", "08001"]


def test_zonas_cp_primero_y_todas() -> None:
    f = _f(tipo="municipios", municipios=["Alcalá de Guadaíra"], codigos_postales=["41500"])
    assert zonas_busqueda(f) == ["41500 Alcalá de Guadaíra"] and zona_texto(f) == "41500 Alcalá de Guadaíra, España"
    varios = _f(tipo="municipios", municipios=["Dos Hermanas", "Utrera", "Carmona"])
    assert zonas_busqueda(varios) == ["Dos Hermanas", "Utrera", "Carmona"]


def test_las_fuentes_de_pago_buscan_en_todas_las_zonas() -> None:
    # antes solo en la primera zona de la lista
    f = _f(tipo="municipios", municipios=["Dos Hermanas", "Utrera", "Carmona"])
    planes = dict(planes_fuentes_marcadas(f, usar_places=True, apify_actores={"google_search"}))
    assert {c.split(" en ")[1] for c in planes["descubrir_places"]["consultas"]} == {"Dos Hermanas", "Utrera", "Carmona"}
    assert all(any(z in c for c in consultas_google(f)) for z in ("Dos Hermanas", "Utrera", "Carmona"))
    # con muchas zonas se recortan palabras, nunca zonas
    zonas = [f"Z{i}" for i in range(10)]
    assert {c.split(" en ")[1] for c in combinar(["a", "b", "c"], zonas, "{p} en {z}")} == set(zonas)


def test_verificacion_de_zona() -> None:
    c = Criterios(codigos_postales={"41500"}, municipios={"alcala de guadaira"}, provincias={"41"}, estados={"activa"})
    assert motivo_incumplimiento(DatosEmpresa(codigos_postales=["41500"]), c) is None
    assert "código postal 41700" in (motivo_incumplimiento(DatosEmpresa(codigos_postales=["41700"]), c) or "")
    assert "provincia de Málaga" in (motivo_incumplimiento(DatosEmpresa(provincias=["Málaga"]), c) or "")
    assert "municipio Utrera" in (motivo_incumplimiento(DatosEmpresa(municipios=["Utrera"]), c) or "")
    assert motivo_incumplimiento(DatosEmpresa(municipios=["ALCALA DE GUADAIRA"]), c) is None
    assert motivo_incumplimiento(DatosEmpresa(), c) is None  # sin datos: no se descarta
    assert "otro país" in (motivo_incumplimiento(DatosEmpresa(telefonos=["+56227550549"]), c) or "")


def test_verificacion_de_estado_forma_y_requisitos() -> None:
    f = FiltrosBusqueda(formas_juridicas=["SL"], requisitos=RequisitosFiltro(telefono=True))
    c = criterios_de(f, set())
    ok = DatosEmpresa(telefonos=["+34954000000"], forma_juridica="S.L.", estado="activa")
    assert motivo_incumplimiento(ok, c) is None
    assert "Estado registral: extinguida" == motivo_incumplimiento(
        DatosEmpresa(telefonos=["+34954000000"], estado="extinguida"), c
    )
    assert "Forma jurídica SA" in (motivo_incumplimiento(DatosEmpresa(telefonos=["+34954000000"], forma_juridica="SA"), c) or "")
    assert "Sin teléfono" in (motivo_incumplimiento(DatosEmpresa(forma_juridica="SL"), c) or "")


def test_filtros_avanzados_llegan_al_filtro_de_sector() -> None:
    f = FiltrosBusqueda(
        ubicacion=UbicacionFiltro(codigos_postales=["41500"]),
        sector=SectorFiltro(
            sector_interno="supermercados", solo_si=["supermercado pequeño de barrio"], descartar_si=["cadena nacional"]
        ),
    )
    prompt = construir_prompt(f, [{"id": "1", "nombre": "Mercadona"}])
    assert "supermercado pequeño de barrio" in prompt and "cadena nacional" in prompt and "41500" in prompt


def test_municipio_con_provincia_al_lado_casa() -> None:
    c = Criterios(municipios={"dos hermanas"}, provincias={"41"})
    assert motivo_incumplimiento(DatosEmpresa(municipios=["Dos Hermanas (Sevilla)"]), c) is None
    assert motivo_incumplimiento(DatosEmpresa(municipios=["Dos Hermanas, Sevilla"]), c) is None


def test_busqueda_sin_sector_no_deja_todo_en_dudoso() -> None:
    from radar.agente.relevancia import busqueda_sin_sector

    sin = FiltrosBusqueda(ubicacion=UbicacionFiltro(codigos_postales=["28108"]))
    assert busqueda_sin_sector(sin) and "NO pide ningún sector" in construir_prompt(sin, [{"id": "1"}])
    con = FiltrosBusqueda(sector=SectorFiltro(sector_interno="fontanería"))
    assert not busqueda_sin_sector(con) and "NO pide ningún sector" not in construir_prompt(con, [{"id": "1"}])
