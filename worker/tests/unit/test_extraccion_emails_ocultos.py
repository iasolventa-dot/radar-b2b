"""Emails que no están en el texto visible de la web (2026-10-01)."""

from radar.extraccion.conector import (
    _descifrar_cfemail,
    _texto_de_pagina,
    desofuscar_texto,
    emails_en_html,
)


def _cf(email: str, clave: int = 0x42) -> str:
    return bytes([clave] + [ord(c) ^ clave for c in email]).hex()


def test_mailto_y_cloudflare() -> None:
    html = f'''<a href="mailto:Info@Climont.es?subject=Hola">Escríbenos</a>
    <a class="__cf_email__" data-cfemail="{_cf("ventas@climont.es")}">[email&#160;protected]</a>'''
    assert emails_en_html(html) == ["info@climont.es", "ventas@climont.es"]


def test_cloudflare_descifrado() -> None:
    assert _descifrar_cfemail(_cf("a@b.es")) == "a@b.es"
    assert _descifrar_cfemail("zz") is None


def test_arroba_escrita() -> None:
    assert desofuscar_texto("info (arroba) jimta (punto) es") == "info@jimta.es"
    assert desofuscar_texto("info [at] jimta.es") == "info@jimta.es"


def test_el_email_oculto_llega_al_texto_que_leen_las_reglas() -> None:
    texto = _texto_de_pagina('<html><body><p>Contacto</p><a href="mailto:hola@empresa.es">Escríbenos</a></body></html>')
    assert "hola@empresa.es" in texto
