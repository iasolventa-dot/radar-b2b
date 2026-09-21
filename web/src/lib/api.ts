// Cliente HTTP del worker de Radar B2B (worker/radar/api, tarea #22).
//
// Cubre los tres endpoints que ESCRIBEN (interpretar una petición,
// confirmarla, cancelarla) — el resto de la lectura del panel pasa por
// Supabase directamente (RLS), igual que las pantallas de golden set/
// revisión, así que no hace falta que el worker esté levantado para ver
// el histórico.
//
// NEXT_PUBLIC_API_URL es la URL pública del worker en Railway. No lleva
// ninguna clave: la API todavía no verifica autenticación (ver docstring
// de radar.api.main — D-03, uso estrictamente interno, a cerrar si esto
// se expone más allá del equipo).
import type { BusquedaInterpretadaOut, ConfirmarBusquedaOut, EstadoApify, EstadoPlaces, FiltrosBusqueda, ProbarPlacesOut, ProfundizarOut } from "@/lib/tipos";

function urlBase(): string {
  const url = process.env.NEXT_PUBLIC_API_URL;
  if (!url) {
    throw new Error(
      "NEXT_PUBLIC_API_URL no está configurada — falta apuntar el panel al worker desplegado en Railway (ver .env.example)."
    );
  }
  return url.replace(/\/$/, "");
}

async function peticionJson<T>(ruta: string, opciones?: RequestInit): Promise<T> {
  let respuesta: Response;
  try {
    respuesta = await fetch(`${urlBase()}${ruta}`, {
      ...opciones,
      headers: { "Content-Type": "application/json", ...(opciones?.headers ?? {}) },
    });
  } catch {
    throw new Error("No se pudo contactar con el worker — ¿está desplegado y accesible NEXT_PUBLIC_API_URL?");
  }

  if (!respuesta.ok) {
    let detalle = respuesta.statusText;
    try {
      const cuerpo = await respuesta.json();
      detalle = cuerpo.detail ?? detalle;
    } catch {
      // el cuerpo no era JSON (p. ej. un 502 de la propia plataforma) — nos quedamos con statusText
    }
    throw new Error(detalle || `Error ${respuesta.status}`);
  }
  return respuesta.json() as Promise<T>;
}

/** POST /busquedas — interpreta la petición y la guarda como 'interpretada', sin gastar presupuesto. */
export function interpretarBusqueda(
  peticion: string,
  contexto: string | null,
  presupuestoEur: number,
  usuarioId: string | null
): Promise<BusquedaInterpretadaOut> {
  return peticionJson<BusquedaInterpretadaOut>("/busquedas", {
    method: "POST",
    body: JSON.stringify({ peticion, contexto, presupuesto_eur: presupuestoEur, usuario_id: usuarioId }),
  });
}

/** POST /busquedas/{id}/confirmar — lanza el planificador en segundo plano en el worker. */
export function confirmarBusqueda(
  id: string,
  opciones: { maxRondas?: number; filtros?: FiltrosBusqueda } = {}
): Promise<ConfirmarBusquedaOut> {
  return peticionJson<ConfirmarBusquedaOut>(`/busquedas/${id}/confirmar`, {
    method: "POST",
    body: JSON.stringify({ max_rondas: opciones.maxRondas ?? 10, filtros: opciones.filtros ?? null }),
  });
}

/** POST /busquedas/{id}/cancelar — cooperativo si está en_curso (el planificador
 * lo recoge entre rondas, no interrumpe una llamada ya en curso); inmediato si
 * está esperando_respuesta (no hay ningún bucle activo que pueda recogerlo). */
export function cancelarBusqueda(id: string): Promise<ConfirmarBusquedaOut> {
  return peticionJson<ConfirmarBusquedaOut>(`/busquedas/${id}/cancelar`, { method: "POST" });
}

/** POST /empresas/{id}/profundizar — 1-4 búsquedas web dirigidas a esta empresa
 * concreta (nombre+NIF/municipio ya conocidos), no un descubrimiento abierto.
 * Presupuesto pequeño a propósito (por defecto 0,30€); responde en la misma
 * petición porque no hay nada que interpretar. */
export function profundizarEmpresa(empresaId: string, maxCosteEur = 0.3): Promise<ProfundizarOut> {
  return peticionJson<ProfundizarOut>(`/empresas/${empresaId}/profundizar`, {
    method: "POST",
    body: JSON.stringify({ max_coste_eur: maxCosteEur }),
  });
}

/** GET /configuracion/google-places — nunca devuelve la clave entera, solo enmascarada. */
export function estadoPlaces(): Promise<EstadoPlaces> {
  return peticionJson<EstadoPlaces>("/configuracion/google-places");
}

/** PUT /configuracion/google-places — guarda la clave (solo la lee el worker) y, opcional, el tope mensual. */
export function guardarClavePlaces(apiKey: string | null, presupuestoMensualEur?: number): Promise<EstadoPlaces> {
  return peticionJson<EstadoPlaces>("/configuracion/google-places", {
    method: "PUT",
    body: JSON.stringify({ api_key: apiKey, presupuesto_mensual_eur: presupuestoMensualEur ?? null }),
  });
}

export function borrarClavePlaces(): Promise<EstadoPlaces> {
  return peticionJson<EstadoPlaces>("/configuracion/google-places", { method: "DELETE" });
}

/** POST /configuracion/google-places/probar — petición de solo IDs (gratuita) para validar la clave. */
export function probarClavePlaces(): Promise<ProbarPlacesOut> {
  return peticionJson<ProbarPlacesOut>("/configuracion/google-places/probar", { method: "POST" });
}

/** Apify (conexión disponible; el agente todavía no la usa). El token solo lo lee el worker. */
export function estadoApify(): Promise<EstadoApify> {
  return peticionJson<EstadoApify>("/configuracion/apify");
}

export function guardarTokenApify(apiToken: string | null, presupuestoMensualUsd?: number): Promise<EstadoApify> {
  return peticionJson<EstadoApify>("/configuracion/apify", {
    method: "PUT",
    body: JSON.stringify({ api_token: apiToken, presupuesto_mensual_usd: presupuestoMensualUsd ?? null }),
  });
}

export function borrarTokenApify(): Promise<EstadoApify> {
  return peticionJson<EstadoApify>("/configuracion/apify", { method: "DELETE" });
}

/** POST /configuracion/apify/probar — `GET /users/me`, sin consumir crédito. */
export function probarTokenApify(): Promise<ProbarPlacesOut> {
  return peticionJson<ProbarPlacesOut>("/configuracion/apify/probar", { method: "POST" });
}
