# 08 — Registro de decisiones y estado del proyecto

> Documento VIVO. Actualízalo al final de cada sesión de trabajo en la que se decida algo (Claude te propondrá el texto). Sustituye este archivo en el conocimiento del Proyecto cada vez que lo cambies.

## Estado actual

- **Fase**: 0 — Decisiones y cimientos (decisiones cerradas; pendientes los cimientos técnicos)
- **Última actualización**: 2026-09-10
- **Siguiente hito**: repo creado + proyecto Supabase + migración inicial aplicada (esquema del doc 03)

## Decisiones tomadas

| ID | Fecha | Decisión | Motivo | Alternativas descartadas |
|---|---|---|---|---|
| T-01 | 2026-09-10 | Pipeline determinista + LLM en puntos de decisión (no agente libre navegando) | Precisión, trazabilidad y coste | Agente autónomo con navegador |
| T-02 | 2026-09-10 | NIF/CIF como clave maestra de persona jurídica; NIF válido distinto = empresas distintas | Evitar fusiones erróneas | Matching solo por nombre/dirección |
| T-03 | 2026-09-10 | Modelo en capas bronce/plata/oro con evidencia por campo | Poder recalcular y auditar | Tabla plana de empresas |
| T-04 | 2026-09-10 | Stack: Supabase + worker Python + n8n (programación) + Next.js en Vercel | Stack conocido; worker para procesos largos y testeables | Todo en n8n; todo en Edge Functions |
| T-05 | 2026-09-10 | Google Places solo para descubrir y verificar en vivo; se persiste únicamente `place_id` | Condiciones de uso de Google Maps Platform (riesgo de perder acceso a la API, no marco legal del proyecto) | Almacenar datos de Places |
| T-06 | 2026-09-10 | ~~Sin scraping de LinkedIn~~ — **revocada por D-10** | — | — |
| T-07 | 2026-09-10 | ~~MVP limitado a datos de empresa y canales genéricos; contactos personales tras revisión legal~~ — **revocada por D-10** | — | — |
| D-01 | 2026-09-10 | Ámbito geográfico del MVP: **Sevilla provincia** | Conoce el mercado (verificación manual fiable del golden set), universo manejable para iterar rápido en Fase 1 | Andalucía occidental, Andalucía, España (se posponen a Fase 2; filtros geográficos diseñados desde el inicio para escalar sin cambios de arquitectura) |
| D-02 | 2026-09-10 | Sector piloto: **Construcción (CNAE 41-43)** | Encaja con cliente actual (EasyProject); fuentes con NIF propio (PLACSP, REA) además de BORME; conocimiento del sector para verificar el golden set | Otro sector |
| D-03 | 2026-09-10 (revisada 2026-09-10) | Uso del MVP: **estrictamente interno de Solventa IA**. No se vende la aplicación ni se da acceso a terceros; no se hacen públicos los datos recogidos, incluidos los personales. Se recogen datos de empresas y de empresarios (autónomos, administradores) para tener una base propia completa y para contrastar la calidad de los datos entre fuentes independientes | Base de datos y herramienta de uso puramente interno, sin distribución externa | Servicio con acceso de clientes a la base; SaaS vendible |
| D-04 | 2026-09-10 | Presupuesto mensual de APIs: **100-150 €/mes** para Fase 0-2 (≈10 € hosting, 20-30 € Google Places, 20-30 € búsqueda web, 30-50 € LLM) | Cubre la validación del golden set (~200 empresas) sin comprometer capital antes de medir la métrica clave (coste por empresa verificada) | Fijar presupuesto mayor sin datos de esa métrica |
| D-05 | 2026-09-10 | **Sin proveedor comercial** de tamaño/facturación por ahora; prueba gratuita solo si el golden set confirma que es el cuello de botella | Tamaño es el campo más difícil sin proveedor, pero se puede medir la brecha real primero con señales gratuitas (INE DIRCE, nº de sedes, antigüedad) | Contratar prueba con uno o varios proveedores desde ya |
| D-06 | 2026-09-10 | Búsqueda web: **herramienta de búsqueda de la API de Anthropic** como base, comparada con Tavily/Exa/Serper sobre una muestra de 50-100 consultas antes de escalar | Sin infraestructura extra; comparación por coste y calidad en español, sin descartar ninguna por motivo contractual | — |
| D-07 | 2026-09-10 | Hosting del worker: **Railway** en Fase 0-1; migración a Hetzner evaluada en Fase 2-3 si el volumen lo justifica | Deploy simple sin DevOps mientras el volumen es bajo y los trabajos son por lotes, no always-on | VPS (Hetzner) desde el inicio |
| D-08 | 2026-09-10 | **Incluir autónomos** en el MVP, sin restricción especial frente a otras entidades (ver D-10) | Relevante en construcción (muchos autónomos) | Excluir autónomos del MVP |
| D-09 | 2026-09-10 | Versión CNAE de referencia: **CNAE-2025** como principal, con tabla de correspondencias a CNAE-2009 cargada desde el inicio | Comunicación a la AEAT obligatoria antes del 30/6/2026, ya vigente a fecha de esta decisión | Usar solo CNAE-2009 |
| D-10 | 2026-09-10 | **Cambio de enfoque**: el proyecto deja de estar condicionado por (a) la venta de un producto propio concreto (EasyProject) y (b) el marco legal (`06_marco_legal_cumplimiento.md`) como restricción de diseño. El foco es la capacidad técnica del agente — encontrar, clasificar y verificar empresas y empresarios bajo petición — para una base de datos interna completa (ver D-03: no se publica ni se vende). Consecuencia directa: T-06 y T-07 quedan revocadas; autónomos, contactos personales y redes sociales (LinkedIn incluido) se tratan como cualquier otra fuente/entidad, sin control derivado de RGPD/LOPDGDD/LSSI en el diseño. Doc 06 queda archivado como referencia, no como restricción | Foco pedido explícitamente en la capacidad del agente y en la completitud/calidad de una base interna, no en un modelo de negocio ni en un ejercicio de cumplimiento normativo | Mantener el marco legal como salvaguarda de diseño; atar el caso de uso a EasyProject; ofrecer la base a terceros |

