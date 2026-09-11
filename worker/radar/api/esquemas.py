"""Modelos de petición/respuesta de la API (FastAPI los usa también para
generar el esquema OpenAPI en `/docs`, útil para que la web sepa qué
esperar sin tener que leer este código)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from radar.agente.interpretacion import FiltrosBusqueda
from radar.api.estado import EstadoBusqueda


class PeticionBusquedaIn(BaseModel):
    peticion: str = Field(min_length=3, description="Petición en lenguaje natural, p. ej. 'constructoras de Sevilla de 10 a 50 empleados'")
    contexto: str | None = Field(default=None, description="Contexto adicional opcional para la interpretación")
    presupuesto_eur: float = Field(gt=0, description="Presupuesto en EUR para el planificador")
    usuario_id: str | None = Field(
        default=None,
        description=(
            "uuid de auth.users si la web ya tiene sesión de Supabase — de momento no se verifica "
            "aquí (D-03: uso estrictamente interno), es una simplificación conocida a revisar antes "
            "de exponer esto fuera de la red interna."
        ),
    )


class BusquedaInterpretadaOut(BaseModel):
    id: str
    filtros: FiltrosBusqueda
    supuestos: list[str]
    preguntas: list[str]


class ConfirmarBusquedaIn(BaseModel):
    max_rondas: int = Field(default=10, ge=1, le=50)
    filtros: FiltrosBusqueda | None = Field(
        default=None, description="Si se manda, sustituye a los filtros interpretados (para que el usuario los edite antes de lanzar)"
    )


class ConfirmarBusquedaOut(BaseModel):
    id: str
    estado: EstadoBusqueda


class BusquedaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    peticion: str
    filtros: FiltrosBusqueda
    presupuesto_eur: float
    estado: str  # texto libre en BD (ver radar.api.estado) — no se restringe aquí para no romper con estados futuros
    rondas: int
    estadisticas: dict[str, Any]
    coste_eur: float
    creado_en: datetime
    finalizado_en: datetime | None
