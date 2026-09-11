"""Evalúa la salida del pipeline de resolución de entidades contra el golden
set (skill `agente-busqueda-empresas`, `references/evaluacion.md`; doc 07 §6).

Estado: **esqueleto**, todavía no ejecutable de verdad — depende de dos cosas
que no existen aún en el proyecto:

1. `entidades.csv` con las ~200 filas verificadas de verdad (hoy solo tiene
   la cabecera y filas de ejemplo marcadas como ficticias — ver README.md).
2. Un `clusters.csv` real generado por el pipeline de resolución de
   entidades (`radar.resolucion`, todavía por construir) a partir de
   `registros_entrada.csv`.

Cuando ambos existan, este script:
- Compara los pares de registros que el pipeline fusionó contra los que
  realmente son la misma entidad (columna `entidad_id_real` de
  `registros_entrada.csv`, que se rellena al promover cada fila revisada
  desde `registros_entrada.csv` a `entidades.csv`).
- Calcula precisión y exhaustividad de fusión, fusiones erróneas,
  duplicados no detectados, precisión por campo y % de inactivas que se
  cuelan como activas.
- Guarda el resultado con fecha y commit en `historico.csv` para poder
  comparar contra la ejecución anterior (regla de oro: si baja la
  precisión de fusión, el cambio no entra aunque suba la cobertura).

No ejecutar contra datos ficticios y sacar conclusiones — solo sirve una
vez que `entidades.csv` tiene verificaciones reales.
"""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

RAIZ = Path(__file__).resolve().parent


def pares(filas: list[dict], columna: str) -> set[tuple[str, str]]:
    grupos: dict[str, list[str]] = {}
    for fila in filas:
        clave = fila.get(columna) or ""
        if not clave or clave in ("", "NINGUNA"):
            continue
        grupos.setdefault(clave, []).append(fila["id_fila"])
    return {tuple(sorted(p)) for idx in grupos.values() for p in combinations(idx, 2)}


def evaluar(registros_entrada: list[dict], clusters: dict[str, str]) -> dict:
    """`clusters`: id_fila -> cluster_id, salida del pipeline a evaluar."""
    for fila in registros_entrada:
        fila["cluster_id"] = clusters.get(fila["id_fila"], "")

    reales = pares(registros_entrada, "entidad_id_real")
    predichos = pares(registros_entrada, "cluster_id")
    verdaderos_positivos = len(reales & predichos)

    por_entidad_real: dict[str, set[str]] = {}
    for fila in registros_entrada:
        er = fila.get("entidad_id_real")
        if er and er != "NINGUNA":
            por_entidad_real.setdefault(er, set()).add(fila.get("cluster_id", ""))
    entidades_partidas = sum(1 for clusters_de_una in por_entidad_real.values() if len(clusters_de_una) > 1)

    return {
        "precision_fusion": verdaderos_positivos / len(predichos) if predichos else 1.0,
        "exhaustividad_fusion": verdaderos_positivos / len(reales) if reales else 1.0,
        "fusiones_erroneas": sorted(predichos - reales),
        "duplicados_no_detectados": sorted(reales - predichos),
        "entidades_partidas": entidades_partidas,
        "n_registros_evaluados": len(registros_entrada),
        "n_con_verdad_conocida": sum(
            1 for f in registros_entrada if f.get("entidad_id_real") not in (None, "", "NINGUNA")
        ),
    }


def cargar_csv(ruta: Path) -> list[dict]:
    with ruta.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--clusters",
        type=Path,
        help="CSV con columnas id_fila,cluster_id (salida del pipeline a evaluar)",
    )
    ap.add_argument("--commit", default="", help="Hash de commit para el histórico")
    args = ap.parse_args()

    ruta_entrada = RAIZ / "registros_entrada.csv"
    if not ruta_entrada.exists():
        raise SystemExit(
            f"No existe {ruta_entrada}. Genera candidatos primero con "
            "scripts/generar_candidatos_golden.py y promueve filas revisadas a entidades.csv."
        )
    if args.clusters is None or not args.clusters.exists():
        raise SystemExit(
            "Falta --clusters con la salida del pipeline de resolución de entidades "
            "(todavía no existe ese pipeline en el proyecto — ver docstring)."
        )

    registros = cargar_csv(ruta_entrada)
    filas_clusters = cargar_csv(args.clusters)
    clusters = {f["id_fila"]: f["cluster_id"] for f in filas_clusters}

    resultado = evaluar(registros, clusters)

    print(f"Registros evaluados: {resultado['n_registros_evaluados']}")
    print(f"Con entidad_id_real conocida: {resultado['n_con_verdad_conocida']}")
    print(f"Precisión de fusión: {resultado['precision_fusion']:.3f} (objetivo >= 0.995)")
    print(f"Exhaustividad de fusión: {resultado['exhaustividad_fusion']:.3f} (objetivo >= 0.95)")
    print(f"Fusiones erróneas: {len(resultado['fusiones_erroneas'])}")
    print(f"Duplicados no detectados: {len(resultado['duplicados_no_detectados'])}")
    print(f"Entidades partidas en varios clusters: {resultado['entidades_partidas']}")

    historico = RAIZ / "historico.csv"
    es_nuevo = not historico.exists()
    with historico.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if es_nuevo:
            writer.writerow(
                ["fecha", "commit", "precision_fusion", "exhaustividad_fusion", "fusiones_erroneas", "duplicados_no_detectados"]
            )
        writer.writerow(
            [
                datetime.now(UTC).isoformat(timespec="seconds"),
                args.commit,
                f"{resultado['precision_fusion']:.4f}",
                f"{resultado['exhaustividad_fusion']:.4f}",
                len(resultado["fusiones_erroneas"]),
                len(resultado["duplicados_no_detectados"]),
            ]
        )
    print(f"\nResultado añadido a {historico}")


if __name__ == "__main__":
    main()
