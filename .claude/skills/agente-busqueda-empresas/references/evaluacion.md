# Evaluación con golden set

Sin golden set no se puede afirmar que la base está "bien contrastada". Todo cambio de reglas, prompts o fuentes se mide aquí antes de aceptarse.

## 1. Estructura

```
worker/tests/golden/
├── README.md                 # zona, sector, fecha, criterios de verificación, quién verificó
├── entidades.csv             # la verdad: una fila por entidad real
├── registros_entrada.csv     # registros "sucios" de varias fuentes que el pipeline debe resolver
└── evaluar.py                # calcula las métricas
```

### `entidades.csv` (verdad verificada a mano)
| columna | ejemplo | notas |
|---|---|---|
| `entidad_id` | G001 | id propio del golden set |
| `nif` | B41123456 | verificado en 2 fuentes |
| `razon_social` | CONSTRUCCIONES PEREZ MARTIN SL | |
| `nombre_comercial` | Pérez Obras | |
| `estado` | activa / disuelta / cerrada | |
| `sede_cp`, `sede_municipio` | 41011, Sevilla | sede operativa |
| `telefono_ok` | +34955123456 | confirmado llamando (muestra) |
| `web` | perezobras.es | |
| `caso_dificil` | homonimo / franquicia / agencia_web / traslado / … | vacío si es normal |
| `verificado_por`, `verificado_en` | JM, 2026-09-20 | |

### `registros_entrada.csv`
Registros tal como llegan de las fuentes (incluidos duplicados, erratas, datos viejos), con la columna `entidad_id_real` que indica a qué entidad pertenece cada uno (o `NINGUNA` si es basura).

## 2. Métricas

**Resolución de entidades** (sobre pares de registros de entrada):
- *Precisión de fusión* = pares fusionados que realmente son la misma entidad / pares fusionados. Objetivo ≥ 99,5 %.
- *Exhaustividad de fusión* = pares de la misma entidad que se fusionaron / pares de la misma entidad. Objetivo ≥ 95 %.
- *Fusiones erróneas* (falsos positivos) listadas una a una: son el error más grave.
- *Duplicados residuales* = entidades reales que acaban en más de un cluster.

**Precisión por campo** (sobre el registro oro resultante vs. `entidades.csv`): NIF, razón social, estado, CP de sede, teléfono, web.

**Estado**: % de entidades disueltas/cerradas que el pipeline entrega como activas (objetivo ≤ 2 %).

**Cobertura** (modo descubrimiento desde cero): % de entidades del golden set que el pipeline encuentra.

**Coste**: total y por entidad verificada.

## 3. Esqueleto de `evaluar.py`

```python
"""Evalúa la salida del pipeline contra el golden set.
Entrada: registros_entrada.csv (con entidad_id_real) + clusters.csv (salida del pipeline con cluster_id)."""
from itertools import combinations
import pandas as pd

def pares(df, col):
    grupos = df.groupby(col).groups
    return {tuple(sorted(p)) for idx in grupos.values() for p in combinations(idx, 2)}

def evaluar(entrada: pd.DataFrame, clusters: pd.DataFrame) -> dict:
    df = entrada.merge(clusters[["id_fila", "cluster_id"]], on="id_fila")
    df = df[df.entidad_id_real != "NINGUNA"].set_index("id_fila")
    reales, predichos = pares(df, "entidad_id_real"), pares(df, "cluster_id")
    vp = len(reales & predichos)
    return {
        "precision_fusion": vp / len(predichos) if predichos else 1.0,
        "exhaustividad_fusion": vp / len(reales) if reales else 1.0,
        "fusiones_erroneas": sorted(predichos - reales),
        "duplicados_no_detectados": sorted(reales - predichos),
        "entidades_partidas": int((df.groupby("entidad_id_real").cluster_id.nunique() > 1).sum()),
    }
```

Con la skill `verificacion-empresas-es` se genera `clusters.csv`:
`python procesar_empresas.py deduplicar registros_entrada.csv -d salida/`

## 4. Proceso

1. Ejecutar `evaluar.py` y guardar el resultado con la fecha y el commit en `worker/tests/golden/historico.csv`.
2. Comparar con la ejecución anterior. **Si baja la precisión de fusión o sube el % de inactivas entregadas, el cambio no entra**, aunque suba la cobertura.
3. Revisar a mano cada fusión errónea nueva y convertirla en test de regresión en `test_lib_empresas.py`.
4. Ampliar el golden set cuando se añada un sector o zona nuevos (mínimo 100 entidades por combinación relevante).
5. Re-verificar el golden set cada 6 meses (las empresas cambian).
