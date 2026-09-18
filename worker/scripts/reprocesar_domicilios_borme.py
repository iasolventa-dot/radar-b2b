"""Reprocesa `registros_brutos` de BORME ya guardados con el fix de
domicilio (`radar.fuentes.borme.parsear_datos_acto`, 2026-09-18):
`acto_a_registro_bruto` dejaba `domicilio=None` siempre, sin ni intentar
leer el campo "Domicilio:" (constitución) / "Cambio de domicilio social."
(cambio de domicilio) del texto, pese a que el BORME publica la dirección
completa en el 100% de las constituciones (confirmado corriendo BORME 30
días sobre Sevilla: 82% de las empresas sin ninguna fila en `sedes`).

Sin este script, el fix solo se aplicaría a actos NUEVOS que se descubran
a partir de ahora -- los ya capturados se quedarían sin sede para siempre
aunque el texto crudo (`registros_brutos.payload.texto`) sí tenga la
dirección completa. No vuelve a llamar a la API del BOE: reparsea el texto
que ya está en la base de datos.

Uso (con el entorno virtual del worker activado):
    python scripts\\reprocesar_domicilios_borme.py
"""

from __future__ import annotations

import psycopg

from radar.config import get_settings
from radar.fuentes.base import CamposExtraidos
from radar.fuentes.borme import parsear_datos_acto
from radar.orquestador import bd


def _ejecutar() -> None:
    settings = get_settings()
    if not settings.supabase_db_url:
        raise SystemExit("SUPABASE_DB_URL no está configurada — ver .env.example")

    contadores = {"actualizada": 0, "sin_domicilio_en_texto": 0, "error": 0}
    with psycopg.connect(settings.supabase_db_url, autocommit=False) as conn:
        fuente = bd.obtener_fuente("borme", conn)
        with conn.cursor() as cur:
            cur.execute(
                "select rb.id, rb.empresa_id, rb.payload->>'texto' "
                "from registros_brutos rb join fuentes f on f.id = rb.fuente_id "
                "where f.codigo = 'borme' and rb.empresa_id is not null"
            )
            filas = cur.fetchall()
        print(f"{len(filas)} registro(s) de BORME con empresa asociada a reprocesar.")

        for registro_id, empresa_id, texto in filas:
            datos = parsear_datos_acto(texto or "")
            if not datos["domicilio"]:
                contadores["sin_domicilio_en_texto"] += 1
                continue
            try:
                campos = CamposExtraidos(
                    domicilio=datos["domicilio"],
                    codigo_postal=datos["codigo_postal"],
                    municipio=datos["municipio"],
                    provincia="Sevilla",
                )
                bd.upsert_sede(str(empresa_id), campos, {"cp": datos["codigo_postal"]}, fuente, conn)
                conn.commit()
                contadores["actualizada"] += 1
                print(f"  [actualizada] {empresa_id} -> {datos['domicilio']} ({datos['codigo_postal']}, {datos['municipio']})")
            except Exception as exc:  # noqa: BLE001 — se informa y se sigue con el siguiente registro
                conn.rollback()
                contadores["error"] += 1
                print(f"  [error] registro_bruto {registro_id} (empresa {empresa_id}): {exc}")

    print("\nReprocesado de domicilios BORME:")
    for k, v in contadores.items():
        print(f"  - {k}: {v}")


if __name__ == "__main__":
    _ejecutar()
