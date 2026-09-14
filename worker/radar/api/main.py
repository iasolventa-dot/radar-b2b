"""App de FastAPI (tarea #22, ver `radar.api` para el porqué). Tres
endpoints escriben, tres leen:

1. ``POST /busquedas`` — interpreta la petición (`radar.agente.interpretacion`)
   y la guarda con `estado='interpretada'`, SIN gastar presupuesto todavía
   (doc 02 §2, paso 1: "confirmación del usuario" antes de planificar).
2. ``POST /busquedas/{id}/confirmar`` — lanza `radar.agente.planificador.planificar`
   EN SEGUNDO PLANO (`BackgroundTasks`) y devuelve al momento; la web sigue
   el progreso con el GET de abajo (los resultados llegan a
   `busquedas.rondas`/`estadisticas` ronda a ronda, no solo al final).
3. ``POST /busquedas/{id}/cancelar`` — pide parar una búsqueda `en_curso`
   (cooperativo, entre rondas — no interrumpe una llamada ya en curso) o
   cierra directamente una que esté `esperando_respuesta` (migración
   202609141400, ver docstring de la función `cancelar`).
4. ``GET /busquedas/{id}`` / ``GET /busquedas`` / ``GET /salud`` — lectura.

Simplificación conocida (documentada también en `PeticionBusquedaIn.usuario_id`):
sin autenticación todavía — `usuario_id` se guarda tal cual lo manda la web,
sin verificar el JWT de Supabase. Vale para D-03 (uso estrictamente
interno, red no expuesta a terceros) pero es lo primero a cerrar si esto
se expone más allá del equipo.

`BackgroundTasks` (no una cola de verdad) es intencionadamente la solución
más simple que funciona: un solo proceso Railway, sin infraestructura
adicional. Si el proceso muere a mitad de una búsqueda (Ctrl+C, corte de
luz, recarga de `--reload`...), esa fila se queda en `estado='en_curso'`
en la base de datos aunque ya no haya ningún bucle corriéndola — al
arrancar de nuevo (`_lifespan`, ver `cerrar_busquedas_huerfanas`), el
worker cierra automáticamente cualquier búsqueda que encuentre en ese
estado, porque por construcción de este diseño (un solo proceso) no puede
haber sido creada por el proceso que acaba de arrancar. Es la razón por
la que cancelar es cooperativo y no instantáneo mientras el proceso SÍ
está vivo: no hay un job externo al que enviarle una señal real, solo una
columna que el propio bucle comprueba entre rondas.
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager

import httpx
import psycopg
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from radar.agente.interpretacion import FiltrosBusqueda, interpretar_peticion
from radar.agente.planificador import (
    HERRAMIENTAS_QUE_CONSUMEN_PRESUPUESTO,
    ResultadoPlanificador,
    RondaPlanificador,
    planificar,
)
from radar.api.bd_busquedas import (
    cerrar_busquedas_huerfanas,
    crear_busqueda,
    debe_cancelarse,
    finalizar_busqueda_db,
    guardar_progreso_ronda,
    listar_busquedas,
    marcar_en_curso,
    obtener_busqueda,
    solicitar_cancelacion,
)
from radar.api.esquemas import (
    BusquedaInterpretadaOut,
    BusquedaOut,
    ConfirmarBusquedaIn,
    ConfirmarBusquedaOut,
    PeticionBusquedaIn,
)
from radar.api.estado import estado_final_de
from radar.config import get_settings


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Al arrancar (no en cada request): cierra cualquier búsqueda
    `en_curso` huérfana de un proceso anterior — ver docstring de
    `cerrar_busquedas_huerfanas`. Sin `SUPABASE_DB_URL` configurada no
    revienta el arranque por esto: se limita a avisarlo por stderr, igual
    que cualquier otro endpoint sin esa variable (`_requerir_db_url`)."""
    settings = get_settings()
    if settings.supabase_db_url:
        try:
            with psycopg.connect(settings.supabase_db_url) as conn:
                n = cerrar_busquedas_huerfanas(conn)
            if n:
                print(f"[arranque] {n} búsqueda(s) 'en_curso' huérfanas de un proceso anterior, cerradas.", file=sys.stderr)
        except psycopg.Error as exc:
            print(f"[arranque] no se pudo comprobar búsquedas huérfanas: {exc}", file=sys.stderr)
    yield


app = FastAPI(title="Radar B2B — worker API", version="0.1.0", lifespan=_lifespan)

_settings_arranque = get_settings()
if _settings_arranque.cors_allow_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in _settings_arranque.cors_allow_origins.split(",") if o.strip()],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )


def _requerir_db_url() -> str:
    settings = get_settings()
    if not settings.supabase_db_url:
        raise HTTPException(status_code=500, detail="SUPABASE_DB_URL no está configurada en el worker")
    return settings.supabase_db_url


