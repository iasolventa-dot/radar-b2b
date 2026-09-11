"""Respeta `robots.txt` antes de descargar cualquier página (doc 02 §3:
"Leer webs de empresas respetando `robots.txt` y límites de velocidad").

Un `robots.txt` ausente o que devuelve error se trata como "todo permitido"
(comportamiento estándar de `urllib.robotparser` y de la mayoría de bots).
"""

from __future__ import annotations

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

AGENTE = "RadarB2B"

# Un `RobotFileParser` por dominio, cacheado en memoria durante el proceso
# (no entre ejecuciones — es barato de volver a pedir y así respeta cambios).
_cache: dict[str, RobotFileParser] = {}


async def permitido(url: str, cliente: httpx.AsyncClient, agente: str = AGENTE) -> bool:
    origen = urlparse(url)
    if origen.scheme not in ("http", "https") or not origen.netloc:
        return False
    clave = f"{origen.scheme}://{origen.netloc}"
    rp = _cache.get(clave)
    if rp is None:
        rp = RobotFileParser()
        try:
            r = await cliente.get(f"{clave}/robots.txt", timeout=10)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except httpx.HTTPError:
            rp.parse([])
        _cache[clave] = rp
    return rp.can_fetch(agente, url)
