"""Tests de la lógica de métricas de `tests/golden/evaluar.py` con datos
sintéticos en memoria (no toca `entidades.csv` ni `registros_entrada.csv`)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "golden"))

from evaluar import evaluar


def test_fusion_perfecta():
    registros = [
        {"id_fila": "1", "entidad_id_real": "E1"},
        {"id_fila": "2", "entidad_id_real": "E1"},
        {"id_fila": "3", "entidad_id_real": "E2"},
    ]
    clusters = {"1": "C1", "2": "C1", "3": "C2"}
    resultado = evaluar(registros, clusters)
    assert resultado["precision_fusion"] == 1.0
    assert resultado["exhaustividad_fusion"] == 1.0
    assert resultado["fusiones_erroneas"] == []
    assert resultado["duplicados_no_detectados"] == []
    assert resultado["entidades_partidas"] == 0


def test_fusion_erronea():
    # 1 y 3 son entidades distintas pero el pipeline las fusiona
    registros = [
        {"id_fila": "1", "entidad_id_real": "E1"},
        {"id_fila": "2", "entidad_id_real": "E1"},
        {"id_fila": "3", "entidad_id_real": "E2"},
    ]
    clusters = {"1": "C1", "2": "C1", "3": "C1"}
    resultado = evaluar(registros, clusters)
    assert resultado["precision_fusion"] < 1.0
    assert ("1", "3") in resultado["fusiones_erroneas"] or ("3", "1") in resultado["fusiones_erroneas"]


def test_duplicado_no_detectado():
    # misma entidad real, el pipeline las deja en clusters distintos
    registros = [
        {"id_fila": "1", "entidad_id_real": "E1"},
        {"id_fila": "2", "entidad_id_real": "E1"},
    ]
    clusters = {"1": "C1", "2": "C2"}
    resultado = evaluar(registros, clusters)
    assert resultado["exhaustividad_fusion"] == 0.0
    assert resultado["entidades_partidas"] == 1


def test_registros_sin_verdad_se_ignoran():
    registros = [
        {"id_fila": "1", "entidad_id_real": "NINGUNA"},
        {"id_fila": "2", "entidad_id_real": ""},
    ]
    # sin verdad conocida y sin fusiones predichas: no hay nada que evaluar,
    # no se penaliza por defecto (precision/exhaustividad = 1.0)
    clusters = {"1": "C1", "2": "C2"}
    resultado = evaluar(registros, clusters)
    assert resultado["n_con_verdad_conocida"] == 0
    assert resultado["precision_fusion"] == 1.0
    assert resultado["exhaustividad_fusion"] == 1.0
