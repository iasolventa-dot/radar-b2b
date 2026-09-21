"""
Tests de regresión de lib_empresas y extraer_datos_legales.
Ejecutar:  python -m pytest test_lib_empresas.py -q    (o simplemente: python test_lib_empresas.py)
Cópialos a worker/tests/unit/ del repo: si alguien cambia una regla, estos casos avisan.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_empresas as L  # noqa: E402
from extraer_datos_legales import extraer, html_a_texto  # noqa: E402


def cif(letra, siete):
    d, l = L._control_cif(siete)
    return letra + siete + (l if letra in "NPQRSW" else d)


def reg(**k):
    return L.normalizar_registro(k)


# ---------- NIF ----------
def test_nif_sociedad_valido_y_formatos():
    n = cif("B", "4112345")
    assert L.validar_nif(n)["valido"]
    assert L.validar_nif(f"{n[0]}-{n[1:3]}.{n[3:6]}.{n[6:]}")["valido"]
    assert L.validar_nif("ES" + n)["nif"] == n


def test_nif_invalido_y_tipos():
    assert not L.validar_nif("B41123458")["valido"]
    assert L.validar_nif("12345678Z")["tipo"] == "dni" and L.validar_nif("12345678Z")["valido"]
    assert L.validar_nif("X1234567L")["valido"] and L.validar_nif("X1234567L")["persona_fisica"]


# ---------- Normalización ----------
def test_forma_juridica():
    assert L.extraer_forma_juridica("Construcciones Pérez, S.L.") == ("SL", "construcciones perez")
    assert L.extraer_forma_juridica("Reformas Sur S.L.U.")[0] == "SLU"
    assert L.extraer_forma_juridica("Aceites del Sur S. Coop. And.")[0] == "SCA"
    assert L.normalizar_nombre("Construcciones Muñoz SL") == L.normalizar_nombre("CONSTRUCCIONES MUNOZ S.L.")


def test_telefonos():
    assert L.normalizar_telefono("955 12 34 56")["e164"] == "+34955123456"
    assert L.normalizar_telefono("0034 654 321 987")["tipo"] == "movil"
    assert L.normalizar_telefono("902 123 456")["tipo"] == "especial"
    assert not L.normalizar_telefono("12345")["valido"]


def test_cp_y_dominios_y_email():
    assert L.validar_cp("4001")["cp"] == "04001"
    assert L.validar_cp("41001", "Huelva")["coherente_provincia"] is False
    assert L.validar_cp("15001", "La Coruña")["coherente_provincia"] is True
    assert L.extraer_dominio("https://www.perezobras.es/contacto") == "perezobras.es"
    assert L.extraer_dominio("perez.com.es") == "perez.com.es"
    assert L.normalizar_email("info@x.es")["es_generico"] is True
    assert L.normalizar_email("juan.perez@x.es")["es_generico"] is False


# ---------- Matching ----------
def test_nif_distinto_nunca_fusiona():
    a = reg(razon_social="Reformas Hogar Plus SL", nif=cif("B", "4155555"), web="reformashogarplus.com", telefono="955334455")
    b = reg(razon_social="Reformas Hogar Plus SL", nif=cif("B", "2166666"), web="reformashogarplus.com", telefono="955334455")
    assert L.comparar(a, b)["decision"] == "distinta"


def test_nif_igual_nombres_distintos_va_a_revision():
    n = cif("B", "4177777")
    a = reg(razon_social="Talleres Martín SL", nif=n)
    b = reg(razon_social="Diseño Web Sur SL", nif=n)
    assert L.comparar(a, b)["decision"] == "revision"


def test_mismo_nombre_y_telefono_fusiona():
    a = reg(razon_social="Construcciones Pérez, S.L.", telefono="955 12 34 56", cp="41001")
    b = reg(razon_social="CONSTRUCCIONES PEREZ SL", telefono="+34955123456", cp="41001")
    assert L.comparar(a, b)["decision"] == "misma"


def test_homonimos_en_otra_provincia_no_fusionan():
    a = reg(razon_social="Construcciones García SL", cp="41010")
    b = reg(razon_social="Construcciones García S.L.", cp="28001")
    assert L.comparar(a, b)["decision"] == "distinta"


def test_nombres_genericos_no_fusionan():
    a = reg(razon_social="Reformas y Construcciones del Sur SL", cp="41010")
    b = reg(razon_social="Construcciones del Sur SL", cp="41010")
    assert L.comparar(a, b)["decision"] == "distinta"


def test_mismo_dominio_minimo_revision():
    a = reg(razon_social="Construcciones Pérez SL", web="https://www.perezobras.es")
    b = reg(nombre_comercial="Pérez Obras", web="perezobras.es")
    assert L.comparar(a, b)["decision"] == "revision"


def test_forma_juridica_distinta_no_fusiona_automaticamente():
    a = reg(razon_social="Estructuras Alcor SA", telefono="955212121", cp="41500")
    b = reg(razon_social="Estructuras Alcor SL", telefono="955212121", cp="41500")
    assert L.comparar(a, b)["decision"] != "misma"


def test_telefono_compartido_no_puntua():
    a = reg(razon_social="Pinturas Sol", telefono="954999999", cp="41001")
    b = reg(razon_social="Fontanería Luna SL", telefono="954999999", cp="41001")
    assert L.comparar(a, b, telefonos_compartidos={"+34954999999"})["decision"] == "distinta"


# ---------- Extracción de aviso legal ----------
def test_extraccion_aviso_legal_con_agencia():
    n_emp, n_ag = cif("B", "4112345"), cif("B", "4177777")
    html = (f"<p>El titular de este sitio web es <b>Construcciones Pérez Martín, S.L.</b>, con C.I.F.: {n_emp}. "
            "Inscrita en el Registro Mercantil de Sevilla, Tomo 4.567, Folio 123, Hoja SE-78901.</p>"
            f"<footer>Diseño web: Agencia Creativa Sur SL (CIF {n_ag})</footer>")
    r = extraer(html_a_texto(html), "perezobras.es")
    assert r["nifs"][0]["nif"] == n_emp
    assert r["nifs"][1]["cerca_de_mencion_agencia"]
    assert r["razones_sociales"][0].startswith("Construcciones Pérez Martín")
    assert r["registro_mercantil"] == {"registro": "Sevilla", "tomo": "4.567", "folio": "123", "hoja": "SE-78901"}


if __name__ == "__main__":
    fallos = 0
    for nombre, f in list(globals().items()):
        if nombre.startswith("test_") and callable(f):
            try:
                f()
                print("OK  ", nombre)
            except AssertionError as e:
                fallos += 1
                print("FALLO", nombre, e)
    sys.exit(1 if fallos else 0)
