# 02 — Arquitectura técnica

## 1. Idea central

No construimos "un LLM que navega libremente por internet y rellena una tabla". Eso produce datos inventados, duplicados y costes descontrolados. Construimos un **pipeline determinista con puntos de decisión inteligentes**:

- El **código** hace todo lo que se puede verificar: descargar, parsear, normalizar, validar dígitos de control, comparar, deduplicar, calcular confianza.
- El **LLM** interviene donde hace falta criterio: entender la petición, generar consultas de búsqueda, extraer datos de páginas web desordenadas, arbitrar duplicados ambiguos y decidir qué fuente consultar a continuación.

## 2. Flujo de una búsqueda (de la petición a la base verificada)

```
 Petición en lenguaje natural
        │
 [1] INTERPRETAR  (LLM) ──► filtros estructurados (CNAE, municipios INE, tamaño…) ──► confirmación del usuario
        │
 [2] CONSULTAR BD PROPIA ──► empresas ya verificadas y frescas que cumplen filtros
        │                    + estimación de cobertura (vs. INE DIRCE) → ¿cuántas faltan?
        │
 [3] PLANIFICAR  (LLM + reglas) ──► qué fuentes, qué consultas, qué rejilla geográfica, presupuesto
        │
 [4] DESCUBRIR (conectores en paralelo) ──► registros_brutos (payload + fuente + URL + fecha)
        │   BORME · Google Places · buscador web · directorios sectoriales · licitaciones · proveedores comerciales
        │
 [5] ENRIQUECER ──► para cada candidato con web: descargar inicio, aviso legal, contacto, privacidad
        │           extracción (LLM con salida estructurada) de NIF, razón social, domicilio, teléfonos, emails
        │
 [6] NORMALIZAR (código) ──► NIF validado, teléfono E.164, dirección geocodificada, nombre normalizado, dominio
        │
 [7] RESOLVER ENTIDADES (código + LLM en zona gris) ──► vincular a empresa existente / crear nueva / cola de revisión
        │
 [8] VERIFICAR Y PUNTUAR (código) ──► confianza por campo según fuentes independientes que coinciden + frescura
        │                               estado (activa / dudosa / disuelta…)
        │
 [9] ENTREGAR ──► resultados filtrados por confianza mínima, tabla/mapa, exportación con columnas de confianza y fuente
        │
[10] MANTENER (programado) ──► BORME diario, re-verificación de lo caducado, alertas
```

Los pasos 4-8 son un **bucle**: tras una ronda, el planificador mira cuántas empresas verificadas hay, qué lagunas quedan (zonas sin cubrir, empresas sin NIF, campos con baja confianza) y cuánto presupuesto resta, y decide si hacer otra ronda. Ahí está la parte "agéntica".

## 3. Componentes y tecnología

| Componente | Tecnología | Responsabilidad |
|---|---|---|
| Base de datos | **Supabase Postgres** + extensiones `postgis`, `pg_trgm`, `unaccent` (y `vector` opcional) | Modelo de datos (doc 03), búsquedas geográficas y difusas, RLS |
| Cola de trabajos | **Supabase Queues (pgmq)** | Desacoplar pasos del pipeline; reintentos; paralelismo controlado |
| Evidencias | **Supabase Storage** | Guardar HTML/capturas de las páginas de donde se extrajo cada dato (auditoría) cuando las condiciones de la fuente lo permitan |
| Worker | **Python** en contenedor (Railway, Fly.io o un VPS) | Conectores, extracción, normalización, matching, verificación. Procesos largos que no caben en funciones serverless |
| LLM | **API de Anthropic** (y OpenAI opcional) | Interpretación, planificación, extracción, arbitraje. Modelo potente para planificar/arbitrar; modelo rápido y barato para extracción masiva. Verificar modelos vigentes en la documentación |
| Búsqueda web | API de búsqueda (Brave Search, Serper, Tavily, Exa…) y/o la herramienta de búsqueda web del propio API de Anthropic | Descubrir webs corporativas y fichas en directorios |
| Descarga web | `httpx` + extractor de texto (p. ej. `trafilatura`/`selectolax`); `playwright` solo para webs que requieren JS | Leer webs de empresas respetando `robots.txt` y límites de velocidad |
| Geocodificación | **CartoCiudad (IGN)** como principal (datos abiertos, almacenables); Google solo como apoyo en vivo | Normalizar direcciones españolas y obtener coordenadas |
| Orquestación programada | **n8n** | Cron del BORME diario, re-verificaciones, notificaciones, exportar a Google Sheets/CRM |
| Frontend | **Next.js en Vercel** | Chat con el agente, tabla y mapa de resultados, cola de revisión, exportaciones |
| Código | **GitHub** monorepo | CI con tests del núcleo de normalización/matching |