def _coste_de_ronda(ronda: RondaPlanificador) -> float:
    if ronda.herramienta not in HERRAMIENTAS_QUE_CONSUMEN_PRESUPUESTO:
        return 0.0
    return float(ronda.resultado.get("coste_eur", 0.0) or 0.0)


@app.get("/salud")
def salud() -> dict[str, bool]:
    """Para el healthcheck de Railway — no toca BD ni LLM, solo confirma que el proceso responde."""
    return {"ok": True}


@app.post("/busquedas", response_model=BusquedaInterpretadaOut)
async def crear(peticion_in: PeticionBusquedaIn) -> BusquedaInterpretadaOut:
    db_url = _requerir_db_url()
    # a un hilo aparte: interpretar_peticion es una llamada de red bloqueante (no async) — no
    # queremos parar el event loop de FastAPI mientras responde el LLM.
    resultado = await asyncio.to_thread(interpretar_peticion, peticion_in.peticion, peticion_in.contexto)
    if resultado.error or resultado.filtros is None:
        raise HTTPException(status_code=502, detail=f"la interpretación falló: {resultado.error}")

    with psycopg.connect(db_url) as conn:
        busqueda_id = crear_busqueda(
            conn, peticion=peticion_in.peticion, filtros=resultado.filtros,
            presupuesto_eur=peticion_in.presupuesto_eur, usuario_id=peticion_in.usuario_id,
        )
    return BusquedaInterpretadaOut(
        id=busqueda_id, filtros=resultado.filtros, supuestos=resultado.filtros.supuestos, preguntas=resultado.filtros.preguntas
    )


async def _ejecutar_planificador_en_fondo(busqueda_id: str, max_rondas: int) -> None:
    """Corre fuera del ciclo de vida del request — abre sus propias
    conexiones (la del request ya se habrá cerrado). Nunca lanza: un fallo
    aquí no tiene a quién devolvérselo (la respuesta HTTP ya se mandó), así
    que se captura y se deja constancia en la propia fila de `busquedas`."""
    settings = get_settings()
    db_url = settings.supabase_db_url
    if not db_url:
        return  # _requerir_db_url ya lo comprobó al confirmar; defensivo por si settings cambió entretanto

    with psycopg.connect(db_url) as conn_lectura:
        busqueda = obtener_busqueda(conn_lectura, busqueda_id)
    if busqueda is None:
        return

    filtros = FiltrosBusqueda.model_validate(busqueda.filtros)
    presupuesto_eur = busqueda.presupuesto_eur
    max_rondas_reales = busqueda.estadisticas.get("max_rondas", max_rondas)

    rondas_persistidas: list[RondaPlanificador] = []

    async def on_ronda(ronda: RondaPlanificador) -> None:
        rondas_persistidas.append(ronda)
        coste_acumulado = sum(_coste_de_ronda(r) for r in rondas_persistidas)
        # conexión propia por ronda: son pocas rondas (máx. `max_rondas`), no vale la pena
        # mantener una conexión abierta durante minutos entre rondas del LLM.
        with psycopg.connect(db_url) as conn:
            guardar_progreso_ronda(
                conn, busqueda_id, rondas_hasta_ahora=rondas_persistidas, max_rondas=max_rondas_reales, coste_gastado_eur=coste_acumulado
            )

    async def debe_cancelar() -> bool:
        # conexión propia, mismo motivo que on_ronda -- y misma cadencia:
        # se llama una vez por ronda, no vale la pena mantener nada abierto.
        with psycopg.connect(db_url) as conn:
            return debe_cancelarse(conn, busqueda_id)

    try:
        # `httpx.AsyncClient` es un context manager async; `psycopg.connect(...)` es sync — no se
        # pueden combinar en un solo `async with` (mypy lo marca, y de hecho no funcionaría en runtime).
        async with httpx.AsyncClient() as cliente_http:
            with psycopg.connect(db_url, autocommit=False) as conn_trabajo:
                resultado = await planificar(
                    conn_trabajo, cliente_http, filtros, presupuesto_eur=presupuesto_eur, max_rondas=max_rondas_reales,
                    on_ronda=on_ronda, debe_cancelar=debe_cancelar, busqueda_id=busqueda_id,
                )
    except Exception as exc:  # noqa: BLE001 — nunca dejar la búsqueda en 'en_curso' colgada para siempre
        resultado_error = ResultadoPlanificador(error=str(exc))
        with psycopg.connect(db_url) as conn:
            finalizar_busqueda_db(
                conn, busqueda_id, estado="error", rondas=rondas_persistidas, max_rondas=max_rondas_reales,
                coste_gastado_eur=sum(_coste_de_ronda(r) for r in rondas_persistidas), resultado=resultado_error,
            )
        return

    with psycopg.connect(db_url) as conn:
        finalizar_busqueda_db(
            conn, busqueda_id, estado=estado_final_de(resultado), rondas=resultado.rondas,
            max_rondas=max_rondas_reales, coste_gastado_eur=resultado.coste_gastado_eur, resultado=resultado,
        )


