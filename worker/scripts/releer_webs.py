"""Relee las webs de las empresas ya guardadas con el extractor corregido y
retira los teléfonos, emails y cargos que solo venían de una lectura errónea de
esa web (criterio completo en `radar.extraccion.relectura`).

Uso (con el entorno virtual del worker activado):

    python scripts\\releer_webs.py --prueba --limite 20   # solo informa, no escribe
    python scripts\\releer_webs.py                        # todas

Coste: leer webs es gratis; el extractor llama al modelo de extracción solo
cuando las reglas no bastan (céntimos en total).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter

import httpx
import psycopg

import radar  # noqa: F401 -- truststore (certificados de Windows)
from radar.config import get_settings
from radar.extraccion import enriquecer_varias
from radar.extraccion.conector import nombre_de_persona
from radar.extraccion.relectura import (
    FUENTE_WEB,
    LeidoEnWeb,
    digitos_telefono,
    nombre_plano,
    retirar_canal,
)
from radar.orquestador import procesar_registro

_SQL_EMPRESAS = """
select e.id::text, e.dominio_web from empresas e
where e.fusionada_en is null and e.dominio_web is not null and (
  exists (select 1 from observaciones o join fuentes f on f.id = o.fuente_id
          where o.empresa_id = e.id and o.vigente and f.nombre = %(web)s and o.campo in ('telefono', 'email'))
  or exists (select 1 from cargos c join fuentes f on f.id = c.fuente_id
             where c.empresa_id = e.id and c.vigente is not false and f.nombre = %(web)s))
order by e.id
"""
_SQL_CANALES = """
select c.id, c.tipo::text, c.valor,
  coalesce((select array_agg(distinct f.nombre) from observaciones o join fuentes f on f.id = o.fuente_id
            where o.empresa_id = c.empresa_id and o.vigente and o.campo = c.tipo::text
              and (case when c.tipo = 'telefono'
                        then right(regexp_replace(coalesce(o.valor_norm, o.valor_original), '\\D', '', 'g'), 9)
                           = right(regexp_replace(c.valor, '\\D', '', 'g'), 9)
                        else lower(coalesce(o.valor_norm, o.valor_original)) = lower(c.valor) end)), '{}')
from canales_contacto c
where c.empresa_id = %s and c.tipo::text in ('telefono', 'email') and c.estado is distinct from 'invalido'
"""
_SQL_CARGOS = """
select c.id, p.nombre from cargos c join personas p on p.id = c.persona_id join fuentes f on f.id = c.fuente_id
where c.empresa_id = %s and c.vigente is not false and f.nombre = %s
"""


def _retirar(conn: psycopg.Connection, empresa_id: str, leido: LeidoEnWeb, prueba: bool, cuenta: Counter) -> None:
    for canal_id, tipo, valor, fuentes in conn.execute(_SQL_CANALES, (empresa_id,)).fetchall():
        leidos = leido.telefonos if tipo == "telefono" else leido.emails
        encontrado = (digitos_telefono(valor) if tipo == "telefono" else valor.lower()) in leidos
        if not retirar_canal(set(fuentes), encontrado, len(leidos)):
            continue
        cuenta[f"{tipo}_retirado"] += 1
        if prueba:
            print(f"    - {tipo} {valor}")
            continue
        conn.execute("update canales_contacto set estado = 'invalido', actualizado_en = now() where id = %s", (canal_id,))
        filtro = (
            "right(regexp_replace(coalesce(valor_norm, valor_original), '\\D', '', 'g'), 9) = %s"
            if tipo == "telefono" else "lower(coalesce(valor_norm, valor_original)) = %s"
        )
        conn.execute(
            f"update observaciones set vigente = false where empresa_id = %s and campo = %s and vigente and {filtro} "
            "and fuente_id = (select id from fuentes where nombre = %s)",
            (empresa_id, tipo, digitos_telefono(valor) if tipo == "telefono" else valor.lower(), FUENTE_WEB),
        )
    for cargo_id, nombre in conn.execute(_SQL_CARGOS, (empresa_id, FUENTE_WEB)).fetchall():
        # Nombre roto (con cargos dentro): siempre. Si no, solo si la relectura
        # encontró personas y esta ya no está.
        if nombre_de_persona(nombre) and (not leido.personas or nombre_plano(nombre) in leido.personas):
            continue
        cuenta["cargo_retirado"] += 1
        if prueba:
            print(f"    - cargo de {nombre!r}")
            continue
        conn.execute("update cargos set vigente = false where id = %s", (cargo_id,))


async def main(limite: int | None, prueba: bool, lote: int) -> None:
    db_url = get_settings().supabase_db_url
    cuenta: Counter = Counter()
    with psycopg.connect(db_url) as conn:
        empresas = conn.execute(_SQL_EMPRESAS, {"web": FUENTE_WEB}).fetchall()
        conn.commit()
        if limite:
            empresas = empresas[:limite]
        print(f"{len(empresas)} empresas con datos sacados de su web", flush=True)
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as cliente:
            for i in range(0, len(empresas), lote):
                bloque = empresas[i : i + lote]
                urls = {eid: f"https://{dominio}" for eid, dominio in bloque}
                leidas = await enriquecer_varias(cliente, list(urls.values()))
                for eid, dominio in bloque:
                    registro = leidas.get(urls[eid])
                    if registro is None:
                        cuenta["web_no_legible"] += 1
                        continue
                    cuenta["web_releida"] += 1
                    if prueba:
                        print(f"  {dominio}: tel {sorted(registro.campos.telefonos)}", flush=True)
                    try:
                        if not prueba:
                            procesar_registro(registro, conn, empresa_destino=eid)
                        _retirar(conn, eid, LeidoEnWeb.de_registro(registro), prueba, cuenta)
                        conn.commit()
                    except Exception as exc:  # noqa: BLE001 -- una empresa que falla no para las demás
                        conn.rollback()
                        cuenta["error"] += 1
                        print(f"  error en {dominio}: {exc}", flush=True)
                print(f"{min(i + lote, len(empresas))}/{len(empresas)} {json.dumps(dict(cuenta))}", flush=True)
    print("FIN", json.dumps(dict(cuenta)), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limite", type=int, default=None)
    parser.add_argument("--prueba", action="store_true", help="solo informa: no escribe en la base de datos")
    parser.add_argument("--lote", type=int, default=20)
    args = parser.parse_args()
    asyncio.run(main(args.limite, args.prueba, args.lote))
