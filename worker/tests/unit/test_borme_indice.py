"""Índice local del BORME: qué días se dan por cargados (sin red ni BD)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from radar.fuentes import borme_indice


class _ConectorFalso:
    def __init__(self, _cliente: Any) -> None:
        pass

    async def _actos_de_provincia(self, dia: date, provincia: str) -> list[Any]:
        return []


def _cargar(monkeypatch: pytest.MonkeyPatch, dias: list[date]) -> list[date]:
    guardados: list[date] = []
    monkeypatch.setattr(borme_indice, "ConectorBorme", _ConectorFalso)
    monkeypatch.setattr(borme_indice, "dias_pendientes", lambda *a: dias)
    monkeypatch.setattr(borme_indice, "_guardar_actos", lambda conn, dia, prov, actos: guardados.append(dia))
    asyncio.run(borme_indice.cargar_dias(None, None, "Madrid", dias[0], dias[-1]))  # type: ignore[arg-type]
    return guardados


def test_dia_reciente_sin_actos_no_se_marca_como_cargado(monkeypatch: pytest.MonkeyPatch) -> None:
    hoy = datetime.now(UTC).date()
    assert _cargar(monkeypatch, [hoy]) == []


def test_dia_antiguo_sin_actos_es_festivo_y_se_marca(monkeypatch: pytest.MonkeyPatch) -> None:
    antiguo = datetime.now(UTC).date() - timedelta(days=30)
    assert _cargar(monkeypatch, [antiguo]) == [antiguo]
