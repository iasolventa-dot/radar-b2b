"""Procesa la cola de `candidatos_duplicado` pendientes con el arbitraje LLM
(`radar.resolucion.arbitraje`, doc 05 §2.5): por cada candidato, junta el
contexto de las dos empresas (nombre, NIF, sedes, administradores, objeto
social, fuentes) y le pregunta al LLM si son la misma empresa, dos empresas
distintas, o si no hay evidencia suficiente para decidir.

Con confianza alta (`CONFIANZA_MINIMA_AUTOMATICA`):
  - "misma"    -> fusiona con `fusionar_empresas` (la empresa_b desaparece
                  de los resultados, toda su evidencia pasa a empresa_a).
  - "distinta" -> marca el candidato como `rechazado` (quedan las dos).
Con confianza baja, o decisión "incierto": el candidato se queda
`pendiente` -- lo revisa una persona en el panel (`/duplicados`). El LLM
juzga, el código decide si esa opinión es lo bastante segura para actuar
solo (principio 4 y 5 del proyecto): nunca fusiona a ciegas.

Job periódico (mismo patrón que `ejecutar_placsp.py`/`cargar_dirce.py`), no
herramienta del agente -- se ejecuta a mano o programado, normalmente justo
después de `ejecutar_borme.py`/`ejecutar_placsp.py`.

Uso (con el entorno virtual del worker activado):
    python scripts\\arbitrar_duplicados.py
"""

from __future__ import annotations

import psycopg

from radar.config import get_settings
from radar.orquestador import bd
from radar.resolucion.arbitraje import CONFIANZA_MINIMA_AUTOMATICA, arbitrar


def _ejecutar() -> None:
    settings = get_settings()
    if not settings.supabase_db_url:
        raise SystemExit("SUPABASE_DB_URL no está configurada — ver .env.example")

    contadores = {"fusionado": 0, "descartado": 0, "pendiente": 0, "error": 0}
    with psycopg.connect(settings.supabase_db_url, autocommit=False) as conn:
        candidatos = bd.candidatos_duplicado_pendientes(conn)
        print(f"{len(candidatos)} candidato(s) pendiente(s) de arbitrar.")

        for c in candidatos:
            try:
                empresa_a = bd.cargar_contexto_arbitraje(c["empresa_a"], conn)
                empresa_b = bd.cargar_contexto_arbitraje(c["empresa_b"], conn)
            except ValueError as exc:
                # una de las dos ya se fusionó/borró en una pasada anterior de este mismo lote
                print(f"  [error] candidato {c['id']}: {exc}")
                contadores["error"] += 1
                continue

            resultado = arbitrar(c["puntuacion"], c["senales"], empresa_a, empresa_b)
            if resultado.respuesta is None:
                print(f"  [error] {empresa_a['razon_social']!r} vs {empresa_b['razon_social']!r}: {resultado.error}")
                contadores["error"] += 1
                continue

            r = resultado.respuesta
            try:
                bd.guardar_opinion_llm_candidato(c["id"], r.model_dump(), conn)
                if r.decision == "misma" and r.confianza >= CONFIANZA_MINIMA_AUTOMATICA:
                    bd.fusionar_empresas_rpc(
                        origen=c["empresa_b"], destino=c["empresa_a"],
                        motivo=f"arbitraje LLM ({r.confianza:.2f}): {r.motivo}", decidido_por="arbitraje_llm",
                        puntuacion=c["puntuacion"], candidato_id=c["id"], conn=conn,
                    )
                    conn.commit()
                    print(f"  [fusionado] {empresa_a['razon_social']!r} = {empresa_b['razon_social']!r} ({r.confianza:.2f}): {r.motivo}")
                    contadores["fusionado"] += 1
                elif r.decision == "distinta" and r.confianza >= CONFIANZA_MINIMA_AUTOMATICA:
                    bd.descartar_candidato_duplicado(c["id"], "arbitraje_llm", conn)
                    conn.commit()
                    print(f"  [descartado] {empresa_a['razon_social']!r} != {empresa_b['razon_social']!r} ({r.confianza:.2f}): {r.motivo}")
                    contadores["descartado"] += 1
                else:
                    conn.commit()  # guarda igualmente opinion_llm, para que el panel la muestre como ayuda a la revisión humana
                    print(
                        f"  [pendiente] {empresa_a['razon_social']!r} vs {empresa_b['razon_social']!r}: "
                        f"{r.decision} ({r.confianza:.2f}) -- queda para revisión humana"
                    )
                    contadores["pendiente"] += 1
            except Exception as exc:  # noqa: BLE001 — se informa y se sigue con el siguiente candidato
                conn.rollback()
                contadores["error"] += 1
                print(f"  [error] candidato {c['id']}: {exc}")

    print("\nArbitraje de duplicados:")
    for accion, n in contadores.items():
        print(f"  - {accion}: {n}")


if __name__ == "__main__":
    _ejecutar()
