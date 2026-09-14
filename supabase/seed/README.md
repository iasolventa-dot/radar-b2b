# Catálogos semilla

Datos de referencia que se cargan una vez y cambian poco (no son parte de la migración de esquema porque son datos, no estructura).

## Ficheros

Se generan desde los ficheros oficiales del INE con `worker/scripts/generar_catalogos.py` y se cargan en Supabase con `worker/scripts/cargar_catalogos.py`. **No se editan a mano**: si hay que cambiarlos, se regeneran.

- **`cnae.csv`** — estructura de CNAE-2009 (1.010 rúbricas) y CNAE-2025 (1.060), con jerarquía sección/división/grupo/clase. Las dos versiones conviven porque `cnae` tiene clave primaria `(codigo, version)` desde la migración `202609140001` (D-18): los códigos se solapan entre versiones con contenidos distintos.
- **`cnae_correspondencias.csv`** — 3.330 correspondencias teóricas del INE entre ambas versiones, en los dos sentidos. **No es una relación 1:1**: solo 425 de las 629 clases de CNAE-2009 tienen destino único. Caso relevante para el sector piloto: CNAE-2009 `4110` (promoción inmobiliaria) pasa a CNAE-2025 `6812`, fuera de la división 41.
- **`municipios.csv`** — 8.132 municipios con código INE, provincia y CCAA (relación a 1 de enero de 2026). El nombre lleva el artículo pospuesto con coma, tal como lo publica el INE (`Palacios y Villafranca, Los`).

La tabla `fuentes` se siembra directamente en la migración inicial (`202609100001_esquema_inicial.sql`, sección 12) — no hace falta un seed aparte para ella.

## Uso

```powershell
# 1. Aplicar la migración que prepara las tablas
python scripts\aplicar_migracion.py 202609140001

# 2. (Opcional) Regenerar los CSV desde el INE
python scripts\generar_catalogos.py

# 3. Cargar en Supabase
python scripts\cargar_catalogos.py
```

Ambos scripts se ejecutan desde `worker/` con el entorno virtual activado. `generar_catalogos.py` necesita `openpyxl`, que está en las dependencias `dev` (`pip install -e ".[dev]"`).

## Pendiente

- **`sectores.csv`** — taxonomía comercial propia (p. ej. "Reformas integrales") mapeada a códigos CNAE y palabras clave. No se puede descargar de ninguna parte: es una decisión de producto, hay que escribirla a mano.
- **Límites municipales del IGN** para la columna `geom` de `municipios`, si en algún momento hacen falta filtros por polígono.
