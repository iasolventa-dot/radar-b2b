"""Tests de regresión de `radar.resolucion.scoring` (doc 05 §2.2-2.4).

Puerto de los casos de matching de `verificacion-empresas-es/scripts/test_lib_empresas.py`
(skill) contra los módulos del worker.
"""

from radar.normalizacion.nif import _control_cif
from radar.normalizacion.registro import normalizar_registro
from radar.resolucion.scoring import comparar


def cif(letra: str, siete: str) -> str:
    d, l = _control_cif(siete)
    return letra + siete + (l if letra in "NPQRSW" else d)


def reg(**k):
    return normalizar_registro(k)


def test_nif_distinto_nunca_fusiona():
    a = reg(razon_social="Reformas Hogar Plus SL", nif=cif("B", "4155555"), web="reformashogarplus.com", telefono="955334455")
    b = reg(razon_social="Reformas Hogar Plus SL", nif=cif("B", "2166666"), web="reformashogarplus.com", telefono="955334455")
    assert comparar(a, b)["decision"] == "distinta"


def test_nif_igual_nombres_distintos_va_a_revision():
    n = cif("B", "4177777")
    a = reg(razon_social="Talleres Martín SL", nif=n)
    b = reg(razon_social="Diseño Web Sur SL", nif=n)
    assert comparar(a, b)["decision"] == "revision"


def test_mismo_nombre_y_telefono_fusiona():
    a = reg(razon_social="Construcciones Pérez, S.L.", telefono="955 12 34 56", cp="41001")
    b = reg(razon_social="CONSTRUCCIONES PEREZ SL", telefono="+34955123456", cp="41001")
    assert comparar(a, b)["decision"] == "misma"


def test_homonimos_en_otra_provincia_no_fusionan():
    a = reg(razon_social="Construcciones García SL", cp="41010")
    b = reg(razon_social="Construcciones García S.L.", cp="28001")
    assert comparar(a, b)["decision"] == "distinta"


def test_nombres_genericos_no_fusionan():
    a = reg(razon_social="Reformas y Construcciones del Sur SL", cp="41010")
    b = reg(razon_social="Construcciones del Sur SL", cp="41010")
    assert comparar(a, b)["decision"] == "distinta"


def test_mismo_dominio_marca_y_sociedad_es_la_misma():
    # Antes "revision"; desde 2026-09-23 (R8) marca + razón social bajo la misma web propia = misma empresa.
    a = reg(razon_social="Construcciones Pérez SL", web="https://www.perezobras.es")
    b = reg(nombre_comercial="Pérez Obras", web="perezobras.es")
    assert comparar(a, b)["decision"] == "misma"


def test_mismo_dominio_dos_marcas_sin_razon_social_es_la_misma():
    a = reg(nombre_comercial="Pérez Obras", web="https://www.perezobras.es")
    b = reg(nombre_comercial="Obras y Reformas Pérez", web="perezobras.es")
    assert comparar(a, b)["decision"] == "misma"


def test_web_sin_nombre_y_negocio_con_la_misma_web_son_la_misma():
    a = reg(nombre_comercial="Persianas AyOl", web="persianasayol.com", telefono="625793044")
    b = reg(web="https://persianasayol.com/")
    assert comparar(a, b)["regla"] == "R8_marca_y_sociedad_misma_web"


def test_forma_juridica_distinta_no_fusiona_automaticamente():
    a = reg(razon_social="Estructuras Alcor SA", telefono="955212121", cp="41500")
    b = reg(razon_social="Estructuras Alcor SL", telefono="955212121", cp="41500")
    assert comparar(a, b)["decision"] != "misma"


def test_telefono_compartido_no_puntua():
    a = reg(razon_social="Pinturas Sol", telefono="954999999", cp="41001")
    b = reg(razon_social="Fontanería Luna SL", telefono="954999999", cp="41001")
    assert comparar(a, b, telefonos_compartidos={"+34954999999"})["decision"] == "distinta"


def test_nombre_identico_sin_ubicacion_es_la_misma_sociedad():
    """Caso real encontrado corriendo BORME (2026-09-18, Sevilla, 30 días):
    'VIMOINSA VIVIENDAS PREFABRICADAS SL' se registró 3 veces como empresa
    nueva porque el BORME no da NIF ni domicilio en la mayoría de actos --
    sin esta regla, el nombre solo (0.45) nunca llega a UMBRAL_REVISION
    (0.55) y el duplicado desaparece sin dejar rastro en
    candidatos_duplicado."""
    # Desde 2026-09-25 (R9): misma denominación + misma forma jurídica = misma
    # sociedad (el Registro Mercantil no admite dos iguales).
    a = reg(razon_social="VIMOINSA VIVIENDAS PREFABRICADAS SL")
    b = reg(razon_social="VIMOINSA VIVIENDAS PREFABRICADAS SOCIEDAD LIMITADA")
    resultado = comparar(a, b)
    assert resultado["decision"] == "misma"
    assert resultado["regla"] == "R9_denominacion_social_identica"


