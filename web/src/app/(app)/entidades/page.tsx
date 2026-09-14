import { Clock3, ShieldCheck, type LucideIcon } from "lucide-react";
import { crearClienteServidor } from "@/lib/supabase/server";
import { ETIQUETA_CASO, OBJETIVO_POR_CASO } from "@/lib/tipos";

export const dynamic = "force-dynamic";

export default async function PaginaEntidades() {
  const supabase = await crearClienteServidor();

  const [{ data: entidades, count }, { count: pendientes }] = await Promise.all([
    supabase
      .from("golden_entidades")
      .select("*", { count: "exact" })
      .order("creado_en", { ascending: false })
      .limit(200),
    supabase
      .from("golden_candidatos")
      .select("*", { count: "exact", head: true })
      .eq("estado_revision", "pendiente"),
  ]);

  const conteoPorCaso: Record<string, number> = {};
  for (const clave of Object.keys(OBJETIVO_POR_CASO)) conteoPorCaso[clave] = 0;
  for (const fila of entidades ?? []) {
    const clave = fila.caso_dificil ?? "";
    conteoPorCaso[clave] = (conteoPorCaso[clave] ?? 0) + 1;
  }

  const totalPromovidas = (entidades ?? []).length;
  const totalObjetivo = Object.values(OBJETIVO_POR_CASO).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          Golden set — Radar B2B
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Construcción, provincia de Sevilla (D-11). Uso estrictamente interno de Solventa IA.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <TarjetaEstadistica
          icono={ShieldCheck}
          etiqueta="Entidades verificadas"
          valor={`${totalPromovidas} / ${totalObjetivo}`}
          color="emerald"
        />
        <TarjetaEstadistica
          icono={Clock3}
          etiqueta="Candidatos pendientes de revisar"
          valor={String(pendientes ?? 0)}
          color="amber"
        />
      </div>

      <div>
        <h2 className="mb-3 text-sm font-semibold text-slate-700">Progreso por categoría</h2>
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50">
                <tr>
                  <th className="th-panel">Categoría</th>
                  <th className="th-panel">Verificadas</th>
                  <th className="th-panel">Objetivo</th>
                  <th className="th-panel">Progreso</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {Object.entries(OBJETIVO_POR_CASO).map(([clave, objetivo]) => {
                  const actual = conteoPorCaso[clave] ?? 0;
                  const completo = actual >= objetivo;
                  const pct = Math.min(100, Math.round((actual / objetivo) * 100));
                  return (
                    <tr key={clave || "normal"} className="transition-colors hover:bg-slate-50/70">
                      <td className="px-4 py-3 font-medium text-slate-700">{ETIQUETA_CASO[clave]}</td>
                      <td className="px-4 py-3 text-slate-600">{actual}</td>
                      <td className="px-4 py-3 text-slate-400">{objetivo}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="h-2 w-32 overflow-hidden rounded-full bg-slate-100">
                            <div
                              className={`h-full rounded-full transition-all ${
                                completo ? "bg-emerald-500" : "bg-brand-500"
                              }`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <span
                            className={`text-xs font-medium ${
                              completo ? "text-emerald-600" : "text-slate-400"
                            }`}
                          >
                            {pct}%
                          </span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div>
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-sm font-semibold text-slate-700">Entidades</h2>
          <p className="text-xs text-slate-400">{count ?? 0} entidades</p>
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
    </div>
  );
}

function TarjetaEstadistica({
  icono: Icono,
  etiqueta,
  valor,
  color,
}: {
  icono: LucideIcon;
  etiqueta: string;
  valor: string;
  color: "emerald" | "amber";
}) {
  const estilos: Record<typeof color, string> = {
    emerald: "bg-emerald-50 text-emerald-600",
    amber: "bg-amber-50 text-amber-600",
  };

  return (
    <div className="card flex items-center gap-4 px-5 py-4">
      <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${estilos[color]}`}>
        <Icono className="h-5 w-5" />
      </span>
      <div>
        <p className="text-xs text-slate-500">{etiqueta}</p>
        <p className="mt-0.5 text-2xl font-semibold text-slate-900">{valor}</p>
      </div>
    </div>
  );
}
