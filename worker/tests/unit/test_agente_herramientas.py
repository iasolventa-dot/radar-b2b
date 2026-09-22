"""Tests de las partes de `radar.agente.herramientas` que no tocan la BD ni
la red: construcción del SQL de filtros, coincidencia de sector, esquemas
de herramientas y el despacho de `ejecutar_herramienta` (con dobles falsos
para las funciones con efectos secundarios). `consultar_bd`,
`descubrir_borme` y `buscar_web` en sí se prueban de forma manual/
integración, igual que el resto del orquestador (ver docstring del
módulo)."""

from __future__ import annotations

import asyncio

import pytest

from radar.agente.herramientas import (
    HERRAMIENTAS,
    _coincide_sector,
    _url_no_apta_para_enriquecer,
    a_tool_param_anthropic,
    a_tool_param_openai,
    construir_where_empresas,
    ejecutar_herramienta,
    estimar_cobertura,
    finalizar_busqueda,
    fuera_de_zona,
    preguntar_usuario,
    resolver_codigos_municipio,
)
from radar.agente.interpretacion import FiltrosBusqueda, SectorFiltro, TamanoFiltro, UbicacionFiltro

# ---------- construir_where_empresas ----------


def test_where_por_defecto_excluye_fusionadas_y_autonomos():
    sql, params = construir_where_empresas(FiltrosBusqueda())
    assert "e.fusionada_en is null" in sql
    assert "e.es_persona_fisica = false" in sql
    assert "estado" in sql
    assert params  # al menos el array de estados por defecto


def test_where_incluir_autonomos_no_filtra_persona_fisica():
    sql, _ = construir_where_empresas(FiltrosBusqueda(incluir_autonomos=True))
    assert "es_persona_fisica" not in sql


def test_where_cnae_y_tamano():
    filtros = FiltrosBusqueda(
        sector=SectorFiltro(codigos_cnae=["41", "43"]),
        tamano=TamanoFiltro(empleados_min=10, empleados_max=50),
    )
    sql, params = construir_where_empresas(filtros)
    # doc 08 D-18: cnae_coincide compara por prefijo, no por igualdad exacta
    # (["41"] debe casar con "4101"/"41.02", cosa que `= any` nunca hacía).
    assert "cnae_coincide(e.cnae_principal, %s)" in sql
    assert "cnae_principal = any" not in sql
    assert "empleados_max >= %s" in sql
    assert "empleados_min <= %s" in sql
    assert ["41", "43"] in params
    assert 10 in params
    assert 50 in params


def test_where_provincia_prevalece_sobre_municipio():
    filtros = FiltrosBusqueda(ubicacion=UbicacionFiltro(provincias=["Sevilla"], municipios=["Écija"]))
    sql, params = construir_where_empresas(filtros, codigos_municipio=["41039"])
    assert "s.provincia = any" in sql
    assert "s.municipio_ine" not in sql
    assert ["Sevilla"] in params


def test_where_sin_provincia_usa_codigos_municipio_resueltos():
    """`construir_where_empresas` ya no compara contra el texto crudo del
    BORME (`municipio_nombre`): recibe los códigos INE ya resueltos por
    `resolver_codigos_municipio` y filtra por `municipio_ine`."""
    filtros = FiltrosBusqueda(ubicacion=UbicacionFiltro(municipios=["Écija", "Osuna"]))
    sql, params = construir_where_empresas(filtros, codigos_municipio=["41039", "41068"])
    assert "s.municipio_ine = any" in sql
    assert "s.municipio_nombre" not in sql
    assert ["41039", "41068"] in params


def test_where_municipio_sin_codigos_resueltos_no_filtra():
    """Si ningún nombre resolvió contra el catálogo `municipios` (p. ej. un
    nombre inventado o mal escrito por el LLM), no se añade ninguna condición
    de ubicación — mejor no filtrar que fingir un filtro que nunca casaría
    (principio 5, nunca inventar)."""
    filtros = FiltrosBusqueda(ubicacion=UbicacionFiltro(municipios=["Sitio Que No Existe"]))
    sql, _ = construir_where_empresas(filtros, codigos_municipio=[])
    assert "municipio" not in sql
    assert "sedes" not in sql


