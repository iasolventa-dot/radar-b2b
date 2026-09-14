"""Tests de la lógica de parseo y normalización de
`scripts/generar_catalogos.py` (no descarga nada del INE ni toca la BD).

Mismo patrón de import que `test_evaluar_golden.py`: `scripts/` no es un
paquete instalable, así que se añade a `sys.path`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from generar_catalogos import estructura_desde, limpiar_codigo, nivel_de, normalizar_texto


# ---------------------------------------------------------------------
# normalizar_texto: debe coincidir con la función homónima de Postgres
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("SEVILLA", "sevilla"),
        ("Alcalá de Guadaíra", "alcala de guadaira"),
        ("ALCALA DE GUADAIRA", "alcala de guadaira"),
        # Convención del INE (artículo pospuesto con coma) frente al texto
        # del BORME, que además llega truncado sin el paréntesis de cierre.
        ("Palacios y Villafranca, Los", "palacios y villafranca los"),
        ("PALACIOS Y VILLAFRANCA (LOS", "palacios y villafranca los"),
        ("Cuervo de Sevilla, El", "cuervo de sevilla el"),
        ("CUERVO DE SEVILLA (EL", "cuervo de sevilla el"),
        # `unaccent` de Postgres convierte la ñ en n, así que aquí también.
        # Verificado contra la BD: ninguno de los 8.132 municipios conserva
        # la ñ en `nombre_norm`. Coherente con el doc 05 §2.3.
        ("Bolaños de Calatrava", "bolanos de calatrava"),
        ("  espacios   multiples  ", "espacios multiples"),
    ],
)
def test_normalizar_texto(entrada: str, esperado: str) -> None:
    assert normalizar_texto(entrada) == esperado


def test_borme_y_ine_normalizan_igual() -> None:
    """El caso concreto que mantenía `sedes.municipio_ine` a null."""
    assert normalizar_texto("PALACIOS Y VILLAFRANCA (LOS") == normalizar_texto(
        "Palacios y Villafranca, Los"
    )


# ---------------------------------------------------------------------
# limpiar_codigo: el INE publica con punto y a veces como entero
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("41.01", "4101"),
        ("01.1", "011"),
        ("F", "F"),
        (41, "41"),  # división numérica que openpyxl devuelve como int
        (1, "01"),  # el cero a la izquierda no se puede perder
        ("43.9", "439"),
        ("  42.11  ", "4211"),
    ],
)
def test_limpiar_codigo(entrada: object, esperado: str) -> None:
    assert limpiar_codigo(entrada) == esperado


@pytest.mark.parametrize("codigo,nivel", [("F", 1), ("41", 2), ("410", 3), ("4101", 4)])
def test_nivel_de(codigo: str, nivel: int) -> None:
    assert nivel_de(codigo) == nivel


# ---------------------------------------------------------------------
# estructura_desde: jerarquía correcta y padres antes que hijos
# ---------------------------------------------------------------------
def test_estructura_asigna_padres() -> None:
    pares = [
        ("F", "CONSTRUCCIÓN"),
        ("41", "Construcción de edificios"),
        ("410", "Construcción de edificios"),
        ("4101", "Construcción de edificios residenciales"),
        ("43", "Actividades de construcción especializada"),
        ("431", "Demolición y preparación de terrenos"),
    ]
    por_codigo = {f[0]: f for f in estructura_desde(pares)}

    assert por_codigo["F"][3] is None
    assert por_codigo["41"][3] == "F"  # la división cuelga de su sección
    assert por_codigo["43"][3] == "F"
    assert por_codigo["410"][3] == "41"
    assert por_codigo["4101"][3] == "410"
    assert por_codigo["431"][3] == "43"


def test_estructura_ordena_padres_primero() -> None:
    """La clave ajena se comprueba fila a fila: el padre va antes."""
    pares = [("F", "CONSTRUCCIÓN"), ("41", "Edificios"), ("410", "Edificios"), ("4101", "Residenciales")]
    niveles = [f[2] for f in estructura_desde(pares)]
    assert niveles == sorted(niveles)


def test_estructura_ignora_duplicados() -> None:
    pares = [("F", "CONSTRUCCIÓN"), ("41", "Edificios"), ("41", "Edificios repetido")]
    filas = estructura_desde(pares)
    assert len([f for f in filas if f[0] == "41"]) == 1
