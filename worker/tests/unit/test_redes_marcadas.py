"""Fase 3c: LinkedIn, Facebook y rastreo de webs marcados (sin red ni BD)."""

from __future__ import annotations

import asyncio
from typing import Any

from radar.agente.redes_marcadas import fuentes_marcadas_finales, reserva_redes


class _ConexionVacia:
    """Ninguna web enlaza a redes y todas tienen contacto."""

    def execute(self, *_a: Any, **_k: Any) -> _ConexionVacia:
        return self

    def fetchall(self) -> list[tuple]:
        return []


def test_reserva_solo_de_lo_marcado_y_con_tope() -> None:
    assert reserva_redes(set(), 1.0) == 0
    assert reserva_redes({"linkedin", "google_maps"}, 1.0) == 0.04
    # nunca más del 30 % del presupuesto
    assert reserva_redes({"linkedin", "facebook", "web_crawler"}, 0.2) == 0.2 * 0.3


def test_sin_marcar_no_hace_nada() -> None:
    rondas = asyncio.run(
        fuentes_marcadas_finales(
            _ConexionVacia(), None, busqueda_id="b", actores={"google_maps"},  # type: ignore[arg-type]
            max_coste_eur=1.0, telefonos_compartidos=None,
        )
    )
    assert rondas == []


def test_marcadas_sin_datos_quedan_registradas_con_su_motivo() -> None:
    rondas = asyncio.run(
        fuentes_marcadas_finales(
            _ConexionVacia(), None, busqueda_id="b", actores={"linkedin", "facebook", "web_crawler"},  # type: ignore[arg-type]
            max_coste_eur=1.0, telefonos_compartidos=None,
        )
    )
    assert [r[0] for r in rondas] == ["enriquecer_con_linkedin", "enriquecer_con_facebook", "enriquecer_con_apify"]
    assert all(r[2]["coste_eur"] == 0.0 and r[2]["motivo_parada"] for r in rondas)
