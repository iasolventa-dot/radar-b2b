

def test_ficha_en_directorio_no_es_la_web_de_la_empresa() -> None:
    from radar.agente.completar_contacto import es_ficha_de_tercero

    assert es_ficha_de_tercero("LA ENCINA GRAN CAPITAN SL", "https://www.profymarket.com/contratistas/la-encina-gran-capitan-sl")
    assert not es_ficha_de_tercero("LA ENCINA GRAN CAPITAN SL", "https://laencinagrancapitan.es/contacto")
    assert not es_ficha_de_tercero("MELEN PROJECTS SL", "https://melenprojects.com/aviso-legal")
    assert not es_ficha_de_tercero("MELEN PROJECTS SL", "https://otra.com/")


def test_ruta_de_ficha_de_directorio() -> None:
    from radar.normalizacion.dominio import parece_ficha_de_directorio

    assert parece_ficha_de_directorio("https://portal.es/contratistas/la-encina-sl")
    assert parece_ficha_de_directorio("https://guia.es/ficha/12345")
    assert not parece_ficha_de_directorio("https://reformasperez.es/empresa/quienes-somos")
    assert not parece_ficha_de_directorio("https://reformasperez.es/")
