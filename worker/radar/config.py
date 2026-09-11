"""Configuración del worker, cargada desde variables de entorno.

Nunca hardcodear claves aquí ni en el código que las use — todo pasa por
`Settings`, que a su vez lee del entorno (y de un `.env` en desarrollo).
Ver `.env.example` en la raíz del repo para la lista completa de variables
y docs/08_registro_decisiones.md (D-04, D-06, D-07) para los valores
por defecto acordados.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Supabase --------------------------------------------------------
    supabase_url: str = Field(default="", description="URL del proyecto Supabase")
    supabase_service_role_key: str = Field(
        default="", description="Service role key (el worker se salta RLS)"
    )
    supabase_db_url: str = Field(
        default="", description="Cadena de conexión Postgres directa (para pgmq)"
    )

    # --- LLM ---------------------------------------------------------------
    # Doc 02 §3 deja los dos como opción ("API de Anthropic y OpenAI opcional");
    # `proveedor_llm` decide cuál usa de verdad `radar.extraccion.llm` y
    # `radar.fuentes.buscador_web` en cada momento — por defecto OpenAI
    # (2026-09-11: el proyecto solo tiene contratada esa cuenta). Cambiar a
    # "anthropic" en cuanto haya clave de Anthropic no requiere tocar código,
    # solo esta variable (y `MODELO_PLANIFICADOR`/`MODELO_EXTRACCION`, que son
    # específicos de cada proveedor).
    proveedor_llm: Literal["openai", "anthropic"] = Field(default="openai")
    anthropic_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")
    modelo_planificador: str = Field(
        default="gpt-5.6-sol",
        description=(
            "Modelo potente: interpretar, planificar, arbitrar (doc 07 §2). "
            "Verificado 2026-09-11 contra developers.openai.com/api/docs/models — "
            "cambia si `proveedor_llm` es 'anthropic' (ahí usar algo tipo claude-sonnet-*, verificar el vigente)."
        ),
    )
    modelo_extraccion: str = Field(
        default="gpt-5.6-luna",
        description=(
            "Modelo rápido y barato: extracción masiva (doc 07 §2). "
            "Verificado 2026-09-11 (soporta salida estructurada) — mismo comentario que modelo_planificador."
        ),
    )

    # --- Fuentes (D-06, D-07) ----------------------------------------------
    google_places_api_key: str = Field(default="")
    search_api_provider: str = Field(
        default="openai",
        description="openai | anthropic | tavily | exa | serper (D-06: comparar antes de escalar)",
    )
    search_api_key: str = Field(default="")

    # --- Presupuesto (D-04) -------------------------------------------------
    presupuesto_mensual_eur: float = Field(default=125.0)
    presupuesto_por_busqueda_eur_defecto: float = Field(default=20.0)

    # --- Caché de descargas web ---------------------------------------------
    cache_descargas_dias: int = Field(default=30)
    cache_descargas_dir: str = Field(
        default=".cache/descargas_web",
        description=(
            "Caché local en disco de radar.extraccion.descarga. En un contenedor "
            "efímero (Railway) no sobrevive a un redeploy — ver docstring de ese módulo."
        ),
    )


@lru_cache
def get_settings() -> Settings:
    """Instancia cacheada de `Settings` (léela una vez por proceso)."""
    return Settings()
