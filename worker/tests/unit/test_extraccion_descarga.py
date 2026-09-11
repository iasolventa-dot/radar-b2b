"""Tests de `radar.extraccion.descarga.encontrar_enlaces_legales` (doc 04
§3, paso 1) — la única parte de ese módulo que no necesita red."""

from radar.extraccion.descarga import encontrar_enlaces_legales


def test_encuentra_enlace_por_texto():
    html = '<html><body><a href="/legal.html">Aviso Legal</a></body></html>'
    assert encontrar_enlaces_legales(html, "https://perezobras.es/") == ["https://perezobras.es/legal.html"]


def test_encuentra_enlace_por_href_aunque_el_texto_no_diga_nada():
    html = '<html><body><a href="/aviso-legal">Más info</a></body></html>'
    assert encontrar_enlaces_legales(html, "https://perezobras.es/") == ["https://perezobras.es/aviso-legal"]


def test_ignora_mailto_tel_y_anclas():
    html = """
    <a href="mailto:info@x.es">Contacto</a>
    <a href="tel:+34955123456">Llamar</a>
    <a href="#contacto">Contacto</a>
    """
    assert encontrar_enlaces_legales(html, "https://perezobras.es/") == []


def test_resuelve_urls_relativas_y_dedup():
    html = """
    <a href="/contacto">Contacto</a>
    <a href="/contacto">Contáctanos</a>
    <a href="https://perezobras.es/privacidad">Privacidad</a>
    """
    enlaces = encontrar_enlaces_legales(html, "https://perezobras.es/inicio")
    assert enlaces == ["https://perezobras.es/contacto", "https://perezobras.es/privacidad"]


def test_no_confunde_enlaces_normales():
    html = '<a href="/productos">Productos</a><a href="/blog">Blog</a>'
    assert encontrar_enlaces_legales(html, "https://perezobras.es/") == []
