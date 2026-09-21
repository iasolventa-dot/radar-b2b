---
name: agente-busqueda-empresas
description: Plantillas y procedimiento para construir el agente de búsqueda y verificación de empresas del proyecto Radar B2B — conectores de fuentes de datos (BORME, Google Places, webs corporativas, licitaciones, directorios), prompts del agente (interpretación de peticiones, planificador, extracción web, arbitraje de duplicados, clasificación CNAE), definiciones de herramientas para tool use de la API de Anthropic, bucle del planificador, control de costes y evaluación con golden set. Úsala SIEMPRE que se vaya a diseñar, programar, revisar o depurar cualquier pieza del agente o del pipeline de descubrimiento de empresas, incluso si el usuario solo dice "hagamos el conector de X", "escribe el prompt de…", "cómo evalúo…" o "el agente encuentra duplicados".
---

# Construcción del agente de búsqueda de empresas (Radar B2B)

El agente orquesta un pipeline determinista (ver docs 02 y 07 del proyecto): **el código verifica, el LLM juzga**. Esta skill contiene las plantillas para construir cada pieza de forma coherente con el resto.

## Qué leer según la tarea

| Tarea | Lee |
|---|---|
| Crear o revisar un **conector de fuente** | `references/plantilla_conector.md` |
| Escribir o ajustar un **prompt** (interpretación, planificador, extracción, arbitraje, CNAE) | `references/prompts.md` |
| Definir las **herramientas** del agente (tool use) | `references/herramientas.json` |
| **Evaluar** cambios o montar el golden set | `references/evaluacion.md` |
| Normalizar/validar/deduplicar datos | skill `verificacion-empresas-es` |

## Reglas de diseño (el porqué)

1. **El agente no escribe en la BD ni lee páginas enteras.** Las herramientas hacen el trabajo y devuelven resúmenes cortos (recuentos, muestras, errores). Así el contexto no se llena de HTML y el coste no se dispara.
2. **Salida estructurada siempre** que un LLM produzca datos (JSON validado con esquema; si no valida, reintento con el error, máx. 2).
3. **Nada entra como verificado solo porque lo diga un LLM.** Lo extraído por modelo se guarda como observación con la fuente real (la URL leída) y pasa las mismas validaciones deterministas; la inferencia pura usa la fuente `inferencia_llm` (fiabilidad 0,2).
4. **Cada fuente respeta sus condiciones** (tabla `fuentes`: `permite_almacenar`, `campos_almacenables`). Google Places → solo `place_id` persistente. Sin scraping de LinkedIn.
5. **Presupuesto explícito** por búsqueda; cada herramienta informa de su coste; el planificador para al agotarlo o ante rendimientos decrecientes.
6. **Todo cambio de prompt, regla o fuente se evalúa contra el golden set** antes de darlo por bueno (`references/evaluacion.md`).
7. **Verifica la documentación vigente** de cualquier API externa (endpoints, precios, cuotas, modelos) antes de fijarla en código; cita la fuente y regístrala en el registro de decisiones.

## Procedimiento general para una pieza nueva

1. Sitúa la pieza en el flujo del doc 02 (qué paso, qué entra, qué sale).
2. Parte de la plantilla correspondiente; adapta sin romper los contratos (forma de `registros_brutos.campos`, esquemas JSON de salida).
3. Escribe el código completo con tests (unitarios con fixtures reales guardados, sin llamadas de red en los tests).
4. Mide contra el golden set: precisión, duplicados, coste.
5. Propón la entrada para `08_registro_decisiones.md`.

## Convenciones

- Python ≥ 3.11, `httpx` asíncrono, `pydantic` para esquemas, `tenacity` para reintentos, logs estructurados (JSON).
- Tablas y columnas en español `snake_case`; migraciones en `supabase/migrations/`.
- Modelos: uno potente para planificar/arbitrar y uno rápido y barato para extracción/clasificación masiva; nombre del modelo en configuración, nunca en el código.
