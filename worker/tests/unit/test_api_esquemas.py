"""Tests de validación de `radar.api.esquemas` — puro pydantic, sin BD ni red."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from radar.api.esquemas import ConfirmarBusquedaIn, PeticionBusquedaIn


def test_peticion_busqueda_in_valida():
    p = PeticionBusquedaIn(peticion="constructoras de Sevilla", presupuesto_eur=5.0)
    assert p.contexto is None
    assert p.usuario_id is None


def test_peticion_busqueda_in_rechaza_presupuesto_no_positivo():
    with pytest.raises(ValidationError):
        PeticionBusquedaIn(peticion="constructoras de Sevilla", presupuesto_eur=0)


def test_peticion_busqueda_in_rechaza_peticion_demasiado_corta():
    with pytest.raises(ValidationError):
        PeticionBusquedaIn(peticion="ab", presupuesto_eur=5.0)


def test_confirmar_busqueda_in_valores_por_defecto():
    c = ConfirmarBusquedaIn()
    assert c.max_rondas == 10
    assert c.filtros is None


def test_confirmar_busqueda_in_rechaza_max_rondas_fuera_de_rango():
    with pytest.raises(ValidationError):
        ConfirmarBusquedaIn(max_rondas=100)
    with pytest.raises(ValidationError):
        ConfirmarBusquedaIn(max_rondas=0)
