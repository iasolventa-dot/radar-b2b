"""Contrato común de los conectores de fuente (doc 02 / skill `agente-busqueda-empresas`).

Un conector descubre o enriquece empresas desde UNA fuente y produce
`RegistroBruto`s (capa bronce). No normaliza ni deduplica: eso lo hacen
`radar.normalizacion` y `radar.resolucion` a partir de `campos`.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class CamposExtraidos:
    """Campos que el conector logró extraer, sin normalizar todavía."""

    razon_social: str | None = None
    nombre_comercial: str | None = None
    nif: str | None = None
    forma_juridica: str | None = None
    domicilio: str | None = None
    codigo_postal: str | None = None
    municipio: str | None = None
    provincia: str | None = None
    lat: float | None = None
    lon: float | None = None
    telefonos: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    web: str | None = None
    cnae: str | None = None
    # Versión del código anterior ('CNAE-2009' | 'CNAE-2025', tabla `cnae`
    # de la migración 202609140001, doc 08 D-18). `cnae` sin `cnae_version`
    # no se puede guardar: la clave de `cnae` es compuesta (codigo, version)
    # porque los códigos se solapan entre versiones con contenidos distintos
    # — un conector que rellene `cnae` DEBE rellenar también esta versión.
    cnae_version: str | None = None
    estado: str | None = None  # 'operativa', 'cerrada', 'disuelta'... tal como lo dice la fuente
    empleados: str | None = None  # rango tal cual lo da la fuente
    extra: dict[str, Any] = field(default_factory=dict)  # place_id, hoja registral, url_borme...


@dataclass
class RegistroBruto:
    """Una observación cruda de una fuente (capa bronce, tabla `registros_brutos`)."""

    fuente: str  # = fuentes.codigo
    id_externo: str | None
    url: str | None
    payload: dict[str, Any]  # SOLO lo que la fuente permite almacenar (tabla `fuentes`)
    campos: CamposExtraidos
    capturado_en: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def hash_contenido(self) -> str:
        base = json.dumps(
            {"f": self.fuente, "id": self.id_externo, "p": self.payload},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(base.encode()).hexdigest()


@dataclass
class ResultadoTrabajo:
    registros: int = 0
    errores: int = 0
    coste_eur: float = 0.0
    detalle: dict[str, Any] = field(default_factory=dict)


class Conector(ABC):
    codigo: str  # debe existir en la tabla `fuentes`
    coste_unitario_eur: float = 0.0

    @abstractmethod
    def estimar_coste(self, parametros: dict) -> float:
        """Coste esperado de ejecutar `descubrir` con estos parámetros (para el planificador)."""

    @abstractmethod
    def descubrir(
        self, parametros: dict, max_coste_eur: float
    ) -> AsyncIterator[RegistroBruto]:
        """Genera registros brutos. Debe parar al alcanzar max_coste_eur."""
