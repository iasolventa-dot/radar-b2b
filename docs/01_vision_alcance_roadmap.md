# 01 — Visión, alcance y roadmap

## 1. Problema

Las bases de datos de empresas que se consiguen hoy (directorios, scrapers de Google Maps, listas compradas) tienen cuatro defectos recurrentes:

1. **Duplicados y confusiones**: la misma empresa aparece 3 veces con nombres ligeramente distintos, o dos empresas distintas con nombres parecidos se fusionan por error.
2. **Datos desactualizados**: teléfonos que ya no funcionan, direcciones antiguas, webs caídas.
3. **Empresas muertas**: sociedades disueltas o negocios cerrados que siguen apareciendo como activos.
4. **Sin trazabilidad**: no se sabe de dónde sale cada dato ni cuándo se comprobó, así que no se puede confiar en ninguno.

## 2. Solución

Un sistema compuesto por:

- **Un agente conversacional** al que se le pide, en lenguaje natural, un conjunto de empresas ("empresas de reformas en el Aljarafe con web propia", "instaladoras eléctricas de Andalucía occidental de más de 20 empleados").
- **Un pipeline de descubrimiento y verificación** que busca candidatos en varias fuentes, extrae sus datos, los normaliza, detecta duplicados, contrasta cada campo entre fuentes independientes y asigna una confianza.
- **Una base de datos maestra** en Supabase que acumula conocimiento: cada búsqueda enriquece la base, y las búsquedas futuras se sirven primero desde lo ya verificado.
- **Un proceso de mantenimiento** que re-verifica datos antiguos y detecta automáticamente cambios (disoluciones en BORME, cierres en Google, webs caídas).

El producto final son **leads**: empresas (y, cuando se encuentren, sus empresarios/contactos) encontradas, clasificadas y verificadas, listas para que Solventa IA las use en prospección comercial de cualquier producto. Es de **uso estrictamente interno** (ver doc 08, D-03): no se vende ni se hace pública, ni la aplicación ni los datos que recoge.

## 3. Usuarios y casos de uso

| Caso de uso | Ejemplo | Prioridad |
|---|---|---|
| Prospección comercial propia de Solventa IA | "Constructoras medianas de Sevilla y Huelva" (para cualquiera de sus productos) | MVP |
| Generar listados para clientes | "Proveedores de áridos en Andalucía para un cliente" | Fase 2 |
| Enriquecer/limpiar una lista que ya tiene el usuario | Subir un Excel y devolverlo deduplicado y verificado | Fase 2 |

> Nota de alcance (D-03): la base es de uso interno. "Generar listados para clientes" significa una entrega puntual gestionada por Solventa IA (como cualquier entregable de consultoría), no acceso de terceros a la plataforma ni venta de datos — eso queda fuera de alcance (ver Fase 5 más abajo).

## 4. Filtros que debe soportar

- **Geográficos**: país (España en el MVP), comunidad autónoma, provincia, municipio (código INE), código postal, radio alrededor de un punto, polígono libre (p. ej. "Aljarafe").
- **Sector**: CNAE (código y jerarquía), sector interno propio (taxonomía más comercial, p. ej. "reformas integrales"), palabras clave del objeto social o de la web.
- **Tamaño**: rango de empleados (micro <10, pequeña 10-49, mediana 50-249, grande ≥250), rango de facturación si hay fuente.
- **Forma jurídica**: S.L., S.A., cooperativa, autónomo, etc.
- **Estado**: activa verificada, probablemente activa, dudosa… (por defecto solo activas).
- **Presencia digital**: tiene web, tiene email, tiene teléfono verificado, tiene LinkedIn de empresa.
- **Contacto**: persona de contacto, administrador o decisor identificado (nombre, cargo, canal), cuando la fuente lo permita.
- **Antigüedad**: fecha de constitución.
- **Calidad**: confianza mínima global o por campo, frescura máxima ("verificado en los últimos 90 días").
- **Otros**: ha licitado con la administración, está en el REA (construcción), etc.

## 5. Qué significa "bien contrastada" (criterios de calidad medibles)

| Métrica | Definición | Objetivo MVP |
|---|---|---|
| Precisión de identidad | % de registros donde NIF + razón social + domicilio corresponden a la misma entidad real | ≥ 98 % |
| Tasa de duplicados | % de entidades reales que aparecen más de una vez en el resultado | ≤ 1 % |
| Falsas fusiones | % de registros que mezclan datos de dos empresas distintas | ≤ 0,5 % |
| Precisión de teléfono | % de teléfonos que corresponden a la empresa (muestreo manual) | ≥ 90 % |
| Empresas inactivas colándose | % de empresas marcadas activas que están disueltas/cerradas | ≤ 2 % |
| Frescura | % de campos de contacto verificados hace menos de 180 días | ≥ 90 % |
| Cobertura | empresas encontradas / universo estimado (INE DIRCE para ese CNAE y provincia) | medir, sin objetivo fijo en MVP |
| Coste | coste total (APIs + LLM) / empresas verificadas | medir y bajar en cada iteración |

Estas métricas se miden contra un **conjunto de referencia (golden set)** verificado a mano (ver doc 07).

## 6. Fuera de alcance (por ahora)

- Envío de comunicaciones comerciales desde la plataforma — el producto entrega leads, no es una herramienta de campañas.
- Países distintos de España (el diseño debe permitirlo, pero las fuentes del MVP son españolas).

## 7. Roadmap por fases

Cada fase termina con algo que funciona y se puede probar.

### Fase 0 — Decisiones y cimientos (1 semana)
- Cerrar las decisiones abiertas del `08_registro_decisiones.md` (ámbito, sector piloto, uso, presupuesto).
- Crear repo, proyecto Supabase, estructura de carpetas.
- **Entregable**: repo con la migración inicial aplicada (esquema del doc 03).

### Fase 1 — Núcleo de calidad sin agente (2-3 semanas)
- Librería de normalización y validación (NIF, teléfonos, direcciones, nombres) con tests.
- Motor de resolución de entidades (matching + fusión + cola de revisión).
- Ingesta de una fuente oficial (BORME) y de la web propia de las empresas (aviso legal).
- Crear el golden set: ~200 empresas de un sector y zona piloto verificadas a mano.
- **Entregable**: script que recibe una lista de candidatos y devuelve empresas consolidadas con confianza por campo, evaluado contra el golden set.

### Fase 2 — Descubrimiento multi-fuente (2-3 semanas)
- Conectores: Google Places, buscador web vía API, directorios sectoriales (REA, licitaciones públicas), redes sociales (LinkedIn u otras) cuando aporten señal.
- Estimación de cobertura con INE DIRCE.
- Cola de trabajos (pgmq en Supabase) y worker.
- **Entregable**: una búsqueda por sector + provincia que produce una base verificada end-to-end, con informe de métricas y coste.

### Fase 3 — El agente (2 semanas)
- Interpretación de peticiones en lenguaje natural → filtros estructurados.
- Planificador que decide qué fuentes consultar según lagunas y presupuesto.
- Interfaz de chat en Next.js + vista de resultados (tabla y mapa) + exportación CSV/Excel.
- **Entregable**: pedir "X en Y" en el chat y obtener la base verificada.

### Fase 4 — Mantenimiento y frescura (1-2 semanas)
- Ingesta diaria del BORME para detectar disoluciones, cambios de domicilio y denominación.
- Re-verificación programada (n8n) priorizando datos caducados.
- Cola de revisión humana en la interfaz.

### Fase 5 — (fuera de alcance por ahora)
Multi-usuario, cuotas, facturación, API de terceros — descartado mientras rija D-03 (uso estrictamente interno).
