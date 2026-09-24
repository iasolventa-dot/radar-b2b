from datetime import UTC, datetime, timedelta

from radar.verificacion.confianza import consolidar_campo
from radar.verificacion.conflictos import clasificar_conflicto

AHORA = datetime(2026, 9, 24, tzinfo=UTC)


def obs(valor, conf, grupo, dias=0, fuente="Web", oficial=False):
    return {
        "valor_norm": valor, "valor_original": valor, "confianza_fuente": conf, "grupo_independencia": grupo,
        "observado_en": AHORA - timedelta(days=dias), "es_registro_oficial": oficial, "fuente_nombre": fuente,
    }


def clasificar(campo, observaciones):
    return clasificar_conflicto(consolidar_campo(campo, observaciones, AHORA), observaciones)


def test_un_solo_valor_no_es_conflicto():
    assert clasificar("razon_social", [obs("perez sl", 0.85, "web"), obs("perez sl", 0.95, "rm")]) is None


def test_campos_multivalor_no_generan_conflicto():
    assert clasificar("telefono", [obs("+34911111111", 0.85, "web"), obs("+34922222222", 0.55, "google")]) is None


def test_varias_fuentes_contra_una_es_evidencia_fuerte():
    c = clasificar("web", [
        obs("perez.es", 0.85, "web_propia"), obs("perez.es", 0.55, "google"), obs("perez.es", 0.60, "osm"),
        obs("perezobras.com", 0.85, "otra_web"),
    ])
    assert c is not None and c.tipo == "resuelto_con_evidencia" and c.valor_elegido == "perez.es"
    assert "fuentes independientes" in c.motivo


def test_dato_antiguo_sustituido_por_uno_nuevo_igual_de_fiable():
    c = clasificar("razon_social", [
        obs("PEREZ OBRAS SL", 0.85, "web_a", dias=400), obs("PEREZ REFORMAS SL", 0.85, "web_b", dias=2),
    ])
    assert c is not None and c.tipo == "resuelto_con_evidencia" and c.valor_elegido == "PEREZ REFORMAS SL"
    assert "antiguo" in c.motivo


def test_fuentes_parecidas_contradictorias_quedan_sin_contrastar():
    c = clasificar("razon_social", [obs("ALFA SL", 0.85, "web_a", dias=3), obs("BETA SL", 0.85, "web_b", dias=1)])
    assert c is not None and c.tipo == "sin_contrastar"
    assert {a["valor"] for a in c.alternativas} == {"ALFA SL", "BETA SL"}


def test_alternativa_residual_no_cuenta():
    # 0.30 < UMBRAL_ALTERNATIVA: una sola fuente muy poco fiable no crea contradicción.
    assert clasificar("nif", [obs("B11111111", 0.9, "placsp"), obs("B22222222", 0.2, "llm")]) is None


def test_valor_decidido_por_una_persona_no_reabre_la_contradiccion():
    assert clasificar("razon_social", [
        obs("ALFA SL", 0.85, "web_a"), obs("BETA SL", 0.85, "web_b"), obs("BETA SL", 0.98, "manual", fuente="Verificación manual"),
    ]) is None
