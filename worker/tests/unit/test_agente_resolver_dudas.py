from radar.agente.interpretacion import FiltrosBusqueda, SectorFiltro, UbicacionFiltro
from radar.agente.relevancia import construir_prompt, perfil_para_prompt
from radar.agente.resolver_dudas import evidencia_identidad, evidencia_valor

WEB = """Fontanería Zultrax. Llámanos al 911 000 772. info@zultrax.es.
Aviso legal: el titular de esta web es ZULTRAX INSTALACIONES, S.L., con CIF B88770003."""


def test_identidad_confirmada_por_telefono_en_la_web():
    motivo = evidencia_identidad({"nombre_comercial": "Otra Cosa", "telefonos": ["+34911000772"]}, WEB)
    assert motivo and "911000772" in motivo.replace(" ", "").replace("+34", "")


def test_identidad_confirmada_por_nombre_distintivo_en_la_web():
    assert evidencia_identidad({"nombre_comercial": "Zultrax"}, WEB)


def test_identidad_sin_evidencia():
    assert evidencia_identidad({"nombre_comercial": "Fontanería Pérez", "telefonos": ["612345678"]}, WEB) is None
    assert evidencia_identidad({"telefonos": ["911000772"]}, "") is None


def test_valor_que_aparece_en_la_web_gana():
    alternativas = [{"valor": "ZULTRAX MONTAJES SL"}, {"valor": "ZULTRAX INSTALACIONES SL"}]
    assert evidencia_valor("razon_social", alternativas, WEB) == {"valor": "ZULTRAX INSTALACIONES SL"}


def test_si_aparecen_los_dos_o_ninguno_no_decide():
    assert evidencia_valor("razon_social", [{"valor": "ALFA SL"}, {"valor": "BETA SL"}], WEB) is None
    assert evidencia_valor("nif", [{"valor": "B88770003"}, {"valor": "B11111111"}], WEB) == {"valor": "B88770003"}


def test_prompt_de_relevancia_incluye_sector_zona_y_empresas():
    filtros = FiltrosBusqueda(
        ubicacion=UbicacionFiltro(tipo="municipios", municipios=["Colmenar Viejo"]),
        sector=SectorFiltro(sector_interno="Fontanería", palabras_clave=["fontanero"]),
    )
    perfil = perfil_para_prompt(("id1", "Calorfon", None, None, None, None, "Colmenar Viejo", "Fontanero", None, None, "apify_maps: nueva"))
    assert perfil == {"id": "id1", "nombre": "Calorfon", "municipio": "Colmenar Viejo", "categoria_google_maps": "Fontanero", "encontrada_por": "apify_maps: nueva"}
    p = construir_prompt(filtros, [perfil])
    assert "Fontanería" in p and "Colmenar Viejo" in p and "Calorfon" in p
