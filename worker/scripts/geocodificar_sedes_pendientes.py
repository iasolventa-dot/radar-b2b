"""Geocodifica con CartoCiudad (IGN, gratis, sin clave) las sedes que ya
tienen domicilio real pero ningún `geom` -- normal en las que
`reprocesar_domicilios_borme.py` acaba de rellenar: ese script solo
reparsea texto y escribe dirección/CP/municipio, no llama a ninguna API
externa (separación deliberada del proyecto entre `fuentes/` que hablan
con el exterior y `orquestador/` que solo escribe BD).

También arregla, de paso, que `sedes.geocodificador`/`precision_geo`
estaban siempre a NULL incluso cuando la geocodificación sí funcionaba
(el pipeline en vivo, `radar.orquestador.procesar`, descartaba ese dato
del resultado -- ver commit "geocodificador/precision_geo nunca se
escribían").

`geocodificar()` es "mejor esfuerzo" (doc del módulo): nunca lanza, y no
lo intenta si no hay `direccion_original` con calle -- solo CP/municipio
daría un punto `"poblacion"` arbitrario, que se rechaza siempre. Pero
"portal"/"callejero" tampoco es garantía: confirmado en vivo que
CartoCiudad a veces resuelve una calle al municipio EQUIVOCADO sin que el
`type` lo delate (25 de 152 en el primer backfill real, 16%) -- se valida
cada resultado contra `bd.buscar_municipio_ine` (código INE determinista
a partir del NOMBRE del municipio, no de lo que diga el geocodificador)
antes de aceptarlo.

Uso (con el entorno virtual del worker activado):
    python scripts\\geocodificar_sedes_pendientes.py
"""

from __future__ import annotations

import re

import psycopg

from radar.config import get_settings
from radar.fuentes.base import CamposExtraidos
from radar.fuentes.cartociudad import geocodificar
from radar.orquestador import bd

# CartoCiudad falla a la primera pasada con la dirección "tal cual" del
# BORME casi siempre (confirmado en vivo: 19/450, 4%) porque el propio
# `direccion_original` repite el código postal como texto ("- CODIGO
# POSTAL 41701", "- CP 41219", o el CP suelto al final) además de traerlo
# ya por separado en `sedes.codigo_postal` -- ese ruido dentro de la calle
# confunde al geocodificador (probado con pares idénticos con/sin el
# sufijo: sin él, resuelve "portal" limpio; con él, sin resultado). Se
# quita solo eso, nunca el resto de la dirección (piso/puerta no se toca:
# quitarlo también ayuda a veces, pero no siempre, y no hay forma fiable
# de distinguir cuándo sin arriesgarse a comerse parte de la calle).
_RE_RUIDO_CP_ETIQUETADO = re.compile(
    r"\s*-?\s*(?:C\.?\s?P\.?:?|C[OÓ]DIGO\s+POSTAL)\s*:?\s*(?:\d{2}\.\d{3}|\d{5})\.?", re.IGNORECASE
)
_RE_RUIDO_CP_SUELTO_FINAL = re.compile(r"\s*-\s*(?:\d{2}\.\d{3}|\d{5})\s*$")


def _limpiar_para_geocodificar(direccion: str) -> str:
    limpia = _RE_RUIDO_CP_ETIQUETADO.sub("", direccion)
    limpia = _RE_RUIDO_CP_SUELTO_FINAL.sub("", limpia)
    return re.sub(r"\s+", " ", limpia).strip(" ,-")


def _ejecutar() -> None:
    settings = get_settings()
    if not settings.supabase_db_url:
        raise SystemExit("SUPABASE_DB_URL no está configurada — ver .env.example")

    contadores = {"geocodificada": 0, "sin_resultado_fiable": 0, "error": 0}
    with psycopg.connect(settings.supabase_db_url, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id, empresa_id, tipo, direccion_original, municipio_nombre, provincia "
                "from sedes where geom is null and direccion_original is not null and activa"
            )
            filas = cur.fetchall()
        print(f"{len(filas)} sede(s) con domicilio y sin coordenadas.")

        # `upsert_sede` pide la `FuenteInfo` de quien originó la sede -- la
        # propia fila no guarda de qué fuente vino. Todas las sedes con
        # domicilio de esta sesión vienen de BORME; como la fila ya existe
        # (este script solo geocodifica, nunca crea sedes nuevas), esto
        # solo se usaría para `fiabilidad_base` si por lo que sea hiciera
        # falta un insert, cosa que no debería pasar aquí.
        fuente_borme = bd.obtener_fuente("borme", conn)

        for sede_id, empresa_id, tipo, direccion, municipio, provincia in filas:
            try:
                direccion_limpia = _limpiar_para_geocodificar(direccion)
                resultado = geocodificar(direccion_limpia, municipio, provincia)
                if resultado is None and direccion_limpia != direccion:
                    resultado = geocodificar(direccion, municipio, provincia)  # por si la limpieza se comió algo útil

                if resultado is not None and municipio:
                    esperado = bd.buscar_municipio_ine(municipio, provincia, conn)
                    if esperado and resultado.municipio_ine and esperado != resultado.municipio_ine:
                        print(f"  [municipio_equivocado] sede {sede_id}: {direccion!r} ({municipio}) -> INE {resultado.municipio_ine}, esperado {esperado}")
                        resultado = None

                if resultado is None:
                    contadores["sin_resultado_fiable"] += 1
                    print(f"  [sin_resultado] sede {sede_id}: {direccion!r} ({municipio})")
                    continue

                campos = CamposExtraidos(
                    domicilio=direccion, municipio=municipio, provincia=provincia,
                    lat=resultado.lat, lon=resultado.lon,
                )
                bd.upsert_sede(
                    str(empresa_id), campos, {}, fuente_borme, conn, tipo=tipo,
                    geocodificador="cartociudad", precision_geo=resultado.tipo, municipio_ine=resultado.municipio_ine,
                )
                conn.commit()
                contadores["geocodificada"] += 1
                print(f"  [geocodificada] sede {sede_id}: {direccion!r} -> ({resultado.lat:.5f}, {resultado.lon:.5f}) [{resultado.tipo}]")
            except Exception as exc:  # noqa: BLE001 — se informa y se sigue con la siguiente sede
                conn.rollback()
                contadores["error"] += 1
                print(f"  [error] sede {sede_id}: {exc}")

    print("\nGeocodificación de sedes pendientes:")
    for k, v in contadores.items():
        print(f"  - {k}: {v}")


if __name__ == "__main__":
    _ejecutar()
