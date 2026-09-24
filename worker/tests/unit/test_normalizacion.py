"""Tests de regresión de `radar.normalizacion` (doc 05 §1).

Puerto de `verificacion-empresas-es/scripts/test_lib_empresas.py` (skill) a
los módulos del worker. Si cambias una regla aquí, cámbiala también en
doc 05 y en esa skill.
"""

from radar.normalizacion.direccion import validar_cp
from radar.normalizacion.dominio import extraer_dominio, normalizar_email
from radar.normalizacion.nif import _control_cif, validar_nif
from radar.normalizacion.nombre import extraer_forma_juridica, normalizar_nombre
from radar.normalizacion.registro import normalizar_registro
from radar.normalizacion.telefono import normalizar_telefono


def cif(letra: str, siete: str) -> str:
    d, l = _control_cif(siete)
    return letra + siete + (l if letra in "NPQRSW" else d)


def reg(**k):
    return normalizar_registro(k)


# ---------- NIF ----------
def test_nif_sociedad_valido_y_formatos():
    n = cif("B", "4112345")
    assert validar_nif(n)["valido"]
    assert validar_nif(f"{n[0]}-{n[1:3]}.{n[3:6]}.{n[6:]}")["valido"]
    assert validar_nif("ES" + n)["nif"] == n


def test_nif_invalido_y_tipos():
    assert not validar_nif("B41123458")["valido"]
    assert validar_nif("12345678Z")["tipo"] == "dni" and validar_nif("12345678Z")["valido"]
    assert validar_nif("X1234567L")["valido"] and validar_nif("X1234567L")["persona_fisica"]


# ---------- Normalización ----------
def test_forma_juridica():
    assert extraer_forma_juridica("Construcciones Pérez, S.L.") == ("SL", "construcciones perez")
    assert extraer_forma_juridica("Reformas Sur S.L.U.")[0] == "SLU"
    assert extraer_forma_juridica("Aceites del Sur S. Coop. And.")[0] == "SCA"
    assert normalizar_nombre("Construcciones Muñoz SL") == normalizar_nombre("CONSTRUCCIONES MUNOZ S.L.")


def test_telefonos():
    assert normalizar_telefono("955 12 34 56")["e164"] == "+34955123456"
    assert normalizar_telefono("0034 654 321 987")["tipo"] == "movil"
    assert normalizar_telefono("902 123 456")["tipo"] == "especial"
    assert not normalizar_telefono("12345")["valido"]


def test_cp_y_dominios_y_email():
    assert validar_cp("4001")["cp"] == "04001"
    assert validar_cp("41001", "Huelva")["coherente_provincia"] is False
    assert validar_cp("15001", "La Coruña")["coherente_provincia"] is True
    assert extraer_dominio("https://www.perezobras.es/contacto") == "perezobras.es"
    assert extraer_dominio("perez.com.es") == "perez.com.es"
    assert normalizar_email("info@x.es")["es_generico"] is True
    assert normalizar_email("juan.perez@x.es")["es_generico"] is False


def test_normalizar_registro_combina_campos():
    n = cif("B", "4112345")
    r = reg(
        razon_social="Construcciones Pérez, S.L.",
        nif=n,
        telefono="955 12 34 56",
        cp="4001",
        provincia="Sevilla",
        web="https://www.perezobras.es",
    )
    assert r["nif"] == n and r["nif_valido"] is True
    assert r["forma_juridica"] == "SL"
    assert r["telefonos"] == ["+34955123456"]
    assert r["cp"] == "04001"
    assert r["dominio"] == "perezobras.es"
    assert r["forma_coherente_nif"] is True  # letra B ↔ SL


def test_telefono_de_relleno_no_es_valido():
    from radar.normalizacion.telefono import normalizar_telefono

    assert normalizar_telefono("+34 600 000 000")["valido"] is False
    assert normalizar_telefono("954 11 22 33")["valido"] is True


def test_dni_en_una_sociedad_no_es_su_nif() -> None:
    r = normalizar_registro({"razon_social": "ELING S.L.U.", "nif": "08369853S"})
    assert r["nif"] is None and r["nif_valido"] is None
    assert "descartado" in (r["nif_aviso"] or "")


def test_dni_en_comunidad_de_bienes_o_autonomo_se_conserva() -> None:
    assert normalizar_registro({"razon_social": "HERMANOS PEREZ CB", "nif": "08369853S"})["nif"] == "08369853S"
    assert normalizar_registro({"razon_social": "Candido Mendez", "nif": "08369853S"})["nif"] == "08369853S"
