"use client";

// Botón de "búsqueda en profundidad" para UNA empresa concreta (roadmap
// 2026-09-21, petición del usuario: "búsqueda en profundidad de una empresa
// específica cuando la resolución automática no puede decidir"). A
// diferencia de una búsqueda normal (formulario-nueva-busqueda.tsx), aquí no
// hay nada que interpretar -- worker/radar/agente/profundizar.py construye
// las consultas solas a partir de lo que ya se sabe de esta empresa
// (nombre, NIF, municipio) y responde en la misma petición, así que esto es
// una llamada síncrona con spinner, no un `router.push` a una pantalla de
// progreso.

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Loader2, Search } from "lucide-react";
import { profundizarEmpresa } from "@/lib/api";
import type { ProfundizarOut } from "@/lib/tipos";

const PRESUPUESTO_POR_DEFECTO_EUR = 0.3;

export function BotonProfundizar({ empresaId }: { empresaId: string }) {
  const router = useRouter();
  const [cargando, setCargando] = useState(false);
  const [resultado, setResultado] = useState<ProfundizarOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function ejecutar() {
    setCargando(true);
    setError(null);
    setResultado(null);
    try {
      const r = await profundizarEmpresa(empresaId, PRESUPUESTO_POR_DEFECTO_EUR);
      setResultado(r);
      router.refresh(); // trae las observaciones/sedes/canales nuevos que acaba de guardar
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCargando(false);
    }
  }

  const r = resultado?.resultado as Record<string, unknown> | undefined;

  return (
    <div className="card space-y-3 p-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">Búsqueda en profundidad</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Lanza 1-4 búsquedas web dirigidas solo a esta empresa (nombre + NIF/municipio ya conocidos),
            hasta {PRESUPUESTO_POR_DEFECTO_EUR.toFixed(2)} €. Útil cuando faltan datos o hay dudas de si un
            duplicado es la misma empresa.
          </p>
        </div>
        <button type="button" onClick={ejecutar} disabled={cargando} className="btn-secondary shrink-0">
          {cargando ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" /> Buscando…
            </>
          ) : (
            <>
              <Search className="h-4 w-4" /> Profundizar
            </>
          )}
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-3 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <p>{error}</p>
        </div>
      )}

      {resultado && !error && (
        <div className="space-y-2 rounded-lg bg-slate-50 p-3 text-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Consultas ejecutadas</p>
          <ul className="space-y-0.5 text-slate-600">
            {resultado.consultas.map((c, i) => (
              <li key={i} className="font-mono text-xs">
                {c}
              </li>
            ))}
          </ul>
          {r && (
            <p className="text-slate-600">
              {String(r.urls_encontradas ?? 0)} URL(s) encontradas ·{" "}
              {String(r.vinculado ?? 0)} vinculada(s) a esta empresa u otra ·{" "}
              {String(r.en_revision ?? 0)} a revisión ·{" "}
              {String(r.nueva_empresa ?? 0)} nueva(s) · coste {Number(r.coste_eur ?? 0).toFixed(4)} €
            </p>
          )}
        </div>
      )}
    </div>
  );
}
