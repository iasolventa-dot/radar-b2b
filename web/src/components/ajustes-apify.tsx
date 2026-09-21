"use client";

// Sección de Ajustes para Apify: pegar el token de API, probarlo sin coste y fijar un
// tope mensual. El token se manda al worker (PUT) y solo el worker puede leerlo.
// La conexión está disponible pero el agente todavía no la usa.

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, KeyRound, Loader2, Trash2 } from "lucide-react";
import { borrarTokenApify, estadoApify, guardarTokenApify, probarTokenApify } from "@/lib/api";
import type { EstadoApify } from "@/lib/tipos";

export function AjustesApify() {
  const [estado, setEstado] = useState<EstadoApify | null>(null);
  const [token, setToken] = useState("");
  const [presupuesto, setPresupuesto] = useState("");
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [mensaje, setMensaje] = useState<{ ok: boolean; texto: string } | null>(null);

  useEffect(() => {
    estadoApify()
      .then((e) => {
        setEstado(e);
        setPresupuesto(String(e.presupuesto_mensual_usd));
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
      if (token.trim().length > 0) {
        setEstado(await guardarTokenApify(token.trim(), tope));
        setToken("");
        setMensaje({ ok: true, texto: "Token guardado. Pulsa «Probar token» para comprobarlo." });
      } else if (tope !== undefined) {
        setEstado(await guardarTokenApify(null, tope));
        setMensaje({ ok: true, texto: "Tope mensual actualizado." });
      } else {
        throw new Error("Pega el token de API de Apify.");
      }
    });

  const probar = () =>
    ejecutar("probar", async () => {
      const r = await probarTokenApify();
      setMensaje({ ok: r.ok, texto: r.mensaje });
    });

  const borrar = () =>
    ejecutar("borrar", async () => {
      setEstado(await borrarTokenApify());
      setMensaje({ ok: true, texto: "Token eliminado." });
    });

  const gastoPct =
    estado && estado.presupuesto_mensual_usd > 0
      ? Math.min(100, (estado.gasto_mes_usd / estado.presupuesto_mensual_usd) * 100)
      : 0;

  return (
    <div className="card space-y-5 p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-700">
            <KeyRound className="h-4 w-4 text-slate-400" /> Apify (de pago)
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            Conexión con la API de Apify. Solo se usa en las búsquedas donde marques «Incluir Apify» (rastreo de
            webs de empresa). Apify es un servicio aparte, con cuenta y facturación propias.
          </p>
        </div>
        <span
          className={`badge shrink-0 ${estado?.configurado ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}
        >
          {estado === null ? "…" : estado.configurado ? "Configurado" : "Sin token"}
        </span>
      </div>

      {estado?.configurado && (
        <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
          <p>
            Token actual: <span className="font-mono">{estado.token_enmascarado}</span>
          </p>
          <div className="mt-2">
            <div className="flex justify-between text-xs text-slate-500">
              <span>Gasto este mes: {estado.gasto_mes_usd.toFixed(2)} $</span>
              <span>Tope mensual: {estado.presupuesto_mensual_usd.toFixed(2)} $</span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-200">
              <div className="h-full bg-brand-600" style={{ width: `${gastoPct}%` }} />
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="sm:col-span-2">
          <label htmlFor="token-apify" className="label-field">
            Token de API
          </label>
          <input
            id="token-apify"
            type="password"
            autoComplete="off"
            placeholder={estado?.configurado ? "Pega un token nuevo para sustituirlo" : "apify_api_…"}
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className="input-field font-mono"
            disabled={ocupado !== null}
          />
        </div>
        <div>
          <label htmlFor="tope-apify" className="label-field">
            Tope mensual ($)
          </label>
          <input
            id="tope-apify"
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
          className={`flex items-start gap-3 rounded-lg p-3 text-sm ${mensaje.ok ? "bg-emerald-50 text-emerald-800" : "bg-rose-50 text-rose-800"}`}
        >
          {mensaje.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />}
          <p>{mensaje.texto}</p>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={guardar} disabled={ocupado !== null} className="btn-primary">
          {ocupado === "guardar" ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Guardar
        </button>
        <button type="button" onClick={probar} disabled={ocupado !== null || !estado?.configurado} className="btn-secondary">
          {ocupado === "probar" ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Probar token
        </button>
        {estado?.configurado && (
          <button type="button" onClick={borrar} disabled={ocupado !== null} className="btn-secondary">
            <Trash2 className="h-4 w-4" /> Quitar token
          </button>
        )}
      </div>

      <p className="text-xs text-slate-400">
        Crea el token en Apify Console → Settings → API &amp; Integrations. Se guarda en la base de datos y solo lo
        lee el worker local; nunca se muestra entero.
      </p>
    </div>
  );
}
