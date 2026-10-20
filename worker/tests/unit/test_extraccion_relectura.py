"""Relectura de webs ya guardadas: qué se retira. Sin BD ni red."""

from __future__ import annotations

from radar.extraccion.relectura import FUENTE_WEB, LeidoEnWeb, retirar_canal
from radar.fuentes.base import CamposExtraidos, RegistroBruto


def test_solo_se_retira_lo_que_solo_respaldaba_la_web_y_ya_no_aparece():
    assert retirar_canal({FUENTE_WEB}, encontrado=False, leidos_del_tipo=2)
    assert not retirar_canal({FUENTE_WEB}, encontrado=True, leidos_del_tipo=2)
    # lo confirma otra fuente (Maps): se queda aunque la web ya no lo muestre
    assert not retirar_canal({FUENTE_WEB, "Google Maps (vía Apify, no oficial)"}, encontrado=False, leidos_del_tipo=2)
    # sin evidencia registrada no se decide nada
    assert not retirar_canal(set(), encontrado=False, leidos_del_tipo=2)
    # la relectura no encontró ninguno (portada que no se pudo leer bien): no se toca
    assert not retirar_canal({FUENTE_WEB}, encontrado=False, leidos_del_tipo=0)


def test_lo_leido_incluye_telefonos_espanoles_de_las_reglas_y_personas():
    registro = RegistroBruto(
        fuente="web_empresa", id_externo=None, url="https://x.es/",
        payload={"reglas": {"telefonos": ["+34955000001", "+18095520435"], "emails": [{"email": "Obras@x.es"}]}},
        campos=CamposExtraidos(
            telefonos=["+34 600 000 001"], emails=["info@x.es"],
            extra={"personas_contacto": [{"nombre": "José Pérez", "cargo": "Gerente"}]},
        ),
    )
    leido = LeidoEnWeb.de_registro(registro)
    assert leido.telefonos == {"600000001", "955000001"}
    assert leido.emails == {"info@x.es", "obras@x.es"}
    assert leido.personas == {"jose perez"}
