"""Tests de `radar.orquestador.logica` y `radar.orquestador.senales_borme`
— las partes del orquestador que no tocan la base de datos (`bd.py` y
`procesar.py` se prueban de forma manual/integración contra Supabase, con
`scripts/ejecutar_borme.py`, igual que `radar.resolucion.blocking`)."""

from datetime import UTC, datetime

from radar.fuentes.base import CamposExtraidos
from radar.orquestador.logica import (
    campos_a_dict_normalizacion,
    combinar_dimension_contacto,
    combinar_dimension_identidad,
    decidir_resolucion,
    texto_representativo,
)
from radar.orquestador.senales_borme import mapear_senales_borme
from radar.verificacion.confianza import consolidar_campo

AHORA = datetime(2026, 9, 11, tzinfo=UTC)


def test_campos_a_dict_normalizacion_mapea_claves():
    campos = CamposExtraidos(
        razon_social="Construcciones Pérez SL", nif="B41123456", telefonos=["955123456"],
        codigo_postal="41001", provincia="Sevilla", extra={"place_id": "abc123"},
    )
    d = campos_a_dict_normalizacion(campos)
    assert d["razon_social"] == "Construcciones Pérez SL"
    assert d["cp"] == "41001"
    assert d["place_id"] == "abc123"
    assert d["telefonos"] == ["955123456"]


# ---------- decidir_resolucion ----------
def _candidato(empresa_id, **kw):
    base = {
        "empresa_id": empresa_id, "nif": None, "nif_valido": None, "nombre_norm": "", "comercial_norm": "",
        "forma_juridica": None, "dominio": None, "telefonos": [], "telefonos_especiales": [], "emails": [],
        "cp": None, "provincia": None, "cod_provincia": None, "lat": None, "lon": None, "place_id": None,
    }
    base.update(kw)
    return base


def test_decidir_resolucion_sin_candidatos_crea():
    d = decidir_resolucion({"nif": None, "nif_valido": None}, [])
    assert d.accion == "crear"
    assert d.empresa_id is None


def test_decidir_resolucion_mismo_nif_vincula():
    nuevo = {"nif": "B41123456", "nif_valido": True, "nombre_norm": "construcciones perez",
              "comercial_norm": "", "forma_juridica": "SL", "dominio": None, "telefonos": [],
              "telefonos_especiales": [], "emails": [], "cp": None, "provincia": None,
              "cod_provincia": None, "lat": None, "lon": None, "place_id": None}
    candidato = _candidato("emp-1", nif="B41123456", nif_valido=True, nombre_norm="construcciones perez")
    d = decidir_resolucion(nuevo, [candidato])
    assert d.accion == "vincular"
    assert d.empresa_id == "emp-1"


def test_decidir_resolucion_nif_distinto_crea():
    nuevo = {"nif": "B41123456", "nif_valido": True, "nombre_norm": "construcciones perez",
              "comercial_norm": "", "forma_juridica": "SL", "dominio": None, "telefonos": [],
              "telefonos_especiales": [], "emails": [], "cp": None, "provincia": None,
              "cod_provincia": None, "lat": None, "lon": None, "place_id": None}
    candidato = _candidato("emp-1", nif="B99999999", nif_valido=True, nombre_norm="construcciones perez")
    d = decidir_resolucion(nuevo, [candidato])
    assert d.accion == "crear"


def test_decidir_resolucion_zona_gris_crea_y_revisa():
    # Sin NIF en ninguno de los dos, mismo dominio -> puntuación en zona de revisión (0.55-0.80)
    nuevo = {"nif": None, "nif_valido": None, "nombre_norm": "perez obras", "comercial_norm": "",
              "forma_juridica": None, "dominio": "perezobras.es", "telefonos": [], "telefonos_especiales": [],
              "emails": [], "cp": None, "provincia": None, "cod_provincia": None, "lat": None, "lon": None,
              "place_id": None}
    candidato = _candidato("emp-1", nombre_norm="construcciones martinez", dominio="perezobras.es")
    d = decidir_resolucion(nuevo, [candidato])
    assert d.accion == "crear_y_revisar"
    assert d.mejor_candidato_id == "emp-1"


def test_decidir_resolucion_elige_el_mejor_de_varios():
    nuevo = {"nif": None, "nif_valido": None, "nombre_norm": "construcciones perez sevilla",
              "comercial_norm": "", "forma_juridica": None, "dominio": None, "telefonos": [],
              "telefonos_especiales": [], "emails": [], "cp": None, "provincia": None,
              "cod_provincia": None, "lat": None, "lon": None, "place_id": None}
    lejano = _candidato("emp-lejano", nombre_norm="reformas del norte")
    cercano = _candidato("emp-cercano", nombre_norm="construcciones perez sevilla")
    d = decidir_resolucion(nuevo, [lejano, cercano])
    assert d.mejor_candidato_id == "emp-cercano"


# ---------- combinar dimensiones ----------
def test_combinar_dimension_identidad_promedia():
    obs_nif = [{"valor_norm": "B1", "confianza_fuente": 0.9, "grupo_independencia": "g", "observado_en": AHORA}]
    obs_rs = [{"valor_norm": "perez", "confianza_fuente": 0.7, "grupo_independencia": "g", "observado_en": AHORA}]
    res_nif = consolidar_campo("nif", obs_nif, AHORA)
    res_rs = consolidar_campo("razon_social", obs_rs, AHORA)
    assert combinar_dimension_identidad(res_nif, res_rs) == round((0.9 + 0.7) / 2, 4)


def test_combinar_dimension_identidad_sin_datos_es_cero():
    assert combinar_dimension_identidad(None, None) == 0.0


def test_combinar_dimension_contacto_usa_el_maximo():
    obs_tel = [{"valor_norm": "+34955000000", "confianza_fuente": 0.9, "grupo_independencia": "g", "observado_en": AHORA}]
    obs_email = [{"valor_norm": "a@b.es", "confianza_fuente": 0.4, "grupo_independencia": "g", "observado_en": AHORA}]
    res_tel = consolidar_campo("telefono", obs_tel, AHORA)
    res_email = consolidar_campo("email", obs_email, AHORA)
    assert combinar_dimension_contacto(res_tel, res_email) == 0.9


# ---------- texto_representativo ----------
def test_texto_representativo_elige_mas_confianza():
    obs = [
        {"valor_norm": "perez", "valor_original": "Perez SL", "confianza_fuente": 0.5, "observado_en": AHORA},
        {"valor_norm": "perez", "valor_original": "PEREZ S.L.", "confianza_fuente": 0.9, "observado_en": AHORA},
    ]
    assert texto_representativo(obs, "perez") == "PEREZ S.L."


def test_texto_representativo_sin_valor_none():
    assert texto_representativo([], None) is None


# ---------- senales_borme ----------
def test_senales_borme_extincion():
    assert mapear_senales_borme(["extincion"]).borme_extincion is True


def test_senales_borme_disolucion():
    assert mapear_senales_borme(["disolucion"]).borme_disolucion == "sin_liquidacion"


def test_senales_borme_constitucion_es_senal_positiva():
    s = mapear_senales_borme(["constitucion"])
    assert s.acto_societario_no_extintivo_reciente is True


def test_senales_borme_sin_actos_relevantes():
    from radar.verificacion.estado import SenalesEstado

    assert mapear_senales_borme(["nombramiento"]) == SenalesEstado()
