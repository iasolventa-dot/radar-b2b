# 03 — Modelo de datos

El SQL completo y probado (PostgreSQL 16 + PostGIS 3) está en `03b_schema_inicial.sql`. Este documento explica el porqué.

## 1. Tres capas (bronce → plata → oro)

| Capa | Tabla(s) | Qué guarda | Regla |
|---|---|---|---|
| **Bronce** | `registros_brutos` | Lo que devuelve cada fuente, tal cual, con URL y fecha | Nunca se modifica; solo cambia su `estado` de resolución |
| **Plata** | `observaciones` | Cada afirmación de una fuente sobre un campo de una empresa ("la web X dice que el teléfono es Y el día Z") | Nunca se borra; se marca `vigente=false` si queda superada |
| **Oro** | `empresas`, `sedes`, `canales_contacto`, `identificadores` | El registro consolidado que se entrega, con confianza y fecha de última verificación | Se recalcula a partir de las observaciones (reglas del doc 05) |

Ventaja: si mañana cambiamos las reglas de verificación, **recalculamos la capa oro sin volver a buscar nada**, porque la evidencia está guardada. Y ante cualquier dato podemos responder "¿de dónde sale esto?".

## 2. Entidades principales

- **`empresas`**: una fila = una entidad jurídica (una sociedad con su NIF) o un empresario individual. El NIF es único cuando existe. Guarda razón social, nombre comercial, forma jurídica, estado, CNAE, tamaño, dominio web y la confianza global.
- **`sedes`**: una empresa tiene 1..N ubicaciones (domicilio social, sede operativa, delegaciones, naves). Dirección desglosada + código INE del municipio + punto geográfico (PostGIS). **El domicilio social del BORME a menudo no es donde trabaja la empresa** (puede ser una gestoría): por eso se distinguen tipos.
- **`canales_contacto`**: teléfonos, emails, web y redes, cada uno con valor normalizado, estado, confianza y última verificación. `es_generico` distingue `info@empresa.es` (dato de empresa) de `juan.perez@empresa.es` (dato personal).
- **`identificadores`**: todos los identificadores externos de la empresa (NIF, VAT UE, `place_id` de Google, URL de LinkedIn, hoja registral, número REA…). La restricción `unique(tipo, valor)` impide que un mismo `place_id` acabe asignado a dos empresas: es una defensa estructural contra fusiones erróneas.

## 3. Resolución de entidades

- **`candidatos_duplicado`**: pares de empresas que podrían ser la misma, con puntuación, señales (qué coincide y qué choca) y, si se consultó, el veredicto del LLM. Es la **cola de revisión**.
- **`fusiones`**: historial de fusiones con una instantánea del registro absorbido, para poder **deshacer**. La empresa absorbida no se borra: queda con `fusionada_en` apuntando a la superviviente (así los enlaces antiguos siguen resolviendo).
- **`eventos_empresa`**: historial legible de cambios (cambio de estado, de domicilio, teléfono inválido, acto BORME…).

## 4. Búsquedas del agente

- **`busquedas`**: petición original, filtros estructurados confirmados, presupuesto, estado, rondas, estadísticas y coste.
- **`busqueda_resultados`**: qué empresas encajan con cada búsqueda y por qué.

## 5. Catálogos

- **`fuentes`**: cada fuente con su fiabilidad de partida, si sus condiciones permiten almacenar contenido (`permite_almacenar`, `campos_almacenables`) y su `grupo_independencia`. Dos fuentes del mismo grupo (p. ej. dos directorios que se copian entre sí) **no cuentan como confirmación independiente**.
- **`cnae`**, **`municipios`** (código INE), **`sectores`** (taxonomía comercial propia mapeada a CNAE + palabras clave).

## 6. Decisiones de diseño relevantes

1. **Normalización en base de datos y en el worker.** El trigger `tg_empresas_normalizar` garantiza que `razon_social_norm`, `nif` y `dominio_web` estén siempre normalizados aunque alguien inserte a mano. El worker aplica además la normalización completa (teléfonos, direcciones) con librerías Python.
2. **Búsqueda difusa con `pg_trgm`** sobre nombres normalizados (índices GIN) y **geográfica con PostGIS** (índice GiST). La función `buscar_candidatos_empresa(nombre, lon, lat, radio)` es el primer paso ("blocking") del matching.
3. **Confianza como número 0-1 por campo** + fecha de última verificación. La confianza efectiva decae con el tiempo (doc 05).
4. **Contenido de fuentes con restricciones**: si `fuentes.permite_almacenar = false`, el `payload` de `registros_brutos` debe guardar solo lo permitido (p. ej. para Google Places, el `place_id`) y la observación se usa como verificación en vivo.
5. **RLS activado** en todas las tablas. El worker usa la `service_role` key; la web, usuarios autenticados con lectura. Se endurecerá en la fase de producto multi-usuario (actualmente fuera de alcance, ver D-03).

## 7. Pendiente para siguientes migraciones

- Cargar catálogos: CNAE (INE), municipios con código INE y, opcionalmente, límites municipales (IGN).
- Tabla de **personas con cargo** (administradores del BORME) y de **contactos personales**: ya no requieren análisis legal previo (ver D-10), quedan pendientes solo de diseño de esquema.
- Tabla de **caché de descargas web** (url, fecha, hash, ruta en Storage).
- Tabla de **costes** por llamada a API/LLM si `busquedas.coste_eur` se queda corto.
- Función SQL o job que recalcule `confianza_global` y `estado` a partir de `observaciones`.
