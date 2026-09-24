"""Fases deterministas alrededor del bucle del planificador LLM.

Motivo (confirmado en la BD real 2026-09-23): con las 5 casillas de Apify
marcadas y token válido, el LLM seguía eligiendo solo BORME/OSM ("fuentes
gratuitas primero", según su prompt) y Apify no se llamaba nunca -- y lo
que da el BORME no trae ni web, ni teléfono, ni email. Así que:

1. `fase_fuentes_marcadas` (ANTES del LLM): las fuentes de pago que el usuario
   ha marcado en la búsqueda se ejecutan siempre, con argumentos deducidos
   de los filtros confirmados. Si el usuario las marca, es que las quiere.
2. el bucle LLM de siempre, con el presupuesto que quede.
3. `completar_contacto` (DESPUÉS del LLM, `radar.agente.completar_contacto`).

Cada fase es una "ronda" más del progreso (mismo `RondaPlanificador`), así
que el panel la muestra y su coste se descuenta del presupuesto igual.
"""

from __future__ import annotations

from typing import Any

from radar.agente.consultas import zona_texto
from radar.agente.herramientas import ContextoHerramientas, ejecutar_herramienta
from radar.agente.interpretacion import FiltrosBusqueda

# Reparto del presupuesto de la búsqueda entre las fuentes marcadas: fracción
# del presupuesto total y tope absoluto (EUR), para que una búsqueda de 20 €
# no se gaste todo en Maps de una vez.
# Maps es la fuente con más precisión y contacto (en búsquedas reales: casi
# todos los negocios con teléfono, más de la mitad con web); Google Search trae
# más ruido (directorios, webs de otros sectores), así que recibe menos.
REPARTO = {
    "descubrir_apify_maps": (0.50, 0.25),
    "descubrir_places": (0.30, 0.15),
    "descubrir_google_search": (0.10, 0.04),
    "enriquecer_con_facebook": (0.15, 0.06),
    "enriquecer_con_linkedin": (0.10, 0.04),
}
SECTOR_GENERICO = {"", "todos", "todos los sectores", "cualquiera", "general"}


def palabras_para_mapas(filtros: FiltrosBusqueda, maximo: int = 3) -> list[str]:
    """Lo que se escribe en el buscador de Maps/Places: las palabras clave del
    sector, o el sector interno, o "empresa" si la petición no tiene sector."""
    sector = (filtros.sector.sector_interno or "").strip()
    palabras = [p.strip() for p in filtros.sector.palabras_clave if p and p.strip()]
    # El nombre del sector primero: las palabras clave del LLM a veces son
    # demasiado genéricas para Maps ("instalaciones de agua" trajo una fuente
    # pública de un parque).
    candidatas = ([sector] if sector.lower() not in SECTOR_GENERICO else []) + palabras
    vistas: list[str] = []
    for p in candidatas:
        if p.lower() not in {v.lower() for v in vistas}:
            vistas.append(p)
    return vistas[:maximo] or ["empresa"]


# Directorios que Google devuelve primero y que nunca son la web de una
# empresa (ya se descartan al procesar, pero cada uno ocupa un resultado que
# se paga): se excluyen en la propia consulta.
SITIOS_EXCLUIDOS_GOOGLE = (
    "paginasamarillas.es", "habitissimo.es", "cronoshare.com", "starofservice.es", "empresite.eleconomista.es",
    "infoisinfo.es", "tuugo.es", "milanuncios.com", "einforma.com", "infocif.es",
)


def consultas_google(filtros: FiltrosBusqueda, maximo: int = 3) -> list[str]:
    zona = (zona_texto(filtros) or "").removesuffix(", España")
    if not zona:
        return []
    exclusiones = " ".join(f"-site:{s}" for s in SITIOS_EXCLUIDOS_GOOGLE)
    return [f"{p} {zona} {exclusiones}" for p in palabras_para_mapas(filtros, maximo)]


def presupuesto_para(herramienta: str, presupuesto_total_eur: float, restante_eur: float) -> float:
    fraccion, tope = REPARTO[herramienta]
    return max(0.0, min(presupuesto_total_eur * fraccion, tope, restante_eur))


def planes_fuentes_marcadas(
    filtros: FiltrosBusqueda, *, usar_places: bool, apify_actores: frozenset[str] | set[str]
) -> list[tuple[str, dict[str, Any]]]:
    """Qué se lanza en la fase inicial y con qué argumentos (sin tope de coste,
    que se añade al ejecutar según lo que quede). Pura, para poder testearla."""
    if not zona_texto(filtros):
        return []
    palabras = palabras_para_mapas(filtros)
    planes: list[tuple[str, dict[str, Any]]] = []
    if "google_maps" in apify_actores:
        planes.append(("descubrir_apify_maps", {"palabras_clave": palabras}))
    if usar_places:
        zona = zona_texto(filtros) or ""
        planes.append(("descubrir_places", {"consultas": [f"{p} en {zona.removesuffix(', España')}" for p in palabras]}))
    if "google_search" in apify_actores:
        consultas = consultas_google(filtros)
        if consultas:
            planes.append(("descubrir_google_search", {"consultas": consultas}))
    return planes


async def ejecutar_con_tope(
    nombre: str, argumentos: dict[str, Any], contexto: ContextoHerramientas, presupuesto_total_eur: float
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Ejecuta una herramienta de pago con su parte del presupuesto. Devuelve
    (argumentos_con_tope, resultado). Nunca lanza."""
    args = {**argumentos, "max_coste_eur": round(presupuesto_para(nombre, presupuesto_total_eur, contexto.presupuesto_restante_eur), 4)}
    if args["max_coste_eur"] <= 0:
        return args, {"motivo_parada": "sin_presupuesto", "coste_eur": 0.0}
    try:
        return args, await ejecutar_herramienta(nombre, args, contexto)
    except ValueError as exc:
        return args, {"error": str(exc), "coste_eur": 0.0}
