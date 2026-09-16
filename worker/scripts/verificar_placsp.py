"""Verificación manual de ConectorPLACSP contra un ZIP real ya descargado
(no vuelve a descargarlo -- lee el fichero local directamente). Pensado
para ejecutarse una vez, a mano, para confirmar que el conector funciona
contra un fichero de verdad antes de usarlo en producción -- ver el
docstring de radar.fuentes.placsp sobre por qué esto no se pudo verificar
desde el entorno de desarrollo.

Uso (con el entorno virtual del worker activado):
    python scripts\\verificar_placsp.py C:\\ruta\\a\\placsp_202508.zip
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radar.fuentes.placsp import (
    PREFIJOS_CPV_CONSTRUCCION,
    _entradas_de_zip,
    es_cpv_relevante,
    parsear_entrada,
    provincia_de_nuts,
)


def main() -> int:
    if len(sys.argv) != 2:
        sys.exit("Uso: python scripts\\verificar_placsp.py <ruta al zip>")
    ruta = Path(sys.argv[1])
    if not ruta.exists():
        sys.exit(f"No existe: {ruta}")

    print(f"Leyendo {ruta} ({ruta.stat().st_size:,} bytes)...")
    contenido = ruta.read_bytes()

    print("Recorriendo las <entry> del zip (puede tardar uno o dos minutos)...")
    n_entries = 0
    n_deleted_o_sin_contrato = 0
    contratos_totales: list = []
    provincias: Counter[str] = Counter()
    cpv_construccion = 0

    for entry in _entradas_de_zip(contenido):
        n_entries += 1
        contratos = parsear_entrada(entry)
        if not contratos:
            n_deleted_o_sin_contrato += 1
            continue
        for c in contratos:
            contratos_totales.append(c)
            prov = provincia_de_nuts(c.nuts)
            if prov:
                provincias[prov] += 1
            if es_cpv_relevante(c.cpv, PREFIJOS_CPV_CONSTRUCCION):
                cpv_construccion += 1

    print()
    print(f"<entry> totales en el zip:                 {n_entries:,}")
    print(f"  sin ningún lote con NIF+nombre válidos:   {n_deleted_o_sin_contrato:,}")
    print(f"  contratos adjudicados extraídos:          {len(contratos_totales):,}")
    print(f"  de los cuales, CPV de construcción (45):  {cpv_construccion:,}")
    print()
    print("Top 10 provincias por nº de contratos:")
    for prov, n in provincias.most_common(10):
        print(f"  {prov}: {n}")

    print()
    print("Muestra de 3 contratos de construcción reales, si hay alguno:")
    construccion = [c for c in contratos_totales if es_cpv_relevante(c.cpv, PREFIJOS_CPV_CONSTRUCCION)]
    for c in construccion[:3]:
        print(f"  {c.adjudicatario_nombre} (NIF {c.adjudicatario_nif}) -- {c.importe_adjudicado} EUR"
              f" -- provincia: {provincia_de_nuts(c.nuts)} -- {c.titulo[:80]}...")

    if not construccion:
        print("  (ninguno en este mes/fichero -- no es necesariamente un fallo,"
              " puede que ese mes no haya adjudicaciones de construcción con NIF real)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
