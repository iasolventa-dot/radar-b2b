"""Mapeo de un item de Apify `apify/facebook-pages-scraper` a `RegistroBruto`
(fuente 'facebook', migración 202609221000).

Campos verificados en apify.com/apify/facebook-pages-scraper (input-schema y
ejemplo de salida, 2026-09-22): title/pageName, facebookUrl/pageUrl, address,
phone, email, website/websites.

`address` llega como una sola cadena sin desglosar (p. ej. "Calle X 12,
Sevilla, España"): se guarda tal cual en `domicilio`, sin inventar
municipio/provincia a partir de ella -- eso lo resuelve la normalización
(`radar.normalizacion`) o una fuente que sí dé el dato estructurado.
"""

from __future__ import annotations

from typing import Any

from radar.fuentes.base import CamposExtraidos, RegistroBruto


def pagina_a_registro(item: dict[str, Any]) -> RegistroBruto | None:
    """`None` si no hay nombre de página."""
    nombre = (item.get("title") or item.get("pageName") or "").strip()
    if not nombre:
        return None

    telefono = (item.get("phone") or "").strip()
    email = (item.get("email") or "").strip()
    webs = item.get("websites") or []
    web = (webs[0] if webs else item.get("website") or "").strip()
    url_pagina = item.get("facebookUrl") or item.get("pageUrl")

    campos = CamposExtraidos(
        nombre_comercial=nombre,
        domicilio=(item.get("address") or "").strip() or None,
        telefonos=[telefono] if telefono else [],
        emails=[email] if email else [],
        web=web or None,
        extra={"facebook_id": item.get("pageId") or item.get("facebookId"), "categorias": item.get("categories")},
    )
    return RegistroBruto(
        fuente="facebook",
        id_externo=item.get("pageId") or item.get("facebookId"),
        url=url_pagina,
        payload={"pageId": item.get("pageId"), "categories": item.get("categories")},
        campos=campos,
    )
