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
# Los Actors de pago por evento (Google Maps, Google Search...) rechazan con un
# 400 cualquier `maxTotalChargeUsd` inferior a este mínimo ("Maximum cost per
# run is less than the allowed minimum of $0.50", `pricingInfo.minimalMaxTotalChargeUsd`,
# confirmado en vivo 2026-09-23). Por eso el tope por ejecución nunca baja de
# aquí, y el gasto REAL se limita con el número de resultados (`max_items` +
# los límites propios de la entrada de cada Actor), que es lo que cobran.
MINIMO_TOPE_APIFY_USD = 0.5
LECTURAS_COSTE = 6


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


# Reintentos ante fallos de CONEXIÓN (visto en vivo 2026-10-01: "no se pudo
# contactar con Apify: ConnectError" en mitad de una búsqueda, mientras la
# misma llamada aislada funcionaba). El cliente compartido de la búsqueda lee
# a la vez decenas de webs; si su conexión falla, se reintenta con un cliente
# nuevo (conexiones limpias) tras una pausa creciente.
INTENTOS_CONEXION = 3
PAUSA_REINTENTO_S = 2.0


def _texto_error(exc: Exception) -> str:
    detalle = str(exc).strip()
    return f"{type(exc).__name__}" + (f" ({detalle[:160]})" if detalle else "")


async def _peticion(
    cliente: httpx.AsyncClient, metodo: str, url: str, *, solo_fallos_de_conexion: bool, pausa_s: float, **kwargs: Any
) -> httpx.Response:
    """Hace la petición y reintenta con un cliente nuevo si falla la conexión.
    `solo_fallos_de_conexion=True` (lanzar una ejecución): solo se reintenta
    si la petición NO llegó a enviarse (ConnectError/ConnectTimeout), para no
    lanzar -- y pagar -- el mismo Actor dos veces."""
    ultimo: Exception | None = None
    for intento in range(INTENTOS_CONEXION):
        try:
            if intento == 0:
                return await cliente.request(metodo, url, **kwargs)
            async with httpx.AsyncClient() as nuevo:
                return await nuevo.request(metodo, url, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            ultimo = exc
        except httpx.TransportError as exc:
            if solo_fallos_de_conexion:
                raise
            ultimo = exc
        if intento < INTENTOS_CONEXION - 1:
            await asyncio.sleep(pausa_s * (intento + 1))
    assert ultimo is not None
    raise ultimo


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
    max_coste_usd: float = MINIMO_TOPE_APIFY_USD,
    timeout_s: int = 120,
    max_items: int = 100,
    intervalo_s: float = 3.0,
) -> ResultadoActor:
    """Lanza el Actor, espera a que termine (hasta `timeout_s`) y devuelve los
    items del dataset. `max_items` limita cuántos resultados se COBRAN
    (parámetro `maxItems` de la API) y cuántos se leen; `max_coste_usd` va como
    `maxTotalChargeUsd`, nunca por debajo de `MINIMO_TOPE_APIFY_USD`."""
    cab = {"Authorization": f"Bearer {token}"}
    params = {
        "maxTotalChargeUsd": max(max_coste_usd, MINIMO_TOPE_APIFY_USD),
        "maxItems": max_items,
        "timeout": timeout_s,
    }
    try:
        r = await _peticion(
            cliente, "POST", f"{URL_BASE}/actors/{_id_actor(actor_id)}/runs", solo_fallos_de_conexion=True,
            pausa_s=PAUSA_REINTENTO_S if intervalo_s else 0.0,
            params=params, json=entrada or {}, headers=cab, timeout=60.0,
        )
    except httpx.HTTPError as exc:
        return ResultadoActor(error=f"no se pudo contactar con Apify: {_texto_error(exc)}")
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
        espera += max(intervalo_s, 1.0)  # cada consulta cuenta al menos 1 s: nunca bucle infinito
        try:
            rr = await _peticion(
                cliente, "GET", f"{URL_BASE}/actor-runs/{run_id}", solo_fallos_de_conexion=False,
                pausa_s=PAUSA_REINTENTO_S if intervalo_s else 0.0, headers=cab, timeout=30.0,
            )
        except httpx.HTTPError as exc:
            resultado.error = f"no se pudo consultar la ejecución: {_texto_error(exc)}"
            return resultado
        if rr.status_code != 200:
            resultado.error = _mensaje_error(rr.status_code, None)
            return resultado
        run = rr.json().get("data") or {}
        resultado.estado = run.get("status")

    if resultado.estado not in ESTADOS_FINALES and run_id:
        # Se agotó la espera: la ejecución seguiría corriendo (y cobrando) en
        # Apify aunque aquí ya no se lea. Visto en la consola 2026-10-01: "This
        # Actor timed out" mientras Radar la registraba a 0 €.
        await _abortar(cliente, cab, run_id)
    resultado.coste_usd = float(run.get("usageTotalUsd") or 0.0)
    if resultado.estado != "SUCCEEDED":
        resultado.error = f"la ejecución terminó en estado {resultado.estado}"
        return resultado

    dataset_id = run.get("defaultDatasetId")
    try:
        ri = await _peticion(
            cliente, "GET", f"{URL_BASE}/datasets/{dataset_id}/items", solo_fallos_de_conexion=False,
            pausa_s=PAUSA_REINTENTO_S if intervalo_s else 0.0,
            params={"limit": max_items, "clean": "true"}, headers=cab, timeout=60.0,
        )
    except httpx.HTTPError as exc:
        resultado.error = f"no se pudo leer el dataset: {_texto_error(exc)}"
        return resultado
    if ri.status_code != 200:
        resultado.error = _mensaje_error(ri.status_code, None)
        return resultado
    datos = ri.json()
    resultado.items = datos if isinstance(datos, list) else []
    resultado.coste_usd = max(resultado.coste_usd, await _coste_asentado(cliente, cab, run_id, intervalo_s))
    return resultado


async def _coste_asentado(cliente: httpx.AsyncClient, cab: dict[str, str], run_id: str | None, intervalo_s: float) -> float:
    """`usageTotalUsd` justo al terminar la ejecución todavía no incluye todos
    los eventos cobrados (visto en vivo: 0 $ al terminar, 0,012 $ segundos
    después; y con una sola relectura se registraba un ~12 % menos de lo real,
    2026-10-01). Se relee hasta que dos lecturas seguidas coinciden (como
    mucho `LECTURAS_COSTE` veces). Lo que aún falte lo corrige
    `radar.agente.costes_apify.conciliar_costes_apify` al final de la búsqueda."""
    if not run_id:
        return 0.0
    anterior = -1.0
    for _ in range(LECTURAS_COSTE):
        await asyncio.sleep(intervalo_s)
        actual = await coste_real(cliente, cab, run_id)
        if actual is None:
            return max(anterior, 0.0)
        if actual > 0 and actual == anterior:
            return actual
        anterior = actual
    return max(anterior, 0.0)


async def coste_real(cliente: httpx.AsyncClient, cab: dict[str, str], run_id: str) -> float | None:
    """`usageTotalUsd` actual de una ejecución (`None` si no se pudo leer)."""
    try:
        r = await cliente.get(f"{URL_BASE}/actor-runs/{run_id}", headers=cab, timeout=30.0)
        return float((r.json().get("data") or {}).get("usageTotalUsd") or 0.0) if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None


async def _abortar(cliente: httpx.AsyncClient, cab: dict[str, str], run_id: str) -> None:
    try:
        await cliente.post(f"{URL_BASE}/actor-runs/{run_id}/abort", headers=cab, timeout=30.0)
    except httpx.HTTPError:
        pass
