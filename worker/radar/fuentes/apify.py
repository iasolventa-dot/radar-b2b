"""Cliente de la API de Apify (https://docs.apify.com/api/v2) -- tubería genérica
para ejecutar un Actor con la entrada que se le pase y leer su dataset. No
interpreta ni filtra qué Actor se ejecuta ni con qué entrada: eso es cosa de
quien lo llama. Apify es un servicio de terceros con su propia clave y
facturación.

Endpoints verificados en docs.apify.com/api/v2 (2026-09-21): POST
/v2/actors/{id}/runs (Bearer, `maxTotalChargeUsd`, `timeout`, `memory`),
GET /v2/actor-runs/{runId}, GET /v2/datasets/{id}/items, GET /v2/users/me.
El token nunca aparece en mensajes de error.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx

URL_BASE = "https://api.apify.com/v2"
ESTADOS_FINALES = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}



class ApifyError(Exception):
    pass


@dataclass
class ResultadoActor:
    run_id: str | None = None
    estado: str | None = None
    coste_usd: float = 0.0
    items: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


def _mensaje_error(status: int, cuerpo: Any) -> str:
    detalle = None
    if isinstance(cuerpo, dict):
        detalle = (cuerpo.get("error") or {}).get("message")
    return f"Apify respondió {status}" + (f": {detalle}" if detalle else "")


def _id_actor(actor_id: str) -> str:
    # la API acepta "usuario/actor" o "usuario~actor"
    return actor_id.replace("/", "~")


async def probar_token(cliente: httpx.AsyncClient, token: str) -> tuple[bool, str]:
    """`GET /users/me`: no consume crédito."""
    try:
        r = await cliente.get(f"{URL_BASE}/users/me", headers={"Authorization": f"Bearer {token}"}, timeout=30.0)
    except httpx.HTTPError as exc:
        return False, f"no se pudo contactar con Apify: {type(exc).__name__}"
    if r.status_code != 200:
        try:
            cuerpo = r.json()
        except ValueError:
            cuerpo = None
        return False, _mensaje_error(r.status_code, cuerpo)
    usuario = (r.json().get("data") or {}).get("username", "")
    return True, f"Token válido{(' (cuenta ' + usuario + ')') if usuario else ''}."


async def ejecutar_actor(
    cliente: httpx.AsyncClient,
    token: str,
    actor_id: str,
    entrada: dict[str, Any] | None = None,
    *,
    max_coste_usd: float = 0.5,
    timeout_s: int = 120,
    max_items: int = 100,
    intervalo_s: float = 3.0,
) -> ResultadoActor:
    """Lanza el Actor con tope de coste (`maxTotalChargeUsd`), espera a que
    termine (hasta `timeout_s`) y devuelve los items del dataset."""
    cab = {"Authorization": f"Bearer {token}"}
    params = {"maxTotalChargeUsd": max_coste_usd, "timeout": timeout_s}
    try:
        r = await cliente.post(
            f"{URL_BASE}/actors/{_id_actor(actor_id)}/runs", params=params, json=entrada or {}, headers=cab, timeout=60.0
        )
    except httpx.HTTPError as exc:
        return ResultadoActor(error=f"no se pudo contactar con Apify: {type(exc).__name__}")
    if r.status_code not in (200, 201):
        try:
            cuerpo = r.json()
        except ValueError:
            cuerpo = None
        return ResultadoActor(error=_mensaje_error(r.status_code, cuerpo))
    run = r.json().get("data") or {}
    run_id = run.get("id")
    resultado = ResultadoActor(run_id=run_id, estado=run.get("status"))

    espera = 0.0
    while resultado.estado not in ESTADOS_FINALES and espera <= timeout_s + 30:
        await asyncio.sleep(intervalo_s)
        espera += intervalo_s
        try:
            rr = await cliente.get(f"{URL_BASE}/actor-runs/{run_id}", headers=cab, timeout=30.0)
        except httpx.HTTPError as exc:
            resultado.error = f"no se pudo consultar la ejecución: {type(exc).__name__}"
            return resultado
        if rr.status_code != 200:
            resultado.error = _mensaje_error(rr.status_code, None)
            return resultado
        run = rr.json().get("data") or {}
        resultado.estado = run.get("status")

    resultado.coste_usd = float(run.get("usageTotalUsd") or 0.0)
    if resultado.estado != "SUCCEEDED":
        resultado.error = f"la ejecución terminó en estado {resultado.estado}"
        return resultado

    dataset_id = run.get("defaultDatasetId")
    try:
        ri = await cliente.get(
            f"{URL_BASE}/datasets/{dataset_id}/items", params={"limit": max_items, "clean": "true"}, headers=cab, timeout=60.0
        )
    except httpx.HTTPError as exc:
        resultado.error = f"no se pudo leer el dataset: {type(exc).__name__}"
        return resultado
    if ri.status_code != 200:
        resultado.error = _mensaje_error(ri.status_code, None)
        return resultado
    datos = ri.json()
    resultado.items = datos if isinstance(datos, list) else []
    return resultado
