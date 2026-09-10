# Radar B2B

Agente de IA que descubre, clasifica y verifica empresas y empresarios españoles bajo petición en lenguaje natural, y los guarda en una base de datos propia, filtrable y con trazabilidad a nivel de campo.

**Uso estrictamente interno de Solventa IA** (D-03): no se vende la aplicación ni se hacen públicos los datos que recoge, incluidos los personales (autónomos, administradores, contactos). Se recogen precisamente para tener una base propia completa y para contrastar su calidad entre fuentes independientes.

Toda la documentación de fondo (visión, arquitectura, modelo de datos, fuentes, verificación, diseño del agente, registro de decisiones) vive en [`docs/`](./docs) — es una copia de la Base de Conocimiento del Proyecto en Claude, y debe mantenerse igual que ella.

## Estado

Fase 0 cerrada (decisiones D-01 a D-10, ver `docs/08_registro_decisiones.md`). Repositorio recién generado — pendiente Fase 1 (núcleo de calidad: normalización, resolución de entidades, golden set).

## Estructura

```
radar-b2b/
├── supabase/       # esquema (migraciones SQL) y catálogos semilla
├── worker/         # pipeline en Python: conectores, normalización, matching, agente
├── web/            # interfaz Next.js (Fase 3)
├── n8n/             # workflows de orquestación programada (Fase 2+)
└── docs/           # documentación del proyecto (espejo de la Base de Conocimiento)
```

Detalle de cada carpeta en `docs/02_arquitectura_tecnica.md` §4.

## Arranque rápido

### 1. Base de datos (Supabase)

```bash
supabase init            # si el repo aún no tiene supabase/config.toml propio
supabase link --project-ref TU_REF
supabase db push         # aplica supabase/migrations/202609100001_esquema_inicial.sql
```

Alternativa rápida: pega el contenido de `supabase/migrations/202609100001_esquema_inicial.sql` en el *SQL Editor* del panel de Supabase y ejecútalo.

Comprueba en *Table Editor* que existen `empresas`, `sedes`, `fuentes` (con 11 filas), etc.

### 2. Worker (Python)

```bash
cd worker
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example ../.env   # rellena las claves reales
pytest                       # debe pasar en verde con el esqueleto tal cual
```

### 3. Siguiente paso real

Ver `docs/08_registro_decisiones.md` (sección "Estado actual") y la guía personal `00_COMO_MONTARLO_PASO_A_PASO.md` (no forma parte de este repo) para la Fase 1: golden set, primeros conectores (BORME, PLACSP, REA) y pipeline de normalización/deduplicación.

## Convenciones

- Idioma: código, comentarios, commits y documentación en español. Tablas y columnas en `snake_case`, sin tildes.
- Migraciones SQL siempre numeradas y en `supabase/migrations/`, nunca editadas a mano en Supabase sin migración correspondiente.
- Ningún cambio en reglas de normalización/matching se da por bueno sin tests y sin evaluarlo contra el golden set (`worker/tests/golden/`).
- Ver `docs/01_INSTRUCCIONES_DEL_PROYECTO.md` para el resto de principios de trabajo.
