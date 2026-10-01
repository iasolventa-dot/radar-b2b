"""Identificación del CIF por búsqueda: el código verifica lo que propone el
buscador o el modelo (sin red ni BD)."""

from radar.agente.completar_identidad import (
    cif_valido_para,
    elegir_de_resultados,
    nombre_limpio,
    nombre_para_verificar,
    propuesta_de_texto,
)

# B91030973 y A41011271 tienen dígito de control válido (vistos en búsquedas reales)
CIF_B = "B91030973"
CIF_A = "A41011271"


def test_nombre_limpio_quita_sufijo_y_forma() -> None:
    assert nombre_limpio("EMIF | Alcalá de Guadaira") == "emif"
    assert nombre_limpio("Climatizaciones Montaño, S.L.") == "climatizaciones montano"


def test_el_municipio_no_cuenta_para_coincidir() -> None:
    n = nombre_para_verificar("Climasol Alcalá", "Alcalá de Guadaíra")
    assert not cif_valido_para(n, CIF_B, "CLIMATIZACIONES ALCALA SL")


def test_cif_valido_con_nombre_y_forma_coherentes() -> None:
    assert cif_valido_para("Irriplant", CIF_B, "IRRIPLANT SL")
    assert not cif_valido_para("Irriplant", "B91030974", "IRRIPLANT SL")  # dígito de control
    assert not cif_valido_para("Irriplant", CIF_B, "OTRA EMPRESA DISTINTA SL")  # otro nombre
    assert not cif_valido_para("Irriplant", CIF_A, "IRRIPLANT SL")  # letra A con forma SL
    assert not cif_valido_para("Irriplant", "08369853S", "IRRIPLANT SL")  # DNI, no sociedad


def test_elige_el_cif_del_extracto_que_nombra_a_la_empresa() -> None:
    resultados = [
        {"title": "IRRIPLANT SL - Dos Hermanas - Infocif", "description": f"CIF {CIF_B}. Domicilio en Dos Hermanas", "url": "https://x"},
        {"title": "IRRIPLANT SL: CIF y teléfono", "description": f"NIF: {CIF_B}", "url": "https://y"},
        {"title": "Otra empresa SL", "description": "CIF B12345674", "url": "https://z"},
    ]
    p = elegir_de_resultados("Irriplant", resultados)
    assert p is not None and p.nif == CIF_B and p.razon_social == "IRRIPLANT SL"


def test_sin_coincidencia_no_propone_nada() -> None:
    assert elegir_de_resultados("Irriplant", [{"title": "Nada que ver SL", "description": f"CIF {CIF_B}"}]) is None


def test_respuesta_del_modelo_null_o_json_roto() -> None:
    assert propuesta_de_texto('{"cif": null, "razon_social": null, "url": null}', []) is None
    assert propuesta_de_texto("no lo sé", []) is None
    p = propuesta_de_texto(f'```json\n{{"cif": "{CIF_B}", "razon_social": "IRRIPLANT SL", "url": null}}\n```', ["https://u"])
    assert p is not None and p.url == "https://u"


def test_homonima_de_otra_localidad_no_se_acepta() -> None:
    resultados = [{"title": "IRRIPLANT SL - Infocif", "description": f"CIF {CIF_B}. Domicilio en Marbella (Málaga)", "url": "u"}]
    assert elegir_de_resultados("Irriplant", resultados, {"utrera", "sevilla"}) is None
    resultados[0]["description"] = f"CIF {CIF_B}. Domicilio en Utrera (Sevilla)"
    p = elegir_de_resultados("Irriplant", resultados, {"utrera", "sevilla"})
    assert p is not None and "Utrera" in p.evidencia


def test_titulo_con_dos_puntos() -> None:
    r = [{"title": "Irriplant SL: teléfono, CIF y dirección", "description": f"CIF {CIF_B}", "url": "u"}]
    p = elegir_de_resultados("Irriplant", r)
    assert p is not None and p.razon_social == "Irriplant SL"
