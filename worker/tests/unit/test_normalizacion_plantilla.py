"""Plantilla: tramos de LinkedIn, menciones en webs y encaje con el filtro."""

from __future__ import annotations

from radar.normalizacion.plantilla import (
    encaje_en_filtro,
    plantilla_en_texto,
    rango_empleados,
    texto_rango,
)


def test_tramos_de_linkedin() -> None:
    assert rango_empleados("11-50 employees") == (11, 50)
    assert rango_empleados("2-10 employees") == (2, 10)
    assert rango_empleados("5,001-10,000 employees") == (5001, 10000)
    assert rango_empleados("10,001+ employees") == (10001, None)
    assert rango_empleados("Myself only") == (1, 1)
    assert rango_empleados("") is None and rango_empleados("muchos") is None


def test_menciones_en_webs() -> None:
    assert plantilla_en_texto("Contamos con un equipo de más de 40 profesionales cualificados.") == "más de 40 profesionales"
    assert rango_empleados("más de 40 profesionales") == (40, None)
    assert plantilla_en_texto("Nuestra plantilla de 120 trabajadores") == "120 trabajadores"
    assert plantilla_en_texto("un equipo formado por entre 20 y 30 personas") == "entre 20 y 30 personas"
    assert rango_empleados("entre 20 y 30 personas") == (20, 30)
    assert plantilla_en_texto("Más de 1.200 empleados en toda España") == "Más de 1.200 empleados"
    # no son plantilla
    assert plantilla_en_texto("Más de 500 clientes satisfechos y 30 años de experiencia") is None
    assert plantilla_en_texto("Calle Mayor 12, 41001 Sevilla") is None


def test_encaje_con_el_filtro() -> None:
    assert encaje_en_filtro((11, 50), 10, 200) == "dentro"
    assert encaje_en_filtro((2, 10), 10, 200) == "dentro"  # puede tener 10
    assert encaje_en_filtro((1, 1), 10, 200) == "fuera"
    assert encaje_en_filtro((501, 1000), 10, 200) == "fuera"
    assert encaje_en_filtro((40, None), 10, 200) == "dentro"
    assert encaje_en_filtro((1001, None), 10, 200) == "fuera"
    assert encaje_en_filtro(None, 10, 200) == "desconocido"
    assert encaje_en_filtro((3, 3), None, 5) == "dentro"


def test_texto_del_rango() -> None:
    assert texto_rango(11, 50) == "11-50" and texto_rango(40, None) == "más de 40" and texto_rango(120, 120) == "120"


def test_consolidacion_categoria_y_motivo() -> None:
    from datetime import UTC, datetime

    from radar.agente.interpretacion import FiltrosBusqueda, TamanoFiltro
    from radar.agente.tamano import motivo_fuera, tiene_filtro_de_plantilla
    from radar.orquestador.bd import categoria_tamano
    from radar.orquestador.procesar import plantilla_consolidada

    viejo, nuevo = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
    obs = [
        {"valor_original": "11-50 employees", "valor_norm": "11-50 employees", "confianza_fuente": 0.6,
         "observado_en": viejo, "fuente_nombre": "LinkedIn"},
        {"valor_original": "más de 40 profesionales", "valor_norm": "más de 40 profesionales", "confianza_fuente": 0.75,
         "observado_en": nuevo, "fuente_nombre": "Web corporativa"},
        {"valor_original": "muchos", "valor_norm": "muchos", "confianza_fuente": 0.9, "observado_en": nuevo, "fuente_nombre": "X"},
    ]
    assert plantilla_consolidada(obs) == (40, None, "Web corporativa: más de 40 profesionales")
    assert plantilla_consolidada([]) is None
    assert categoria_tamano(11, 50) == "desconocido"  # cruza pequeña y mediana
    assert categoria_tamano(11, 49) == "pequena" and categoria_tamano(2, 9) == "micro"
    assert categoria_tamano(300, None) == "grande" and categoria_tamano(120, 120) == "mediana"
    f = FiltrosBusqueda(tamano=TamanoFiltro(empleados_min=10, empleados_max=200))
    assert tiene_filtro_de_plantilla(f) and not tiene_filtro_de_plantilla(FiltrosBusqueda())
    assert motivo_fuera(1, 1, "LinkedIn: Myself only", f) == (
        "Plantilla fuera del rango pedido (10-200 empleados): 1 empleados (LinkedIn: Myself only)"
    )


def test_captura_desde_linkedin_y_web() -> None:
    from radar.extraccion.reglas import extraer
    from radar.fuentes.apify_linkedin import empresa_a_registro

    r = empresa_a_registro({"name": "Acme", "companySize": "51-200 employees", "employeeCount": 87})
    assert r is not None and r.campos.empleados == "51-200 employees"
    assert extraer("Somos una constructora con un equipo de más de 60 trabajadores.").plantilla == "más de 60 trabajadores"
