import { AlertTriangle, Ban, GitMerge } from "lucide-react";
import { crearClienteServidor } from "@/lib/supabase/server";
import { confirmarFusion, descartarDuplicado } from "./acciones";

export const dynamic = "force-dynamic";

// candidatos_duplicado se rellena desde que existe radar.resolucion
// (tarea #21) -- radar.orquestador.procesar crea una empresa nueva Y deja
// aquí un candidato pendiente cuando no está seguro de si es la misma que
// una ya existente o una empresa distinta con nombre parecido. Hasta esta
// sesión, nada leía esta tabla ni resolvía nunca esos candidatos: se
// acumulaban para siempre y las dos empresas quedaban separadas en
// cualquier búsqueda, aunque fueran la misma en realidad.

interface EmpresaResumen {
  id: string;
  razon_social: string;
  nif: string | null;
  forma_juridica: string | null;
  objeto_social: string | null;
  estado: string | null;
  confianza_global: number | null;
}

export default async function PaginaDuplicados() {
  const supabase = await crearClienteServidor();

  const { data: candidatos, count } = await supabase
    .from("candidatos_duplicado")
    .select("id, empresa_a, empresa_b, puntuacion, senales, creado_en", { count: "exact" })
    .eq("estado", "pendiente")
    .order("puntuacion", { ascending: false })
    .limit(100);

  const idsEmpresas = Array.from(
    new Set((candidatos ?? []).flatMap((c) => [c.empresa_a, c.empresa_b]))
  );

  // Consulta plana aparte (no anidada en la de candidatos_duplicado): el
  // cliente de Supabase no tiene tipos generados y su inferencia de tipos
  // por plantillas de texto no soporta bien selects complejos -- mismo
  // motivo que ya obligó a separar consultas en progreso-busqueda.tsx y
  // en /empresas/[id].
  const { data: empresasFilas } = idsEmpresas.length
    ? await supabase
        .from("empresas")
        .select("id, razon_social, nif, forma_juridica, objeto_social, estado, confianza_global")
        .in("id", idsEmpresas)
    : { data: [] as EmpresaResumen[] };

  const empresaPorId = new Map((empresasFilas ?? []).map((e) => [e.id, e as EmpresaResumen]));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Posibles duplicados</h1>
        <p className="mt-1 text-sm text-slate-500">
          Empresas que el resolutor de entidades no pudo distinguir con seguridad de otra ya existente
          — {count ?? 0} pendientes de revisar.
        </p>
      </div>

      {(candidatos ?? []).length === 0 && (
        <div className="card flex flex-col items-center gap-2 p-14 text-center text-slate-400">
          <GitMerge className="h-8 w-8" strokeWidth={1.5} />
          <p className="text-sm">No hay ningún candidato pendiente de revisar.</p>
        </div>
      )}

      <div className="space-y-4">
        {(candidatos ?? []).map((c) => {
          const a = empresaPorId.get(c.empresa_a);
          const b = empresaPorId.get(c.empresa_b);
          if (!a || !b) return null;
          return (
            <div key={c.id} className="card p-5">
              <div className="mb-3 flex items-center justify-between">
                <span className="badge bg-amber-100 text-amber-800">
                  <AlertTriangle className="mr-1 h-3 w-3" />
                  puntuación {c.puntuacion.toFixed(2)}
                </span>
                <span className="text-xs text-slate-400">{new Date(c.creado_en).toLocaleDateString("es-ES")}</span>
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <TarjetaEmpresa empresa={a} />
                <TarjetaEmpresa empresa={b} />
              </div>

              {c.senales && Object.keys(c.senales).length > 0 && (
                <p className="mt-3 text-xs text-slate-400">
                  Señales: {Object.entries(c.senales as Record<string, unknown>).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(" · ")}
                </p>
              )}

              <div className="mt-4 flex flex-wrap items-center gap-2">
                <form action={confirmarFusion}>
                  <input type="hidden" name="candidato_id" value={c.id} />
                  <input type="hidden" name="origen" value={b.id} />
                  <input type="hidden" name="destino" value={a.id} />
                  <input type="hidden" name="puntuacion" value={c.puntuacion} />
                  <button type="submit" className="btn-primary">
                    <GitMerge className="h-4 w-4" />
                    Son la misma — conservar &quot;{a.razon_social}&quot;
                  </button>
                </form>
                <form action={confirmarFusion}>
                  <input type="hidden" name="candidato_id" value={c.id} />
                  <input type="hidden" name="origen" value={a.id} />
                  <input type="hidden" name="destino" value={b.id} />
                  <input type="hidden" name="puntuacion" value={c.puntuacion} />
                  <button type="submit" className="btn-secondary">
                    <GitMerge className="h-4 w-4" />
                    Son la misma — conservar &quot;{b.razon_social}&quot;
                  </button>
                </form>
                <form action={descartarDuplicado}>
                  <input type="hidden" name="candidato_id" value={c.id} />
                  <button type="submit" className="btn-danger">
                    <Ban className="h-4 w-4" />
                    No son la misma empresa
                  </button>
                </form>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TarjetaEmpresa({ empresa }: { empresa: EmpresaResumen }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <p className="font-medium text-slate-800">{empresa.razon_social}</p>
      <p className="mt-1 text-xs text-slate-500">
        {empresa.nif ?? "sin NIF"} · {empresa.forma_juridica ?? "forma jurídica desconocida"} · {empresa.estado ?? "estado desconocido"}
        {empresa.confianza_global != null && ` · confianza ${empresa.confianza_global.toFixed(2)}`}
      </p>
      {empresa.objeto_social && <p className="mt-2 text-xs text-slate-500">{empresa.objeto_social}</p>}
    </div>
  );
}
