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


def test_mismo_dominio_minimo_revision():
    a = reg(razon_social="Construcciones Pérez SL", web="https://www.perezobras.es")
    b = reg(nombre_comercial="Pérez Obras", web="perezobras.es")
    assert comparar(a, b)["decision"] == "revision"


def test_forma_juridica_distinta_no_fusiona_automaticamente():
    a = reg(razon_social="Estructuras Alcor SA", telefono="955212121", cp="41500")
    b = reg(razon_social="Estructuras Alcor SL", telefono="955212121", cp="41500")
    assert comparar(a, b)["decision"] != "misma"


def test_telefono_compartido_no_puntua():
    a = reg(razon_social="Pinturas Sol", telefono="954999999", cp="41001")
    b = reg(razon_social="Fontanería Luna SL", telefono="954999999", cp="41001")
    assert comparar(a, b, telefonos_compartidos={"+34954999999"})["decision"] == "distinta"


def test_nombre_identico_sin_ubicacion_va_a_revision():
    """Caso real encontrado corriendo BORME (2026-09-18, Sevilla, 30 días):
    'VIMOINSA VIVIENDAS PREFABRICADAS SL' se registró 3 veces como empresa
    nueva porque el BORME no da NIF ni domicilio en la mayoría de actos --
    sin esta regla, el nombre solo (0.45) nunca llega a UMBRAL_REVISION
    (0.55) y el duplicado desaparece sin dejar rastro en
    candidatos_duplicado."""
    a = reg(razon_social="VIMOINSA VIVIENDAS PREFABRICADAS SL")
    b = reg(razon_social="VIMOINSA VIVIENDAS PREFABRICADAS SOCIEDAD LIMITADA")
    resultado = comparar(a, b)
    assert resultado["decision"] == "revision"
    assert resultado["regla"] == "R4_nombre_identico_sin_senal_ubicacion"


def test_nombre_identico_con_ubicacion_distinta_sigue_sin_fusionar():
    """La regla nueva no debe tocar el caso ya cubierto por
    test_homonimos_en_otra_provincia_no_fusionan: en cuanto hay una señal de
    ubicación que las distingue, siguen siendo 'distinta', no 'revision'."""
    a = reg(razon_social="Construcciones García SL", cp="41010")
    b = reg(razon_social="Construcciones García S.L.", cp="28001")
    assert comparar(a, b)["decision"] == "distinta"