def test_nombre_identico_sin_forma_juridica_sigue_en_revision():
    a = reg(nombre_comercial="Vimoinsa Viviendas Prefabricadas")
    b = reg(razon_social="VIMOINSA VIVIENDAS PREFABRICADAS")
    assert comparar(a, b)["decision"] == "revision"


def test_misma_denominacion_con_distinta_forma_juridica_no_es_r9():
    a = reg(razon_social="VIMOINSA VIVIENDAS PREFABRICADAS SL")
    b = reg(razon_social="VIMOINSA VIVIENDAS PREFABRICADAS SA")
    assert comparar(a, b)["regla"] != "R9_denominacion_social_identica"


def test_nombre_identico_con_ubicacion_distinta_sigue_sin_fusionar():
    """La regla nueva no debe tocar el caso ya cubierto por
    test_homonimos_en_otra_provincia_no_fusionan: en cuanto hay una señal de
    ubicación que las distingue, siguen siendo 'distinta', no 'revision'."""
    a = reg(razon_social="Construcciones García SL", cp="41010")
    b = reg(razon_social="Construcciones García S.L.", cp="28001")
    assert comparar(a, b)["decision"] == "distinta"


# ---------- cruce entre fuentes (2026-09-21) ----------


def test_nombre_comercial_abreviado_en_el_mismo_punto_va_a_revision_no_a_fusion():
    """OSM: 'Grupo Inversor'; BORME: razón social completa. Mismas coordenadas."""
    osm = reg(nombre_comercial="Grupo Inversor", lat=37.40426, lon=-5.94973)
    borme = reg(razon_social="GRUPO INVERSOR DOMINGUEZ PEREZ SL", lat=37.40427, lon=-5.94972)
    r = comparar(osm, borme)
    assert r["decision"] == "revision"
    assert r["regla"] == "R5_mismo_punto_nombre_parcial"


def test_mismo_punto_con_nombre_distinto_no_se_relaciona():
    """Dos negocios en el mismo portal con nombres sin nada en común no se cruzan."""
    a = reg(nombre_comercial="Fontanería Cobreplas", lat=37.40426, lon=-5.94973)
    b = reg(razon_social="ELECTRICIDAD NAVARRO SL", lat=37.40427, lon=-5.94972)
    assert comparar(a, b)["decision"] == "distinta"


def test_mismo_punto_solo_palabra_generica_en_comun_no_llega_a_revision():
    a = reg(nombre_comercial="Reformas Rápidas", lat=37.40426, lon=-5.94973)
    b = reg(razon_social="REFORMAS GUADAIRA SL", lat=37.40427, lon=-5.94972)
    assert comparar(a, b)["decision"] == "distinta"


def test_nombre_parcial_a_kilometros_no_se_relaciona():
    a = reg(nombre_comercial="Grupo Inversor", lat=37.40426, lon=-5.94973)
    b = reg(razon_social="GRUPO INVERSOR DOMINGUEZ PEREZ SL", lat=37.60, lon=-5.50)
    assert comparar(a, b)["decision"] == "distinta"


def test_mismo_dominio_con_nombres_distintos_marca_y_sociedad_es_la_misma():
    """Caso B del cruce entre fuentes: mismo dominio propio, nombre comercial vs razón social (R8, 2026-09-23)."""
    a = reg(nombre_comercial="Meta360", web="https://meta360.es/")
    b = reg(razon_social="TECNOLOGIAS Y SERVICIOS DIGITALES SL", web="meta360.es")
    r = comparar(a, b)
    assert r["decision"] == "misma"


def test_mismo_nombre_y_mismo_punto_es_la_misma_empresa():
    a = reg(nombre_comercial="Instalaciones Garmel", lat=37.40426, lon=-5.94973)
    b = reg(razon_social="INSTALACIONES GARMEL SL", lat=37.40427, lon=-5.94972)
    r = comparar(a, b)
    assert r["decision"] == "misma" and r["regla"] == "R6_mismo_nombre_mismo_punto"


