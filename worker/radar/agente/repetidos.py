"""Resultados repetidos dentro de una búsqueda (2026-11-12).

La resolución de entidades une registros de distintas fuentes cuando hay señal
suficiente (CIF, web + nombre...), pero a veces la misma empresa queda en dos
fichas: Maps y la web propia con nombres distintos, Places y Google, una
sociedad del BORME y su nombre comercial... y la búsqueda la muestra dos veces.

Esta fase agrupa los resultados de UNA búsqueda que son claramente la misma
empresa y deja solo la ficha más completa:
- mismo CIF;
- misma web propia (dominio que no es de una plataforma);
- mismo teléfono Y nombre parecido (un teléfono compartido con otro nombre
  puede ser una gestoría o una centralita: eso no basta).

Las demás pasan a «descartado» en esa búsqueda con el motivo («Repetida de
X: misma web»), recuperables en la Cola de revisión. No se fusionan ni se
borran fichas: unir empresas en la base de datos es una decisión con más
consecuencias (principio 3) y sigue en manos de «Datos sin contrastar».
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import psycopg

from radar.agente.completar_contacto import coincide
from radar.normalizacion.dominio import es_dominio_plataforma


@dataclass
class Ficha:
    empresa_id: str
    nombre: str
    nif: str | None = None
    dominio: str | None = None
    telefonos: list[str] = field(default_factory=list)


def _digitos(t: str) -> str:
    return "".join(ch for ch in t if ch.isdigit())[-9:]


def agrupar_repetidas(fichas: list[Ficha]) -> list[tuple[Ficha, list[tuple[Ficha, str]]]]:
    """Grupos de la misma empresa: (la que se queda, [(repetida, motivo)]).
    `fichas` viene ordenada de más a menos completa: la primera de cada grupo
    es la que se queda."""
    padre = list(range(len(fichas)))
    motivo: dict[int, str] = {}

    def raiz(i: int) -> int:
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    def unir(i: int, j: int, por: str) -> None:
        a, b = raiz(i), raiz(j)
        if a == b:
            return
        alta, baja = (a, b) if a < b else (b, a)  # se queda la más completa (índice menor)
        padre[baja] = alta
        motivo.setdefault(baja, por)

    por_nif: dict[str, int] = {}
    por_dominio: dict[str, int] = {}
    por_telefono: dict[str, list[int]] = {}
    for i, f in enumerate(fichas):
        if f.nif:
            if f.nif in por_nif:
                unir(por_nif[f.nif], i, "mismo CIF")
            else:
                por_nif[f.nif] = i
        if f.dominio and not es_dominio_plataforma(f.dominio):
            if f.dominio in por_dominio:
                unir(por_dominio[f.dominio], i, "misma web")
            else:
                por_dominio[f.dominio] = i
        for t in {_digitos(t) for t in f.telefonos if len(_digitos(t)) == 9}:
            for j in por_telefono.get(t, []):
                # Mismo teléfono solo cuenta con nombre parecido; y nunca une
                # dos fichas con CIF distinto (son sociedades distintas).
                if coincide(fichas[j].nombre, f.nombre) and not (f.nif and fichas[j].nif and f.nif != fichas[j].nif):
                    unir(j, i, "mismo teléfono y nombre parecido")
            por_telefono.setdefault(t, []).append(i)

    grupos: dict[int, list[tuple[Ficha, str]]] = {}
    for i in range(len(fichas)):
        r = raiz(i)
        if r != i:
            grupos.setdefault(r, []).append((fichas[i], motivo.get(i, "misma empresa")))
    return [(fichas[r], repetidas) for r, repetidas in sorted(grupos.items())]


_SQL = """
select r.empresa_id::text, coalesce(r.razon_social, r.nombre_comercial, ''), r.nif, r.dominio_web,
  coalesce((select array_agg(c.valor) from canales_contacto c
            where c.empresa_id = r.empresa_id and c.tipo::text = 'telefono' and c.estado is distinct from 'invalido'), '{}')
from resultados_busqueda(%s, 1000000, 0) r
join busqueda_resultados br on br.busqueda_id = %s and br.empresa_id = r.empresa_id
where not br.relevancia_revisada and coalesce(br.clasificacion, '') <> 'aceptado'
"""


def quitar_repetidos(conn: psycopg.Connection, busqueda_id: str) -> dict[str, Any]:
    """Deja una sola ficha por empresa en los resultados de la búsqueda (la
    más completa: `resultados_busqueda` ya viene ordenada así)."""
    fichas = [Ficha(f[0], f[1], f[2], f[3], list(f[4])) for f in conn.execute(_SQL, (busqueda_id, busqueda_id)).fetchall()]
    grupos = agrupar_repetidas(fichas)
    quitadas = 0
    for queda, repetidas in grupos:
        for ficha, motivo in repetidas:
            conn.execute(
                "update busqueda_resultados set clasificacion = 'descartado', motivo_relevancia = %s "
                "where busqueda_id = %s and empresa_id = %s and not relevancia_revisada",
                (f"Repetida de «{queda.nombre}» ({motivo})"[:300], busqueda_id, ficha.empresa_id),
            )
            quitadas += 1
    conn.commit()
    return {"revisadas": len(fichas), "grupos": len(grupos), "repetidas_quitadas": quitadas, "coste_eur": 0.0}
