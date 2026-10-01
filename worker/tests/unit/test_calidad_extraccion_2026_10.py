"""Casos vistos en la búsqueda real «ingeniería en Dos Hermanas» (2026-10-01)."""

from radar.extraccion.reglas import limpiar_razon_social
from radar.normalizacion.dominio import (
    es_dominio_plataforma,
    extraer_dominio,
    parece_ficha_de_directorio,
)


def test_frase_del_aviso_legal_no_es_la_razon_social() -> None:
    assert limpiar_razon_social("Participación en el capital social de Cox Abg Group, S.A") == "Cox Abg Group, S.A"
    assert limpiar_razon_social("Filial de Montrel S.A") == "Montrel S.A"


def test_directorio_de_un_periodico_no_es_la_web_de_la_empresa() -> None:
    url = "https://cincodias.elpais.com/directorio-empresas/empresa/638643/ingenieria-y-construcciones-del-sur"
    assert parece_ficha_de_directorio(url)
    assert es_dominio_plataforma(extraer_dominio(url))
    assert not parece_ficha_de_directorio("https://ingesur.es/empresa/historia")


def test_email_del_delegado_de_proteccion_de_datos_no_es_contacto() -> None:
    from radar.normalizacion.registro import es_email_privacidad, normalizar_registro

    assert es_email_privacidad("dpo.multimap.es@mapfre.com")
    assert es_email_privacidad("protecciondedatos@empresa.es")
    assert not es_email_privacidad("info@dpointerior.es")
    r = normalizar_registro({"razon_social": "MULTIMAP, S.A", "emails": ["dpo.multimap.es@mapfre.com", "info@multimap.es"]})
    assert r["emails"] == ["info@multimap.es"]


def test_nombre_de_pagina_sin_sufijo_de_localidad() -> None:
    from radar.normalizacion.nombre import limpiar_nombre_pagina

    assert limpiar_nombre_pagina("EMIF | Alcalá de Guadaira") == "EMIF"
    assert limpiar_nombre_pagina("L&M CLIMA S.C. | Alcalá de Guadaira") == "L&M CLIMA S.C."
    assert limpiar_nombre_pagina("Climont") == "Climont"


def test_sumario_del_borme_con_un_solo_elemento() -> None:
    from radar.fuentes.borme import _como_lista

    assert _como_lista({"codigo": "A"}) == [{"codigo": "A"}]
    assert _como_lista([{"codigo": "A"}, "x"]) == [{"codigo": "A"}]
    assert _como_lista(None) == []


def test_municipio_con_provincia_entre_parentesis() -> None:
    from radar.agente.interpretacion import UbicacionFiltro

    u = UbicacionFiltro(tipo="municipios", municipios=["Carmona (Sevilla)", "Utrera"])
    assert u.municipios == ["Carmona", "Utrera"] and u.provincias == ["Sevilla"]


def test_email_de_plantilla_no_es_contacto() -> None:
    from radar.normalizacion.registro import es_email_plantilla, normalizar_registro

    assert es_email_plantilla("hello@mycompany.com") and es_email_plantilla("mail@example.com")
    assert not es_email_plantilla("info@casticarmo.com")
    assert normalizar_registro({"razon_social": "X SL", "emails": ["mail@example.com"]})["emails"] == []


def test_razon_social_del_proveedor_web() -> None:
    from radar.extraccion.conector import es_proveedor_web

    assert es_proveedor_web("Telefónica Soluciones De Informática Y Comunicaciones De España S A U", "carpinteriametalicaensevilla.es")
    assert not es_proveedor_web("Telefónica de España SAU", "telefonica.es")
    assert not es_proveedor_web("Puertas Metalicas Castillo Carmona SL", "casticarmo.com")
