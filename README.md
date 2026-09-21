# Radar B2B

Agente de IA de Solventa IA (uso estrictamente interno) que, a partir de una petición en lenguaje natural ("constructoras de Sevilla de 10 a 50 empleados"), descubre empresas en varias fuentes, las verifica cruzando fuentes independientes y las guarda en Supabase con trazabilidad a nivel de campo.

- Estado real del proyecto y qué está verificado: [`PROJECT_STATUS.md`](./PROJECT_STATUS.md)
- Principios, convenciones y cómo trabajar en el repo: [`CLAUDE.md`](./CLAUDE.md)
- Diseño y decisiones históricas: [`docs/`](./docs) (referencia; verifícalo contra el código)

## Estructura

```
supabase/   migraciones SQL numeradas (nunca se edita una ya aplicada)
worker/     Python: conectores, normalización, resolución de entidades, agente, API FastAPI
web/        panel Next.js
docs/       documentación de diseño
```

## Arranque en local

```bash
# Worker (desde worker/, con el venv activado y worker/.env o ../.env configurado)
uvicorn radar.api.main:app --reload --port 8000

# Panel (desde web/, con web/.env.local: NEXT_PUBLIC_API_URL=http://localhost:8000 y claves de Supabase)
npm run dev        # http://localhost:3000
```

Migraciones: `python scripts/aplicar_migracion.py <fichero.sql>` (desde `worker/`).

## Comprobaciones

```bash
# worker/
pytest && ruff check radar scripts tests && mypy radar
# web/
npx tsc --noEmit && npm run lint && npm run build
```

Claves de servicios de pago (Google Places) se pegan en **Ajustes** del panel, no en el código.
