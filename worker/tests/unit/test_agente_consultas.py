from radar.agente.consultas import generar_consultas
from radar.agente.interpretacion import FiltrosBusqueda, SectorFiltro, UbicacionFiltro


def _f(zonas=None, palabras=None, sector="", tipo="municipios"):
    return FiltrosBusqueda(
        ubicacion=UbicacionFiltro(tipo=tipo, **({"municipios": zonas} if tipo == "municipios" else {"provincias": zonas})),
        sector=SectorFiltro(sector_interno=sector, palabras_clave=palabras or []),
    )


def test_sin_zona_no_genera_nada():
    assert generar_consultas(FiltrosBusqueda()) == []


def test_usa_palabras_clave_y_zona():
    cs = generar_consultas(_f(["Alcalá de Guadaíra"], ["fontanería"]), max_consultas=3)
    assert cs[0] == '"fontanería" "Alcalá de Guadaíra"'
    assert all("Alcalá de Guadaíra" in c for c in cs)


def test_sector_construccion_sin_palabras_usa_las_por_defecto():
    cs = generar_consultas(_f(["Sevilla"], sector="construccion"), max_consultas=6)
    assert any("constructora" in c for c in cs)


def test_sin_duplicados_y_respeta_maximo():
    cs = generar_consultas(_f(["A", "B"], ["x", "y"]), max_consultas=4)
    assert len(cs) == len({c.lower() for c in cs}) == 4


def test_provincia_si_no_hay_municipios():
    cs = generar_consultas(_f(["Sevilla"], ["reformas"], tipo="provincias"), max_consultas=1)
    assert cs == ['"reformas" "Sevilla"']


def test_zona_texto_prioriza_municipio_sobre_provincia():
    from radar.agente.consultas import zona_texto

    assert zona_texto(_f(["Alcalá de Guadaíra"], tipo="municipios")) == "Alcalá de Guadaíra, España"
    assert zona_texto(_f(["Sevilla"], tipo="provincias")) == "Sevilla, España"
    assert zona_texto(FiltrosBusqueda()) is None


def test_palabras_para_mapas_prioriza_el_sector_y_google_excluye_directorios():
    from radar.agente.fases import consultas_google, palabras_para_mapas
    from radar.agente.interpretacion import SectorFiltro, UbicacionFiltro

    f = FiltrosBusqueda(
        ubicacion=UbicacionFiltro(tipo="municipios", municipios=["Colmenar Viejo"]),
        sector=SectorFiltro(sector_interno="Fontanería", palabras_clave=["fontanería", "fontanero", "instalaciones de agua"]),
    )
    assert palabras_para_mapas(f) == ["Fontanería", "fontanero", "instalaciones de agua"]
    c = consultas_google(f)
    assert c[0].startswith("Fontanería Colmenar Viejo") and "-site:paginasamarillas.es" in c[0]


def test_fuentes_marcadas_se_usan_aunque_la_busqueda_sea_de_toda_espana():
    # 2026-10-20: «reformas hoteleras» sin zona -> Maps, Places y Google marcados quedaban «no se usó».
    from radar.agente.consultas import zona_o_espana
    from radar.agente.fases import planes_fuentes_marcadas

    f = FiltrosBusqueda(sector=SectorFiltro(sector_interno="reformas hoteleras"))
    assert zona_o_espana(f) == "España"
    planes = dict(planes_fuentes_marcadas(f, usar_places=True, apify_actores={"google_maps", "google_search"}))
    assert set(planes) == {"descubrir_apify_maps", "descubrir_places", "descubrir_google_search"}
    assert planes["descubrir_places"]["consultas"][0] == "reformas hoteleras en España"
    assert planes["descubrir_google_search"]["consultas"][0].startswith("reformas hoteleras España ")
