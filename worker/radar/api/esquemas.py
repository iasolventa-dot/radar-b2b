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
    usar_google_places: bool = Field(default=False, description="Permite descubrir con Google Places (de pago) en esta búsqueda")
    usar_apify: bool = Field(default=False, description="Permite enriquecer webs con Apify (de pago) en esta búsqueda")
    filtros: FiltrosBusqueda | None = Field(
        default=None, description="Si se manda, sustituye a los filtros interpretados (para que el usuario los edite antes de lanzar)"
    )


class ConfirmarBusquedaOut(BaseModel):
    id: str
    estado: EstadoBusqueda


class ProfundizarIn(BaseModel):
    max_coste_eur: float = Field(default=0.30, gt=0, le=2.0, description="Tope de gasto para esta búsqueda dirigida -- pequeño a propósito (1-2 rondas)")


class ProfundizarOut(BaseModel):
    empresa_id: str
    consultas: list[str]
    resultado: dict[str, Any]
    error: str | None = None


class GuardarClavePlacesIn(BaseModel):
    api_key: str | None = Field(default=None, min_length=20, max_length=200, description="Clave de API de Google Cloud con Places API (New); si se omite, solo se actualiza el tope mensual")
    presupuesto_mensual_eur: float | None = Field(default=None, ge=0, le=1000)


class EstadoPlacesOut(BaseModel):
    configurada: bool
    clave_enmascarada: str | None = None
    origen: str | None = None  # 'panel' | 'env'
    presupuesto_mensual_eur: float
    gasto_mes_eur: float


class GuardarTokenApifyIn(BaseModel):
    api_token: str | None = Field(default=None, min_length=10, max_length=200, description="Token de API de Apify; si se omite, solo se actualiza el tope mensual")
    presupuesto_mensual_usd: float | None = Field(default=None, ge=0, le=1000)


class EstadoApifyOut(BaseModel):
    configurado: bool
    token_enmascarado: str | None = None
    presupuesto_mensual_usd: float
    gasto_mes_usd: float


class ProbarPlacesOut(BaseModel):
    ok: bool
    mensaje: str


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
