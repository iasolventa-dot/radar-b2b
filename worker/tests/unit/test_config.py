"""Comprueba que la configuración carga con valores por defecto razonables.

Sirve como humo (smoke test) de que el esqueleto del worker está bien
cableado: si esto falla, algo está mal en `radar/config.py` o en el
entorno, antes incluso de tocar lógica de negocio.
"""

from radar.config import Settings


def test_settings_carga_con_valores_por_defecto() -> None:
    settings = Settings(_env_file=None)  # ignora .env: solo probamos los defaults
    assert settings.presupuesto_mensual_eur == 125.0
    assert settings.proveedor_llm == "openai"
    assert settings.search_api_provider == "openai"
    assert settings.modelo_planificador
    assert settings.modelo_extraccion


def test_settings_lee_variables_de_entorno(monkeypatch) -> None:
    monkeypatch.setenv("PRESUPUESTO_MENSUAL_EUR", "200")
    monkeypatch.setenv("SEARCH_API_PROVIDER", "tavily")
    monkeypatch.setenv("PROVEEDOR_LLM", "anthropic")
    settings = Settings(_env_file=None)
    assert settings.presupuesto_mensual_eur == 200.0
    assert settings.search_api_provider == "tavily"
    assert settings.proveedor_llm == "anthropic"
