"""OpenStreetMap vía Overpass API -- fuente libre de descubrimiento por zona y
sector (tags `office=construction_company`, `craft=*`...). Licencia ODbL:
almacenable citando "© OpenStreetMap contributors" (tabla `fuentes`, código
'osm'). Verificado en vivo el 2026-09-21: 44 elementos de construcción en
Sevilla capital, 28 con teléfono y 7 con web.

Limitaciones reales (no se disimulan):
- Datos de voluntarios: cobertura y frescura irregulares (algún elemento con
  `survey:date` de 2012). Por eso `fiabilidad_base` = 0,60.
- Casi nunca hay NIF ni razón social: `name` es el nombre COMERCIAL. Se guarda
  como `nombre_comercial`; la razón social se dejará a otras fuentes.
- Overpass aplica límite de carga por IP: responde con una página HTML de
  error ("rate_limited") en vez de JSON. Se reintenta con espera y se
  distingue de una respuesta válida vacía -- nunca se interpreta un error
  como "0 resultados".
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from radar.fuentes.base import CamposExtraidos, Conector, RegistroBruto

URL_OVERPASS = "https://overpass-api.de/api/interpreter"
USER_AGENT = "radar-b2b-solventa/0.1 (uso interno; iasolventa@gmail.com)"
ATRIBUCION = "© OpenStreetMap contributors (ODbL)"

# Oficios de construcción con `craft=*` en OSM (valores reales del tagging).
CRAFTS_CONSTRUCCION = (
    "builder", "carpenter", "electrician", "plumber", "roofer", "plasterer", "painter", "tiler", "hvac",
    "glaziery", "stonemason", "metal_construction", "window_construction", "floorer", "insulation",
    "scaffolder", "paver", "concrete", "handicraft_construction",
)

_RE_CODIGO_INE = re.compile(r"^\d{5}$")
_RE_PALABRA = re.compile(r"^[\w\- ]{2,40}$", re.UNICODE)


class OverpassError(Exception):
    pass


def construir_consulta(
    codigos_ine_municipio: list[str],
    *,
    sector: str = "construccion",
    palabras_clave: list[str] | None = None,
    limite: int = 500,
    timeout_s: int = 90,
) -> str:
    """Consulta Overpass QL. Solo acepta códigos INE de 5 dígitos y palabras
    clave "seguras" (letras/números/espacios/guion) -- lo que se interpola en
    la consulta nunca viene crudo del usuario o del LLM."""
    if not codigos_ine_municipio:
        raise ValueError("hace falta al menos un código INE de municipio")
    for c in codigos_ine_municipio:
        if not _RE_CODIGO_INE.match(c):
            raise ValueError(f"código INE inválido: {c!r}")

    partes_area = "".join(
        f'rel["boundary"="administrative"]["ine:municipio"="{c}"];map_to_area->.a{i};\n'
        for i, c in enumerate(codigos_ine_municipio)
    )
    filtros: list[str] = []
    crafts = "|".join(CRAFTS_CONSTRUCCION)
    for i in range(len(codigos_ine_municipio)):
        if sector == "construccion":
            filtros.append(f'  nwr(area.a{i})["office"="construction_company"];')
            filtros.append(f'  nwr(area.a{i})["craft"~"^({crafts})$"];')
        for p in palabras_clave or []:
            if not _RE_PALABRA.match(p):
                continue
            filtros.append(f'  nwr(area.a{i})["name"~"{p}",i]["office"];')
            filtros.append(f'  nwr(area.a{i})["name"~"{p}",i]["craft"];')
    if not filtros:
        raise ValueError("sin filtros: sector desconocido y sin palabras clave válidas")
    return (
        f"[out:json][timeout:{timeout_s}];\n{partes_area}(\n" + "\n".join(filtros) + f"\n);\nout center tags {int(limite)};"
    )


def _tag(tags: dict[str, str], *claves: str) -> str | None:
    for c in claves:
        v = tags.get(c)
        if v and v.strip():
            return v.strip()
    return None


def _lista_valores(valor: str | None) -> list[str]:
    if not valor:
        return []
    return [v.strip() for v in re.split(r"[;,]", valor) if v.strip()]


def elemento_a_registro(el: dict[str, Any]) -> RegistroBruto | None:
    """`None` si el elemento no tiene nombre (sin nombre no hay empresa que
    resolver: un punto anónimo `craft=builder` no es un candidato)."""
    tags: dict[str, str] = el.get("tags") or {}
    nombre = _tag(tags, "name", "brand", "operator")
    if not nombre:
        return None

    calle = _tag(tags, "addr:street")
    numero = _tag(tags, "addr:housenumber")
    domicilio = None
    if calle:
        domicilio = f"{calle} {numero}".strip() if numero else calle

    lat = el.get("lat") if el.get("lat") is not None else (el.get("center") or {}).get("lat")
    lon = el.get("lon") if el.get("lon") is not None else (el.get("center") or {}).get("lon")

    tipo, osm_id = el.get("type"), el.get("id")
    web = _tag(tags, "website", "contact:website", "url")
    campos = CamposExtraidos(
        nombre_comercial=nombre,
        domicilio=domicilio,
        codigo_postal=_tag(tags, "addr:postcode"),
        municipio=_tag(tags, "addr:city"),
        provincia=_tag(tags, "addr:province"),
        lat=float(lat) if lat is not None else None,
        lon=float(lon) if lon is not None else None,
        telefonos=_lista_valores(_tag(tags, "phone", "contact:phone", "contact:mobile", "mobile")),
        emails=_lista_valores(_tag(tags, "email", "contact:email")),
        web=web,
        extra={
            "osm_tipo": tipo,
            "osm_id": osm_id,
            "oficio": _tag(tags, "craft", "office"),
            "fecha_survey": _tag(tags, "survey:date", "check_date"),
            "atribucion": ATRIBUCION,
        },
    )
    return RegistroBruto(
        fuente="osm",
        id_externo=f"{tipo}/{osm_id}",
        url=f"https://www.openstreetmap.org/{tipo}/{osm_id}",
        payload={"tags": tags, "atribucion": ATRIBUCION},
        campos=campos,
    )


def parsear_respuesta(texto: str) -> list[dict[str, Any]]:
    """Lanza `OverpassError` si la respuesta no es JSON de Overpass (p. ej. la
    página HTML de "rate_limited")."""
    import json

    t = texto.lstrip()
    if not t.startswith("{"):
        limpio = re.sub(r"<[^>]+>", " ", t)
        limpio = " ".join(limpio.split())[:300]
        raise OverpassError(f"respuesta no JSON de Overpass: {limpio}")
    datos = json.loads(t)
    if datos.get("remark") and "error" in str(datos["remark"]).lower():
        raise OverpassError(str(datos["remark"])[:300])
    return list(datos.get("elements") or [])


async def consultar_overpass(
    cliente: httpx.AsyncClient, consulta: str, *, reintentos: int = 3, espera_s: float = 15.0
) -> list[dict[str, Any]]:
    ultimo: Exception | None = None
    for intento in range(reintentos):
        try:
            r = await cliente.post(
                URL_OVERPASS, data={"data": consulta}, headers={"User-Agent": USER_AGENT}, timeout=120.0
            )
            if r.status_code == 200:
                return parsear_respuesta(r.text)
            ultimo = OverpassError(f"HTTP {r.status_code}")
        except (httpx.HTTPError, OverpassError) as exc:
            ultimo = exc
        if intento < reintentos - 1:
            await asyncio.sleep(espera_s * (intento + 1))
    raise OverpassError(f"Overpass no respondió tras {reintentos} intentos: {ultimo}")


class ConectorOSM(Conector):
    codigo = "osm"
    coste_unitario_eur = 0.0

    def __init__(self, cliente: httpx.AsyncClient):
        self.cliente = cliente

    def estimar_coste(self, parametros: dict) -> float:
        return 0.0

    async def descubrir(self, parametros: dict, max_coste_eur: float) -> AsyncIterator[RegistroBruto]:
        consulta = construir_consulta(
            list(parametros["codigos_ine_municipio"]),
            sector=parametros.get("sector", "construccion"),
            palabras_clave=parametros.get("palabras_clave"),
            limite=int(parametros.get("limite", 500)),
        )
        for el in await consultar_overpass(self.cliente, consulta):
            registro = elemento_a_registro(el)
            if registro is not None:
                yield registro
