"""Generador determinista de consultas de descubrimiento para el buscador web.

El buscador web es una fuente de descubrimiento (no solo de enriquecimiento):
esto construye, a partir de los filtros confirmados, varias consultas
literales por sector y zona con patrones distintos (nombre del sector, "empresa
de X", "X teléfono", "X contacto aviso legal"), para que el agente no dependa
de que el LLM se acuerde de variar. Código puro, sin red.
"""

from __future__ import annotations

from radar.agente.interpretacion import FiltrosBusqueda

PALABRAS_POR_DEFECTO_CONSTRUCCION = ["empresa de reformas", "constructora", "empresa de construcción"]
PATRONES = (
    '"{kw}" "{zona}"',
    "{kw} {zona} teléfono",
    "{kw} {zona} contacto aviso legal",
)


def _zonas(filtros: FiltrosBusqueda, max_zonas: int) -> list[str]:
    u = filtros.ubicacion
    zonas = list(u.municipios) or list(u.provincias) or list(u.ccaa)
    return zonas[:max_zonas]


def zona_texto(filtros: FiltrosBusqueda) -> str | None:
    """Una zona como texto para actors de Apify que buscan por ubicación libre
    (`locationQuery` de compass/crawler-google-places, `countryCode`+contexto
    de google-search-scraper): el municipio más específico si lo hay, si no la
    provincia, si no la CCAA. `None` si la búsqueda no trae ninguna zona (no
    tiene sentido pedirle a un Actor de pago que busque "por España")."""
    u = filtros.ubicacion
    zonas = u.municipios or u.provincias or u.ccaa
    return f"{zonas[0]}, España" if zonas else None


def generar_consultas(filtros: FiltrosBusqueda, *, max_consultas: int = 6, max_zonas: int = 3, max_palabras: int = 3) -> list[str]:
    """Hasta `max_consultas` consultas distintas, intercalando patrones y
    palabras clave para maximizar la variedad de resultados con pocas
    consultas. Lista vacía si los filtros no traen ninguna zona (una consulta
    sin zona devolvería resultados de toda España)."""
    zonas = _zonas(filtros, max_zonas)
    if not zonas:
        return []
    palabras = [p.strip() for p in filtros.sector.palabras_clave if p.strip()][:max_palabras]
    if not palabras:
        sector = (filtros.sector.sector_interno or "").strip()
        if "constru" in sector.lower() or not sector:
            palabras = PALABRAS_POR_DEFECTO_CONSTRUCCION[:max_palabras]
        else:
            palabras = [sector]

    consultas: list[str] = []
    vistas: set[str] = set()
    for patron in PATRONES:
        for zona in zonas:
            for kw in palabras:
                c = patron.format(kw=kw, zona=zona)
                if c.lower() not in vistas:
                    vistas.add(c.lower())
                    consultas.append(c)
                if len(consultas) >= max_consultas:
                    return consultas
    return consultas
