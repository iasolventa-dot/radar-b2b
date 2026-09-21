"""Búsqueda en profundidad de UNA empresa concreta (petición del usuario,
roadmap 2026-09-21): cuando la resolución automática no puede decidir si
dos registros son la misma empresa (queda en `candidatos_duplicado`), o
cuando una empresa tiene pocos datos, esto lanza un puñado de búsquedas
web MUY dirigidas -- con lo que ya se sabe de ella: razón social, NIF,
domicilio -- en vez del descubrimiento abierto de `radar.agente.planificador`.

No hay ninguna ambigüedad que interpretar (a diferencia de una búsqueda
normal): las consultas se construyen de forma determinista a partir de
los datos ya guardados, así que esto NO pasa por el LLM planificador --
solo reutiliza `radar.agente.herramientas.buscar_web`, que ya hace todo el
trabajo real (buscar, leer cada URL de verdad, resolver contra la empresa
existente vía NIF/nombre+ubicación -- `radar.orquestador.procesar_registro`
-- y guardar observaciones nuevas sin sobreescribir las anteriores).

El resultado puede, según a qué empresa case cada URL encontrada:
- reforzar ESTA MISMA empresa (`vinculado` a `empresa_id`) -- el caso
  normal, más observaciones para los mismos campos,
- vincularse a OTRA empresa -- señal de un posible homónimo/franquicia,
- o crear un candidato nuevo / mandarlo a `candidatos_duplicado` -- igual
  que cualquier otro resultado de `buscar_web`. No hay lógica especial
  aquí para forzar que todo case con `empresa_id`: eso sería fingir una
  certeza que la propia evidencia no da (principio 5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import psycopg

from radar.agente.herramientas import buscar_web

PRESUPUESTO_POR_DEFECTO_EUR = 0.30


@dataclass
class DatosEmpresaProfundizar:
    id: str
    razon_social: str
    nif: str | None
    municipio: str | None
    provincia: str | None
    dominio_web: str | None


def cargar_datos_empresa(empresa_id: str, conn: psycopg.Connection) -> DatosEmpresaProfundizar | None:
    with conn.cursor() as cur:
        cur.execute("select e.id, e.razon_social, e.nif, e.dominio_web from empresas e where e.id = %s", (empresa_id,))
        fila = cur.fetchone()
        if fila is None:
            return None
        # domicilio_social si existe, si no cualquier sede activa -- misma
        # prioridad que la página de detalle
        # (web/src/app/(app)/empresas/[id]/page.tsx) y mismos valores reales
        # de tipo_sede (radar.orquestador.bd.upsert_sede).
        cur.execute(
            "select s.municipio_nombre, s.provincia from sedes s "
            "where s.empresa_id = %s and s.activa "
            "order by (s.tipo = 'domicilio_social') desc limit 1",
            (empresa_id,),
        )
        sede = cur.fetchone()
    return DatosEmpresaProfundizar(
        id=str(fila[0]),
        razon_social=fila[1],
        nif=fila[2],
        dominio_web=fila[3],
        municipio=sede[0] if sede else None,
        provincia=sede[1] if sede else None,
    )


def construir_consultas(datos: DatosEmpresaProfundizar) -> list[str]:
    """Patrones de consulta del doc 04 §5, dirigidos a UNA empresa conocida
    en vez de a un sector/zona entero: nombre entre comillas + NIF entre
    comillas (si se conoce) es la consulta más discriminante posible que
    existe -- casi imposible que devuelva la página de otra empresa. Sin
    NIF (el caso normal para lo que viene del BORME, que nunca lo publica),
    se recurre a nombre + municipio, que es más ambiguo pero sigue siendo
    mucho más dirigido que una búsqueda de descubrimiento por sector."""
    consultas: list[str] = []
    if datos.nif:
        consultas.append(f'"{datos.razon_social}" "{datos.nif}"')
    if datos.municipio:
        consultas.append(f'"{datos.razon_social}" "{datos.municipio}" aviso legal')
    else:
        consultas.append(f'"{datos.razon_social}" aviso legal contacto')
    if datos.dominio_web:
        consultas.append(f"site:{datos.dominio_web} contacto")
    return consultas


@dataclass
class ResultadoProfundizar:
    empresa_id: str
    consultas: list[str]
    resultado_buscar_web: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


async def profundizar_empresa(
    empresa_id: str,
    conn: psycopg.Connection,
    cliente_http: httpx.AsyncClient,
    cliente_llm: Any | None,
    *,
    max_coste_eur: float = PRESUPUESTO_POR_DEFECTO_EUR,
) -> ResultadoProfundizar:
    datos = cargar_datos_empresa(empresa_id, conn)
    if datos is None:
        return ResultadoProfundizar(empresa_id=empresa_id, consultas=[], error="empresa no encontrada")

    consultas = construir_consultas(datos)
    resultado = await buscar_web(
        conn, cliente_http, cliente_llm,
        consultas=consultas, max_resultados_por_consulta=3, max_coste_eur=max_coste_eur,
    )
    return ResultadoProfundizar(empresa_id=empresa_id, consultas=consultas, resultado_buscar_web=resultado)