@app.post("/busquedas/{busqueda_id}/confirmar", response_model=ConfirmarBusquedaOut)
async def confirmar(busqueda_id: str, confirmar_in: ConfirmarBusquedaIn, tareas: BackgroundTasks) -> ConfirmarBusquedaOut:
    db_url = _requerir_db_url()
    with psycopg.connect(db_url) as conn:
        busqueda = obtener_busqueda(conn, busqueda_id)
        if busqueda is None:
            raise HTTPException(status_code=404, detail="búsqueda no encontrada")
        if busqueda.estado not in ("interpretada", "esperando_respuesta"):
            raise HTTPException(status_code=409, detail=f"la búsqueda está en estado '{busqueda.estado}', no se puede (re)confirmar")

        filtros = confirmar_in.filtros or FiltrosBusqueda.model_validate(busqueda.filtros)
        marcar_en_curso(conn, busqueda_id, filtros=filtros, max_rondas=confirmar_in.max_rondas)

    tareas.add_task(_ejecutar_planificador_en_fondo, busqueda_id, confirmar_in.max_rondas)
    return ConfirmarBusquedaOut(id=busqueda_id, estado="en_curso")


@app.get("/busquedas/{busqueda_id}", response_model=BusquedaOut)
async def obtener(busqueda_id: str) -> BusquedaOut:
    db_url = _requerir_db_url()
    with psycopg.connect(db_url) as conn:
        busqueda = obtener_busqueda(conn, busqueda_id)
    if busqueda is None:
        raise HTTPException(status_code=404, detail="búsqueda no encontrada")
    return BusquedaOut(
        id=busqueda.id, peticion=busqueda.peticion, filtros=FiltrosBusqueda.model_validate(busqueda.filtros),
        presupuesto_eur=busqueda.presupuesto_eur, estado=busqueda.estado, rondas=busqueda.rondas,
        estadisticas=busqueda.estadisticas, coste_eur=busqueda.coste_eur, creado_en=busqueda.creado_en, finalizado_en=busqueda.finalizado_en,
    )


@app.get("/busquedas", response_model=list[BusquedaOut])
async def listar(limite: int = 20) -> list[BusquedaOut]:
    db_url = _requerir_db_url()
    with psycopg.connect(db_url) as conn:
        busquedas = listar_busquedas(conn, limite=limite)
    return [
        BusquedaOut(
            id=b.id, peticion=b.peticion, filtros=FiltrosBusqueda.model_validate(b.filtros), presupuesto_eur=b.presupuesto_eur,
            estado=b.estado, rondas=b.rondas, estadisticas=b.estadisticas, coste_eur=b.coste_eur, creado_en=b.creado_en, finalizado_en=b.finalizado_en,
        )
        for b in busquedas
    ]


@app.post("/busquedas/{busqueda_id}/cancelar", response_model=ConfirmarBusquedaOut)
async def cancelar(busqueda_id: str) -> ConfirmarBusquedaOut:
    """No hay un job externo al que mandarle una señal: la búsqueda corre
    en este mismo proceso vía `BackgroundTasks` (doc 08 D-16). Si está
    `en_curso`, solo se marca `cancelar_solicitado` — el propio bucle del
    planificador la recoge entre rondas (ver `_ejecutar_planificador_en_fondo`
    y `radar.agente.planificador`, parámetro `debe_cancelar`) y es quien
    escribe `estado='cancelada'` al terminar. Si está `esperando_respuesta`,
    no hay ningún bucle activo que pueda recogerlo (ya paró solo al llamar
    a `preguntar_usuario`), así que se cierra el estado aquí mismo.

    Caso límite: si el proceso que estaba corriendo esa búsqueda ya murió
    (Ctrl+C, corte de luz...) antes de que se pidiera cancelar, este
    endpoint marca el flag igualmente pero NADIE va a recogerlo nunca —
    parece que "no hace nada" porque, en efecto, no puede hacer nada: el
    bucle que debía comprobarlo ya no existe. Se resuelve solo al
    reiniciar el worker (`_lifespan`, `cerrar_busquedas_huerfanas`), no
    aquí; no hay forma de distinguir desde este endpoint un proceso lento
    de uno muerto.
    """
    db_url = _requerir_db_url()
    with psycopg.connect(db_url) as conn:
        busqueda = obtener_busqueda(conn, busqueda_id)
        if busqueda is None:
            raise HTTPException(status_code=404, detail="búsqueda no encontrada")
        if busqueda.estado not in ("en_curso", "esperando_respuesta"):
            raise HTTPException(
                status_code=409,
                detail=f"la búsqueda está en estado '{busqueda.estado}', no se puede cancelar",
            )
        nuevo_estado = solicitar_cancelacion(
            conn, busqueda_id, resolver_inmediatamente=busqueda.estado == "esperando_respuesta"
        )
    return ConfirmarBusquedaOut(id=busqueda_id, estado=nuevo_estado)
