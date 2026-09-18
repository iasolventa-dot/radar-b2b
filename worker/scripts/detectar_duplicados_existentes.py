"""Recorre las empresas ya guardadas y vuelve a aplicar bloqueo + puntuación
(`radar.resolucion.blocking`/`scoring`, doc 05 §2.1-2.4) para encontrar
pares que deberían haber quedado en `candidatos_duplicado` pero no
llegaron -- por ejemplo, pares guardados antes de un cambio de calibración
de `scoring.py` (commit "nombre casi idéntico sin ubicación", 2026-09-18:
antes de esa regla, un nombre exacto sin NIF ni domicilio en ninguno de los
dos lados nunca llegaba a `UMBRAL_REVISION` y el duplicado se perdía sin
dejar rastro).

No fusiona nada por sí mismo: solo inserta en `candidatos_duplicado`
(`bd.insertar_candidato_duplicado`, que ya ignora pares repetidos con su
propio `on conflict do nothing`) -- decidir si de verdad son la misma
empresa es cosa de `scripts/arbitrar_duplicados.py` (LLM) o de una persona
en el panel (`/duplicados`). Pensado como paso puntual (o periódico tras
recalibrar el scoring), no parte del flujo normal de cada `RegistroBruto`
-- eso ya lo hace `radar.orquestador.procesar_registro` en el momento.

Uso (con el entorno virtual del worker activado):
    python scripts\\detectar_duplicados_existentes.py
"""

from __future__ import annotations

import psycopg

from radar.config import get_settings
from radar.orquestador import bd
from radar.resolucion.blocking import buscar_candidatos
from radar.resolucion.blocking import telefonos_compartidos as cargar_telefonos_compartidos
from radar.resolucion.scoring import comparar


def _ejecutar() -> None:
    settings = get_settings()
    if not settings.supabase_db_url:
        raise SystemExit("SUPABASE_DB_URL no está configurada — ver .env.example")

    nuevos = 0
    revisados = 0
    with psycopg.connect(settings.supabase_db_url, autocommit=False) as conn:
        compartidos = cargar_telefonos_compartidos(conexion=conn)
        with conn.cursor() as cur:
            cur.execute("select id, razon_social from empresas where fusionada_en is null order by creado_en")
            empresas = cur.fetchall()
        print(f"{len(empresas)} empresas activas a revisar.")

        for empresa_id, razon_social in empresas:
            if not razon_social:
                continue
            revisados += 1
            registro = bd.cargar_registro_empresa_normalizado(str(empresa_id), conn)
            candidatos = buscar_candidatos(razon_social, registro.get("lon"), registro.get("lat"), conexion=conn)
            for c in candidatos:
                if c.empresa_id == str(empresa_id):
                    continue
                otro = bd.cargar_registro_empresa_normalizado(c.empresa_id, conn)
                resultado = comparar(registro, otro, compartidos)
                if resultado["decision"] == "revision":
                    bd.insertar_candidato_duplicado(str(empresa_id), c.empresa_id, resultado, conn)
                    conn.commit()
                    nuevos += 1
                    print(f"  [candidato] {razon_social!r} ~ {c.razon_social!r} (puntuación {resultado['puntuacion']}, {resultado['regla']})")

    print(f"\n{revisados} empresas revisadas -> {nuevos} par(es) insertado(s) en candidatos_duplicado (los ya existentes se ignoran).")


if __name__ == "__main__":
    _ejecutar()
