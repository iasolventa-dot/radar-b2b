"""Tests de `radar.clasificacion.reglas` contra objeto_social REALES
capturados con BORME/Sevilla (2026-09-18, ver commit) -- no textos
inventados, para no probar contra un formato que el BOE en realidad no usa."""

from radar.clasificacion.reglas import extraer_codigos_explicitos


def test_principal_y_una_secundaria_formato_barra():
    texto = (
        "Actividad principal: 82.91 / Actividades de las agencias de cobros y de las "
        "oficinas de crédito.Otras actividades: 62.90 / Otros servicios relacionados "
        "con las tecnologías de la información y la informática."
    )
    r = extraer_codigos_explicitos(texto)
    assert r.principal == "8291"
    assert r.secundarios == ["6290"]


def test_codigo_suelto_entre_guiones_sin_marca_principal():
    texto = (
        "el mantenimiento y la reparación de todo tipo de vehículos de motor -CNAE 9531-. "
        "Todas las citadas operaciones podrán ser realizadas por la Sociedad"
    )
    r = extraer_codigos_explicitos(texto)
    assert r.principal == "9531"
    assert r.secundarios == []


def test_marca_otras_sin_codigo_detras_no_rompe():
    """'Otras actividades:' seguido de basura (aquí, una dirección mal
    cortada) no debe generar un secundario falso."""
    texto = (
        "Actividad principal: 43.99 / Otras actividades de construcción especializada "
        "n.c.o.p. Otras actividades: Domicilio: AVDA ANDALUCIA 205 - CODIGO POSTAL "
        "41702 (DOS HERMANAS)"
    )
    r = extraer_codigos_explicitos(texto)
    assert r.principal == "4399"
    assert r.secundarios == []


def test_codigo_como_palabra_cnae_tras_marca_principal():
    texto = (
        "La sociedad tendrá por objeto principal la actividad correspondiente al CNAE "
        "6622.- Agencia de seguros generales e intermediación financiera"
    )
    r = extraer_codigos_explicitos(texto)
    assert r.principal == "6622"


def test_descripcion_antes_del_codigo_cnae_dos_puntos():
    texto = (
        "Actividad principal: Explotación establecimientos de hostelería y "
        "restauración. CNAE: 5611.-Otras actividades: Servicio de catering"
    )
    r = extraer_codigos_explicitos(texto)
    assert r.principal == "5611"


def test_principal_con_varias_secundarias():
    texto = (
        "Actividad principal: 01.61 / Actividades de apoyo a la agricultura.- Otras "
        "actividades: 01.62 / Actividades de apoyo a la ganadería, 01.63 / Actividades "
        "de preparación posterior a la cosecha y tratamiento de semillas para "
        "reproducción, 02.40 / Servicios de apoyo a la silvicultura, 47.81 / Comercio"
    )
    r = extraer_codigos_explicitos(texto)
    assert r.principal == "0161"
    assert r.secundarios == ["0162", "0163", "0240", "4781"]


def test_dos_codigos_sueltos_sin_marca_principal_no_adivina():
    """Sin 'actividad principal' que distinga cuál es cuál, con más de un
    código no se adivina -- mejor vacío que equivocarse (principio 5)."""
    texto = "Constituye el objeto social -CNAE 6421- y también -CNAE 6820-"
    r = extraer_codigos_explicitos(texto)
    assert r.principal is None
    assert r.secundarios == []


def test_sin_ningun_codigo():
    r = extraer_codigos_explicitos("Otras actividades de consultoría de gestión empresarial")
    assert r.principal is None
    assert r.secundarios == []


def test_texto_vacio_o_none():
    assert extraer_codigos_explicitos(None).principal is None
    assert extraer_codigos_explicitos("").principal is None


def test_codigos_extraidos_bool():
    from radar.clasificacion.reglas import CodigosExtraidos

    assert not CodigosExtraidos()
    assert CodigosExtraidos(principal="4399")
