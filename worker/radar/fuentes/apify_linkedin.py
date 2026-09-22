"""Mapeo de un item de Apify `automation-lab/linkedin-company-scraper` a
`RegistroBruto` (fuente 'linkedin', ya en el catálogo desde el esquema
inicial -- habilitada para almacenar en la migración 202609221000).

Campos verificados en apify.com/automation-lab/linkedin-company-scraper
(input-schema y ejemplo de salida, 2026-09-22): name, linkedinUrl, website,
description, industry, companyType, companySize, employeeCount,
followerCount, foundedYear, headquarters, street, city, state, country,
postalCode, specialties.
"""

from __future__ import annotations

from typing import Any

from radar.fuentes.base import CamposExtraidos, RegistroBruto


def _domicilio(item: dict[str, Any]) -> str | None:
    calle = (item.get("street") or "").strip()
    if calle:
        return calle
    return (item.get("headquarters") or "").strip() or None


def empresa_a_registro(item: dict[str, Any]) -> RegistroBruto | None:
    """`None` si no hay nombre (p. ej. una resolución por nombre que no
    encontró página de empresa)."""
    nombre = (item.get("name") or "").strip()
    if not nombre:
        return None

    web = (item.get("website") or "").strip()
    campos = CamposExtraidos(
        nombre_comercial=nombre,
        domicilio=_domicilio(item),
        codigo_postal=(item.get("postalCode") or "").strip() or None,
        municipio=(item.get("city") or "").strip() or None,
        provincia=(item.get("state") or "").strip() or None,
        web=web or None,
        extra={
            "linkedin_url": item.get("linkedinUrl"),
            "industria": item.get("industry"),
            "tamano": item.get("companySize"),
            "empleados": item.get("employeeCount"),
            "descripcion": item.get("description"),
            "especialidades": item.get("specialties"),
        },
    )
    return RegistroBruto(
        fuente="linkedin",
        id_externo=item.get("linkedinUrl"),
        url=item.get("linkedinUrl"),
        payload={"linkedinUrl": item.get("linkedinUrl"), "industry": item.get("industry")},
        campos=campos,
    )
