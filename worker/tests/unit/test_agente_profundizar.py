"""Tests de `radar.agente.profundizar.construir_consultas` -- pura, sin red ni BD."""

from radar.agente.profundizar import DatosEmpresaProfundizar, construir_consultas


def _datos(**overrides) -> DatosEmpresaProfundizar:
    base = {"id": "1", "razon_social": "CONSTRUCCIONES EJEMPLO SL", "nif": None, "municipio": None, "provincia": None, "dominio_web": None}
    base.update(overrides)
    return DatosEmpresaProfundizar(**base)


def test_con_nif_la_primera_consulta_es_nombre_y_nif():
    consultas = construir_consultas(_datos(nif="B12345678"))
    assert consultas[0] == '"CONSTRUCCIONES EJEMPLO SL" "B12345678"'


def test_sin_nif_no_hay_consulta_de_nif():
    consultas = construir_consultas(_datos())
    assert not any("B12345678" in c for c in consultas)


def test_con_municipio_la_consulta_de_aviso_legal_lo_incluye():
    consultas = construir_consultas(_datos(municipio="Alcalá de Guadaíra"))
    assert any("Alcalá de Guadaíra" in c and "aviso legal" in c for c in consultas)


def test_sin_municipio_cae_a_consulta_generica():
    consultas = construir_consultas(_datos())
    assert any("aviso legal" in c for c in consultas)
    assert not any("None" in c for c in consultas)


def test_con_dominio_web_anade_consulta_site():
    consultas = construir_consultas(_datos(dominio_web="ejemplo.es"))
    assert "site:ejemplo.es contacto" in consultas


def test_sin_ningun_dato_extra_hay_al_menos_una_consulta():
    consultas = construir_consultas(_datos())
    assert len(consultas) >= 1
