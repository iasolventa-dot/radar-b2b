import { ShieldCheck } from "lucide-react";
import { crearClienteServidor } from "@/lib/supabase/server";
import { ETIQUETA_CASO } from "@/lib/tipos";

export const dynamic = "force-dynamic";

export default async function PaginaEntidades() {
  const supabase = await crearClienteServidor();
  const { data: entidades, count } = await supabase
    .from("golden_entidades")
    .select("*", { count: "exact" })
    .order("creado_en", { ascending: false })
    .limit(200);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          Golden set — entidades verificadas
        </h1>
        <p className="mt-1 text-sm text-slate-500">{count ?? 0} entidades</p>
      </div>

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="th-panel">ID</th>
                <th className="th-panel">Razón social</th>
                <th className="th-panel">NIF</th>
                <th className="th-panel">Estado</th>
                <th className="th-panel">Caso</th>
                <th className="th-panel">Municipio</th>
                <th className="th-panel">Verificado</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {(entidades ?? []).map((e) => (
                <tr key={e.id_golden} className="transition-colors hover:bg-slate-50/70">
                  <td className="px-4 py-3 font-mono text-xs text-slate-400">{e.id_golden}</td>
                  <td className="px-4 py-3 font-medium text-slate-800">{e.razon_social}</td>
                  <td className="px-4 py-3">
                    {e.nif ? (
                      <span className="font-mono text-slate-700">{e.nif}</span>
                    ) : (
                      <span className="badge bg-amber-100 text-amber-800">sin NIF</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{e.estado ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-600">
                    {e.caso_dificil ? (
                      <span className="badge bg-brand-50 text-brand-700">
                        {ETIQUETA_CASO[e.caso_dificil] ?? e.caso_dificil}
                      </span>
                    ) : (
                      <span className="badge bg-slate-100 text-slate-600">Normal</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{e.municipio ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-400">{e.fecha_verificacion ?? "—"}</td>
                </tr>
              ))}
              {(entidades ?? []).length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-14">
                    <div className="flex flex-col items-center gap-2 text-center text-slate-400">
                      <ShieldCheck className="h-8 w-8" strokeWidth={1.5} />
                      <p className="text-sm">Todavía no se ha promovido ninguna entidad.</p>
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
