# Plantilla de conector de fuente

Un conector = un módulo en `worker/radar/fuentes/<codigo>.py` que descubre o enriquece empresas desde una fuente y produce `RegistroBruto`s. No normaliza ni deduplica: eso es trabajo de las capas siguientes.

## Checklist antes de escribir código

- [ ] **Documentación vigente** revisada (endpoint, autenticación, cuotas, paginación, precio). Anotar URL y fecha en `08_registro_decisiones.md`.
- [ ] **Condiciones de uso**: ¿se puede automatizar? ¿se puede almacenar el contenido? ¿qué campos? ¿atribución obligatoria? → rellenar la fila en la tabla `fuentes` (`permite_almacenar`, `campos_almacenables`, `grupo_independencia`, `notas_condiciones`).
- [ ] **Datos personales**: ¿devuelve nombres de personas, DNI, emails personales? → minimizar (doc 06).
- [ ] **Fiabilidad por campo** inicial (se calibra luego con el golden set).
- [ ] **Coste por unidad** (llamada, resultado, página) para que el planificador pueda presupuestar.
- [ ] **Límites de velocidad** y reintentos con espera exponencial; `robots.txt` si es web.
- [ ] **Fixtures**: guardar 3-5 respuestas reales (anonimizadas si hace falta) en `worker/tests/fixtures/<codigo>/` para tests sin red.

## Contrato

```python
# worker/radar/fuentes/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator
import hashlib, json


@dataclass
class CamposExtraidos:
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
    estado: str | None = None            # 'operativa', 'cerrada', 'disuelta'… tal como lo dice la fuente
    empleados: str | None = None         # rango tal cual
    extra: dict[str, Any] = field(default_factory=dict)  # place_id, linkedin_url, hoja registral…


@dataclass
class RegistroBruto:
    fuente: str                          # = fuentes.codigo
    id_externo: str | None
    url: str | None
    payload: dict[str, Any]              # SOLO lo que la fuente permite almacenar
    campos: CamposExtraidos
    capturado_en: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def hash_contenido(self) -> str:
        base = json.dumps({"f": self.fuente, "id": self.id_externo, "p": self.payload}, sort_keys=True, default=str)
        return hashlib.sha256(base.encode()).hexdigest()


@dataclass
class ResultadoTrabajo:
    registros: int = 0
    errores: int = 0
    coste_eur: float = 0.0
    detalle: dict[str, Any] = field(default_factory=dict)


class Conector(ABC):
    codigo: str                          # debe existir en la tabla `fuentes`
    coste_unitario_eur: float = 0.0

    @abstractmethod
    def estimar_coste(self, parametros: dict) -> float:
        """Coste esperado de ejecutar `descubrir` con estos parámetros (para el planificador)."""

    @abstractmethod
    def descubrir(self, parametros: dict, max_coste_eur: float) -> AsyncIterator[RegistroBruto]:
        """Genera registros brutos. Debe parar al alcanzar max_coste_eur."""
```

## Esqueleto de un conector

```python
# worker/radar/fuentes/ejemplo.py
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from .base import Conector, RegistroBruto, CamposExtraidos


class ConectorEjemplo(Conector):
    codigo = "ejemplo"
    coste_unitario_eur = 0.0

    def __init__(self, cliente: httpx.AsyncClient, config):
        self.cliente, self.config = cliente, config

    def estimar_coste(self, parametros: dict) -> float:
        return len(parametros.get("consultas", [])) * self.coste_unitario_eur

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, max=30))
    async def _pedir(self, url: str, params: dict) -> dict:
        r = await self.cliente.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    async def descubrir(self, parametros, max_coste_eur):
        gastado = 0.0
        for consulta in parametros["consultas"]:
            if gastado + self.coste_unitario_eur > max_coste_eur:
                break
            datos = await self._pedir(self.config.url, {"q": consulta})
            gastado += self.coste_unitario_eur
            for item in datos.get("resultados", []):
                yield RegistroBruto(
                    fuente=self.codigo,
                    id_externo=item.get("id"),
                    url=item.get("url"),
                    payload=item,                      # recortar si la fuente no permite almacenar
                    campos=CamposExtraidos(razon_social=item.get("nombre"), telefonos=[item.get("telefono")] if item.get("telefono") else []),
                )
```

## Notas por fuente

- **Google Places**: `payload` = `{"place_id": ...}` únicamente. Los demás campos se usan en memoria para el matching y la verificación en vivo del momento y se registra la verificación (fuente, fecha, resultado), no el contenido. Rejilla: dividir el polígono de la zona en celdas, consultar cada celda con varias categorías/sinónimos; si una celda satura el máximo de resultados, subdividirla. Revisar términos EEE.
- **BORME**: sumario diario vía API de datos abiertos del BOE → PDFs de la sección A por provincia → parsear actos (constitución, cambio de domicilio/denominación, disolución, extinción, concurso…). Guardar el identificador del anuncio. Detectar actos que afectan a empresas ya en BD por razón social normalizada + provincia (+ datos registrales si los hay).
- **Web de la empresa**: descargar portada, localizar enlaces a aviso legal/contacto/privacidad; respetar `robots.txt`; `User-Agent` identificable; caché por URL; `extraer_datos_legales.py` (skill de verificación) antes de cualquier LLM.
- **Buscador web**: los resultados solo aportan URLs y pistas; el dato se confirma leyendo la página.
- **PLACSP / REA**: aportan NIF + razón social: excelentes anclas de identidad; entrar por NIF en el matching.

## Tests mínimos de un conector

1. Parsea correctamente cada fixture guardado (campos esperados).
2. Respeta `max_coste_eur` (no hace más llamadas de las permitidas).
3. No guarda en `payload` campos no permitidos por la fuente.
4. Maneja errores (429, 5xx, timeout) con reintentos y los cuenta en `ResultadoTrabajo.errores`.