def test_where_ccaa_se_aplica_cuando_no_hay_provincia_ni_municipio():
    """ubicacion.ccaa se capturaba desde la interpretación pero nunca se
    usaba en el filtro (doc 08) — se une por sedes.municipio_ine con la
    función normalizar_ccaa (migración 202609141200), no necesita
    resolución previa en Python (a diferencia de municipios) porque es una
    función SQL inmutable comparable en ambos lados de la consulta."""
    filtros = FiltrosBusqueda(ubicacion=UbicacionFiltro(ccaa=["Andalucía"]))
    sql, params = construir_where_empresas(filtros)
    assert "normalizar_ccaa(m.ccaa)" in sql
    assert "join municipios m on m.codigo_ine = s.municipio_ine" in sql
    assert ["Andalucía"] in params


def test_where_provincia_prevalece_sobre_ccaa():
    """Igual que con municipios: provincias es más específico y gana."""
    filtros = FiltrosBusqueda(ubicacion=UbicacionFiltro(provincias=["Sevilla"], ccaa=["Andalucía"]))
    sql, params = construir_where_empresas(filtros)
    assert "s.provincia = any" in sql
    assert "normalizar_ccaa" not in sql
    assert ["Sevilla"] in params


def test_where_exclusiones_se_aplican_aunque_cnae_o_palabras_coincidan():
    """exclusiones sigue siendo un AND-NOT estricto por fuera del OR de
    codigos_cnae/palabras_clave: una empresa que caiga en el CNAE pero
    mencione una palabra excluida debe descartarse igual."""
    filtros = FiltrosBusqueda(sector=SectorFiltro(codigos_cnae=["41"], exclusiones=["reforma menor"]))
    sql, params = construir_where_empresas(filtros)
    assert "not exists" in sql
    assert ["reforma menor"] in params


def test_where_palabras_clave_de_sector_se_aplican():
    """Antes esta condición no existía: sin codigos_cnae explícitos (el caso
    normal, porque BORME nunca da CNAE), sector.palabras_clave se ignoraba
    por completo en consultar_bd — solo se usaba al descubrir, nunca al
    consultar lo ya guardado."""
    filtros = FiltrosBusqueda(sector=SectorFiltro(palabras_clave=["reformas", "obra civil"]))
    sql, params = construir_where_empresas(filtros)
    assert "e.objeto_social" in sql
    assert "e.razon_social" in sql
    assert "extensions.unaccent" in sql
    assert ["reformas", "obra civil"] in params


def test_where_cnae_y_palabras_clave_combinados():
    """codigos_cnae y palabras_clave son dos formas ALTERNATIVAS de
    reconocer el mismo sector (OR), no dos requisitos simultáneos (AND) --
    se combinaban con AND hasta 2026-09-18, y con el clasificador CNAE
    cubriendo solo el 11% de las empresas (radar.clasificacion) eso
    excluía en la práctica a cualquier empresa sin clasificar aunque su
    objeto_social mencionara el sector tal cual. Confirmado en vivo:
    "empresas de informática en Sevilla" no encontraba ninguna empresa de
    informática real de la base por este motivo -- ver commit que corrigió
    esto y la normalización de versión de CNAE en el mismo hallazgo."""
    filtros = FiltrosBusqueda(sector=SectorFiltro(codigos_cnae=["41"], palabras_clave=["residencial"]))
    sql, params = construir_where_empresas(filtros)
    assert "cnae_coincide(e.cnae_principal, %s)" in sql
    assert "e.objeto_social" in sql
    assert " or " in sql
    assert ["41"] in params
    assert ["residencial"] in params


# ---------- resolver_codigos_municipio ----------


def test_resolver_codigos_municipio_lista_vacia_no_toca_bd():
    """No debe ejecutar ninguna consulta si no hay nombres que resolver —
    importante porque aquí no hay un doble falso de conn, un `execute`
    real fallaría."""
    assert resolver_codigos_municipio([], conn=None) == []  # type: ignore[arg-type]


# ---------- estimar_cobertura ----------


def test_estimar_cobertura_sin_codigos_cnae_no_toca_bd():
    resultado = estimar_cobertura(None, FiltrosBusqueda())  # type: ignore[arg-type]
    assert resultado["soportado"] is False
    assert "codigos_cnae" in resultado["motivo"]


def test_estimar_cobertura_sin_ubicacion_no_toca_bd():
    resultado = estimar_cobertura(None, FiltrosBusqueda(sector=SectorFiltro(codigos_cnae=["41"])))  # type: ignore[arg-type]
    assert resultado["soportado"] is False
    assert "ubicación" in resultado["motivo"]


# ---------- _coincide_sector ----------


def test_coincide_sector_sin_palabras_clave_acepta_todo():
    assert _coincide_sector("cualquier cosa", "Cualquier SL", []) is True


