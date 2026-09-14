import Link from "next/link";
import { ArrowRight, History, Search } from "lucide-react";
import { crearClienteServidor } from "@/lib/supabase/server";
import { COLOR_ESTADO_BUSQUEDA, ETIQUETA_ESTADO_BUSQUEDA, type BusquedaFila } from "@/lib/tipos";

// Lectura directa contra Supabase (RLS, `busquedas` tiene política de
// lectura para `authenticated`) — igual que el resto del panel, así el
// histórico se ve aunque el worker de Railway esté caído. Solo crear/
// confirmar una búsqueda pasa por `radar.api` (lib/api.ts).
export const dynamic = "force-dynamic";

const POR_PAGINA = 30;

export default async function PaginaBusquedas() {
  const supabase = await crearClienteServidor();
  const { data: busquedas, count } = await supabase
    .from("busquedas")
    .select("id, peticion, filtros, presupuesto_eur, estado, rondas, estadisticas, coste_eur, creado_en, finalizado_en", {
      count: "exact",
    })
    .order("creado_en", { ascending: false })
    .limit(POR_PAGINA);

  const filas = (busquedas ?? []) as unknown as BusquedaFila[];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Búsquedas</h1>
          <p className="mt-1 text-sm text-slate-500">{count ?? 0} búsquedas lanzadas</p>
        </div>
        <Link href="/" className="btn-primary">
          <Search className="h-4 w-4" /> Nueva búsqueda
        </Link>
      </div>

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="th-panel">Petición</th>
                <th className="th-panel">Estado</th>
                <th className="th-panel">Rondas</th>
                <th className="th-panel">Coste</th>
                <th className="th-panel">Lanzada</th>
                <th className="th-panel" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filas.map((b) => (
                <tr key={b.id} className="transition-colors hover:bg-slate-50/70">
                  <td className="max-w-xs truncate px-4 py-3 font-medium text-slate-800" title={b.peticion}>
                    {b.peticion}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`badge ${COLOR_ESTADO_BUSQUEDA[b.estado] ?? "bg-slate-100 text-slate-600"}`}>
                      {ETIQUETA_ESTADO_BUSQUEDA[b.estado] ?? b.estado}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {b.rondas} / {b.estadisticas?.max_rondas ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {b.coste_eur.toFixed(2)} € {b.presupuesto_eur != null && `/ ${Number(b.presupuesto_eur).toFixed(2)} €`}
                  </td>
                  <td className="px-4 py-3 text-slate-400">{new Date(b.creado_en).toLocaleString("es-ES")}</td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      href={`/busquedas/${b.id}`}
                      className="inline-flex items-center gap-1 text-sm font-medium text-brand-600 hover:text-brand-700"
                    >
                      Ver <ArrowRight className="h-3.5 w-3.5" />
                    </Link>
                  </td>
                </tr>
              ))}
              {filas.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-14">
                    <div className="flex flex-col items-center gap-2 text-center text-slate-400">
                      <History className="h-8 w-8" strokeWidth={1.5} />
                      <p className="text-sm">Todavía no se ha lanzado ninguna búsqueda.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
