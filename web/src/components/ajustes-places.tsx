"use client";

// Sección de Ajustes para Google Places: pegar la clave de API, probarla sin
// coste y fijar un tope mensual. La clave se manda al worker (PUT) y solo el
// worker puede leerla -- aquí nunca vuelve entera, solo enmascarada.

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, KeyRound, Loader2, Trash2 } from "lucide-react";
import { borrarClavePlaces, estadoPlaces, guardarClavePlaces, probarClavePlaces } from "@/lib/api";
import type { EstadoPlaces } from "@/lib/tipos";

export function AjustesPlaces() {
  const [estado, setEstado] = useState<EstadoPlaces | null>(null);
  const [clave, setClave] = useState("");
  const [presupuesto, setPresupuesto] = useState("");
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [mensaje, setMensaje] = useState<{ ok: boolean; texto: string } | null>(null);

  useEffect(() => {
    estadoPlaces()
      .then((e) => {
        setEstado(e);
        setPresupuesto(String(e.presupuesto_mensual_eur));
      })
      .catch((err) => setMensaje({ ok: false, texto: err instanceof Error ? err.message : String(err) }));
  }, []);

  async function ejecutar(nombre: string, accion: () => Promise<void>) {
    setOcupado(nombre);
    setMensaje(null);
    try {
      await accion();
    } catch (err) {
      setMensaje({ ok: false, texto: err instanceof Error ? err.message : String(err) });
    } finally {
      setOcupado(null);
    }
  }

  const guardar = () =>
    ejecutar("guardar", async () => {
      const tope = presupuesto.trim() === "" ? undefined : Number(presupuesto);
      if (tope !== undefined && (Number.isNaN(tope) || tope < 0)) throw new Error("El tope mensual debe ser un número ≥ 0.");
      if (clave.trim().length > 0) {
        setEstado(await guardarClavePlaces(clave.trim(), tope));
        setClave("");
        setMensaje({ ok: true, texto: "Clave guardada. Pulsa «Probar clave» para comprobarla." });
      } else if (tope !== undefined) {
        setEstado(await guardarClavePlaces(null, tope));
        setMensaje({ ok: true, texto: "Tope mensual actualizado." });
      } else {
        throw new Error("Pega la clave de API de Google Cloud.");
      }
    });

  const probar = () =>
    ejecutar("probar", async () => {
      const r = await probarClavePlaces();
      setMensaje({ ok: r.ok, texto: r.mensaje });
    });

  const borrar = () =>
    ejecutar("borrar", async () => {
      setEstado(await borrarClavePlaces());
      setMensaje({ ok: true, texto: "Clave eliminada." });
    });

  const gastoPct =
    estado && estado.presupuesto_mensual_eur > 0
      ? Math.min(100, (estado.gasto_mes_eur / estado.presupuesto_mensual_eur) * 100)
      : 0;

  return (
    <div className="card space-y-5 p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="titulo-seccion">
            <span className="icono-seccion">
              <KeyRound className="h-4 w-4" />
            </span>
            Google Places (de pago)
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-600">
            Descubre negocios por zona y categoría. Google solo permite guardar el <code>place_id</code>: los
            datos de cada negocio se usan en el momento para reconocer empresas que ya tenemos o para seguir su
            web propia. Cuesta ~0,035 € por página de 20 resultados (tarifa de lista, a verificar en tu consola
            de Google Cloud).
          </p>
        </div>
        <span
          className={`badge shrink-0 ${estado?.configurada ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"}`}
        >
          {estado === null ? "…" : estado.configurada ? "Configurada" : "Sin clave"}
        </span>
      </div>

      {estado?.configurada && (
        <div className="rounded-xl border border-slate-100 bg-gradient-to-br from-slate-50 to-white p-4 text-sm text-slate-700">
          <p>
            Clave actual: <span className="font-mono">{estado.clave_enmascarada}</span>{" "}
            <span className="text-xs text-slate-400">({estado.origen === "panel" ? "guardada desde el panel" : "del archivo .env"})</span>
          </p>
          <div className="mt-2">
            <div className="flex justify-between text-sm text-slate-500">
              <span>Gasto este mes: {estado.gasto_mes_eur.toFixed(2)} €</span>
              <span>Tope mensual: {estado.presupuesto_mensual_eur.toFixed(2)} €</span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-200">
              <div className="h-full bg-brand-600" style={{ width: `${gastoPct}%` }} />
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="sm:col-span-2">
          <label htmlFor="clave-places" className="label-field">
            Clave de API
          </label>
          <input
            id="clave-places"
            type="password"
            autoComplete="off"
            placeholder={estado?.configurada ? "Pega una clave nueva para sustituirla" : "AIza…"}
            value={clave}
            onChange={(e) => setClave(e.target.value)}
            className="input-field font-mono"
            disabled={ocupado !== null}
          />
        </div>
        <div>
          <label htmlFor="tope-places" className="label-field">
            Tope mensual (€)
          </label>
          <input
            id="tope-places"
            type="number"
            min={0}
            step={0.5}
            value={presupuesto}
            onChange={(e) => setPresupuesto(e.target.value)}
            className="input-field"
            disabled={ocupado !== null}
          />
        </div>
      </div>

      {mensaje && (
        <div
          className={mensaje.ok ? "aviso-ok" : "aviso-error"}
        >
          {mensaje.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />}
          <p>{mensaje.texto}</p>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={guardar} disabled={ocupado !== null} className="btn-primary">
          {ocupado === "guardar" ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Guardar
        </button>
        <button type="button" onClick={probar} disabled={ocupado !== null || !estado?.configurada} className="btn-secondary">
          {ocupado === "probar" ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Probar clave
        </button>
        {estado?.origen === "panel" && (
          <button type="button" onClick={borrar} disabled={ocupado !== null} className="btn-secondary">
            <Trash2 className="h-4 w-4" /> Quitar clave
          </button>
        )}
      </div>

      <p className="text-sm text-slate-400">
        Necesitas una clave de Google Cloud con «Places API (New)» habilitada y facturación activa. La clave se
        guarda en la base de datos y solo la lee el worker local; nunca se muestra entera.
      </p>
    </div>
  );
}