def test_coincide_sector_busca_en_objeto_y_nombre_sin_tildes():
    assert _coincide_sector("Construcción y reforma de edificios", None, ["construccion"]) is True
    assert _coincide_sector(None, "Reformas Pérez SL", ["reformas"]) is True


def test_coincide_sector_no_coincide():
    assert _coincide_sector("Venta al por menor de ropa", "Modas García SL", ["construccion", "obras"]) is False


# ---------- _url_no_apta_para_enriquecer ----------
# Regresión de un fallo real (2026-09-21, primera prueba en vivo de
# radar.agente.profundizar): buscar_web enriqueció una URL del BOE como si
# fuera la web de la empresa buscada y guardó como "empresa" el nombre de
# OTRA empresa del mismo boletín, y en otra URL el propio nombre del BOE.


def test_boe_no_es_apta_para_enriquecer():
    assert _url_no_apta_para_enriquecer("https://www.boe.es/borme/dias/2026/08/25/pdfs/BORME-A-2026-163-41.pdf") is True
    assert _url_no_apta_para_enriquecer("https://boe.es/diario_borme/txt.php?id=BORME-A-2026-163-41") is True


def test_web_de_empresa_normal_si_es_apta():
    assert _url_no_apta_para_enriquecer("https://www.construccionesejemplo.es/aviso-legal") is False


# ---------- esquemas de herramientas ----------


def test_herramientas_tiene_las_trece_implementadas():
    nombres = {h.nombre for h in HERRAMIENTAS}
    assert nombres == {
        "consultar_bd", "estimar_cobertura", "descubrir_borme", "descubrir_osm", "descubrir_places", "enriquecer_con_apify",
        "descubrir_google_search", "descubrir_apify_maps", "enriquecer_con_linkedin", "enriquecer_con_facebook", "buscar_web",
        "preguntar_usuario", "finalizar_busqueda",
    }


def test_a_tool_param_openai_forma_correcta():
    h = next(h for h in HERRAMIENTAS if h.nombre == "buscar_web")
    tool = a_tool_param_openai(h)
    assert tool["type"] == "function"
    assert tool["name"] == "buscar_web"
    assert tool["parameters"] is h.parametros


def test_a_tool_param_anthropic_forma_correcta():
    h = next(h for h in HERRAMIENTAS if h.nombre == "buscar_web")
    tool = a_tool_param_anthropic(h)
    assert tool["name"] == "buscar_web"
    assert tool["input_schema"] is h.parametros


# ---------- preguntar_usuario / finalizar_busqueda ----------


def test_preguntar_usuario_sin_opciones():
    assert preguntar_usuario("¿Incluyo autónomos?") == {"pregunta": "¿Incluyo autónomos?", "opciones": []}


def test_finalizar_busqueda():
    r = finalizar_busqueda("presupuesto_agotado", "Se gastaron los 20€ del tope")
    assert r == {"motivo": "presupuesto_agotado", "resumen": "Se gastaron los 20€ del tope"}


# ---------- ejecutar_herramienta (dispatcher) ----------
# Funciones sync que envuelven `asyncio.run(...)` en vez de `pytest.mark.asyncio`:
# el proyecto no tiene pytest-asyncio como dependencia (el resto del código
# async se prueba de forma manual/integración, ver docstring del módulo) y
# estas rutas del dispatcher no necesitan un event loop real.


class _ContextoFalso:
    """Doble mínimo de `ContextoHerramientas` — no necesita `conn` real
    porque solo se prueban las rutas que no la tocan (preguntar_usuario,
    finalizar_busqueda, validación de argumentos)."""

    def __init__(self):
        self.conn = None
        self.cliente_http = None
        self.cliente_llm = None
        self.filtros = FiltrosBusqueda()
        self.telefonos_compartidos = None
        self.presupuesto_restante_eur = 5.0


def test_ejecutar_herramienta_preguntar_usuario():
    r = asyncio.run(ejecutar_herramienta("preguntar_usuario", {"pregunta": "¿Zona?"}, _ContextoFalso()))  # type: ignore[arg-type]
    assert r["pregunta"] == "¿Zona?"


def test_ejecutar_herramienta_finalizar_busqueda_sin_resumen():
    r = asyncio.run(ejecutar_herramienta("finalizar_busqueda", {"motivo": "max_rondas"}, _ContextoFalso()))  # type: ignore[arg-type]
    assert r == {"motivo": "max_rondas", "resumen": ""}


def test_ejecutar_herramienta_desconocida_lanza():
    with pytest.raises(ValueError, match="desconocida"):
        asyncio.run(ejecutar_herramienta("no_existe", {}, _ContextoFalso()))  # type: ignore[arg-type]