### ¿Por qué el worker en Python y no todo en n8n o Edge Functions?
- El pipeline tiene pasos largos (cientos de descargas web por búsqueda) que superan los límites de tiempo de las funciones serverless.
- La lógica de matching necesita librerías maduras (`rapidfuzz`, `phonenumbers`, `pandas`) y **tests unitarios**: es el corazón de la calidad y no puede vivir en nodos visuales difíciles de testear.
- n8n sigue siendo ideal para lo que hace bien: programar, conectar y notificar.

### ¿Agent SDK o bucle propio?
Opción A: bucle propio con la API de mensajes y *tool use* (control total, fácil de auditar y de limitar coste). Opción B: un framework de agentes (p. ej. el Claude Agent SDK). Recomendación inicial: **bucle propio y simple** para el planificador, porque el pipeline ya es determinista y el agente solo decide "qué hacer después". Revisar si la complejidad crece.

## 4. Estructura del repositorio

```
radar-b2b/
├── supabase/
│   ├── migrations/            # SQL numerado (el esquema inicial está en el doc 03b)
│   └── seed/                  # catálogos: CNAE, municipios INE, fuentes
├── worker/                    # Python
│   ├── radar/
│   │   ├── fuentes/           # un módulo por conector: borme.py, places.py, web.py, rea.py, placsp.py…
│   │   ├── extraccion/        # extracción de datos de HTML (reglas + LLM)
│   │   ├── normalizacion/     # nif.py, telefono.py, direccion.py, nombre.py, dominio.py
│   │   ├── resolucion/        # blocking, scoring, fusión, cola de revisión
│   │   ├── verificacion/      # confianza, frescura, estado
│   │   ├── agente/            # interpretación, planificador, prompts, herramientas
│   │   ├── cola.py            # consumo de pgmq
│   │   └── config.py
│   └── tests/
│       ├── unit/
│       └── golden/            # golden set + script de evaluación
├── web/                       # Next.js
├── n8n/                       # workflows exportados (JSON)
└── docs/                      # estos documentos
```

## 5. Contratos entre pasos

Cada conector de fuente devuelve registros con esta forma mínima (se guardan en `registros_brutos`):

```json
{
  "fuente": "borme",
  "url": "https://…",
  "capturado_en": "2026-09-10T10:00:00Z",
  "id_externo": "…",
  "payload": { "…": "datos crudos tal como vienen" },
  "campos": {
    "razon_social": "CONSTRUCCIONES EJEMPLO SL",
    "nif": null,
    "domicilio": "C/ …",
    "telefonos": [],
    "web": null
  }
}
```

A partir de ahí, normalización y resolución trabajan siempre sobre `campos`, y `payload` queda como evidencia.

## 6. Control de coste y de carga

- Presupuesto por búsqueda (euros y número de llamadas por fuente) fijado antes de empezar; el planificador lo consulta en cada ronda.
- Caché de descargas web por URL (con fecha) para no descargar la misma página dos veces en N días.
- Extracción en dos niveles: primero reglas (regex de NIF, teléfonos, emails en el aviso legal), y solo si faltan campos, LLM.
- Modelos baratos para extracción masiva; modelos potentes solo para planificar y arbitrar.
- Métrica en cada búsqueda: coste total, coste por empresa verificada, llamadas por fuente.

## 7. Observabilidad

- Tabla `busquedas` con estado, estadísticas y coste de cada búsqueda.
- Log estructurado de cada llamada a LLM (prompt resumido, modelo, tokens, coste, resultado) para depurar y ajustar.
- Panel sencillo en la web con métricas de calidad del golden set tras cada cambio de reglas.
