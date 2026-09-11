"""Tests de regresión de `radar.verificacion` (doc 05 §3-§6).

Si cambias un umbral, una semivida o un peso aquí, cámbialo también en
doc 05 y en los módulos correspondientes.
"""

from datetime import UTC, datetime, timedelta

from radar.verificacion.confianza import consolidar_campo
from radar.verificacion.estado import SenalesEstado, determinar_estado
from radar.verificacion.global_ import calcular_confianza_global

AHORA = datetime(2026, 9, 11, tzinfo=UTC)


def obs(valor, confianza, dias_atras, grupo="g1", registro_oficial=False):
    return {
        "valor_norm": valor,
        "confianza_fuente": confianza,
        "grupo_independencia": grupo,
        "observado_en": AHORA - timedelta(days=dias_atras),
        "es_registro_oficial": registro_oficial,
    }


# ---------- consolidar_campo ----------
def test_combina_fuentes_independientes():
    # Dos fuentes independientes con 0.8 cada una -> 1 - (1-0.8)^2 = 0.96
    r = consolidar_campo(
        "telefono",
        [obs("+34955123456", 0.8, 0, grupo="web_propia"), obs("+34955123456", 0.8, 0, grupo="google")],
        ahora=AHORA,
    )
    assert r.ganador.valor == "+34955123456"
    assert r.ganador.confianza == 0.96


def test_mismo_grupo_no_suma_dos_veces():
    # Dos directorios (mismo grupo) que dicen lo mismo cuentan como uno solo.
    r = consolidar_campo(
        "telefono",
        [obs("+34955123456", 0.5, 0, grupo="directorios"), obs("+34955123456", 0.5, 0, grupo="directorios")],
        ahora=AHORA,
    )
    assert r.ganador.confianza == 0.5
    assert r.ganador.n_fuentes_independientes == 1


def test_decaimiento_por_antiguedad():
    # semivida teléfono = 365 días -> a los 365 días, c_efectiva = c/2
    r = consolidar_campo("telefono", [obs("+34955123456", 0.8, 365, grupo="web_propia")], ahora=AHORA)
    assert abs(r.ganador.confianza_efectiva - 0.4) < 0.001


def test_campo_sin_decaimiento():
    r = consolidar_campo("nif", [obs("B41123456", 0.95, 3650, grupo="registro_mercantil")], ahora=AHORA)
    assert r.ganador.confianza_efectiva == r.ganador.confianza == 0.95


def test_gana_mayor_confianza_efectiva():
    r = consolidar_campo(
        "telefono",
        [
            obs("+34955000001", 0.9, 0, grupo="web_propia"),
            obs("+34955000002", 0.5, 0, grupo="directorio"),
        ],
        ahora=AHORA,
    )
    assert r.ganador.valor == "+34955000001"


def test_empate_gana_registro_oficial_en_razon_social():
    r = consolidar_campo(
        "razon_social",
        [
            obs("construcciones perez sl", 0.85, 10, grupo="web_propia"),
            obs("construcciones perez sl antiguo", 0.85, 1, grupo="registro_mercantil", registro_oficial=True),
        ],
        ahora=AHORA,
    )
    assert r.ganador.valor == "construcciones perez sl antiguo"


def test_multivalor_telefonos():
    r = consolidar_campo(
        "telefono",
        [
            obs("+34955000001", 0.9, 0, grupo="web_propia"),
            obs("+34955000002", 0.6, 0, grupo="google"),
            obs("+34955000003", 0.3, 0, grupo="directorio"),
        ],
        ahora=AHORA,
    )
    valores = {v.valor for v in r.multivalor}
    assert valores == {"+34955000001", "+34955000002"}


def test_conflicto_rebaja_confianza():
    ganador_sin_rebaja = consolidar_campo(
        "web", [obs("a.es", 0.85, 0, grupo="web_propia")], ahora=AHORA
    ).ganador.confianza_efectiva
    r = consolidar_campo(
        "web",
        [obs("a.es", 0.85, 0, grupo="web_propia"), obs("b.es", 0.8, 0, grupo="google")],
        ahora=AHORA,
    )
    assert r.conflicto is True
    assert r.ganador.confianza_efectiva < ganador_sin_rebaja


# ---------- estado ----------
def test_estado_borme_extincion_corta_lo_demas():
    s = SenalesEstado(borme_extincion=True, web_viva_reciente=True, google_operativo=True)
    assert determinar_estado(s) == ("extinguida", 0.95)


def test_estado_disolucion_con_y_sin_liquidacion():
    assert determinar_estado(SenalesEstado(borme_disolucion="con_liquidacion")) == ("en_liquidacion", 0.95)
    assert determinar_estado(SenalesEstado(borme_disolucion="sin_liquidacion")) == ("disuelta", 0.95)


def test_estado_dos_senales_positivas_activa():
    s = SenalesEstado(web_viva_reciente=True, google_operativo=True)
    estado, _ = determinar_estado(s)
    assert estado == "activa"


def test_estado_una_senal_probablemente_activa():
    s = SenalesEstado(web_viva_reciente=True)
    estado, _ = determinar_estado(s)
    assert estado == "probablemente_activa"


def test_estado_positivas_y_negativas_dudosa():
    s = SenalesEstado(web_viva_reciente=True, senales_negativas=1)
    estado, _ = determinar_estado(s)
    assert estado == "dudosa"


def test_estado_sin_senales_desconocida():
    estado, _ = determinar_estado(SenalesEstado())
    assert estado == "desconocida"


def test_estado_google_cerrado_sin_positivas_inactiva():
    estado, _ = determinar_estado(SenalesEstado(google_cerrado_permanentemente=True))
    assert estado == "inactiva"


def test_estado_google_cerrado_con_positivas_dudosa():
    estado, _ = determinar_estado(
        SenalesEstado(google_cerrado_permanentemente=True, web_viva_reciente=True, google_operativo=True)
    )
    assert estado == "dudosa"


# ---------- confianza global ----------
def test_confianza_global_pondera_correctamente():
    c = calcular_confianza_global(
        confianza_identidad=1.0, confianza_estado=1.0, confianza_ubicacion=1.0, confianza_contacto=1.0,
        nif_confirmado=True,
    )
    assert c == 1.0


def test_confianza_global_topada_sin_nif():
    c = calcular_confianza_global(
        confianza_identidad=1.0, confianza_estado=1.0, confianza_ubicacion=1.0, confianza_contacto=1.0,
        nif_confirmado=False,
    )
    assert c == 0.6


def test_confianza_global_campo_ausente_cuenta_cero():
    c = calcular_confianza_global(
        confianza_identidad=0.8, confianza_estado=None, confianza_ubicacion=0.5, confianza_contacto=0.5,
        nif_confirmado=True,
    )
    assert c == round(0.40 * 0.8 + 0.15 * 0.5 + 0.20 * 0.5, 4)