## Decisiones abiertas (cerrar en Fase 0)

Ninguna.

## Comprobaciones externas realizadas

| Fecha | Qué se comprobó | Resultado | Fuente |
|---|---|---|---|
| 2026-09-10 | Política de caché de Google Places API | Solo `place_id` almacenable indefinidamente; existen términos específicos EEE | developers.google.com/maps/documentation/places/web-service/policies |
| 2026-09-10 | Obligatoriedad de comunicar CNAE-2025 a la AEAT | Plazo límite 30 de junio de 2026, ya vigente en la fecha de esta decisión | asensioyasociados.com/23062025-2 |
| 2026-09-10 | Precio Google Places API (New), Place Details (tier Essentials) | ≈5 $ por 1.000 solicitudes (tramo 10K-100K/mes) — verificar tarifa exacta antes de contratar | woosmap.com/blog/google-places-api-pricing |
| 2026-09-10 | Precios de APIs de búsqueda web (Tavily, Serper, Exa) | Serper ≈1 $/1.000 consultas, Exa ≈5 $/1.000, Tavily ≈8 $/1.000 — verificar tarifa exacta antes de contratar | buildmvpfast.com/api-costs/ai-search |
| 2026-09-10 | Coste de hosting de un worker pequeño (Railway / Fly.io / Hetzner) | Railway ≈46 $/mes, Fly.io ≈17 $/mes, Hetzner CX22 ≈5 $/mes (escenario always-on, 100 GB egress) | bex.co/blog/2026/09/07/paas-pricing-spread-vs-hetzner-cx22-fleet |

## Registro de sesiones

| Fecha | Qué se hizo | Resultado / siguiente paso |
|---|---|---|
| 2026-09-10 | Creación del paquete de contexto del proyecto (instrucciones, docs, skills) | Montar el Proyecto y cerrar decisiones abiertas |
| 2026-09-10 | Cierre de D-01 a D-09, con verificación de precios y normativa vigente | Fase 0 con decisiones de ámbito/sector/uso/presupuesto/fuentes cerradas |
| 2026-09-10 | D-10: giro de enfoque — fuera EasyProject como caso de uso exclusivo y el marco legal como restricción de diseño; foco 100% en la capacidad técnica del agente | Doc 06 archivado; instrucciones del proyecto, visión y roadmap actualizados |
| 2026-09-10 | Aclaración de D-03: uso estrictamente interno, sin venta ni publicación de datos; los datos personales (autónomos, empresarios, administradores) se recogen para completitud y contraste de calidad, no para distribución | D-03 y D-10 revisadas; siguiente paso: crear repo + proyecto Supabase + migración inicial |
