"""Tests de las funciones puras de `radar.extraccion.conector` (mapear
resultados de reglas/LLM a `CamposExtraidos`) — `enriquecer_desde_web` en sí
necesita red y se prueba de forma manual/integración."""

from radar.extraccion.conector import campos_desde_llm, campos_desde_reglas
from radar.extraccion.llm import RespuestaExtraccionLLM, TitularExtraidoLLM
from radar.extraccion.reglas import (
    DatosLegalesExtraidos,
    EmailEncontrado,
    NifEncontrado,
    RegistroMercantilEncontrado,
)
from radar.fuentes.base import CamposExtraidos


def test_campos_desde_reglas_mapea_lo_encontrado():
    r = DatosLegalesExtraidos(
        nifs=[NifEncontrado(nif="B41123456", tipo="sociedad", etiquetado_como_nif=True, cerca_de_mencion_agencia=False)],
        razones_sociales=["Construcciones Pérez SL"],
        codigos_postales=["41001"],
        telefonos=["+34955123456"],
        emails=[EmailEncontrado(email="info@perezobras.es", es_generico=True, del_dominio=True)],
        registro_mercantil=RegistroMercantilEncontrado(registro="Sevilla", tomo="1234", folio="56", hoja="SE-98765"),
    )
    campos = campos_desde_reglas(r, "perezobras.es")
    assert campos.nif == "B41123456"
    assert campos.razon_social == "Construcciones Pérez SL"
    assert campos.codigo_postal == "41001"
    assert campos.emails == ["info@perezobras.es"]
    assert campos.extra["hoja_registral"] == "SE-98765"
    assert campos.extra["fuente_dato"] == "reglas"


def test_campos_desde_reglas_prefiere_email_del_dominio():
    r = DatosLegalesExtraidos(
        emails=[
            EmailEncontrado(email="info@agenciaweb.com", es_generico=True, del_dominio=False),
            EmailEncontrado(email="contacto@perezobras.es", es_generico=True, del_dominio=True),
        ]
    )
    campos = campos_desde_reglas(r, "perezobras.es")
    assert campos.emails == ["contacto@perezobras.es"]


def test_campos_desde_llm_gana_cuando_responde_algo():
    base = CamposExtraidos(razon_social="Construcciones Pérez SL", nif=None, codigo_postal="41001")
    llm = RespuestaExtraccionLLM(
        titular=TitularExtraidoLLM(razon_social="CONSTRUCCIONES PEREZ, S.L.", nif="B41123456", domicilio="Calle Mayor 12"),
        confianza=0.9,
        notas="NIF claro en el texto, asociado al titular",
    )
    campos = campos_desde_llm(base, llm)
    # el LLM se llamó precisamente porque había dudas: si responde algo,
    # su lectura del mismo texto prevalece sobre el heurístico de reglas.
    assert campos.nif == "B41123456"
    assert campos.razon_social == "CONSTRUCCIONES PEREZ, S.L."
    assert campos.domicilio == "Calle Mayor 12"
    assert campos.extra["fuente_dato"] == "llm"
    assert campos.extra["confianza_llm"] == 0.9


def test_campos_desde_llm_conserva_lo_que_el_llm_deja_en_null():
    base = CamposExtraidos(razon_social="Construcciones Pérez SL", codigo_postal="41001")
    llm = RespuestaExtraccionLLM(titular=TitularExtraidoLLM(nif="B41123456"), confianza=0.6, notas="")
    campos = campos_desde_llm(base, llm)
    # el LLM no dice nada de razón social/CP ("si un dato no aparece,
    # null") -> se conserva lo que ya habían encontrado las reglas.
    assert campos.razon_social == "Construcciones Pérez SL"
    assert campos.codigo_postal == "41001"
    assert campos.nif == "B41123456"