def test_ejecutar_herramienta_buscar_web_sin_consultas_lanza():
    with pytest.raises(ValueError, match="consultas"):
        asyncio.run(ejecutar_herramienta("buscar_web", {"max_coste_eur": 1.0}, _ContextoFalso()))  # type: ignore[arg-type]


def test_ejecutar_herramienta_descubrir_borme_sin_provincia_lanza():
    with pytest.raises(ValueError, match="provincia_titulo"):
        asyncio.run(ejecutar_herramienta("descubrir_borme", {}, _ContextoFalso()))  # type: ignore[arg-type]


def test_herramientas_de_pago_solo_si_se_marcan_y_hay_credencial(monkeypatch):
    from radar import secretos
    from radar.agente.herramientas import herramientas_activas

    def nombres(**kw):
        return {h.nombre for h in herramientas_activas(None, **kw)}  # type: ignore[arg-type]

    TODOS_LOS_ACTORS = {"web_crawler", "google_search", "google_maps", "linkedin", "facebook"}
    HERRAMIENTAS_APIFY = {"enriquecer_con_apify", "descubrir_google_search", "descubrir_apify_maps", "enriquecer_con_linkedin", "enriquecer_con_facebook"}

    monkeypatch.setattr(secretos, "obtener_clave_places", lambda conn: "AIza-x" * 5)
    monkeypatch.setattr(secretos, "obtener_token_apify", lambda conn: "apify_api_x" * 3)
    # con credenciales pero sin marcar ninguna casilla: no se ofrece nada de pago
    assert not (({"descubrir_places"} | HERRAMIENTAS_APIFY) & nombres())
    assert "descubrir_places" in nombres(usar_places=True)
    assert not (HERRAMIENTAS_APIFY & nombres(usar_places=True))
    # cada Actor de Apify se activa uno a uno, independientemente de los demás
    assert nombres(apify_actores={"web_crawler"}) & HERRAMIENTAS_APIFY == {"enriquecer_con_apify"}
    assert nombres(apify_actores=TODOS_LOS_ACTORS) & HERRAMIENTAS_APIFY == HERRAMIENTAS_APIFY
    # marcadas pero sin credencial: tampoco
    monkeypatch.setattr(secretos, "obtener_clave_places", lambda conn: None)
    monkeypatch.setattr(secretos, "obtener_token_apify", lambda conn: None)
    assert not (({"descubrir_places"} | HERRAMIENTAS_APIFY) & nombres(usar_places=True, apify_actores=TODOS_LOS_ACTORS))


def test_ejecutar_herramienta_de_pago_sin_casilla_se_niega():
    from radar.agente.herramientas import ContextoHerramientas

    ctx = ContextoHerramientas(conn=None, cliente_http=None, filtros=FiltrosBusqueda())  # type: ignore[arg-type]
    for nombre, args in (
        ("descubrir_places", {"consultas": ["x"], "max_coste_eur": 1.0}),
        ("enriquecer_con_apify", {"urls": ["https://a.es"], "max_coste_eur": 1.0}),
        ("descubrir_google_search", {"consultas": ["x"], "max_coste_eur": 1.0}),
        ("descubrir_apify_maps", {"palabras_clave": ["x"], "max_coste_eur": 1.0}),
        ("enriquecer_con_linkedin", {"nombres": ["x"], "max_coste_eur": 1.0}),
        ("enriquecer_con_facebook", {"urls": ["https://facebook.com/x"], "max_coste_eur": 1.0}),
    ):
        r = asyncio.run(ejecutar_herramienta(nombre, args, ctx))
        assert "no está habilitado" in r["error"] and r["coste_eur"] == 0.0



def test_directorios_y_redes_no_son_web_propia():
    assert _url_no_apta_para_enriquecer("https://www.paginasamarillas.es/f/sevilla/reformas-x.html") is True
    assert _url_no_apta_para_enriquecer("https://www.linkedin.com/company/reformas-x") is True
    assert _url_no_apta_para_enriquecer("https://www.facebook.com/reformasx") is True
    assert _url_no_apta_para_enriquecer("https://reformasx.es/aviso-legal") is False


def test_fuera_de_zona():
    assert fuera_de_zona("41091", ["41004"]) is True
    assert fuera_de_zona("41004", ["41004"]) is False
    assert fuera_de_zona(None, ["41004"]) is False  # municipio desconocido: no se afirma que esté fuera
    assert fuera_de_zona("41091", []) is False  # sin zona pedida no se filtra
