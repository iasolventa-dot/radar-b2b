"""Interpretación, planificador, prompts y herramientas del agente (doc 07).

Bucle propio (no framework de agentes) con tool use sobre la API del
proveedor de LLM configurado en `settings.proveedor_llm` (openai por
defecto desde 2026-09-11; ver `radar.extraccion.llm` y
`radar.fuentes.buscador_web` para el mismo patrón ya aplicado), según T-01
y doc 02 §3. Las plantillas de prompts y los esquemas JSON de herramientas
completos viven en la skill `agente-busqueda-empresas`.

Pendiente: Fase 3 (tarea #21).
"""
