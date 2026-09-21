from radar.agente.enriquecer_apify import _es_web_propia, agrupar_por_dominio


def test_agrupa_paginas_por_dominio_y_une_el_texto():
    items = [
        {"url": "https://reformasx.es/", "text": "Inicio"},
        {"url": "https://www.reformasx.es/aviso-legal", "text": "Titular: REFORMAS X SL CIF B41000000"},
        {"url": "https://otra.es/", "text": "Otra"},
        {"url": "https://otra.es/vacia", "text": "   "},
        {"url": None, "text": "sin url"},
    ]
    g = agrupar_por_dominio(items)
    assert set(g) == {"reformasx.es", "otra.es"}
    assert g["reformasx.es"]["portada"] == "https://reformasx.es/"
    assert "CIF B41000000" in g["reformasx.es"]["texto"] and len(g["reformasx.es"]["urls"]) == 2
    assert g["otra.es"]["urls"] == ["https://otra.es/"]


def test_solo_webs_propias():
    assert _es_web_propia("https://reformasx.es/aviso-legal") is True
    assert _es_web_propia("https://www.paginasamarillas.es/f/x") is False
    assert _es_web_propia("https://www.boe.es/borme/x.pdf") is False
