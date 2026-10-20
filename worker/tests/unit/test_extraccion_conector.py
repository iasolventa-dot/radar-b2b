"""Tests de las funciones puras de `radar.extraccion.conector` (mapear
resultados de reglas/LLM a `CamposExtraidos`) — `enriquecer_desde_web` en sí
necesita red y se prueba de forma manual/integración."""

from radar.extraccion.conector import (
    campos_desde_llm,
    campos_desde_reglas,
    persona_valida,
    raiz_de,
    telefonos_de_la_empresa,
)
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


def test_se_lee_la_portada_y_no_el_articulo():
    assert raiz_de("https://madeplax.com/reformas-hoteleras-sin-retrasos/") == "https://madeplax.com/"
    assert raiz_de("https://www.x.es") is None and raiz_de("https://www.x.es/") is None


def test_telefonos_extranjeros_fuera_si_hay_espanoles():
    assert telefonos_de_la_empresa(["+34961665957", "+18095520435", "+529848040524"]) == ["+34961665957"]
    assert telefonos_de_la_empresa(["+376650378"]) == ["+376650378"]


TEXTO_EQUIPO = """Nuestro equipo
Arquitecto
Pol Puig
Arquitecto
Sergi Balaguer
Socio
Paco Lago, CEO y Dirección Creativa. Ana Albarracín - Gestión de proyectos.
Contacto: David López"""


def test_personas_del_llm_se_verifican_contra_el_texto():
    assert persona_valida("Paco Lago", "CEO y Dirección Creativa", TEXTO_EQUIPO)
    assert persona_valida("David López", "Contacto", TEXTO_EQUIPO)
    # nombre mal leído de una ficha de equipo (con otros cargos dentro)
    assert not persona_valida("Arquitecto\n Pol Puig\n Arquitecto", "Director de proyectos", TEXTO_EQUIPO)
    assert not persona_valida("Arquitecto Pol Puig", "Socio", TEXTO_EQUIPO)
    # nombre que no está en el texto (inventado) o con un cargo que no está junto a él
    assert not persona_valida("Juan Inventado", "Gerente", TEXTO_EQUIPO)
    assert not persona_valida("Ana Albarracín", "Directora general", TEXTO_EQUIPO)


def test_campos_desde_llm_descarta_personas_no_verificadas():
    from radar.extraccion.llm import PersonaLLM

    llm = RespuestaExtraccionLLM(
        titular=TitularExtraidoLLM(telefonos=["+34933034160", "+18763648888"]),
        personas=[PersonaLLM(nombre="Paco Lago", cargo="CEO"), PersonaLLM(nombre="Arquitecto\n Pol Puig", cargo="Socio")],
        confianza=0.8, notas="",
    )
    campos = campos_desde_llm(CamposExtraidos(), llm, TEXTO_EQUIPO)
    assert [p["nombre"] for p in campos.extra["personas_contacto"]] == ["Paco Lago"]
    assert campos.telefonos == ["+34933034160"]


def test_reglas_no_juntan_nombres_de_lineas_distintas():
    from radar.extraccion.reglas import extraer_personas

    ficha_equipo = "Arquitecto\nSergi Balaguer\nSocio\nArquitecto\nPol Puig\nArquitecto"
    assert extraer_personas(ficha_equipo) == []
    assert extraer_personas("Gerente: Luis Ejemplo Pérez") == [{"nombre": "Luis Ejemplo Pérez", "cargo": "Gerente"}]
