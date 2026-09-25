import Link from "next/link";
import { ArrowRight, BarChart3, Building2, Clock3, ShieldCheck } from "lucide-react";
import { EncabezadoPagina, EstadoVacio, TarjetaCifra } from "@/components/encabezado-pagina";
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
    <div className="entrada space-y-8">
      <EncabezadoPagina
        icono={ShieldCheck}
        antetitulo="Referencia de calidad"
        titulo="Golden set"
        acciones={
          <Link href="/revision" className="btn-primary">
            Revisar candidatos <ArrowRight className="h-4 w-4" />
          </Link>
        }
      >
        <p>Construcción, provincia de Sevilla (D-11). Uso estrictamente interno de Solventa IA.</p>
      </EncabezadoPagina>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <TarjetaCifra
          icono={ShieldCheck}
          etiqueta="Entidades verificadas"
          valor={`${totalPromovidas} / ${totalObjetivo}`}
          tono="verde"
        />
        <TarjetaCifra icono={Clock3} etiqueta="Candidatos pendientes de revisar" valor={pendientes ?? 0} tono="ambar" />
      </div>

      <div>
        <h2 className="titulo-seccion mb-4">
          <span className="icono-seccion">
            <BarChart3 className="h-4 w-4" />
          </span>
          Progreso por categoría
        </h2>
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="tabla-panel">
              <thead>
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
                    <tr key={clave || "normal"} className="group">
                      <td className="td-panel font-medium text-slate-700">{ETIQUETA_CASO[clave]}</td>
                      <td className="td-panel text-slate-600">{actual}</td>
                      <td className="td-panel text-slate-400">{objetivo}</td>
                      <td className="td-panel">
                        <div className="flex items-center gap-2">
                          <div className="h-2.5 w-40 overflow-hidden rounded-full bg-slate-100">
                            <div
                              className={`h-full rounded-full transition-all ${
                                completo ? "bg-gradient-to-r from-emerald-400 to-teal-500" : "bg-gradient-to-r from-brand-500 to-violet-500"
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
          <h2 className="titulo-seccion">
            <span className="icono-seccion">
              <Building2 className="h-4 w-4" />
            </span>
            Entidades
          </h2>
          <p className="text-xs text-slate-400">{count ?? 0} entidades</p>
        </div>
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="tabla-panel">
              <thead>
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
                  <tr key={e.id_golden} className="group">
                    <td className="td-panel font-mono text-xs text-slate-400">{e.id_golden}</td>
                    <td className="td-panel font-medium text-slate-800">{e.razon_social}</td>
                    <td className="td-panel">
                      {e.nif ? (
                        <span className="font-mono text-slate-700">{e.nif}</span>
                      ) : (
                        <span className="badge bg-amber-50 text-amber-700">sin NIF</span>
                      )}
                    </td>
                    <td className="td-panel text-slate-600">{e.estado ?? "—"}</td>
                    <td className="td-panel text-slate-600">
                      {e.caso_dificil ? (
                        <span className="badge bg-brand-50 text-brand-700">
                          {ETIQUETA_CASO[e.caso_dificil] ?? e.caso_dificil}
                        </span>
                      ) : (
                        <span className="badge bg-slate-100 text-slate-600">Normal</span>
                      )}
                    </td>
                    <td className="td-panel text-slate-600">{e.municipio ?? "—"}</td>
                    <td className="td-panel text-slate-400">{e.fecha_verificacion ?? "—"}</td>
                  </tr>
                ))}
                {(entidades ?? []).length === 0 && (
                  <tr>
                    <td colSpan={7}>
                      <EstadoVacio icono={ShieldCheck}>Todavía no se ha promovido ninguna entidad.</EstadoVacio>
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
