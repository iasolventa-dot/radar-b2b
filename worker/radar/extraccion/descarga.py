"""Descarga de páginas web para extracción, con caché local y respeto de
`robots.txt` (doc 02 §3, §6).

Caché: un fichero JSON por URL bajo `settings.cache_descargas_dir`, válido
`settings.cache_descargas_dias` días — evita volver a descargar la misma
página en poco tiempo (doc 02 §6: "Caché de descargas web por URL... para
no descargar la misma página dos veces en N días"). Simplificación
conocida: es un directorio local, así que en un contenedor efímero
(Railway, doc 02 §3) no sobrevive a un redeploy. Para producción, respaldar
en Supabase Storage o en una tabla propia — no implementado todavía, fuera
del alcance mínimo de esta tarea.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import httpx
from selectolax.parser import HTMLParser

from radar.config import get_settings
from radar.extraccion.robots import permitido

CABECERAS = {"User-Agent": "RadarB2B/1.0 (+uso interno Solventa IA; contacto: iasolventa@gmail.com)"}

# Enlaces de portada hacia las páginas donde suele estar el aviso legal
# (doc 04 §3, paso 1).
PATRON_ENLACES_LEGALES = re.compile(
    r"aviso.?legal|legal|privacidad|condiciones|t[eé]rminos|contacto|qui[eé]nes.?somos|sobre.?nosotros|^nosotros$",
    re.IGNORECASE,
)


@dataclass
class PaginaDescargada:
    url: str
    html: str
    desde_cache: bool


def _ruta_cache(url: str) -> Path:
    directorio = Path(get_settings().cache_descargas_dir)
    directorio.mkdir(parents=True, exist_ok=True)
    clave = hashlib.sha256(url.encode()).hexdigest()
    return directorio / f"{clave}.json"


def _leer_cache(url: str) -> str | None:
    ruta = _ruta_cache(url)
    if not ruta.exists():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    edad_dias = (time.time() - datos.get("descargado_en", 0)) / 86400
    if edad_dias > get_settings().cache_descargas_dias:
        return None
    return datos.get("html")


def _guardar_cache(url: str, html: str) -> None:
    ruta = _ruta_cache(url)
    ruta.write_text(json.dumps({"url": url, "descargado_en": time.time(), "html": html}), encoding="utf-8")


async def descargar(url: str, cliente: httpx.AsyncClient) -> PaginaDescargada | None:
    """`None` si `robots.txt` lo prohíbe o la petición falla (404, timeout,
    error de servidor…) — nunca lanza, para que un conector pueda seguir
    con la siguiente URL sin tener que envolver cada llamada en try/except.
    """
    cacheado = _leer_cache(url)
    if cacheado is not None:
        return PaginaDescargada(url=url, html=cacheado, desde_cache=True)
    if not await permitido(url, cliente):
        return None
    try:
        r = await cliente.get(url, headers=CABECERAS, timeout=20, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    _guardar_cache(url, r.text)
    return PaginaDescargada(url=url, html=r.text, desde_cache=False)


def encontrar_enlaces_legales(html: str, url_base: str) -> list[str]:
    """Enlaces de una página (normalmente la portada) hacia aviso legal /
    privacidad / condiciones / contacto / quiénes somos, como URLs
    absolutas (doc 04 §3, paso 1)."""
    parser = HTMLParser(html)
    vistos: set[str] = set()
    encontrados: list[str] = []
    for a in parser.css("a"):
        href = a.attributes.get("href")
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        texto = (a.text() or "").strip()
        if PATRON_ENLACES_LEGALES.search(texto) or PATRON_ENLACES_LEGALES.search(href):
            absoluta = urljoin(url_base, href)
            if absoluta not in vistos:
                vistos.add(absoluta)
                encontrados.append(absoluta)
    return encontrados
