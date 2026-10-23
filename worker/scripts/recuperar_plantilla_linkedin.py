"""Recupera la plantilla de las empresas ya leídas en LinkedIn (2026-10-23).

El conector de LinkedIn recibía el tramo de plantilla («11-50 employees») pero
lo dejaba en `campos.extra.tamano` del registro bruto, sin observación ni
efecto. Esto lo convierte en observación «empleados» (misma fuente, misma URL,
misma fecha de captura) y consolida `empresas.empleados_min/max`. Idempotente:
no duplica observaciones ya creadas.

    python scripts\\recuperar_plantilla_linkedin.py
"""

from __future__ import annotations

import psycopg

import radar  # noqa: F401 -- truststore (certificados de Windows)
from radar.config import get_settings
from radar.orquestador.procesar import _consolidar_plantilla

_SQL = """
select rb.id, rb.empresa_id::text, rb.fuente_id, rb.campos->'extra'->>'tamano', rb.url, rb.capturado_en, f.fiabilidad_base
from registros_brutos rb join fuentes f on f.id = rb.fuente_id
join empresas e on e.id = rb.empresa_id
where f.codigo = 'linkedin' and rb.campos->'extra'->>'tamano' is not null and e.fusionada_en is null
  and not exists (select 1 from observaciones o where o.registro_bruto_id = rb.id and o.campo = 'empleados')
"""


def main() -> None:
    with psycopg.connect(get_settings().supabase_db_url) as conn:
        filas = conn.execute(_SQL).fetchall()
        empresas = set()
        for rb_id, empresa_id, fuente_id, tamano, url, capturado, fiabilidad in filas:
            conn.execute(
                "insert into observaciones (empresa_id, registro_bruto_id, fuente_id, campo, valor_original, valor_norm, "
                "url_evidencia, observado_en, confianza_fuente) values (%s, %s, %s, 'empleados', %s, %s, %s, %s, %s)",
                (empresa_id, rb_id, fuente_id, tamano, tamano, url, capturado, fiabilidad),
            )
            empresas.add(empresa_id)
        for empresa_id in empresas:
            _consolidar_plantilla(empresa_id, conn)
        conn.commit()
        print(f"{len(filas)} observaciones de plantilla creadas en {len(empresas)} empresas")


if __name__ == "__main__":
    main()
