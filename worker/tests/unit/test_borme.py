"""Tests del conector BORME contra fixtures reales (sin red).

Los fixtures en `tests/fixtures/borme/` son una respuesta real del API de
datos abiertos del BOE, capturada el 2026-09-10 (BORME del 2026-09-08,
sección A, provincia SEVILLA).
"""

from __future__ import annotations

import json
from pathlib import Path

from radar.fuentes.borme import (
    ConectorBorme,
    acto_a_registro_bruto,
    parsear_acto,
    parsear_datos_acto,
    parsear_listado_provincia,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "borme"


def test_sumario_fixture_contiene_item_sevilla():
    datos = json.loads((FIXTURES / "sumario_20260908.json").read_text(encoding="utf-8"))
    diario = datos["data"]["sumario"]["diario"][0]
    seccion_a = next(s for s in diario["seccion"] if s["codigo"] == "A")
    titulos = {item["titulo"] for item in seccion_a["item"]}
    assert "SEVILLA" in titulos


def test_parsear_acto_separa_id_y_razon_social():
    id_borme, razon_social = parsear_acto("407615 - PANDORA FORMACION Y EMPLEO SL.", "")
    assert id_borme == "407615"
    assert razon_social == "PANDORA FORMACION Y EMPLEO SL"


def test_parsear_acto_sin_prefijo_numerico():
    id_borme, razon_social = parsear_acto("EMPRESA SIN NUMERO SL.", "")
    assert id_borme is None
    assert razon_social == "EMPRESA SIN NUMERO SL"


def test_parsear_datos_acto_constitucion_con_objeto_social():
    texto = (
        "Constitución. Comienzo de operaciones: 19.08.26. Objeto social: La sociedad "
        "tiene por objeto: Explotación de restaurantes. Domicilio: C/ TULIPANES 12 - "
        "CP 41928 (PALOMARES DEL RIO). Capital: 3.000,00 Euros. Nombramientos. "
        "Adm. Unico: ZHENG FAQUAN.  Datos registrales. S 8 , H SE156182, I/A 1 ( 1.09.26)."
    )
    datos = parsear_datos_acto(texto)
    assert "constitucion" in datos["tipos"]
    assert datos["codigo_postal"] == "41928"
    assert datos["municipio"] == "PALOMARES DEL RIO"
    assert datos["hoja_registral"] == "SE156182"
    assert datos["capital_eur"] == "3.000,00"
    assert "restaurantes" in datos["objeto_social"].lower()


def test_parsear_datos_acto_disolucion_y_extincion():
    texto = (
        "Ceses/Dimisiones. Adm. Solid.: X;Y. Disolución. Voluntaria. Extinción.  "
        "Datos registrales. S 8 , H SE128276, I/A 3 ( 1.09.26)."
    )
    datos = parsear_datos_acto(texto)
    assert "disolucion" in datos["tipos"]
    assert "extincion" in datos["tipos"]
    assert datos["objeto_social"] is None


def test_parsear_datos_acto_cp_con_punto_de_miles():
    texto = "Cambio de domicilio social. C/ MANUFACTURA 1 - 2ºA, C.P 41.927 (MAIRENA DEL ALJARAFE)."
    datos = parsear_datos_acto(texto)
    assert datos["codigo_postal"] == "41927"
    assert datos["municipio"] == "MAIRENA DEL ALJARAFE"


def test_parsear_listado_provincia_fixture_completo():
    xml_bytes = (FIXTURES / "acto_sevilla_20260908.xml").read_bytes()
    actos = parsear_listado_provincia(xml_bytes, "https://www.boe.es/diario_borme/xml.php?id=BORME-A-2026-173-41")
    assert len(actos) >= 30
    razones = {a.razon_social for a in actos}
    assert "UKIYO SUSHI SL" in razones
    assert "MENKAURA SL" in razones

    acto_constitucion = next(a for a in actos if a.razon_social == "UKIYO SUSHI SL")
    assert "constitucion" in acto_constitucion.tipos
    assert acto_constitucion.municipio == "PALOMARES DEL RIO"
    assert acto_constitucion.hoja_registral == "SE156182"
    assert acto_constitucion.es_candidato_construccion_por_objeto is False

    acto_construccion = next(a for a in actos if "RECOFRUIT" in a.razon_social)
    assert acto_construccion.es_candidato_construccion_por_objeto is True

    # falso positivo conocido y evitado: "C/ CARPINTERIA" es un nombre de
    # calle, no debe contar como señal de sector en el domicilio.
    acto_no_construccion = next(a for a in actos if "VIDAM" in a.razon_social)
    assert acto_no_construccion.es_candidato_construccion_por_objeto is False


def test_acto_a_registro_bruto_no_inventa_nif():
    xml_bytes = (FIXTURES / "acto_sevilla_20260908.xml").read_bytes()
    actos = parsear_listado_provincia(xml_bytes, "https://example.invalid/x")
    registro = acto_a_registro_bruto(actos[0])
    assert registro.campos.nif is None
    assert registro.fuente == "borme"
    assert registro.campos.razon_social


def test_acto_a_registro_bruto_marca_disuelta():
    xml_bytes = (FIXTURES / "acto_sevilla_20260908.xml").read_bytes()
    actos = parsear_listado_provincia(xml_bytes, "https://example.invalid/x")
    acto_disuelta = next(a for a in actos if "TENACIGROUP" in a.razon_social)
    registro = acto_a_registro_bruto(acto_disuelta)
    assert registro.campos.estado == "disuelta"


def test_acto_a_registro_bruto_objeto_social_es_campo_de_primera_clase():
    """Antes vivía en campos.extra["objeto_social"] -- un dict con clave de
    texto, sin comprobación de tipos. Ahora es un campo de primer nivel de
    CamposExtraidos (fuentes/base.py) y ya no debe quedar duplicado en
    extra."""
    xml_bytes = (FIXTURES / "acto_sevilla_20260908.xml").read_bytes()
    actos = parsear_listado_provincia(xml_bytes, "https://example.invalid/x")
    acto_con_objeto = next(a for a in actos if a.objeto_social)
    registro = acto_a_registro_bruto(acto_con_objeto)
    assert registro.campos.objeto_social == acto_con_objeto.objeto_social
    assert "objeto_social" not in registro.campos.extra


def test_parsear_datos_acto_extrae_administradores():
    texto = (
        "Ceses/Dimisiones. Adm. Unico: MACIAS GALAN RAQUEL. Nombramientos. "
        "Adm. Unico: LOPEZ GONZALEZ JESUS. Modificaciones estatutarias."
    )
    datos = parsear_datos_acto(texto)
    nombres = [a["nombre"] for a in datos["administradores"]]
    assert "LOPEZ GONZALEZ JESUS" in nombres


def test_parsear_datos_acto_administradores_solidarios_multiples():
    texto = "Nombramientos. Adm. Solid.: ORELLANA GOMEZ MIGUEL;LUPIAÑEZ CASCAJOSA JOSE LUIS."
    datos = parsear_datos_acto(texto)
    nombres = [a["nombre"] for a in datos["administradores"]]
    assert "ORELLANA GOMEZ MIGUEL" in nombres
    assert "LUPIAÑEZ CASCAJOSA JOSE LUIS" in nombres
    # los dos son "Adm. Solid." -- antes de esta sesión esto se perdía, se
    # guardaba solo el nombre (doc 08, migración 202609141600)
    assert all(a["cargo"] == "administrador_solidario" for a in datos["administradores"])


def test_parsear_datos_acto_distingue_consejero_de_consejero_delegado():
    """El regex original agrupaba "Consejero" y "Consejero Delegado" en un
    solo patrón -- perdiendo justo la distinción entre vocal del consejo y
    CEO, que es la que de verdad importa para un lead (doc 08)."""
    texto = "Nombramientos. Consejero Delegado: PEREZ RUIZ ANA. Consejero: GOMEZ DIAZ LUIS."
    datos = parsear_datos_acto(texto)
    por_nombre = {a["nombre"]: a["cargo"] for a in datos["administradores"]}
    assert por_nombre["PEREZ RUIZ ANA"] == "consejero_delegado"
    assert por_nombre["GOMEZ DIAZ LUIS"] == "consejero"


def test_parsear_datos_acto_administrador_mancomunado():
    texto = "Nombramientos. Adm. Mancom.: TORRES LEON PABLO."
    datos = parsear_datos_acto(texto)
    assert datos["administradores"] == [{"nombre": "TORRES LEON PABLO", "cargo": "administrador_mancomunado"}]


def test_parsear_datos_acto_presidente():
    texto = "Nombramientos. Presidente: NOTARIO AGUILAR JOSE ANTONIO."
    datos = parsear_datos_acto(texto)
    assert datos["administradores"] == [{"nombre": "NOTARIO AGUILAR JOSE ANTONIO", "cargo": "presidente"}]


def test_estimar_coste_es_cero():
    conector = ConectorBorme(cliente=None)  # type: ignore[arg-type]
    assert conector.estimar_coste({}) == 0.0


# --- Domicilio (2026-09-18) ------------------------------------------------
#
# Hasta esta fecha `acto_a_registro_bruto` dejaba `domicilio=None` siempre,
# sin ni intentar leer el campo "Domicilio:"/"Cambio de domicilio social."
# del texto -- confirmado corriendo BORME 30 días sobre Sevilla: el 82% de
# las empresas se quedaban sin ninguna fila en `sedes` aunque el 100% de
# los actos de "constitución" SÍ traen domicilio completo en el texto (solo
# el conector no lo leía). Los textos de estos tests son reales, capturados
# en esa corrida -- no inventados.


def test_domicilio_constitucion_cp_suelto_sin_etiqueta():
    texto = (
        "Constitución. Objeto social: Comercio al por menor de vehículos de motor. "
        "Domicilio: C/ AVIADOR CARMONA 4 - 41470 (PEÑAFLOR). Capital: 3.054,00 Euros. "
        "Nombramientos. Adm. Unico: GARCIA DOMINGUEZ MARTA.  Datos registrales. S 8 , H SE155802, I/A 1 (14.08.26)."
    )
    datos = parsear_datos_acto(texto)
    assert datos["domicilio"] == "C/ AVIADOR CARMONA 4 - 41470 (PEÑAFLOR)"
    assert datos["codigo_postal"] == "41470"
    assert datos["municipio"] == "PEÑAFLOR"


def test_domicilio_constitucion_sin_codigo_postal():
    texto = (
        "Constitución. Objeto social: Reparación y mantenimiento de equipos electrónicos y ópticos. "
        "Domicilio: C/ SAN FRANCISCO 29 - 41410 (CARMONA)."
    )
    datos = parsear_datos_acto(texto)
    assert datos["codigo_postal"] == "41410"
    texto_sin_cp = (
        "Constitución. Objeto social: Sociedad holding. "
        "Domicilio: AVDA VIRGEN DE MONTEMAYOR 51 - CARRETERA ARAHAL-EL (ARAHAL). Capital: 4.358.589,00 Euros."
    )
    datos_sin_cp = parsear_datos_acto(texto_sin_cp)
    assert datos_sin_cp["domicilio"] == "AVDA VIRGEN DE MONTEMAYOR 51 - CARRETERA ARAHAL-EL (ARAHAL)"
    assert datos_sin_cp["codigo_postal"] is None
    assert datos_sin_cp["municipio"] == "ARAHAL"


def test_domicilio_cambio_de_domicilio_social_con_codigo_postal_etiquetado():
    texto = (
        "Modificaciones estatutarias. Artículo de los estatutos: 4. Domicilio social.-. "
        "Cambio de domicilio social. URB LOS CLAVELES 9 - CODIGO POSTAL 41510 (MAIRENA DEL ALCOR).  "
        "Datos registrales. S 8 , H SE153590, I/A 2 (11.08.26)."
    )
    datos = parsear_datos_acto(texto)
    assert datos["codigo_postal"] == "41510"
    assert datos["municipio"] == "MAIRENA DEL ALCOR"
    # el boilerplate "Domicilio social.-." de qué artículo cambió NO debe
    # confundirse con la dirección real, que viene después
    assert "Modificaciones" not in (datos["domicilio"] or "")


def test_domicilio_cambio_de_domicilio_social_sin_codigo_postal():
    texto = (
        "Modificaciones estatutarias. Artículo de los estatutos: ARTICULO 3. Domicilio social y web corporativa.-. "
        "Cambio de domicilio social. AVDA REPUBLICA ARGENTINA 35A - PLANTA CUARTA, OFIC (SEVILLA).  "
        "Datos registrales. S 8 , H SE 92899, I/A 15 (11.09.26)."
    )
    datos = parsear_datos_acto(texto)
    assert datos["domicilio"] == "AVDA REPUBLICA ARGENTINA 35A - PLANTA CUARTA, OFIC (SEVILLA)"
    assert datos["municipio"] == "SEVILLA"
    assert datos["codigo_postal"] is None


def test_domicilio_cambio_de_domicilio_se_corta_antes_de_cambio_de_objeto_social():
    texto = (
        "Cambio de domicilio social. C/ LUIS MONTOTO 11 - LOCAL (SEVILLA). Cambio de objeto social. "
        "Constituye la actividad principal la siguiente. : Clasificación Nacional de Actividades Económicas "
        "CNAE es el 5210 \"Depósito y almacenamiento.  Datos registrales. S 8 , H SE146448, I/A 2 (10.09.26)."
    )
    datos = parsear_datos_acto(texto)
    assert datos["domicilio"] == "C/ LUIS MONTOTO 11 - LOCAL (SEVILLA)"
    assert datos["municipio"] == "SEVILLA"


def test_domicilio_ausente_en_actos_sin_direccion():
    """Ceses, nombramientos y revocaciones no repiten la dirección en el
    BORME -- no es un fallo de extracción, el dato no está en el texto."""
    texto = (
        "Ceses/Dimisiones. Adm. Unico: RUIZ DEL POZO CANEL MARIA YOLANDA. "
        "Nombramientos. Adm. Unico: BENITEZ FERNANDEZ JUAN MARIA.  "
        "Datos registrales. S 8 , H SE 39467, I/A 5 (25.08.26)."
    )
    datos = parsear_datos_acto(texto)
    assert datos["domicilio"] is None
    assert datos["codigo_postal"] is None
    assert datos["municipio"] is None


def test_domicilio_cp_de_4_digitos_se_descarta():
    """Caso real de producción (2026-09-18): el propio BOE publicó un CP
    de 4 dígitos ("CP:4193" en vez de 5) -- un CP español SIEMPRE tiene 5
    dígitos, así que se descarta en vez de guardarlo (mejor sin CP que uno
    mal leído -- y de hecho violaba `chk_cp` en `sedes`, revirtiendo el
    reproceso de domicilios a mitad)."""
    texto = "Constitución. Domicilio: C/ NUESTRA SEÑORA DE LOS DOLORES 25 2 C - CP:4193 (BORMUJOS)."
    datos = parsear_datos_acto(texto)
    assert datos["municipio"] == "BORMUJOS"
    assert datos["codigo_postal"] is None


def test_domicilio_cp_literal_sin_numero_no_revienta():
    """Caso real donde el propio BOE escribe "CP" sin ningún dígito detrás
    -- no debe intentar inventar un código postal."""
    texto = (
        "Constitución. Domicilio: AVDA DE UMBRETE 35 - POLIGONO INDUSTRIAL PIBO, CP (BOLLULLOS DE LA MITACION). "
        "Capital: 50.000,00 Euros."
    )
    datos = parsear_datos_acto(texto)
    assert datos["municipio"] == "BOLLULLOS DE LA MITACION"
    assert datos["codigo_postal"] is None


def test_acto_a_registro_bruto_incluye_domicilio():
    """`acto_a_registro_bruto` dejaba `domicilio=None` siempre, sin usar lo
    que `parsear_datos_acto` sí extraía -- por eso `sedes` se quedaba vacía
    para la mayoría de constituciones pese a que el BORME publica la
    dirección completa."""
    xml_bytes = (FIXTURES / "acto_sevilla_20260908.xml").read_bytes()
    actos = parsear_listado_provincia(xml_bytes, "https://ejemplo/actos.xml")
    con_domicilio = [a for a in actos if a.domicilio]
    assert con_domicilio, "el fixture debería tener al menos una constitución con domicilio"
    registro = acto_a_registro_bruto(con_domicilio[0])
    assert registro.campos.domicilio == con_domicilio[0].domicilio
