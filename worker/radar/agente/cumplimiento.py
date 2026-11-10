"""Verificación final de los filtros de la búsqueda sobre TODOS sus resultados
(2026-11-10), vengan de la fuente que vengan.

Cada fuente respeta los filtros a su manera: Maps busca «en» una zona pero
devuelve negocios de alrededor; OSM y el BORME van por municipio o provincia;
LinkedIn, Facebook y el rastreo de webs completan empresas que ya estaban sin
mirar la zona; la búsqueda web solo comprobaba la provincia por el código
postal. Esta fase, al final de toda búsqueda, comprueba con código
(determinista, sin coste) lo que se puede comprobar con los datos ya
guardados:

- Zona: código postal pedido, municipio, provincia/CCAA, y empresas de otro país.
- Estado registral (extinguidas, disueltas, en liquidación… si la búsqueda no las pide).
- Forma jurídica, si la búsqueda la pide.
- Requisitos de contacto (solo con web / teléfono / email genérico).
- Y que ninguna se quede sin pasar el filtro de sector con IA (si se agotó
  su presupuesto, queda «dudosa» en vez de pasar como buena).

Lo que no cumple pasa a «descartado» con el motivo (recuperable en la Cola de
revisión). Lo que no se puede comprobar (sin CP ni municipio conocidos) se
mantiene: no hay dato para descartarlo (principio 5). Nunca toca un
resultado que una persona ya revisó. El sector y los filtros avanzados
(«solo supermercados pequeños») los juzga el LLM en `radar.agente.relevancia`;
la plantilla, `radar.agente.tamano`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import psycopg

from radar.agente.herramientas import parece_extranjera, provincias_de_zona
from radar.agente.interpretacion import FiltrosBusqueda
from radar.normalizacion.direccion import PROVINCIAS, codigo_provincia

ESTADOS_NO_ACTIVOS = {"extinguida", "disuelta", "inactiva", "en_liquidacion", "en_concurso"}
MOTIVO_SIN_REVISAR = "Sin revisar por el filtro de sector (se agotó su presupuesto): comprobar a mano"


def normalizar_lugar(texto: str | None) -> str:
    """'Dos Hermanas (Sevilla)' / 'Dos Hermanas, Sevilla' / 'DOS HERMANAS' -> 'dos hermanas'."""
    plano = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    plano = re.split(r"[(,]", plano)[0]
    return " ".join(plano.replace("-", " ").split())


@dataclass
class DatosEmpresa:
    codigos_postales: list[str] = field(default_factory=list)
    municipios: list[str] = field(default_factory=list)
    provincias: list[str] = field(default_factory=list)
    telefonos: list[str] = field(default_factory=list)
    web: str | None = None
    estado: str | None = None
    forma_juridica: str | None = None
    tiene_email_generico: bool = False


@dataclass
class Criterios:
    """Lo que se exige, ya resuelto (provincias permitidas como códigos)."""

    codigos_postales: set[str] = field(default_factory=set)
    municipios: set[str] = field(default_factory=set)  # normalizados
    provincias: set[str] = field(default_factory=set)  # códigos de 2 cifras
    estados: set[str] = field(default_factory=set)
    formas_juridicas: set[str] = field(default_factory=set)
    exige_web: bool = False
    exige_telefono: bool = False
    exige_email_generico: bool = False


def criterios_de(filtros: FiltrosBusqueda, provincias_permitidas: set[str]) -> Criterios:
    u = filtros.ubicacion
    return Criterios(
        codigos_postales=set(u.codigos_postales),
        municipios={normalizar_lugar(m) for m in u.municipios},
        provincias=provincias_permitidas,
        estados=set(filtros.estados),
        formas_juridicas={f.upper().replace(".", "").strip() for f in filtros.formas_juridicas},
        exige_web=filtros.requisitos.web,
        exige_telefono=filtros.requisitos.telefono,
        exige_email_generico=filtros.requisitos.email_generico,
    )


def _provincias_de(d: DatosEmpresa) -> set[str]:
    cods = {cp[:2] for cp in d.codigos_postales if len(cp) == 5 and cp[:2] in PROVINCIAS}
    cods |= {c for c in (codigo_provincia(p) for p in d.provincias) if c}
    return cods


def motivo_incumplimiento(d: DatosEmpresa, c: Criterios) -> str | None:
    """None si cumple (o no se puede saber); si no, el motivo de descartarla."""
    if parece_extranjera(d.telefonos, d.web):
        return "Fuera de la zona: empresa de otro país (teléfono o web extranjeros)"
    # --- Zona: lo más preciso que se conozca de la empresa manda.
    if c.codigos_postales and d.codigos_postales and not set(d.codigos_postales) & c.codigos_postales:
        return f"Fuera de la zona: código postal {', '.join(d.codigos_postales)} (se piden {', '.join(sorted(c.codigos_postales))})"
    provincias = _provincias_de(d)
    if c.provincias and provincias and not provincias & c.provincias:
        nombres = ", ".join(PROVINCIAS.get(p, p) for p in sorted(provincias))
        return f"Fuera de la zona: provincia de {nombres}"
    cp_confirmado = bool(c.codigos_postales and set(d.codigos_postales) & c.codigos_postales)
    if c.municipios and d.municipios and not cp_confirmado:
        suyos = {normalizar_lugar(m) for m in d.municipios}
        # "Alcalá de Guadaíra / Alcalá" o "Sevilla capital": basta con que uno contenga al otro.
        casa = any(a == b or a in b.split(" / ") or b in a.split(" / ") for a in suyos for b in c.municipios)
        if not casa:
            return f"Fuera de la zona: municipio {', '.join(d.municipios)}"
    # --- Estado registral, forma jurídica y requisitos de contacto.
    if d.estado in ESTADOS_NO_ACTIVOS and d.estado not in c.estados:
        return f"Estado registral: {d.estado.replace('_', ' ')}"
    forma = (d.forma_juridica or "").upper().replace(".", "").strip()
    if c.formas_juridicas and forma and forma not in c.formas_juridicas:
        return f"Forma jurídica {d.forma_juridica} (se piden {', '.join(sorted(c.formas_juridicas))})"
    if c.exige_web and not d.web:
        return "Sin web (la búsqueda solo quiere empresas con web)"
    if c.exige_telefono and not d.telefonos:
        return "Sin teléfono (la búsqueda solo quiere empresas con teléfono)"
    if c.exige_email_generico and not d.tiene_email_generico:
        return "Sin email genérico (la búsqueda lo exige)"
    return None


_SQL = """
select br.empresa_id::text, br.clasificacion, e.dominio_web, e.estado::text, e.forma_juridica,
  coalesce((select array_agg(distinct s.codigo_postal) from sedes s
            where s.empresa_id = e.id and s.activa is not false and s.codigo_postal is not null), '{}'),
  coalesce((select array_agg(distinct s.municipio_nombre) from sedes s
            where s.empresa_id = e.id and s.activa is not false and s.municipio_nombre is not null), '{}'),
  coalesce((select array_agg(distinct s.provincia) from sedes s
            where s.empresa_id = e.id and s.activa is not false and s.provincia is not null), '{}'),
  coalesce((select array_agg(c.valor) from canales_contacto c
            where c.empresa_id = e.id and c.tipo::text = 'telefono' and c.estado is distinct from 'invalido'), '{}'),
  exists (select 1 from canales_contacto c where c.empresa_id = e.id and c.tipo::text = 'email'
          and c.es_generico and c.estado is distinct from 'invalido')
