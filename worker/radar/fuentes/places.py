"""Google Places API (New) -- Text Search. API OFICIAL, con clave propia
(Google Cloud); no es scraping de Maps.

Condiciones de uso que condicionan el diseño (verificadas 2026-09-21 en
cloud.google.com/maps-platform/terms y developers.google.com/maps/
documentation/places/web-service/policies): solo se puede almacenar
indefinidamente el `place_id`; nombre, teléfono, web, dirección... no se
pueden guardar. Por eso este módulo SOLO devuelve datos "en vivo"
(`LugarPlaces`) y NO produce `RegistroBruto`: quien orquesta
(`radar.agente.descubrir_places`) usa esos datos de forma transitoria para
(a) reconocer una empresa que ya tenemos y guardar solo su `place_id`, o
(b) seguir la web PROPIA de la empresa y guardar lo que diga ella.

Costes (a verificar contra la tabla de precios vigente de Google Cloud
antes de subir el presupuesto): Text Search nivel Pro ~32 $/1.000 y nivel
Enterprise (añade teléfono) ~35 $/1.000, con 5.000/1.000 llamadas gratis al
mes por SKU (fuentes de la sesión 2026-09-21, no oficiales al 100%). Se
factura al SKU más alto pedido en el `FieldMask`, así que aquí se calcula
SIEMPRE con la tarifa Enterprise (conservador) y 1 USD ≈ 1 EUR (D-04). La
clave nunca aparece en mensajes de error ni en logs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

URL_TEXT_SEARCH = "https://places.googleapis.com/v1/places:searchText"

CAMPOS_BUSQUEDA = (
    "places.id,places.displayName,places.formattedAddress,places.location,"
    "places.businessStatus,places.websiteUri,places.nationalPhoneNumber"
)
CAMPOS_SOLO_ID = "places.id"

# EUR por petición, tarifa Enterprise de lista (conservadora, "a verificar").
COSTE_PETICION_EUR = 0.035
COSTE_PETICION_SOLO_ID_EUR = 0.0
MAX_RESULTADOS_POR_PAGINA = 20


@dataclass
class LugarPlaces:
    place_id: str
    nombre: str | None
    direccion: str | None
    lat: float | None
    lon: float | None
    estado: str | None  # OPERATIONAL | CLOSED_TEMPORARILY | CLOSED_PERMANENTLY
    web: str | None
    telefono: str | None


@dataclass
class ResultadoPlaces:
    lugares: list[LugarPlaces] = field(default_factory=list)
    siguiente_pagina: str | None = None
    coste_eur: float = 0.0
    error: str | None = None


def parsear_lugares(datos: dict[str, Any]) -> list[LugarPlaces]:
    lugares: list[LugarPlaces] = []
    for p in datos.get("places") or []:
        pid = p.get("id")
        if not pid:
            continue
        loc = p.get("location") or {}
        lugares.append(
            LugarPlaces(
                place_id=pid,
                nombre=(p.get("displayName") or {}).get("text"),
                direccion=p.get("formattedAddress"),
                lat=loc.get("latitude"),
                lon=loc.get("longitude"),
                estado=p.get("businessStatus"),
                web=p.get("websiteUri"),
                telefono=p.get("nationalPhoneNumber"),
            )
        )
    return lugares


def mensaje_error(status_code: int, cuerpo: Any) -> str:
    """Texto de error apto para mostrar: solo el mensaje de Google, nunca
    cabeceras ni la clave."""
    detalle = None
    if isinstance(cuerpo, dict):
        detalle = (cuerpo.get("error") or {}).get("message")
    if status_code in (400, 403) and detalle:
        return f"Google rechazó la petición ({status_code}): {detalle}"[:300]
    return f"Google Places respondió {status_code}" + (f": {detalle}" if detalle else "")[:300]


async def buscar_lugares(
    cliente: httpx.AsyncClient,
    api_key: str,
    consulta: str,
    *,
    pagina: str | None = None,
    tamano_pagina: int = MAX_RESULTADOS_POR_PAGINA,
    solo_id: bool = False,
) -> ResultadoPlaces:
    cuerpo: dict[str, Any] = {
        "textQuery": consulta,
        "languageCode": "es",
        "regionCode": "ES",
        "pageSize": max(1, min(tamano_pagina, MAX_RESULTADOS_POR_PAGINA)),
    }
    if pagina:
        cuerpo["pageToken"] = pagina
    cabeceras = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": CAMPOS_SOLO_ID + ",nextPageToken" if solo_id else CAMPOS_BUSQUEDA + ",nextPageToken",
    }
    try:
        r = await cliente.post(URL_TEXT_SEARCH, json=cuerpo, headers=cabeceras, timeout=30.0)
    except httpx.HTTPError as exc:
        return ResultadoPlaces(error=f"no se pudo contactar con Google Places: {type(exc).__name__}")
    try:
        datos = r.json()
    except ValueError:
        datos = None
    if r.status_code != 200:
        return ResultadoPlaces(error=mensaje_error(r.status_code, datos))
    coste = COSTE_PETICION_SOLO_ID_EUR if solo_id else COSTE_PETICION_EUR
    return ResultadoPlaces(
        lugares=parsear_lugares(datos or {}),
        siguiente_pagina=(datos or {}).get("nextPageToken"),
        coste_eur=coste,
    )


async def probar_clave(cliente: httpx.AsyncClient, api_key: str) -> tuple[bool, str]:
    """Petición mínima de solo IDs (SKU gratuito) para comprobar que la clave
    vale y que la API "Places API (New)" está habilitada en el proyecto."""
    r = await buscar_lugares(cliente, api_key, "constructora Sevilla", tamano_pagina=1, solo_id=True)
    if r.error:
        return False, r.error
    return True, "Clave válida: Places API (New) responde correctamente."
