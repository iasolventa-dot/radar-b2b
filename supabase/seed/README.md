# Catálogos semilla

Datos de referencia que se cargan una vez y cambian poco, pensados para `supabase db seed` o para un script de carga puntual (no son parte de la migración de esquema porque son datos, no estructura).

Pendiente — Fase 1 (doc 03 §7):

- **`cnae.csv`** — catálogo CNAE-2025 (D-09) con jerarquía (sección/división/grupo/clase) y tabla de correspondencias a CNAE-2009, descargado del INE.
- **`municipios.csv`** — municipios con código INE, provincia y CCAA (y opcionalmente límites municipales del IGN para la columna `geom`).
- **`sectores.csv`** — taxonomía comercial propia (p. ej. "Reformas integrales") mapeada a códigos CNAE y palabras clave.

La tabla `fuentes` ya se siembra directamente en la migración inicial (`supabase/migrations/202609100001_esquema_inicial.sql`, sección 12) — no hace falta un seed aparte para ella.
