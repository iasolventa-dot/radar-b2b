# Worker — Radar B2B

Worker Python del pipeline descrito en `../docs/02_arquitectura_tecnica.md`. Conectores, extracción, normalización, resolución de entidades, verificación y el bucle del agente.

## Arranque rápido

```bash
cd worker
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example ../.env   # y rellena las claves
pytest
```

`radar/config.py` carga la configuración desde variables de entorno (ver `.env.example` en la raíz). Nada de claves hardcodeadas en el código.

## Estructura (ver doc 02 §4)

| Paquete | Contenido | Estado |
|---|---|---|
| `radar/fuentes/` | Un módulo por conector: `borme.py`, `places.py`, `web.py`, `rea.py`, `placsp.py`… Cada uno devuelve el contrato del doc 02 §5 | Vacío — Fase 1, Paso 11 de la guía |
| `radar/extraccion/` | Extracción de HTML: reglas primero (regex NIF/teléfono/email), LLM con salida estructurada solo si faltan campos | Vacío — Fase 1 |
| `radar/normalizacion/` | `nif.py`, `telefono.py`, `direccion.py`, `nombre.py`, `dominio.py` — reglas deterministas del doc 05, con tests | Vacío — Fase 1, Paso 12 |
| `radar/resolucion/` | Blocking, puntuación, fusión, cola de revisión (doc 05 §2-3) | Vacío — Fase 1 |
| `radar/verificacion/` | Confianza, frescura, estado (doc 05 §4-6) | Vacío — Fase 1 |
| `radar/agente/` | Interpretación, planificador, prompts, herramientas (doc 07) | Vacío — Fase 3 |
| `radar/cola.py` | Consumo de la cola `pgmq` de Supabase | Implementado (mínimo funcional) |
| `radar/config.py` | Configuración desde entorno | Implementado |

Cada módulo nuevo de `fuentes/` o `normalizacion/` se construye en su propio chat, siguiendo la plantilla de la skill `agente-busqueda-empresas` o `verificacion-empresas-es`, con tests antes de darlo por bueno (ver `08_registro_decisiones.md` y la regla de oro del doc 07 §6: todo cambio se evalúa contra el golden set).