from busqueda_resultados br join empresas e on e.id = br.empresa_id
where br.busqueda_id = %s and e.fusionada_en is null and not br.relevancia_revisada
  and coalesce(br.clasificacion, '') not in ('descartado', 'rechazado', 'aceptado')
"""


def verificar_filtros(conn: psycopg.Connection, filtros: FiltrosBusqueda, busqueda_id: str) -> dict[str, Any]:
    criterios = criterios_de(filtros, provincias_de_zona(filtros, conn))
    cuenta: dict[str, Any] = {"revisadas": 0, "cumplen": 0, "descartadas": 0, "sin_revisar_sector": 0, "motivos": {}}
    for fila in conn.execute(_SQL, (busqueda_id,)).fetchall():
        empresa_id, clasificacion, web, estado, forma, cps, municipios, provincias, telefonos, email_generico = fila
        cuenta["revisadas"] += 1
        datos = DatosEmpresa(
            codigos_postales=list(cps), municipios=list(municipios), provincias=list(provincias),
            telefonos=list(telefonos), web=web, estado=estado, forma_juridica=forma, tiene_email_generico=bool(email_generico),
        )
        motivo = motivo_incumplimiento(datos, criterios)
        if motivo:
            cuenta["descartadas"] += 1
            clave = motivo.split(":")[0]
            cuenta["motivos"][clave] = cuenta["motivos"].get(clave, 0) + 1
            conn.execute(
                "update busqueda_resultados set clasificacion = 'descartado', motivo_relevancia = %s "
                "where busqueda_id = %s and empresa_id = %s and not relevancia_revisada",
                (motivo, busqueda_id, empresa_id),
            )
            continue
        cuenta["cumplen"] += 1
        if clasificacion is None:
            cuenta["sin_revisar_sector"] += 1
            conn.execute(
                "update busqueda_resultados set clasificacion = 'dudoso', motivo_relevancia = %s "
                "where busqueda_id = %s and empresa_id = %s and not relevancia_revisada and clasificacion is null",
                (MOTIVO_SIN_REVISAR, busqueda_id, empresa_id),
            )
    conn.commit()
    return {**cuenta, "coste_eur": 0.0}
