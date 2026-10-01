"""Enlaces a LinkedIn/Facebook en la portada de una web de empresa."""

from radar.extraccion.conector import enlaces_redes, metadatos_portada

HTML = """
<html><head><title>Transportes Pérez</title></head><body>
<a href="https://www.linkedin.com/company/transportes-perez/">LinkedIn</a>
<a href="https://es.linkedin.com/company/transportes-perez">LinkedIn ES</a>
<a href="https://www.facebook.com/TransportesPerezSevilla/">Facebook</a>
<a href="https://www.facebook.com/sharer/sharer.php?u=x">Compartir</a>
<a href="https://www.facebook.com/tr?id=123">pixel</a>
</body></html>
"""


def test_extrae_paginas_de_empresa_y_descarta_botones_de_compartir() -> None:
    r = enlaces_redes(HTML)
    assert r["redes_linkedin"][0] == "https://www.linkedin.com/company/transportes-perez"
    assert r["redes_facebook"] == ["https://www.facebook.com/TransportesPerezSevilla"]


def test_metadatos_incluyen_redes() -> None:
    m = metadatos_portada(HTML)
    assert m["titulo_web"] == "Transportes Pérez"
    assert m["redes_facebook"] == ["https://www.facebook.com/TransportesPerezSevilla"]


def test_sin_redes_listas_vacias() -> None:
    assert enlaces_redes("<html>nada</html>") == {"redes_linkedin": [], "redes_facebook": []}
