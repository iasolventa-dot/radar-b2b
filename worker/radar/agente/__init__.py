"""Interpretación, planificador, prompts y herramientas del agente (doc 07).

Bucle propio (no framework de agentes) con tool use sobre la API del
proveedor de LLM configurado en `settings.proveedor_llm` (openai por
defecto desde 2026-09-11; ver `radar.extraccion.llm` y
`radar.fuentes.buscador_web` para el mismo patrón ya aplicado), según T-01
y doc 02 §3. Las plantillas de prompts y los esquemas JSON de herramientas
completos viven en la skill `agente-busqueda-empresas`.

Tarea #21, entrega incremental (ver `08_registro_decisiones.md`):

- `prompts.py` — plantillas (hecho).
- `interpretacion.py` — petición en lenguaje natural → `FiltrosBusqueda` (hecho).
- Pendiente: `herramientas.py` (wrappers de los conectores existentes como
  tools), `planificador.py` (bucle de tool use), CLI de prueba manual.
  El resto de herramientas del doc 07 §5 (`estimar_cobertura`,
  `arbitrar_duplicados`, `lanzar_descubrimiento`/`estado_trabajos` vía cola,
  `verificar_empresa`/`finalizar_busqueda`) dependen de piezas que no
  existen aún (datos INE DIRCE, consumidor de la cola pgmq, lógica de
  arbitraje) y se abordan en entregas posteriores — ver mensaje del agente
  en el registro de decisiones para el detalle.
"""