def test_mismo_nombre_mismo_punto_pero_forma_juridica_distinta_no_fusiona():
    a = reg(razon_social="INSTALACIONES GARMEL SL", lat=37.40426, lon=-5.94973)
    b = reg(razon_social="INSTALACIONES GARMEL SA", lat=37.40427, lon=-5.94972)
    assert comparar(a, b)["decision"] != "misma"


def test_mismo_nombre_mismo_punto_con_nif_distinto_nunca_fusiona():
    a = reg(razon_social="INSTALACIONES GARMEL SL", nif=cif("B", "4155555"), lat=37.40426, lon=-5.94973)
    b = reg(razon_social="INSTALACIONES GARMEL SL", nif=cif("B", "2166666"), lat=37.40427, lon=-5.94972)
    assert comparar(a, b)["decision"] == "distinta"


def test_mismo_nombre_a_kilometros_no_fusiona():
    a = reg(razon_social="INSTALACIONES GARMEL SL", lat=37.40426, lon=-5.94973)
    b = reg(razon_social="INSTALACIONES GARMEL SL", lat=37.90, lon=-4.77)
    assert comparar(a, b)["decision"] != "misma"


# ---------- hoja registral y series numeradas (2026-09-21) ----------


def test_misma_hoja_registral_es_la_misma_empresa_aunque_no_haya_mas_datos():
    a = reg(razon_social="JOAQUIN FERNANDEZ SA", hoja_registral="SE52426")
    b = reg(razon_social="JOAQUIN FERNANDEZ SA", hoja_registral="se52426")
    r = comparar(a, b)
    assert r["decision"] == "misma" and r["regla"] == "R3b_hoja_registral"


def test_hojas_registrales_distintas_no_activan_la_regla():
    a = reg(razon_social="JOAQUIN FERNANDEZ SA", hoja_registral="SE52426")
    b = reg(razon_social="JOAQUIN FERNANDEZ SA", hoja_registral="SE11111")
    assert comparar(a, b)["regla"] != "R3b_hoja_registral"


def test_series_numeradas_son_empresas_distintas():
    a = reg(razon_social="ARENA GREEN POWER REN 410 SOCIEDAD LIMITADA")
    b = reg(razon_social="ARENA GREEN POWER REN 414 SOCIEDAD LIMITADA")
    r = comparar(a, b)
    assert r["decision"] == "distinta" and r["regla"] == "R7_numeros_distintos"


def test_mismo_numero_no_dispara_la_regla_de_series():
    a = reg(razon_social="ARENA GREEN POWER REN 410 SL")
    b = reg(razon_social="ARENA GREEN POWER REN 410 SL")
    assert comparar(a, b)["regla"] != "R7_numeros_distintos"


def test_numeros_distintos_pero_mismo_dominio_no_se_descarta():
    a = reg(razon_social="ARENA GREEN POWER REN 410 SL", web="arena.es")
    b = reg(razon_social="ARENA GREEN POWER REN 414 SL", web="arena.es")
    assert comparar(a, b)["regla"] != "R7_numeros_distintos"


# ---------- marca + sociedad bajo la misma web (2026-09-23) ----------


def test_marca_de_maps_y_sociedad_del_aviso_legal_con_la_misma_web_son_la_misma():
    marca = reg(nombre_comercial="Ardigral", web="https://piscinas-jardines-algete.com", telefonos=["916239303"])
    sociedad = reg(razon_social="ARTE Y DISEÑO INTEGRALES, S.L", nif="B84628635", web="piscinas-jardines-algete.com")
    r = comparar(marca, sociedad)
    assert r["decision"] == "misma" and r["regla"] == "R8_marca_y_sociedad_misma_web"


def test_dos_sociedades_con_la_misma_web_no_se_fusionan_por_r8():
    a = reg(razon_social="CONSTRUCCIONES ALFA SL", web="grupoalfa.es")
    b = reg(razon_social="PROMOCIONES BETA SL", web="grupoalfa.es")
    assert comparar(a, b)["regla"] != "R8_marca_y_sociedad_misma_web"


def test_r8_no_aplica_con_webs_distintas():
    a = reg(nombre_comercial="Ardigral", web="ardigral.es")
    b = reg(razon_social="ARTE Y DISEÑO INTEGRALES, S.L", web="otra.es")
    assert comparar(a, b)["regla"] != "R8_marca_y_sociedad_misma_web"


def test_mismo_telefono_y_palabra_distintiva_como_minimo_une_con_duda():
    a = reg(nombre_comercial="Zultrax Obras", telefono="911000772")
    b = reg(razon_social="ZULTRAX INSTALACIONES SL", telefono="911000772")
    assert comparar(a, b)["decision"] in ("revision", "misma")
