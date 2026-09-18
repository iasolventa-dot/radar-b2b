"""Clasifica `objeto_social` -> CNAE para empresas que todavía no tienen
`cnae_principal` (doc 05, prompt #5 de la skill agente-busqueda-empresas).
Pendiente desde la sesión de auditoría del 14-16/09 ("se empezó a
construir un clasificador... no confirmado si se terminó") -- no se
terminó, no existía ningún módulo `cnae*` en el repo hasta esta sesión.

Dos pasos, en este orden:
1. Si el objeto_social ya trae el código CNAE explícito en el texto (muy
   habitual en el BORME: "Actividad principal: 43.99 / ...", "CNAE 5611"),
   `radar.clasificacion.reglas` lo extrae y se usa tal cual, validado
   contra el catálogo -- sin gastar ni una llamada a LLM.
2. Si no, `radar.clasificacion.candidatos.buscar_candidatos` propone
   candidatos por similitud de texto (trigram) contra `cnae.descripcion`,
   y `radar.clasificacion.llm.clasificar` elige entre ellos -- nunca
   clasifica a ciegas por similitud sola, ni deja que el modelo invente un
   código fuera de esos candidatos.

Job periódico (mismo patrón que `arbitrar_duplicados.py`), no herramienta
del agente -- se ejecuta a mano o programado, normalmente después de
`ejecutar_borme.py`/`ejecutar_placsp.py` (que son quienes escriben
`objeto_social` hoy).

Uso (con el entorno virtual del worker activado):
    python scripts\\clasificar_cnae.py
"""

from __future__ import annotations

import psycopg

from radar.clasificacion.candidatos import buscar_candidatos, validar_codigo
from radar.clasificacion.llm import clasificar
from radar.clasificacion.reglas import extraer_codigos_explicitos
from radar.config import get_settings
from radar.orquestador import bd

FUENTE_INFERENCIA_LLM_ID = 11  # fuentes.codigo = 'inferencia_llm' (fiabilidad 0.20, doc 03b)

# Por debajo de esta confianza, la clasificación por LLM no se aplica --
# se deja la empresa sin cnae_principal en vez de escribir un dato dudoso
# (principio 5 del proyecto: no inventar). Provisional, como
# CONFIANZA_MINIMA_AUTOMATICA en radar.resolucion.arbitraje: se calibra
# con el golden set.
CONFIANZA_MINIMA_LLM = 0.6


def _ejecutar() -> None:
    settings = get_settings()
    if not settings.supabase_db_url:
        raise SystemExit("SUPABASE_DB_URL no está configurada — ver .env.example")

    contadores = {"explicito": 0, "llm": 0, "sin_clasificar": 0, "error": 0}
    with psycopg.connect(settings.supabase_db_url, autocommit=False) as conn:
        empresas = bd.empresas_con_objeto_social_sin_cnae(conn)
        print(f"{len(empresas)} empresa(s) con objeto_social pendientes de clasificar.")

        for e in empresas:
            empresa_id, version, texto = e["empresa_id"], e["cnae_version"], e["objeto_social"]
            try:
                extraidos = extraer_codigos_explicitos(texto)
                principal_valido = validar_codigo(extraidos.principal, version, conexion=conn) if extraidos.principal else None

                if principal_valido:
                    secundarios_validos = [
                        c for c in (validar_codigo(s, version, conexion=conn) for s in extraidos.secundarios) if c
                    ]
                    bd.actualizar_cnae_empresa(empresa_id, principal_valido, secundarios_validos, version, conn)
                    bd.insertar_observacion_cnae(
                        empresa_id, principal_valido, e["fuente_id"], 0.9,
                        "código CNAE explícito en el objeto_social", conn,
                    )
                    conn.commit()
                    contadores["explicito"] += 1
                    print(f"  [explicito] {empresa_id} -> {principal_valido}")
                    continue

                candidatos = buscar_candidatos(texto, version, conexion=conn)
                resultado = clasificar(texto, candidatos, version)
                if resultado.respuesta is None:
                    print(f"  [error] {empresa_id}: {resultado.error}")
                    contadores["error"] += 1
                    continue

                r = resultado.respuesta
                if r.cnae_principal and r.confianza >= CONFIANZA_MINIMA_LLM:
                    bd.actualizar_cnae_empresa(empresa_id, r.cnae_principal, r.cnaes_secundarios, version, conn)
                    bd.insertar_observacion_cnae(empresa_id, r.cnae_principal, FUENTE_INFERENCIA_LLM_ID, r.confianza, r.evidencia, conn)
                    conn.commit()
                    contadores["llm"] += 1
                    print(f"  [llm] {empresa_id} -> {r.cnae_principal} ({r.confianza:.2f}): {r.evidencia}")
                else:
                    conn.commit()  # nada que deshacer -- no se escribió cnae_principal
                    contadores["sin_clasificar"] += 1
                    print(f"  [sin_clasificar] {empresa_id}: confianza {r.confianza:.2f} -- {r.evidencia}")
            except Exception as exc:  # noqa: BLE001 — se informa y se sigue con la siguiente empresa
                conn.rollback()
                contadores["error"] += 1
                print(f"  [error] {empresa_id}: {exc}")

    print("\nClasificación CNAE:")
    for accion, n in contadores.items():
        print(f"  - {accion}: {n}")


if __name__ == "__main__":
    _ejecutar()
