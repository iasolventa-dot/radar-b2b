"""Tests de `radar.extraccion.reglas` (doc 04 §3). Puerto de
`verificacion-empresas-es/scripts/extraer_datos_legales.py`: si cambias
una regla aquí, cámbiala también en esa skill."""

from radar.extraccion.reglas import extraer, html_a_texto
from radar.normalizacion.nif import _control_cif


def cif(letra: str, siete: str) -> str:
    d, l = _control_cif(siete)
    return letra + siete + (l if letra in "NPQRSW" else d)


def test_html_a_texto_quita_script_y_etiquetas():
    html = "<html><body><script>malo()</script><p>Hola <b>mundo</b></p></body></html>"
    assert "malo()" not in html_a_texto(html)
    assert "Hola" in html_a_texto(html) and "mundo" in html_a_texto(html)


def test_extrae_nif_razon_social_y_contacto():
    nif = cif("B", "4112345")
    texto = (
        "AVISO LEGAL\n"
        "En cumplimiento de la LSSI, se informa que el titular de este sitio web es "
        f"CONSTRUCCIONES PEREZ OBRAS, S.L. con CIF {nif}, "
        "domicilio en Calle Mayor 12, 41001 Sevilla. "
        "Inscrita en el Registro Mercantil de Sevilla, Tomo 1234, Folio 56, Hoja SE-98765. "
        "Teléfono: 955 12 34 56. Email: info@perezobras.es"
    )
    r = extraer(texto, dominio="perezobras.es")
    assert r.nif_titular == nif
    assert any("PEREZ" in rs.upper() for rs in r.razones_sociales)
    assert "+34955123456" in r.telefonos
    assert any(e.email == "info@perezobras.es" and e.del_dominio for e in r.emails)
    assert "41001" in r.codigos_postales
    assert r.registro_mercantil is not None
    assert r.registro_mercantil.hoja == "SE-98765" or r.registro_mercantil.hoja == "SE98765"
    assert not r.necesita_llm


def test_nif_invalido_se_descarta_del_titular():
    valido = cif("B", "4112345")
    invalido = valido[:-1] + ("1" if valido[-1] != "1" else "2")  # rompe el dígito de control
    texto = f"CIF: {invalido} (dígito de control incorrecto a propósito)"
    r = extraer(texto)
    assert r.nif_titular is None
    assert r.nifs == []
    assert invalido in r.nifs_invalidos_etiquetados


def test_detecta_nif_de_agencia_y_lo_penaliza():
    # Separación amplia entre las dos menciones (como en una página real):
    # el radio de "cercanía" del algoritmo es de 150 caracteres, así que un
    # texto demasiado corto haría que ambas menciones se contaminasen entre sí.
    nif_titular, nif_agencia_val = cif("B", "4112345"), cif("B", "9000000")
    relleno = "Somos una empresa de reformas y construcción con más de veinte años de experiencia en el sector. " * 3
    texto = (
        f"Titular: Construcciones Ejemplo SL, CIF {nif_titular}. {relleno}"
        f"Pie de página — Diseño y desarrollo web por Agencia Digital SL, CIF {nif_agencia_val}."
    )
    r = extraer(texto)
    # el NIF de la agencia (cerca de "Diseño web") queda al final, no es el titular
    assert r.nif_titular == nif_titular
    nif_agencia = next(n for n in r.nifs if n.nif == nif_agencia_val)
    assert nif_agencia.cerca_de_mencion_agencia is True
    assert any("agencia" in a for a in r.avisos)


def test_varios_nif_dispara_necesita_llm():
    nif1, nif2 = cif("B", "4112345"), cif("A", "2801586")
    texto = f"CIF {nif1} y también CIF {nif2}, ambos mencionados sin contexto claro."
    r = extraer(texto)
    assert len(r.nifs) == 2
    assert r.necesita_llm is True


def test_sin_datos_necesita_llm():
    r = extraer("Bienvenidos a nuestra web de reformas.")
    assert r.necesita_llm is True
    assert r.nif_titular is None


def test_email_fuera_del_dominio_genera_aviso():
    texto = "Contacto: info@otrodominio.com"
    r = extraer(texto, dominio="perezobras.es")
    assert any("ningún email pertenece" in a for a in r.avisos)
