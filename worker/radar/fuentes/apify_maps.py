"""Mapeo de un item de Apify `compass/crawler-google-places` (Google Maps, no
la API oficial) a `RegistroBruto`. Mismos datos subyacentes que Google Places
pero sin restricción de persistencia de la API oficial (fuente 'apify_google_maps',
migración 202609221000, grupo_independencia='google' -- no confirma nada de
forma independiente respecto a 'google_places').

Campos verificados en apify.com/compass/crawler-google-places/input-schema y
su ficha de salida (2026-09-22): title, address, phone, website, categoryName,
location{lat,lng}, placeId, permanentlyClosed, totalScore.
"""

from __future__ import annotations

from typing import Any

from radar.fuentes.base import CamposExtraidos, RegistroBruto


def lugar_a_registro(item: dict[str, Any]) -> RegistroBruto | None:
    """`None` si no hay nombre (sin nombre no hay candidato) o el lugar está
    `permanentlyClosed` (no se guarda una empresa que ya cerró)."""
    nombre = (item.get("title") or "").strip()
    if not nombre or item.get("permanentlyClosed"):
        return None
    # Sin teléfono ni web no aporta nada a una base de contactos y a menudo ni
    # es una empresa (visto en vivo 2026-09-24: "Fuente de agua potable",
    # categoría "Zona de senderismo", al buscar "instalaciones de agua").
    if not (item.get("phone") or item.get("website")):
        return None

    ubicacion = item.get("location") or {}
    lat, lon = ubicacion.get("lat"), ubicacion.get("lng")
    place_id = item.get("placeId")
    telefono = (item.get("phone") or "").strip()
    web = (item.get("website") or "").strip()

    campos = CamposExtraidos(
        nombre_comercial=nombre,
        domicilio=(item.get("address") or "").strip() or None,
        lat=float(lat) if lat is not None else None,
        lon=float(lon) if lon is not None else None,
        telefonos=[telefono] if telefono else [],
        web=web or None,
        extra={"place_id": place_id, "categoria": item.get("categoryName"), "puntuacion": item.get("totalScore")},
    )
    return RegistroBruto(
        fuente="apify_google_maps",
        id_externo=place_id,
        url=item.get("url") or (f"https://www.google.com/maps/place/?q=place_id:{place_id}" if place_id else None),
        payload={"placeId": place_id, "categoryName": item.get("categoryName")},
        campos=campos,
    )
